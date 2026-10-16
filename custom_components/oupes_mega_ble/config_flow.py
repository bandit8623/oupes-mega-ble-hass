"""Config flow for OUPES Mega integration.

Supports two entry points:
  1. Automatic - HA's bluetooth scanner finds a 'TT' device and calls
     async_step_bluetooth(); the user confirms.
  2. Manual   - user picks 'Add Integration > OUPES Mega' and types the
     Bluetooth MAC address.

After identifying the device, both paths present a method-selection step
with three options for providing the device_key:
  A. Create new key  - factory-reset the device and pair over BLE
  B. Existing key    - enter a known key manually
  C. Cloud login     - fetch the key from the Cleanergy cloud
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfo,
    async_discovered_service_info,
)
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .ble_pairing import PairingResult, async_pair_device, async_provision_wifi
from .cloud_api import (
    async_cloud_login_info,
    async_fetch_cloud_identity,
    async_fetch_device_key,
)
from .cloud_identity import (
    USER_ID_MAX,
    describe_identity_risk,
    open_id_fits,
    user_id_fits,
)
from .local_identity import minted_identity
from .cloud_api import async_cloud_login, async_fetch_device_key
from .const import (
    ATTR78_RUNTIME_MAX,
    CONF_ADDRESS,
    CONF_CONTINUOUS,
    CONF_DEBUG_ATTRS,
    CONF_DEBUG_RAW,
    CONF_DEVICE_ID,
    CONF_DEVICE_KEY,
    CONF_IDENTITY_SOURCE,
    CONF_LIVE_PUSH_INTERVAL,
    CONF_NAME,
    CONF_OPEN_ID,
    CONF_POLL_INTERVAL,
    CONF_PRODUCT_ID,
    CONF_RUNTIME_MAX,
    CONF_STALE_TIMEOUT,
    CONF_USER_ID,
    DOMAIN,
    LIVE_PUSH_MIN_INTERVAL,
    IDENTITY_SOURCE_CLOUD,
    IDENTITY_SOURCE_DERIVED,
    IDENTITY_SOURCE_LOCAL,
    IDENTITY_SOURCE_MANUAL,
    STALE_TIMEOUT,
    UPDATE_INTERVAL,
    series_from_product_id,
)
from .protocol import derive_device_key

_LOGGER = logging.getLogger(__name__)

_HEX_CHARS = frozenset("0123456789abcdefABCDEF")

KEY_METHOD_CREATE = "create_new_key"
KEY_METHOD_EXISTING = "existing_key"
KEY_METHOD_CLOUD = "cloud_login"
KEY_METHOD_LOCAL = "local_claim"
# Ask for the user ID alone. The binding key is md5(account)[:10], so the
# number is the whole credential on the WP family, which is why this needs no
# cloud call, no capture and no WeChat openid.
KEY_METHOD_ACCOUNT = "account_number"


def _valid_device_key(key: str) -> bool:
    return len(key) == 10 and all(c in _HEX_CHARS for c in key)


def _generate_device_key() -> str:
    """Generate a random 10-character hex device key."""
    return secrets.token_hex(5)


def _default_entry_name(local_name: str | None, product_id: str | None) -> str:
    """Friendly default name for a station being added.

    Stations advertise only a family tag - "TT" for the Mega line, "WP" for the
    Guardian / D5 V2 line - and using that tag verbatim would title a device
    "WP". An advertisement carrying a real name keeps it.
    """
    tag = (local_name or "").strip().upper()
    if tag.startswith("WP") or series_from_product_id(product_id) == "guardian":
        return "OUPES Guardian"
    if tag.startswith("TT"):
        return "OUPES Mega"
    return (local_name or "").strip() or "OUPES Power Station"


def _identity_source_phrase(source: str) -> str:
    """Human wording for how a stored identity was obtained.

    A locally minted openId cannot be told apart from a vendor-assigned one by
    looking at it - same length, same alphabet - so the flow records where it
    came from and the UI reads that back.
    """
    if source == IDENTITY_SOURCE_LOCAL:
        return (
            "generated locally by this integration, which is why this station is "
            "absent from every vendor cloud account"
        )
    if source == IDENTITY_SOURCE_CLOUD:
        return "read from your OUPES / Cleanergy cloud account"
    if source == IDENTITY_SOURCE_MANUAL:
        return "typed in by hand"
    if source == IDENTITY_SOURCE_DERIVED:
        return (
            "derived here from your Cleanergy user ID, the same way the "
            "vendor app derives it, so there is nothing to keep in sync"
        )
    # Entries written before provenance was recorded: say nothing specific rather
    # than guess, because a wrong guess sends people hunting for a cloud binding
    # that was never there.
    return "recorded when this station was set up"


def _parse_account_number(raw: Any) -> int:
    """Read an user ID out of a form field.

    The UI control for this is a NumberSelector, which delivers a **float** over
    the websocket and a string over the REST flow API, so ``24680`` can arrive as
    ``24680``, ``24680.0`` or ``"24680"``. ``int("24680.0")`` raises, which used to
    reject a perfectly valid user ID on the first try. Empty, negative,
    fractional and non-numeric input all come back as 0, meaning "not given".
    """
    if raw is None:
        return 0
    if isinstance(raw, bool):
        return 0
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw) if raw == int(raw) else 0
    text = str(raw).strip()
    if not text:
        return 0
    try:
        number = float(text)
    except ValueError:
        return 0
    return int(number) if number == int(number) else 0


def resolve_key_on_account_change(
    previous_uid: int,
    stored_key: str,
    typed_key: str,
    new_uid: int,
) -> str:
    """Which device key to persist when the options form is submitted.

    The rule that matters: a key the integration **derived** is a function of the
    user ID, so if the user ID changes and the key box is left alone,
    carrying the old key over would make the station refuse the frame - it compares
    against the stored ``(user ID, key)`` pair the vendor app wrote, so a new
    user ID paired with a stale key reads as "re-pairing failed" when all that
    happened is a field nobody looked at kept its old value.

    A key the user **typed** is not a function of anything, so it always wins, and a
    stored key that is not ``md5(previous user ID)`` is treated as captured or
    hand-entered and is left alone rather than silently overwritten.

    Returns the key to store; an empty result means "nothing to store".
    """
    typed = (typed_key or "").strip()
    if typed:
        return typed

    stored = (stored_key or "").strip()
    new_uid = int(new_uid or 0)
    previous_uid = int(previous_uid or 0)

    if not new_uid or new_uid == previous_uid:
        # User ID unchanged, or none supplied: nothing here implies the key moved.
        return stored

    if not previous_uid:
        # There is no previous hash to compare against, so the stored key's provenance
        # is unknown and overwriting it would be a guess. With no stored key at all
        # there is nothing to guess about, and a derived key beats an empty one.
        return stored or derive_device_key(new_uid)

    derived_for_previous = derive_device_key(previous_uid)
    if stored and stored != derived_for_previous:
        # Not ours - it came from a capture or the cloud. Never overwrite it.
        return stored

    return derive_device_key(new_uid)


def _is_guardian_series(local_name: str | None, product_id: str | None) -> bool:
    """True when the station belongs to the Guardian / D5 V2 ("WP") family.

    Only these stations bind their AUTH frame to an account identity, so this
    decides whether setup has to obtain openId and userId at all. The advertised
    tag wins over product_id because it is present even when the manufacturer
    data carries no recognisable product field.
    """
    tag = (local_name or "").strip().upper()
    if tag.startswith("WP"):
        return True
    if tag.startswith("TT"):
        return False
    return series_from_product_id(product_id) == "guardian"


def _extract_device_id(manufacturer_data: dict[int, bytes]) -> str | None:
    """Extract the 20-char hex device_id from BLE manufacturer data."""
    for company_id, payload in manufacturer_data.items():
        if len(payload) < 21:
            continue
        flag = company_id & 0xFF
        if flag > 1:
            continue
        first_byte = (company_id >> 8) & 0xFF
        device_id = bytes([first_byte]) + payload[0:9]
        return device_id.hex()
    return None


def _extract_product_id(manufacturer_data: dict[int, bytes]) -> str | None:
    """Extract the 6-char ASCII product_id from BLE manufacturer data.

    The product_id occupies bytes 11-16 of the raw manufacturer AD payload,
    which maps to payload[9:15] after Bleak splits out the 2-byte company_id.
    """
    for company_id, payload in manufacturer_data.items():
        if len(payload) < 15:
            continue
        flag = company_id & 0xFF
        if flag > 1:
            continue
        try:
            pid = payload[9:15].decode("ascii")
            if pid.isprintable() and len(pid) == 6:
                return pid
        except (UnicodeDecodeError, ValueError):
            pass
    return None


def _extract_device_id_for_address(hass, address: str) -> str | None:
    """Search HA's known BLE advertisements for a device_id by MAC."""
    for svc in async_discovered_service_info(hass):
        if svc.address.upper() == address.upper():
            did = _extract_device_id(svc.manufacturer_data)
            if did:
                return did
    return None


def _extract_product_id_for_address(hass, address: str) -> str | None:
    """Search HA's known BLE advertisements for a product_id by MAC."""
    for svc in async_discovered_service_info(hass):
        if svc.address.upper() == address.upper():
            pid = _extract_product_id(svc.manufacturer_data)
            if pid:
                return pid
    return None


class OUPESMegaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OUPES Mega."""

    VERSION = 1

    @staticmethod
    @config_entries.callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "OUPESMegaOptionsFlow":
        return OUPESMegaOptionsFlow(config_entry)

    def __init__(self) -> None:
        self._address: str | None = None
        self._name: str | None = None
        self._device_id: str | None = None
        self._product_id: str | None = None
        self._pairing_key: str | None = None
        self._pairing_task: asyncio.Task | None = None
        self._pairing_error: str | None = None
        # Where a failed pairing hands the user back. Hard-coding create_key made a
        # failure from any other method appear on a form with a different title and
        # instructions that did not describe what had just been attempted.
        self._pairing_return_step: str = "create_key"
        self._wifi_ssid: str = ""
        self._wifi_psk: str = ""
        self._reconfigure_repair: bool = False
        self._reconfigure_task: asyncio.Task | None = None
        self._reconfigure_new_data: dict[str, Any] = {}
        # Recovered from the vendor cloud during the cloud-login step, when the
        # station happens to be bound to the account the user logged in with.
        # Guardian / D5 V2 units need both values in their AUTH frame, so
        # capturing them here saves a manual lookup afterwards. Empty means
        # "not recovered" and leaves the manual path in the options dialog.
        self._identity_open_id: str = ""
        self._identity_user_id: int = 0
        # Provenance of the two values above, so the UI can explain a station that
        # is deliberately missing from a cloud account. See const.py.
        self._identity_source: str = ""
        # The advertised BLE name ("TT" / "WP"), kept apart from _name because
        # _name may have been replaced by a friendly default title.
        self._advertised_name: str = ""
        # Which step to hand control back to once identity has been collected.
        self._identity_next: str = "connection_settings"

    # -- Automatic bluetooth discovery ------------------------------------

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfo
    ) -> FlowResult:
        """Invoked when HA discovers a 'TT' or 'WP' BLE advertisement."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._address = discovery_info.address
        self._device_id = _extract_device_id(discovery_info.manufacturer_data)
        self._product_id = _extract_product_id(discovery_info.manufacturer_data)
        self._advertised_name = discovery_info.name or ""
        self._name = _default_entry_name(discovery_info.name, self._product_id)

        self.context["title_placeholders"] = {
            "name": self._name,
            "address": self._address,
        }
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm the auto-discovered device, then go to method selection."""
        if user_input is not None:
            return await self.async_step_choose_method()

        device_id_display = self._device_id or "not detected"
        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "name": self._name,
                "address": self._address,
                "device_id": device_id_display,
            },
        )

    # -- Manual setup ------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """User-initiated config flow (manual MAC entry)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS].upper().strip()
            name = (user_input.get(CONF_NAME) or "OUPES Power Station").strip()

            parts = address.split(":")
            if len(parts) != 6 or not all(len(p) == 2 for p in parts):
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                self._address = address
                self._name = name
                self._device_id = _extract_device_id_for_address(
                    self.hass, address
                )
                self._product_id = _extract_product_id_for_address(
                    self.hass, address
                )
                return await self.async_step_choose_method()

        # Both families are offered as a suggested address. Filtering on "TT"
        # alone predates Guardian support and left anyone adding a "WP" station by
        # hand with an empty field and no hint that the station was right there.
        discovered = [
            svc
            for svc in async_discovered_service_info(self.hass)
            if (svc.name or "").strip().upper().startswith(("TT", "WP"))
        ]
        suggested_address = discovered[0].address if discovered else ""

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS, default=suggested_address): str,
                    vol.Optional(CONF_NAME, default="OUPES Power Station"): str,
                }
            ),
            errors=errors,
        )

    # -- Method selection --------------------------------------------------

    async def async_step_choose_method(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user pick how to provide the device key."""
        if user_input is not None:
            method = user_input["key_method"]
            if method == KEY_METHOD_CREATE:
                return await self.async_step_create_key()
            if method == KEY_METHOD_EXISTING:
                return await self.async_step_existing_key()
            if method == KEY_METHOD_CLOUD:
                return await self.async_step_cloud_login()
            if method == KEY_METHOD_LOCAL:
                return await self.async_step_local_claim()
            if method == KEY_METHOD_ACCOUNT:
                return await self.async_step_account_number()

        # Order is guidance, and it used to be actively wrong. On the WP family the
        # vendor cloud is the only source of the account identity the station insists
        # on, so leading with "Create a new device key" put the one option that cannot
        # finish on its own in front of the one that can.
        #
        # "Claim with a local identity" is not offered. It was measured on a
        # Guardian 6000 V2 on 2026-10-14: two factory resets, minted identity present
        # in the AUTH frame, both attempts timed out, while the same frame with the
        # real identity is accepted. A blank station does not accept any identity, so
        # the option would only cost someone a factory reset.
        guardian = _is_guardian_series(self._advertised_name, self._product_id)
        # All four are offered whatever the station is, because a hand-typed address
        # carries no advertisement and therefore no family. Manual entry is the path
        # for a station that no proxy could see, which is usually the newer family,
        # so hiding the user ID option here would hide it from exactly the
        # people who need it. The default still splits: an unrecognised station leads
        # with the legacy claim, a known Guardian with the derivation.
        methods = {
            KEY_METHOD_ACCOUNT: "Use my Cleanergy user ID",
            KEY_METHOD_CLOUD: "Fetch key from Cleanergy cloud account",
            KEY_METHOD_EXISTING: "Enter an existing device key",
            KEY_METHOD_CREATE: "Create a new device key (requires factory reset)",
        }

        return self.async_show_form(
            step_id="choose_method",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "key_method",
                        default=KEY_METHOD_ACCOUNT if guardian else KEY_METHOD_CREATE,
                    ): vol.In(methods)
                }
            ),
            description_placeholders={
                "name": self._name,
                "address": self._address,
            },
        )

    # -- Method A: Create new key via BLE pairing -------------------------

    async def async_step_create_key(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect the device key, then start pairing via progress step."""
        errors: dict[str, str] = {}

        # If we're returning here after a failed pairing, show the error.
        if self._pairing_error:
            errors["base"] = self._pairing_error
            self._pairing_error = None

        if user_input is not None:
            if user_input.get("go_back"):
                return await self.async_step_choose_method()
            new_key = user_input.get(CONF_DEVICE_KEY, "").strip().lower()
            if not new_key:
                new_key = _generate_device_key()
            elif not _valid_device_key(new_key):
                errors[CONF_DEVICE_KEY] = "invalid_device_key"

            if not errors:
                self._pairing_key = new_key
                self._wifi_ssid = user_input.get("wifi_ssid", "").strip()
                self._wifi_psk = user_input.get("wifi_psk", "").strip()
                # On this firmware family the identity frame and the WiFi frame are
                # different packets, and only the identity one is accepted. Accepting
                # an SSID here would therefore swap in a frame the station rejects,
                # turning an optional field into a failed pairing. Reject it at the
                # form, where the explanation is legible, instead of ~20 s of
                # "Device did not respond to pairing" for a field marked optional.
                if self._wifi_ssid and _is_guardian_series(
                    self._advertised_name, self._product_id
                ):
                    self._wifi_ssid = self._wifi_psk = ""
                    errors["wifi_ssid"] = "wifi_unsupported_guardian"

            if not errors:
                return await self._maybe_identity("pairing")

        suggested_key = self._pairing_key or _generate_device_key()
        return self.async_show_form(
            step_id="create_key",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_DEVICE_KEY, default=suggested_key): str,
                    vol.Optional("wifi_ssid", default=self._wifi_ssid): str,
                    vol.Optional("wifi_psk", default=self._wifi_psk): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional("go_back", default=False): bool,
                }
            ),
            description_placeholders={
                "name": self._name,
                "address": self._address,
            },
            errors=errors,
        )

    # -- Method D: Claim a station that has no cloud account --------------

    async def async_step_local_claim(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Write a locally generated identity and key into a blank station.

        NO LONGER OFFERED IN THE METHOD PICKER - measured, not guessed.

        The premise was that a factory-reset station has no identity stored and so
        must accept any well-formed one, since that is how the phone app binds it.
        On a Guardian 6000 V2 on 2026-10-14 that was wrong: two factory resets, each
        followed immediately by this path with the minted identity confirmed present
        in the AUTH frame, both timed out with the claim uncompleted. The same frame
        carrying the real cloud identity is accepted by the same station, so the
        single variable - the identity - is what the station checks.

        Kept for the day someone works out what makes an openId acceptable, since
        everything around it (threading identity into pairing, the encoder, the
        tests) is otherwise finished and passing. Do not re-offer it until a real
        station says yes.
        """
        errors: dict[str, str] = {}
        if self._pairing_error:
            errors["base"] = self._pairing_error
            self._pairing_error = None
        if user_input is not None:
            if user_input.get("go_back"):
                return await self.async_step_choose_method()
            if not user_input.get("confirm_local_claim"):
                errors["confirm_local_claim"] = "confirm_required"
            else:
                self._identity_open_id, self._identity_user_id = minted_identity()
                self._identity_source = IDENTITY_SOURCE_LOCAL
                self._pairing_return_step = "local_claim"
                if not self._pairing_key:
                    self._pairing_key = _generate_device_key()
                _LOGGER.info(
                    "Claiming %s with a locally generated identity; this station "
                    "will not appear in any vendor cloud account",
                    self._address,
                )
                return await self.async_step_pairing()

        return self.async_show_form(
            step_id="local_claim",
            data_schema=vol.Schema(
                {
                    vol.Optional("confirm_local_claim", default=False): bool,
                    vol.Optional("go_back", default=False): bool,
                }
            ),
            description_placeholders={"name": self._name},
            errors=errors,
        )

    # -- Shared: BLE pairing progress -------------------------------------

    async def async_step_pairing(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Run BLE pairing in the background while showing a progress spinner."""
        if self._pairing_task is None:
            kwargs = {
                "hass": self.hass,
                "address": self._address,
                "device_key": self._pairing_key,
                # Guardian / D5 V2 stations authenticate with the account
                # identity, so pairing has to have it: an identity-less AUTH is
                # answered and then dropped about four seconds later, which
                # leaves a freshly claimed station unusable.
                "open_id": self._identity_open_id,
                "user_id": self._identity_user_id,
            }
            if self._wifi_ssid:
                kwargs["ssid"] = self._wifi_ssid
                kwargs["psk"] = self._wifi_psk
            self._pairing_task = self.hass.async_create_task(
                async_pair_device(**kwargs),
            )

        if not self._pairing_task.done():
            return self.async_show_progress(
                step_id="pairing",
                progress_action="pairing",
                progress_task=self._pairing_task,
                description_placeholders={
                    "name": self._name,
                    "address": self._address,
                },
            )

        try:
            result = self._pairing_task.result()
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "Unexpected error during BLE pairing with %s",
                self._address,
            )
            result = PairingResult.CONNECTION_FAILED
        finally:
            self._pairing_task = None

        if result == PairingResult.SUCCESS:
            return self.async_show_progress_done(
                next_step_id="pairing_complete"
            )

        # Map failure to error key and go back to create_key form
        if result == PairingResult.DEVICE_NOT_FOUND:
            self._pairing_error = "pairing_device_not_found"
        elif result == PairingResult.CONNECTION_FAILED:
            self._pairing_error = "pairing_connection_failed"
        else:
            self._pairing_error = "pairing_timeout"

        return self.async_show_progress_done(
            next_step_id=self._pairing_return_step
        )

    async def async_step_pairing_complete(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pairing succeeded - proceed to connection settings."""
        return await self.async_step_connection_settings()

    # -- Method A2: User ID, key derived from it ---------------------

    async def async_step_account_number(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pair with nothing but the Cleanergy user ID.

        The binding key the vendor app writes is ``md5(account)[:10]``, so the
        user ID is the whole credential on this family and no capture,
        cloud read or openid is involved. Measured on a Guardian 6000 V2: this
        key with this userId is accepted and streams telemetry with the openId
        field zero-filled, while a foreign userId is refused - the station
        checks these two and ignores the third.

        Only reachable for a station the account has already added in the app,
        because that is what writes the pair into the station.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get("go_back"):
                return await self.async_step_choose_method()
            try:
                account = _parse_account_number(user_input.get(CONF_USER_ID))
            except (TypeError, ValueError):
                account = 0
            if account <= 0:
                errors[CONF_USER_ID] = "invalid_user_id"
            elif not user_id_fits(account):
                errors[CONF_USER_ID] = "invalid_user_id"
            else:
                self._identity_user_id = account
                # Warn, never lock out: a placeholder-shaped id is unusual, not
                # impossible, and refusing it would be an account lockout for
                # whoever holds the earliest account. One WARNING per accepted
                # value (flows run once per attempt, not per poll), phrased so a
                # later BLE timeout in the log points back at its real cause.
                if (risk := describe_identity_risk(account)) is not None:
                    _LOGGER.warning("Accepted user ID may be a placeholder: %s", risk)
                self._pairing_key = derive_device_key(account)
                # Deliberately left empty. The station does not read this field,
                # and inventing a plausible-looking one would be worse than
                # leaving it blank: it would look like a real account link.
                self._identity_open_id = ""
                self._identity_source = IDENTITY_SOURCE_DERIVED
                return await self.async_step_connection_settings()

        return self.async_show_form(
            step_id="account_number",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USER_ID, default=self._identity_user_id or 0
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=USER_ID_MAX,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional("go_back", default=False): bool,
                }
            ),
            description_placeholders={
                "name": self._name,
                "address": self._address,
            },
            errors=errors,
        )

    # -- Method B: Enter existing key -------------------------------------

    async def async_step_existing_key(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manual entry of an already-known device key."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get("go_back"):
                return await self.async_step_choose_method()
            raw_key = user_input.get(CONF_DEVICE_KEY, "").strip().lower()
            if not _valid_device_key(raw_key):
                errors[CONF_DEVICE_KEY] = "invalid_device_key"
            else:
                self._pairing_key = raw_key
                return await self._maybe_identity("connection_settings")

        return self.async_show_form(
            step_id="existing_key",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_DEVICE_KEY, default=""): str,
                    vol.Optional("go_back", default=False): bool,
                }
            ),
            description_placeholders={
                "name": self._name,
                "address": self._address,
            },
            errors=errors,
        )

    # -- Method C: Cloud login --------------------------------------------

    async def async_step_cloud_login(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Fetch the device key from the Cleanergy cloud API."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get("go_back"):
                return await self.async_step_choose_method()
            email = user_input.get("cloud_email", "").strip()
            password = user_input.get("cloud_password", "").strip()

            if not email or not password:
                errors["cloud_email"] = "cloud_login_failed"
            else:
                key, identity = await _cloud_fetch_key_and_identity(
                    self.hass,
                    email,
                    password,
                    self._device_id,
                    self._address,
                )
                if identity is not None and identity.ok:
                    self._identity_open_id = identity.open_id or ""
                    self._identity_user_id = int(identity.user_id or 0)
                    self._identity_source = IDENTITY_SOURCE_CLOUD

                if key:
                    # The cloud holds a real key for this station: pair with it.
                    self._pairing_key = key
                    return await self._maybe_identity("connection_settings")

                if identity is not None and identity.ok:
                    # The cloud record stores the family tag ("WP") in device_key
                    # instead of a real key on this firmware - measured on three
                    # accounts, never a key. That used to mean falling back to a
                    # BLE claim, which the station refuses. It does not need one:
                    # the app writes md5(account)[:10] as the binding key, so the
                    # user ID the login just returned derives it, and the
                    # station is already paired because the owner added it in the
                    # app. Nothing is written to the station on this path.
                    self._pairing_key = derive_device_key(int(identity.user_id))
                    self._identity_source = IDENTITY_SOURCE_DERIVED
                    _LOGGER.info(
                        "OUPES cloud carries no device_key for this station (the "
                        "record holds the family tag), so the binding key was "
                        "derived from the user ID instead"
                    )
                    return await self.async_step_connection_settings()

                # Login worked but the station is not in that account, or the
                # record has no identity. Say which, because the two need
                # different fixes and a station that was unbound from the cloud
                # is a normal state rather than a wrong password.
                errors["cloud_email"] = (
                    f"cloud_identity_{identity.reason}"
                    if identity is not None
                    else "cloud_login_failed"
                )

        return self.async_show_form(
            step_id="cloud_login",
            data_schema=vol.Schema(
                {
                    vol.Optional("cloud_email", default=""): str,
                    vol.Optional("cloud_password", default=""): str,
                    vol.Optional("go_back", default=False): bool,
                }
            ),
            description_placeholders={
                "name": self._name,
                "address": self._address,
            },
            errors=errors,
        )


    # -- Connection settings (final step before entry creation) ----------

    def _needs_identity(self) -> bool:
        """Whether this station still needs an user ID before continuing.

        Guardian / D5 V2 stations put the account identity inside their AUTH
        frame, so without it the station answers and then drops Bluetooth a few
        seconds later - which reads exactly like a range problem. Legacy "TT"
        stations never need it, and a Guardian whose identity already came from
        the cloud does not have to be asked.
        """
        # Only the userId. Measured on a Guardian 6000 V2: the station accepts
        # the frame with the openId field zero-filled and streams telemetry, so
        # asking for it blocks setups for a value the device never reads.
        if self._identity_user_id:
            return False
        return _is_guardian_series(self._advertised_name, self._product_id)

    async def _maybe_identity(self, next_step: str) -> FlowResult:
        """Insert the identity step when the station needs one."""
        if not self._needs_identity():
            if next_step == "pairing":
                return await self.async_step_pairing()
            return await self.async_step_connection_settings()
        self._identity_next = next_step
        return await self.async_step_identity()

    async def async_step_identity(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for the account identity a Guardian / D5 V2 station requires.

        This step is the fallback for the case the cloud could not supply the
        identity - a station that has been unbound from its account, or bound to
        a different one. It is deliberately a dead end for nothing: the values
        are stored on the entry exactly as if the cloud had provided them.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            open_id = str(user_input.get(CONF_OPEN_ID, "") or "").strip()
            try:
                user_id = _parse_account_number(user_input.get(CONF_USER_ID))
            except (TypeError, ValueError):
                user_id = -1

            if not open_id_fits(open_id):
                errors[CONF_OPEN_ID] = "invalid_open_id"
            if user_id <= 0:
                errors[CONF_USER_ID] = "invalid_user_id"

            if not errors:
                self._identity_open_id = open_id
                self._identity_user_id = user_id
                if (risk := describe_identity_risk(user_id)) is not None:
                    _LOGGER.warning("Accepted user ID may be a placeholder: %s", risk)
                self._identity_source = IDENTITY_SOURCE_MANUAL
                if self._identity_next == "pairing":
                    return await self.async_step_pairing()
                return await self.async_step_connection_settings()

        return self.async_show_form(
            step_id="identity",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_OPEN_ID, default=self._identity_open_id): (
                        TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))
                    ),
                    vol.Required(
                        CONF_USER_ID, default=self._identity_user_id or 0
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=USER_ID_MAX,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
            description_placeholders={"name": self._name},
            errors=errors,
        )

    async def async_step_connection_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user choose connection mode before creating the entry."""
        if user_input is not None:
            if user_input.get("go_back"):
                return await self.async_step_choose_method()
            continuous = user_input.get(CONF_CONTINUOUS, True)
            poll_interval = int(user_input.get(
                CONF_POLL_INTERVAL, UPDATE_INTERVAL.total_seconds()
            ))
            live_push_interval = float(user_input.get(
                CONF_LIVE_PUSH_INTERVAL, LIVE_PUSH_MIN_INTERVAL
            ))
            stale_timeout = int(user_input.get(
                CONF_STALE_TIMEOUT, STALE_TIMEOUT.total_seconds() // 60
            ))
            runtime_max = int(user_input.get(CONF_RUNTIME_MAX, ATTR78_RUNTIME_MAX))
            debug_attrs = user_input.get(CONF_DEBUG_ATTRS, False)
            debug_raw = user_input.get(CONF_DEBUG_RAW, False)
            await self.async_set_unique_id(self._address)
            self._abort_if_unique_id_configured()
            options = {
                CONF_CONTINUOUS: continuous,
                CONF_POLL_INTERVAL: poll_interval,
                CONF_LIVE_PUSH_INTERVAL: live_push_interval,
                CONF_STALE_TIMEOUT: stale_timeout,
                CONF_RUNTIME_MAX: runtime_max,
                CONF_DEBUG_ATTRS: debug_attrs,
                CONF_DEBUG_RAW: debug_raw,
                # Empty for Mega-family stations and for any Guardian whose
                # cloud binding could not be read; the options dialog is the
                # fallback in both cases.
                CONF_OPEN_ID: self._identity_open_id,
                CONF_USER_ID: self._identity_user_id,
            }
            if self._identity_source:
                # Recorded, never inferred: a minted openId looks exactly like a
                # vendor-assigned one, and "local" is the only clue that the
                # station will never show up in a cloud device list.
                options[CONF_IDENTITY_SOURCE] = self._identity_source
            return self.async_create_entry(
                title=self._name,
                data={
                    CONF_ADDRESS: self._address,
                    CONF_NAME: self._name,
                    CONF_DEVICE_KEY: self._pairing_key,
                    CONF_DEVICE_ID: self._device_id or "",
                    CONF_PRODUCT_ID: self._product_id or "",
                },
                options=options,
            )

        default_poll = int(UPDATE_INTERVAL.total_seconds())
        default_stale = int(STALE_TIMEOUT.total_seconds() // 60)
        default_live_push = float(LIVE_PUSH_MIN_INTERVAL)

        return self.async_show_form(
            step_id="connection_settings",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CONTINUOUS, default=True): bool,
                    vol.Optional(
                        CONF_POLL_INTERVAL, default=default_poll,
                    ): NumberSelector(NumberSelectorConfig(
                        min=10, max=600, step=1, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )),
                    vol.Optional(
                        CONF_LIVE_PUSH_INTERVAL, default=default_live_push,
                    ): NumberSelector(NumberSelectorConfig(
                        min=1, max=30, step=1, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )),
                    vol.Optional(
                        CONF_STALE_TIMEOUT, default=default_stale,
                    ): NumberSelector(NumberSelectorConfig(
                        min=1, max=120, step=1, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="minutes",
                    )),
                    vol.Optional(
                        CONF_RUNTIME_MAX, default=ATTR78_RUNTIME_MAX,
                    ): NumberSelector(NumberSelectorConfig(
                        min=100, max=50000, step=60, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="minutes",
                    )),
                    vol.Required(CONF_DEBUG_ATTRS, default=False): bool,
                    vol.Required(CONF_DEBUG_RAW, default=False): bool,
                    vol.Optional("go_back", default=False): bool,
                }
            ),
            description_placeholders={
                "name": self._name,
                "address": self._address,
            },
        )

    # -- Reconfigure / re-pair an existing entry -----------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Re-pair or re-provision an already configured device.

        Keeps the same config entry (and therefore all entity IDs and
        history) while re-running the BLE claim sequence or just pushing
        fresh WiFi credentials to the device.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        # Surface errors reported by the background pairing task.
        if self._pairing_error:
            errors["base"] = self._pairing_error
            self._pairing_error = None

        current_key = (
            entry.options.get(CONF_DEVICE_KEY)
            or entry.data.get(CONF_DEVICE_KEY)
            or ""
        )
        current_address = entry.data.get(CONF_ADDRESS, "")
        current_name = entry.data.get(CONF_NAME, "OUPES Power Station")

        if user_input is not None:
            address = user_input.get(CONF_ADDRESS, "").upper().strip()
            name = (user_input.get(CONF_NAME) or current_name).strip()
            device_key = user_input.get(CONF_DEVICE_KEY, "").strip().lower()
            repair = user_input.get("rerun_pairing", False)
            ssid = user_input.get("wifi_ssid", "").strip()
            psk = user_input.get("wifi_psk", "").strip()

            parts = address.split(":")
            if len(parts) != 6 or not all(len(p) == 2 for p in parts):
                errors[CONF_ADDRESS] = "invalid_address"
            elif address != current_address.upper():
                # Guard against pointing this entry at an already configured MAC.
                for other in self.hass.config_entries.async_entries(DOMAIN):
                    if other.entry_id == entry.entry_id:
                        continue
                    if other.data.get(CONF_ADDRESS, "").upper() == address:
                        errors[CONF_ADDRESS] = "already_configured_address"
                        break

            if not _valid_device_key(device_key):
                errors[CONF_DEVICE_KEY] = "invalid_device_key"

            if not errors:
                # See the note in async_step_create_key: an SSID on a Guardian
                # silently downgrades the AUTH frame to one the station drops.
                if ssid and _is_guardian_series(
                    entry.data.get(CONF_NAME, ""), entry.data.get(CONF_PRODUCT_ID)
                ):
                    errors["wifi_ssid"] = "wifi_unsupported_guardian"

            if not errors:
                self._address = address
                self._name = name
                self._pairing_key = device_key
                self._wifi_ssid = ssid
                self._wifi_psk = psk
                self._reconfigure_repair = repair
                # Re-detect the BLE identifiers if we never captured them.
                device_id = entry.data.get(CONF_DEVICE_ID, "") or (
                    _extract_device_id_for_address(self.hass, address) or ""
                )
                product_id = entry.data.get(CONF_PRODUCT_ID, "") or (
                    _extract_product_id_for_address(self.hass, address) or ""
                )
                self._reconfigure_new_data = {
                    **entry.data,
                    CONF_ADDRESS: address,
                    CONF_NAME: name,
                    CONF_DEVICE_KEY: device_key,
                    CONF_DEVICE_ID: device_id,
                    CONF_PRODUCT_ID: product_id,
                }

                if repair or ssid:
                    return await self.async_step_reconfigure_pairing()
                return await self.async_step_reconfigure_save()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=current_name): str,
                    vol.Required(CONF_ADDRESS, default=current_address): str,
                    vol.Required(CONF_DEVICE_KEY, default=current_key): str,
                    vol.Optional("rerun_pairing", default=False): bool,
                    vol.Optional("wifi_ssid", default=self._wifi_ssid): str,
                    vol.Optional("wifi_psk", default=self._wifi_psk): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            description_placeholders={
                "name": current_name,
                "address": current_address,
            },
            errors=errors,
        )

    async def async_step_reconfigure_pairing(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Run re-pairing / WiFi provisioning in the background."""
        if self._reconfigure_task is None:
            kwargs = {
                "hass": self.hass,
                "address": self._address,
                "device_key": self._pairing_key,
            }
            if self._reconfigure_repair:
                # Full claim sequence - device must be in pairing mode. Re-run it
                # with the identity already on the entry, or a Guardian will drop
                # the link seconds after being re-paired.
                reconf_entry = self._get_reconfigure_entry()
                kwargs["open_id"] = str(
                    reconf_entry.options.get(CONF_OPEN_ID, "") or ""
                )
                try:
                    kwargs["user_id"] = int(reconf_entry.options.get(CONF_USER_ID, 0) or 0)
                except (TypeError, ValueError):
                    kwargs["user_id"] = 0
                # Full claim sequence - device must be in pairing mode.
                if self._wifi_ssid:
                    kwargs["ssid"] = self._wifi_ssid
                    kwargs["psk"] = self._wifi_psk
                coro = async_pair_device(**kwargs)
            else:
                # Soft re-provision - no factory reset, just new credentials.
                kwargs["ssid"] = self._wifi_ssid
                kwargs["psk"] = self._wifi_psk
                coro = async_provision_wifi(**kwargs)
            self._reconfigure_task = self.hass.async_create_task(coro)

        if not self._reconfigure_task.done():
            return self.async_show_progress(
                step_id="reconfigure_pairing",
                progress_action=(
                    "pairing" if self._reconfigure_repair else "provisioning_wifi"
                ),
                progress_task=self._reconfigure_task,
                description_placeholders={
                    "name": self._name,
                    "address": self._address,
                },
            )

        try:
            result = self._reconfigure_task.result()
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "Unexpected error while re-pairing OUPES Mega %s", self._address
            )
            result = PairingResult.CONNECTION_FAILED
        finally:
            self._reconfigure_task = None

        if result == PairingResult.SUCCESS:
            return self.async_show_progress_done(next_step_id="reconfigure_save")

        if result == PairingResult.DEVICE_NOT_FOUND:
            self._pairing_error = "pairing_device_not_found"
        elif result == PairingResult.CONNECTION_FAILED:
            self._pairing_error = "pairing_connection_failed"
        else:
            self._pairing_error = "pairing_timeout"

        return self.async_show_progress_done(next_step_id="reconfigure")

    async def async_step_reconfigure_save(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Persist the reconfigured device data and reload the entry."""
        entry = self._get_reconfigure_entry()
        data = self._reconfigure_new_data or dict(entry.data)

        # The device key may also live in options, where it takes priority
        # over entry.data - keep the two in sync so the new key is used.
        options = dict(entry.options)
        if CONF_DEVICE_KEY in options:
            options[CONF_DEVICE_KEY] = data[CONF_DEVICE_KEY]

        return self.async_update_reload_and_abort(
            entry,
            unique_id=data[CONF_ADDRESS],
            title=data.get(CONF_NAME) or entry.title,
            data=data,
            options=options,
            reason="reconfigure_successful",
        )


# -- Helper -------------------------------------------------------------------

async def _cloud_fetch_key_and_identity(
    hass,
    email: str,
    password: str,
    device_id: str | None,
    mac_address: str | None,
) -> tuple[str | None, Any]:
    """Log in to the OUPES cloud once and take the key *and* the account identity.

    Returns ``(device_key, CloudIdentity | None)``. The identity half is best
    effort: it needs the station to appear in that account's bound-device list,
    which is not true of a station that was unbound from the cloud, and the
    caller must cope with that.
    """
    try:
        login_info = await async_cloud_login_info(hass, email, password)
        if not login_info:
            return None, None
        key = await async_fetch_device_key(
            hass,
            device_id=device_id,
            mac_address=mac_address,
            token=login_info.get("token") or "",
        )
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Cloud key fetch failed", exc_info=True)
        return None, None

    identity = None
    try:
        identity = await async_fetch_cloud_identity(
            hass,
            device_id=device_id,
            mac_address=mac_address,
            login_info=login_info,
        )
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Cloud identity lookup failed", exc_info=True)
    return key, identity


# -- Options flow (unchanged) -------------------------------------------------

class OUPESMegaOptionsFlow(config_entries.OptionsFlow):
    """Options flow - lets the user toggle continuous BLE connection mode."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        current_key = (
            self._entry.options.get(CONF_DEVICE_KEY)
            or self._entry.data.get(CONF_DEVICE_KEY)
            or ""
        )
        default_poll = int(UPDATE_INTERVAL.total_seconds())
        default_stale = int(STALE_TIMEOUT.total_seconds() // 60)
        default_live_push = float(LIVE_PUSH_MIN_INTERVAL)

        if user_input is not None:
            raw_key = str(user_input.get(CONF_DEVICE_KEY, "") or "").strip()
            raw_open_id = str(user_input.get(CONF_OPEN_ID, "") or "").strip()
            fetch_mail = str(user_input.get("cloud_email", "") or "").strip()
            fetch_passwd = str(user_input.get("cloud_password", "") or "").strip()
            try:
                raw_user_id = _parse_account_number(user_input.get(CONF_USER_ID))
            except (TypeError, ValueError):
                raw_user_id = -1
            # Set before the optional lookup below: the provenance update at the
            # end reads it whether or not credentials were entered.
            identity = None

            # Optional lookup, so nobody has to poke the vendor API by hand. The
            # credentials exist only inside this call: they are not part of the
            # opts built below, so they cannot reach .storage. Leaving both
            # fields empty keeps the manual path and touches nothing.
            if fetch_mail and fetch_passwd:
                try:
                    identity = await async_fetch_cloud_identity(
                        self.hass,
                        fetch_mail,
                        fetch_passwd,
                        device_id=str(self._entry.data.get(CONF_DEVICE_ID, "") or ""),
                        mac_address=str(self._entry.data.get(CONF_ADDRESS, "") or ""),
                    )
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("Cloud identity lookup failed", exc_info=True)
                    identity = None
                if identity is not None and identity.ok:
                    raw_open_id = identity.open_id or ""
                    raw_user_id = int(identity.user_id or 0)
                else:
                    errors["cloud_email"] = (
                        f"cloud_identity_{identity.reason}"
                        if identity is not None
                        else "cloud_identity_login_failed"
                    )

            if raw_key and not _valid_device_key(raw_key):
                errors[CONF_DEVICE_KEY] = "invalid_device_key"
            # openId occupies a 33-byte field on the wire (32 usable chars plus a
            # terminator) and the user id a 5-byte big-endian integer; anything
            # larger cannot be transmitted, so reject it here rather than have
            # the station silently refuse the frame.
            if not open_id_fits(raw_open_id):
                errors[CONF_OPEN_ID] = "invalid_open_id"
            if not user_id_fits(raw_user_id):
                errors[CONF_USER_ID] = "invalid_user_id"

            if not errors:
                # Assembled field by field instead of copying user_input, so that
                # a future schema addition (credentials, above all) cannot be
                # persisted by accident. Anything absent from this list is simply
                # not stored.
                opts = dict(self._entry.options)
                previous_uid = int(
                    self._entry.options.get(CONF_USER_ID)
                    or self._entry.data.get(CONF_USER_ID)
                    or 0
                )
                opts[CONF_DEVICE_KEY] = resolve_key_on_account_change(
                    previous_uid=previous_uid,
                    stored_key=current_key,
                    typed_key=raw_key,
                    new_uid=raw_user_id,
                )
                opts[CONF_OPEN_ID] = raw_open_id
                opts[CONF_USER_ID] = raw_user_id
                # Only a hand-typed id can be placeholder-shaped; when the cloud
                # supplied it, raw_user_id was replaced by the vendor's value.
                if (identity is None or not identity.ok) and (
                    risk := describe_identity_risk(raw_user_id)
                ) is not None:
                    _LOGGER.warning("Accepted user ID may be a placeholder: %s", risk)
                # Keep provenance honest. A cloud lookup overwrites both values so
                # it also overwrites the label; a hand-edited openId is no longer
                # whatever the previous label claimed. Without this, an entry that
                # was minted locally and later fixed up from the cloud would go on
                # telling the owner to look for a binding that does exist.
                if identity is not None and identity.ok:
                    opts[CONF_IDENTITY_SOURCE] = IDENTITY_SOURCE_CLOUD
                elif raw_open_id != str(
                    self._entry.options.get(CONF_OPEN_ID, "") or ""
                ):
                    opts[CONF_IDENTITY_SOURCE] = IDENTITY_SOURCE_MANUAL
                opts[CONF_CONTINUOUS] = bool(user_input.get(CONF_CONTINUOUS, True))
                opts[CONF_POLL_INTERVAL] = int(
                    user_input.get(CONF_POLL_INTERVAL, default_poll)
                )
                opts[CONF_LIVE_PUSH_INTERVAL] = float(
                    user_input.get(CONF_LIVE_PUSH_INTERVAL, default_live_push)
                )
                opts[CONF_STALE_TIMEOUT] = int(
                    user_input.get(CONF_STALE_TIMEOUT, default_stale)
                )
                opts[CONF_RUNTIME_MAX] = int(
                    user_input.get(CONF_RUNTIME_MAX, ATTR78_RUNTIME_MAX)
                )
                opts[CONF_DEBUG_ATTRS] = bool(user_input.get(CONF_DEBUG_ATTRS, False))
                opts[CONF_DEBUG_RAW] = bool(user_input.get(CONF_DEBUG_RAW, False))
                return self.async_create_entry(title="", data=opts)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_DEVICE_KEY, default=current_key): str,
                    vol.Optional(
                        CONF_OPEN_ID,
                        default=self._entry.options.get(CONF_OPEN_ID, ""),
                    ): TextSelector(TextSelectorConfig(multiline=False)),
                    vol.Optional(
                        CONF_USER_ID,
                        default=self._entry.options.get(CONF_USER_ID, 0),
                    ): NumberSelector(NumberSelectorConfig(
                        min=0, max=1099511627775, step=1, mode=NumberSelectorMode.BOX,
                    )),
                    vol.Required(
                        CONF_CONTINUOUS,
                        default=self._entry.options.get(CONF_CONTINUOUS, True),
                    ): bool,
                    vol.Optional(
                        CONF_POLL_INTERVAL,
                        default=self._entry.options.get(CONF_POLL_INTERVAL, default_poll),
                    ): NumberSelector(NumberSelectorConfig(
                        min=10, max=600, step=1, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )),
                    vol.Optional(
                        CONF_LIVE_PUSH_INTERVAL,
                        default=float(self._entry.options.get(
                            CONF_LIVE_PUSH_INTERVAL, default_live_push
                        )),
                    ): NumberSelector(NumberSelectorConfig(
                        min=1, max=30, step=1, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )),
                    vol.Optional(
                        CONF_STALE_TIMEOUT,
                        default=self._entry.options.get(CONF_STALE_TIMEOUT, default_stale),
                    ): NumberSelector(NumberSelectorConfig(
                        min=1, max=120, step=1, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="minutes",
                    )),
                    vol.Optional(
                        CONF_RUNTIME_MAX,
                        default=self._entry.options.get(CONF_RUNTIME_MAX, ATTR78_RUNTIME_MAX),
                    ): NumberSelector(NumberSelectorConfig(
                        min=100, max=50000, step=60, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="minutes",
                    )),
                    vol.Required(
                        CONF_DEBUG_ATTRS,
                        default=self._entry.options.get(CONF_DEBUG_ATTRS, False),
                    ): bool,
                    vol.Required(
                        CONF_DEBUG_RAW,
                        default=self._entry.options.get(CONF_DEBUG_RAW, False),
                    ): bool,
                    # Transient: used for one cloud request and dropped before the
                    # options are written. Kept at the end of the form so the two
                    # identity fields above read as the primary path.
                    vol.Optional("cloud_email", default=""): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.EMAIL)
                    ),
                    vol.Optional("cloud_password", default=""): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
            # Says where the stored identity came from. A locally minted openId is
            # indistinguishable from a vendor-assigned one by inspection, so this
            # reads the provenance recorded when it was written - and "why is my
            # station missing from my cloud account" stops being a debugging job.
            description_placeholders={
                "identity_source": _identity_source_phrase(
                    str(self._entry.options.get(CONF_IDENTITY_SOURCE, "") or "")
                ),
            },
        )

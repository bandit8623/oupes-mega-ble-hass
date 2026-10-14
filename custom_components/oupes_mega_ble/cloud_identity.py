"""Cloud account identity used by Guardian / D5 V2 ("WP") stations.

Those stations build their BLE AUTH frame (the ``0xA8`` config-net-info packet)
around the *cloud identity* of the account the station is bound to: the
account's ``openId`` string and its numeric id. Both are identifiers, not
credentials - the account password is only ever used to obtain them, and this
integration never stores it.

This module is deliberately free of Home Assistant and ``aiohttp`` imports, so
the vendor JSON shapes and the on-the-wire field limits can be unit tested
without a running Home Assistant (see ``tests/test_cloud_identity.py``).
Everything that talks to the network lives in :mod:`.cloud_api`.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

# On the wire openId occupies a 33-byte field (32 usable characters plus a
# terminator) and the user id a 5-byte big-endian integer, so longer values
# cannot be transmitted at all and must be rejected before we try.
OPEN_ID_MAX_LEN = 32
USER_ID_MAX = 2**40 - 1

# Vendor JSON is inconsistent about casing between endpoints, so accept the
# variants seen in the wild rather than betting on one.
_OPEN_ID_KEYS = ("openId", "open_id", "openid", "openID", "owner_open_id")
_USER_ID_KEYS = ("uid", "userId", "user_id", "user")

# Outcome codes surfaced to the UI as translation keys
# (errors.cloud_identity_<reason>).
REASON_OK = "ok"
REASON_LOGIN_FAILED = "login_failed"
REASON_NOT_BOUND = "not_bound"
REASON_NO_OPEN_ID = "no_open_id"


class CloudIdentity:
    """Result of a cloud identity lookup.

    ``ok`` is True only when both halves of the identity were recovered.
    Otherwise ``reason`` names the failure so the UI can explain it instead of
    showing a generic "login failed".
    """

    __slots__ = ("open_id", "user_id", "reason")

    def __init__(
        self,
        open_id: str | None = None,
        user_id: int | None = None,
        reason: str = REASON_NO_OPEN_ID,
    ) -> None:
        self.open_id = open_id
        self.user_id = user_id
        self.reason = reason

    @property
    def ok(self) -> bool:
        return self.reason == REASON_OK and bool(self.open_id) and bool(self.user_id)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"CloudIdentity(open_id={self.open_id!r}, user_id={self.user_id!r}, reason={self.reason!r})"


def open_id_fits(value: Any) -> bool:
    """True when *value* is empty (meaning "not set") or fits the wire field."""
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    return len(text) <= OPEN_ID_MAX_LEN and text.isascii()


def user_id_fits(value: Any) -> bool:
    """True when *value* is 0 (meaning "not set") or fits the wire field."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return False
    return 0 <= number <= USER_ID_MAX


def coerce_user_id(raw: Any) -> int | None:
    """Normalise a vendor user id (int or decimal string) to ``int``.

    Returns ``None`` for anything unusable, including zero and negative values,
    which never identify an account.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if 0 < raw <= USER_ID_MAX else None
    if isinstance(raw, str):
        text = raw.strip()
        if not text.isdigit():
            return None
        number = int(text)
        return number if 0 < number <= USER_ID_MAX else None
    return None


def extract_open_id(record: Mapping[str, Any] | None) -> str | None:
    """Pull an openId out of a vendor record, or ``None`` if absent/unsuitable."""
    if not isinstance(record, Mapping):
        return None
    for key in _OPEN_ID_KEYS:
        value = record.get(key)
        if not isinstance(value, str):
            continue
        text = value.strip()
        # The cloud has been known to pad these fields; strip NUL/padding.
        text = text.strip("\x00").strip()
        if not text or text == "WP":
            # "WP" is the placeholder the vendor stores in some device records
            # in place of a real identity - never usable as an openId.
            continue
        if len(text) <= OPEN_ID_MAX_LEN and text.isascii():
            return text
    return None


def extract_user_id(*sources: Mapping[str, Any] | None) -> int | None:
    """First plausible user id across *sources*, login response first."""
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in _USER_ID_KEYS:
            number = coerce_user_id(source.get(key))
            if number is not None:
                return number
    return None


def normalise_mac(value: Any) -> str:
    """Upper-case colon form, so ``aa-bb-...`` and ``AA:BB:...`` compare equal."""
    return str(value or "").upper().replace("-", ":")


def find_device_record(
    records: Iterable[Mapping[str, Any]] | None,
    *,
    device_id: str | None = None,
    mac_address: str | None = None,
) -> Mapping[str, Any] | None:
    """Match a bound-device record by cloud ``device_id`` then by MAC.

    Matching order matters: ``device_id`` comes from the BLE advertisement and
    is exact, whereas MAC comparison is a fallback for firmware that does not
    advertise it.
    """
    if not records:
        return None
    records = list(records)
    if device_id:
        for record in records:
            if str(record.get("device_id") or "") == device_id:
                return record
    target = normalise_mac(mac_address)
    if target and target != ":":
        for record in records:
            if normalise_mac(record.get("mac_address")) == target:
                return record
    return None


def resolve_identity(
    login_info: Mapping[str, Any] | None,
    bound_records: Iterable[Mapping[str, Any]] | None,
    *,
    device_id: str | None = None,
    mac_address: str | None = None,
    account_open_id: Mapping[str, Any] | None = None,
) -> CloudIdentity:
    """Work out the station's owning identity from a login response + device list.

    ``openId`` is read from the station's own bound record when present, since a
    single account can own several stations, and falls back to *account_open_id*
    for the (rare) accounts where the platform exposes it only at account level.
    """
    user_id = extract_user_id(login_info)
    record = find_device_record(bound_records, device_id=device_id, mac_address=mac_address)

    if record is None:
        return CloudIdentity(user_id=user_id, reason=REASON_NOT_BOUND)

    open_id = extract_open_id(record) or extract_open_id(account_open_id) or extract_open_id(login_info)
    if not open_id or user_id is None:
        return CloudIdentity(open_id=open_id, user_id=user_id, reason=REASON_NO_OPEN_ID)

    return CloudIdentity(open_id=open_id, user_id=user_id, reason=REASON_OK)

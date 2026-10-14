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

import logging
import re

from typing import Any, Iterable, Mapping

# On the wire openId occupies a 33-byte field (32 usable characters plus a
# terminator) and the user id a 5-byte big-endian integer, so longer values
# cannot be transmitted at all and must be rejected before we try.
OPEN_ID_MAX_LEN = 32
USER_ID_MAX = 2**40 - 1

# Vendor JSON is inconsistent about casing between endpoints, so accept the
# variants seen in the wild rather than betting on one.
_OPEN_ID_KEYS = ("openId", "open_id", "openid", "openID", "owner_open_id")
_LOGGER = logging.getLogger(__name__)
# The vendor has never been confused about spelling in front of us, and the two
# endpoints this family's stations are read from do not carry the field at the
# top level at all (measured: a bound Guardian record exposes addtime, device_id,
# device_key, device_product_id, firmware_version, home, id, mac_address, name,
# online, pic, sku, sn, system, title). So matching is by shape rather than by a
# hand-copied spelling list, and the search descends into nested objects such as
# ``home``, which is the one plausible owner-identity container left unexamined.
_OPEN_ID_KEY_RE = re.compile(r"open_?id", re.IGNORECASE)

# Vendor payloads nest at most two levels deep in what has been observed; the
# limit exists so a malformed or self-referential response cannot spin.
_MAX_SEARCH_DEPTH = 4
_USER_ID_KEYS = ("uid", "userId", "user_id", "user")

# Outcome codes surfaced to the UI as translation keys
# (errors.cloud_identity_<reason>).
REASON_OK = "ok"
REASON_LOGIN_FAILED = "login_failed"
REASON_NOT_BOUND = "not_bound"
REASON_NO_OPEN_ID = "no_open_id"
REASON_NO_USER_ID = "no_user_id"


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


def _usable_open_id(value: Any) -> str | None:
    """Normalise and validate one candidate value, or return ``None``."""
    if not isinstance(value, str):
        return None
    text = value.strip().strip("\x00").strip()
    if not text or text == "WP":
        # "WP" is the placeholder the vendor stores in some device records in
        # place of a real identity - never usable as an openId.
        return None
    if len(text) <= OPEN_ID_MAX_LEN and text.isascii():
        return text
    return None


def _mappings_in(
    obj: Any, depth: int = 0
):
    """Yield *obj* and every mapping nested inside it, to *_MAX_SEARCH_DEPTH*.

    Lists are traversed too: the vendor returns device collections, and an owner
    object reached through one is no less the owner.
    """
    if depth > _MAX_SEARCH_DEPTH:
        return
    if isinstance(obj, Mapping):
        yield obj
        for value in obj.values():
            yield from _mappings_in(value, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            yield from _mappings_in(value, depth + 1)


def describe_key_paths(obj: Any, max_paths: int = 80) -> list[str]:
    """Dotted *names* of every field reachable in *obj*; never any values.

    The diagnostic that settled where the account identity lives had to be safe
    to write to a world-readable log file, so it reports structure only: a
    renaming shows up here just as clearly as the value would, without putting an
    account identifier on disk.
    """
    paths: list[str] = []

    def walk(node: Any, prefix: str, depth: int) -> None:
        if depth > _MAX_SEARCH_DEPTH or len(paths) >= max_paths:
            return
        if isinstance(node, Mapping):
            for key, value in node.items():
                path = f"{prefix}{key}"
                paths.append(path)
                walk(value, f"{path}.", depth + 1)
        elif isinstance(node, (list, tuple)) and node:
            walk(node[0], f"{prefix}[0].", depth + 1)

    walk(obj, "", 0)
    return sorted(paths)


def extract_open_id(record: Mapping[str, Any] | None) -> str | None:
    """Pull an openId out of a vendor record, or ``None`` if absent/unsuitable.

    Searches the whole nested structure, preferring the spellings already known
    on the exact record the caller handed over, then any key whose name contains
    ``openId`` in any casing, then the same descent into nested objects.
    """
    if not isinstance(record, Mapping):
        return None
    mappings = list(_mappings_in(record))
    # Known spellings on the record itself first, then anywhere by name shape.
    for source in mappings[:1]:
        for key in _OPEN_ID_KEYS:
            found = _usable_open_id(source.get(key))
            if found:
                return found
    for source in mappings:
        for key, value in source.items():
            if isinstance(key, str) and _OPEN_ID_KEY_RE.search(key):
                found = _usable_open_id(value)
                if found:
                    return found
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
    extra_sources: Iterable[Any] | None = None,
) -> CloudIdentity:
    """Work out the station's owning identity from a login response + device list.

    ``openId`` is read from the station's own bound record when present, since a
    single account can own several stations, and falls back to *account_open_id*
    for the (rare) accounts where the platform exposes it only at account level.
    *extra_sources* carries whole responses from other endpoints - notably
    ``/api/app/device/info``, whose payload is a different shape again from the
    list entry and is where a per-station owner field would most plausibly sit.
    """
    user_id = extract_user_id(login_info)
    record = find_device_record(bound_records, device_id=device_id, mac_address=mac_address)

    if record is None:
        return CloudIdentity(user_id=user_id, reason=REASON_NOT_BOUND)

    open_id = (
        extract_open_id(record)
        or extract_open_id(account_open_id)
        or extract_open_id(login_info)
        or next(
            (found for src in (extra_sources or ()) if (found := extract_open_id(src))),
            None,
        )
    )
    if not open_id or user_id is None:
        # Field *names* only, never values: an openId is an identifier and does not
        # belong in a log file. But when this fails, the names are the entire
        # diagnostic - it distinguishes "this account has no openId" from "the
        # vendor renamed the field", and without it a user can only report that
        # something failed. One warning per attempt is worth the line in the log.
        # Paths are dotted and nested, because a flat key list is exactly what
        # hid the answer here the first time round.
        _LOGGER.warning(
            "Could not find an account identity in the vendor cloud response for "
            "this station. Device record fields: %s. Login response fields: %s. "
            "Other endpoints searched: %s. (Field paths only; no values are logged.)",
            describe_key_paths(record),
            describe_key_paths(login_info),
            [describe_key_paths(src) for src in (extra_sources or ())],
        )
        return CloudIdentity(
            open_id=open_id,
            user_id=user_id,
            reason=REASON_NO_OPEN_ID if not open_id else REASON_NO_USER_ID,
        )

    return CloudIdentity(open_id=open_id, user_id=user_id, reason=REASON_OK)

"""Cloud API client for OUPES device key and account identity retrieval.

The OUPES cloud API at api.upspowerstation.top provides device metadata
including the per-device ``device_key`` needed for BLE init packet 6, and the
account identity (``openId`` + numeric id) that Guardian / D5 V2 stations embed
in their AUTH frame.

Authentication:
  1. ``POST /api/app/user/login`` with Cleanergy account email/password
     returns a session *token* and the account's ``uid``.
  2. ``GET /api/app/device/list?token=...`` returns all bound devices
     with their ``device_key`` and ``openId``.

The ``device_id`` is extracted from BLE advertising data during discovery.
Device matching falls back to MAC address when device_id is unavailable.

A station that is not present in the caller's device list is reported as
``not_bound`` rather than as a login failure: those two look identical in the
UI but need very different answers from the user. Identity field parsing and
the wire-field limits live in :mod:`.cloud_identity`.

**Important:** This API uses unencrypted HTTP (not HTTPS).  This mirrors
the official Cleanergy app's own behaviour - OUPES does not offer an
HTTPS endpoint.
"""
from __future__ import annotations

import logging

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .cloud_identity import CloudIdentity, find_device_record, resolve_identity

_LOGGER = logging.getLogger(__name__)

API_BASE = "http://api.upspowerstation.top"
_COMMON_PARAMS = {"platform": "android", "lang": "en", "systemVersion": "36"}
_COMMON_HEADERS = {
    "versionname": "1.4.1",
    "lang": "en",
    "package": "com.cleanergy.app",
}
_TIMEOUT = aiohttp.ClientTimeout(total=15)


async def async_cloud_login(
    hass: HomeAssistant,
    email: str,
    password: str,
) -> str | None:
    """Log in to the OUPES cloud and return the session token.

    Calls ``POST /api/app/user/login`` with the user's Cleanergy account
    credentials.  Returns the token string on success, ``None`` on failure.
    """
    info = await async_cloud_login_info(hass, email, password)
    return (info or {}).get("token") or None


async def async_cloud_login_info(
    hass: HomeAssistant,
    email: str,
    password: str,
) -> dict | None:
    """Log in and return the whole ``info`` object (token *and* ``uid``).

    The account id is needed alongside the token for the Guardian / D5 V2 AUTH
    frame, which is why this exists next to :func:`async_cloud_login`.
    """
    session = async_get_clientsession(hass)
    payload = {
        "mail": email,
        "passwd": password,
        "lang": "en",
        "platform": "android",
        "systemVersion": 36,
    }
    try:
        async with session.post(
            f"{API_BASE}/api/app/user/login",
            json=payload,
            headers=_COMMON_HEADERS,
            timeout=_TIMEOUT,
        ) as resp:
            if resp.status != 200:
                _LOGGER.debug("Cloud login returned HTTP %d", resp.status)
                return None
            body = await resp.json(content_type=None)
            if body.get("ret") != 1:
                _LOGGER.debug("Cloud login failed: %s", body.get("desc"))
                return None
            info = body.get("info") or {}
            if info.get("token"):
                _LOGGER.debug("Cloud login successful")
                return info
            _LOGGER.debug("Cloud login response missing token")
            return None
    except Exception as exc:
        _LOGGER.debug("Cloud login request failed: %s", exc)
        return None


async def async_fetch_device_key(
    hass: HomeAssistant,
    *,
    device_id: str | None = None,
    mac_address: str | None = None,
    token: str = "",
) -> str | None:
    """Fetch the device_key for an OUPES device from the cloud API.

    Requires a valid *token* from :func:`async_cloud_login`.

    Tries strategies in order:
      1. ``/api/app/device/info`` with *device_id* and *token*.
      2. ``/api/app/device/list`` matched by *device_id* or *mac_address*.

    Returns the 10-char hex device_key, or ``None`` on failure.
    """
    if not token:
        _LOGGER.debug("No cloud token provided — cannot fetch device_key")
        return None

    session = async_get_clientsession(hass)

    # Strategy 1: direct device info lookup by device_id
    if device_id:
        key = await _fetch_by_device_id(session, device_id, token)
        if key:
            return key

    # Strategy 2: list all devices and match by device_id or MAC
    key = await _fetch_from_list(session, token, device_id, mac_address)
    if key:
        return key

    return None


async def _fetch_by_device_id(
    session: aiohttp.ClientSession,
    device_id: str,
    token: str,
) -> str | None:
    """GET /api/app/device/info?device_id=...&token=... -> device_key."""
    info = await fetch_device_info_payload(session, device_id, token)
    return _extract_key(info)


async def fetch_device_info_payload(
    session: aiohttp.ClientSession,
    device_id: str,
    token: str,
) -> dict | list | None:
    """GET /api/app/device/info and hand back the whole ``info`` object.

    The key lookup only wanted one field out of this response and threw the rest
    away. That payload is a different shape from the ``/device/list`` entry - and
    the list entry was measured to carry no account identity at all - so the
    whole object is worth keeping for the identity search.
    """
    params = {**_COMMON_PARAMS, "device_id": device_id, "token": token}
    try:
        async with session.get(
            f"{API_BASE}/api/app/device/info",
            params=params,
            headers=_COMMON_HEADERS,
            timeout=_TIMEOUT,
        ) as resp:
            if resp.status != 200:
                _LOGGER.debug(
                    "Cloud API /device/info returned HTTP %d", resp.status
                )
                return None
            body = await resp.json(content_type=None)
            if body.get("ret") != 1:
                _LOGGER.debug(
                    "Cloud API /device/info error: %s", body.get("desc")
                )
                return None
            return body.get("info")
    except Exception as exc:
        _LOGGER.debug("Cloud API /device/info request failed: %s", exc)
        return None


async def async_fetch_device_info(
    hass: HomeAssistant, device_id: str, token: str
) -> dict | list | None:
    """``/api/app/device/info`` payload for one station, for identity searching."""
    if not device_id or not token:
        return None
    return await fetch_device_info_payload(
        async_get_clientsession(hass), device_id, token
    )


async def async_fetch_bound_devices(
    hass: HomeAssistant, token: str
) -> tuple[list[dict], dict] | None:
    """Return ``(bound_records, account_info)`` for the session *token*.

    ``None`` means the request failed; an empty record list means the account
    genuinely has no station bound to it, which is a different problem and is
    reported as such by :func:`resolve_identity`.
    """
    if not token:
        _LOGGER.debug("No cloud token provided - cannot fetch device list")
        return None
    session = async_get_clientsession(hass)
    params = {**_COMMON_PARAMS, "token": token}
    try:
        async with session.get(
            f"{API_BASE}/api/app/device/list",
            params=params,
            headers=_COMMON_HEADERS,
            timeout=_TIMEOUT,
        ) as resp:
            if resp.status != 200:
                _LOGGER.debug("Cloud API /device/list returned HTTP %d", resp.status)
                return None
            body = await resp.json(content_type=None)
            if body.get("ret") != 1:
                _LOGGER.debug("Cloud API /device/list error: %s", body.get("desc"))
                return None
            info = body.get("info") or {}
            records = [d for d in (info.get("bind") or []) if isinstance(d, dict)]
            # "share" holds stations shared *to* this account; an owner-facing
            # lookup should not silently match those.
            return records, info
    except Exception as exc:
        _LOGGER.debug("Cloud API /device/list request failed: %s", exc)
        return None


async def async_fetch_cloud_identity(
    hass: HomeAssistant,
    email: str = "",
    password: str = "",
    *,
    device_id: str | None = None,
    mac_address: str | None = None,
    login_info: dict | None = None,
) -> CloudIdentity:
    """Recover the openId + numeric user id that a Guardian / D5 V2 AUTH needs.

    One login, one device-list call - unless *login_info* is supplied, in which
    case that login is reused and only the list is fetched (the config flow
    wants the device key from the same session). Never stores or returns the
    password. The result carries a reason code when it fails, so the UI can tell
    "wrong password" apart from "this station is not bound to that account" -
    the second being the usual reason a station keeps dropping the link.
    """
    if login_info is None:
        login_info = await async_cloud_login_info(hass, email, password)
    if not login_info:
        return CloudIdentity(reason="login_failed")
    fetched = await async_fetch_bound_devices(hass, login_info.get("token") or "")
    if fetched is None:
        return CloudIdentity(reason="login_failed")
    records, account_info = fetched
    # ``/device/info`` is the one per-station endpoint whose payload we were
    # discarding after reading device_key. Search it for the identity too.
    device_info = await async_fetch_device_info(
        hass, device_id or "", login_info.get("token") or ""
    )
    return resolve_identity(
        login_info,
        records,
        device_id=device_id,
        mac_address=mac_address,
        account_open_id=account_info,
        extra_sources=[device_info] if device_info else None,
    )


async def _fetch_from_list(
    session: aiohttp.ClientSession,
    token: str,
    device_id: str | None,
    mac_address: str | None,
) -> str | None:
    """GET /api/app/device/list, find device by id or MAC, return its key."""
    params = {**_COMMON_PARAMS, "token": token}
    try:
        async with session.get(
            f"{API_BASE}/api/app/device/list",
            params=params,
            headers=_COMMON_HEADERS,
            timeout=_TIMEOUT,
        ) as resp:
            if resp.status != 200:
                _LOGGER.debug(
                    "Cloud API /device/list returned HTTP %d", resp.status
                )
                return None
            body = await resp.json(content_type=None)
            if body.get("ret") != 1:
                _LOGGER.debug(
                    "Cloud API /device/list error: %s", body.get("desc")
                )
                return None
            info = body.get("info") or {}
            devices = info.get("bind", [])
            record = find_device_record(devices, device_id=device_id, mac_address=mac_address)
            if record is not None:
                return _extract_key(record)
    except Exception as exc:
        _LOGGER.debug("Cloud API /device/list request failed: %s", exc)
    return None


def _extract_key(device_data: dict | list | None) -> str | None:
    """Pull a valid 10-char hex device_key from a device info dict."""
    if isinstance(device_data, list):
        device_data = device_data[0] if device_data else None
    if not isinstance(device_data, dict):
        return None
    key = device_data.get("device_key", "")
    if isinstance(key, str) and len(key) == 10 and all(
        c in "0123456789abcdefABCDEF" for c in key
    ):
        return key
    _LOGGER.debug("Cloud API returned invalid or missing device_key: %r", key)
    return None

"""OUPES Mega Power Station - Home Assistant custom integration."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

try:  # HA >= 2024.4 exposes the stop signal as a bus event
    from homeassistant.core import BUS_EVENT_HOME_ASSISTANT_STOP as _STOP_EVENT
except ImportError:  # older cores only have the legacy constant
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP as _STOP_EVENT

from .const import (
    ATTR78_RUNTIME_MAX,
    CONF_ADDRESS,
    CONF_CONTINUOUS,
    CONF_DEBUG_ATTRS,
    CONF_DEBUG_RAW,
    CONF_DEVICE_KEY,
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
    STALE_TIMEOUT,
    UPDATE_INTERVAL,
)
from .coordinator import OUPESMegaCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH, Platform.NUMBER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OUPES Mega from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    name: str = entry.data.get(CONF_NAME, "OUPES Mega")

    continuous: bool = entry.options.get(CONF_CONTINUOUS, True)
    debug_attrs: bool = entry.options.get(CONF_DEBUG_ATTRS, False)
    debug_raw: bool = entry.options.get(CONF_DEBUG_RAW, False)
    poll_interval: int = entry.options.get(
        CONF_POLL_INTERVAL, int(UPDATE_INTERVAL.total_seconds())
    )
    try:
        live_push_interval: float = float(entry.options.get(
            CONF_LIVE_PUSH_INTERVAL, LIVE_PUSH_MIN_INTERVAL
        ))
    except (TypeError, ValueError):
        live_push_interval = LIVE_PUSH_MIN_INTERVAL
    stale_timeout: int = entry.options.get(
        CONF_STALE_TIMEOUT, int(STALE_TIMEOUT.total_seconds() // 60)
    )
    runtime_max: int = entry.options.get(CONF_RUNTIME_MAX, ATTR78_RUNTIME_MAX)

    # Guardian / D5 V2 ("WP") stations bind their AUTH frame to the owner's cloud
    # identity; every other model leaves both unset.
    open_id: str = str(entry.options.get(CONF_OPEN_ID, "") or "").strip()
    try:
        user_id: int = int(entry.options.get(CONF_USER_ID, 0) or 0)
    except (TypeError, ValueError):
        user_id = 0

    device_key: str = (
        entry.options.get(CONF_DEVICE_KEY)
        or entry.data.get(CONF_DEVICE_KEY)
        or ""
    )
    if not device_key:
        raise ConfigEntryNotReady(
            f"No device_key configured for {name} ({address}). "
            "Open the integration options and enter your Cleanergy cloud "
            "email/password to auto-fetch the correct key, or enter it manually."
        )
    coordinator = OUPESMegaCoordinator(
        hass, address, name,
        device_key=device_key,
        product_id=entry.data.get(CONF_PRODUCT_ID, ""),
        open_id=open_id,
        user_id=user_id,
        continuous=continuous,
        poll_interval_seconds=poll_interval,
        live_push_interval_seconds=live_push_interval,
        stale_timeout_minutes=stale_timeout,
        debug_attrs=debug_attrs,
        debug_raw=debug_raw,
        runtime_max_minutes=runtime_max,
    )

    # Perform the first refresh; raises ConfigEntryNotReady if the device
    # is out of range so HA will retry setup automatically.
    try:
        await coordinator.async_config_entry_first_refresh()
    except asyncio.CancelledError:
        # Normal during reload/shutdown - let it propagate so HA can finish.
        # Converting this to ConfigEntryNotReady was observed holding the
        # reload task past HA's final-write stage at shutdown.
        raise
    except Exception as exc:
        raise ConfigEntryNotReady(
            f"Could not connect to OUPES Mega {address}: {exc}"
        ) from exc

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Release the BLE link at the *first* moment HA begins shutting down.
    # Waiting for async_unload_entry is too late when the supervisor's stop
    # grace expires before unload reaches us (docker restart = ~10 s fuse):
    # the proxy keeps a zombie GATT link and refuses every later connection
    # (HCI "Conn Exists") until it is power-cycled. async_shutdown is
    # idempotent, so the normal unload path below stays harmless.
    def _release_ble(_event) -> None:
        hass.async_create_task(coordinator.async_shutdown())

    entry.async_on_unload(
        hass.bus.async_listen_once(_STOP_EVENT, _release_ble)
    )

    if continuous:
        coordinator.start_continuous_connection()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    entry.async_on_unload(coordinator.stop_continuous_connection)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry options update (reload)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is not None:
        # Stops the continuous task and, critically, closes the GATT link so
        # the BLE proxy's connection slot is released. Skipping this is what
        # wedged the ESP32 proxies after repeated restarts.
        await coordinator.async_shutdown()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok

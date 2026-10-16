"""Tripwires for BLE teardown.

Field incident 2026-10-15: after several rapid HA restarts, every BLE device
in the house (Guardian station and a Yale lock) failed to connect with
ESP_GATT_ERROR / connect timeouts. The proxies were fine; the problem was
this integration. On every reload/restart the continuous task's GATT link
was left open on the ESP32:

  * nothing called the coordinator's shutdown on unload, and
  * the task's ``finally: await client.disconnect()`` could not survive the
    cancellation it was being torn down by - the disconnect never reached
    the radio.

BLE proxies expose a small fixed number of connection slots; leaking two or
three of them wedges BLE for the whole house until the proxy is power-cycled.

These tests keep the three legs of the fix in place.
"""

from pathlib import Path

import re

ROOT = Path(__file__).resolve().parent.parent
COORD = (ROOT / "custom_components" / "oupes_mega_ble" / "coordinator.py").read_text(
    encoding="utf-8"
)
INIT = (ROOT / "custom_components" / "oupes_mega_ble" / "__init__.py").read_text(
    encoding="utf-8"
)


def test_continuous_disconnect_is_shielded():
    """The continuous task's disconnect must outlive its own cancellation."""
    # Find the finally block that closes the continuous client.
    m = re.search(
        r"finally:\s*\n(?:.*\n)*?.*?await asyncio\.shield\(asyncio\.wait_for\(\s*client\.disconnect\(\)",
        COORD,
    )
    assert m, (
        "continuous-task teardown lost its shielded disconnect. A plain "
        "'await client.disconnect()' inside a cancelled task is re-raised at "
        "the await and the GATT link stays open on the BLE proxy."
    )


def test_shutdown_releases_active_client_and_is_awaited_on_unload():
    """async_shutdown must close the held client, and unload must await it."""
    assert "async def async_shutdown(self)" in COORD, (
        "coordinator must override async_shutdown: the base class cancels the "
        "update task but knows nothing about the long-lived BLE client."
    )
    # The override must touch _active_client and call super().
    m = re.search(
        r"async def async_shutdown\(self\).*?await super\(\)\.async_shutdown\(\)",
        COORD,
        flags=re.S,
    )
    assert m, "async_shutdown override malformed"
    assert "self._active_client" in m.group(0), (
        "async_shutdown must disconnect the tracked _active_client"
    )
    # __init__ must actually await it during unload, not just cancel the task.
    m2 = re.search(
        r"async def async_unload_entry.*?await coordinator\.async_shutdown\(\)",
        INIT,
        flags=re.S,
    )
    assert m2, (
        "async_unload_entry must await coordinator.async_shutdown() so the "
        "proxy's connection slot is released on reload/restart"
    )


def test_setup_cancellation_propagates():
    """Swallowing setup cancellation into ConfigEntryNotReady held a reload
    task past HA's final-write stage during shutdown (observed in logs)."""
    m = re.search(
        r"await coordinator\.async_config_entry_first_refresh\(\)\s*\n"
        r"\s*except asyncio\.CancelledError:\s*\n\s*(?:#[^\n]*\n\s*)*raise\b",
        INIT,
    )
    assert m, (
        "CancelledError from first refresh must propagate unchanged; "
        "converting it to ConfigEntryNotReady delays shutdown and keeps the "
        "connection open longer than HA is alive to clean up."
    )

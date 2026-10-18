"""Tripwire: BLE must be released at the *start* of HA shutdown.

Field incident 2026-10-17: `docker restart homeassistant` grants roughly a
10-second stop grace. HA's teardown did not reach this integration's
unload path before SIGKILL, so the long-lived GATT link to the Guardian
was never closed. The ESP32 proxy kept the stale link (HCI "Conn Exists")
and refused every subsequent connection - BLE was wedged house-wide until
the proxy was power-cycled. The user's own disable test proved the
disconnect itself works fine; it simply fired too late.

The fix listens for the home-assistant stop signal (bus event, fired at
the very beginning of shutdown) and releases the client there, making the
grace-window race irrelevant. async_shutdown() is guarded to run once so
the normal unload path stays harmless.

These checks keep both legs in place.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = (ROOT / "custom_components" / "oupes_mega_ble" / "__init__.py").read_text(
    encoding="utf-8"
)
COORD = (ROOT / "custom_components" / "oupes_mega_ble" / "coordinator.py").read_text(
    encoding="utf-8"
)


def test_setup_registers_stop_listener() -> None:
    assert "async_listen_once(_STOP_EVENT" in INIT, (
        "__init__.py must register a home-assistant stop listener so the "
        "BLE link is released at the start of shutdown, not whenever unload "
        "gets to us."
    )
    assert "entry.async_on_unload" in INIT, (
        "The stop listener must be unregistered with entry.async_on_unload "
        "so reloads do not stack duplicate listeners."
    )
    assert "BUS_EVENT_HOME_ASSISTANT_STOP" in INIT, (
        "Prefer the modern bus event; the legacy EVENT_HOMEASSISTANT_STOP "
        "import must remain as the fallback for older cores."
    )


def test_listener_releases_via_coordinator_shutdown() -> None:
    # The listener callback must route to the coordinator's release path
    # (which shields the disconnect from cancellation), not a raw close.
    assert "coordinator.async_shutdown()" in INIT, (
        "The stop listener must call coordinator.async_shutdown(); that is "
        "the path that shields the BLE disconnect so it reaches the proxy."
    )


def test_shutdown_is_idempotent() -> None:
    # stop listener + async_unload_entry both call async_shutdown(); the
    # second call must be a no-op, never disconnect a reloaded client.
    assert "_shutdown_started" in COORD, (
        "coordinator.async_shutdown() must guard against double execution "
        "(stop listener fires it early; unload calls it again)."
    )


def test_release_callback_is_thread_safe() -> None:
    """Regression 2026-10-17 (second incident): HA may run the stop callback
    from an executor thread. ``hass.async_create_task`` from a non-loop
    thread is rejected by HA 2026's frame guard - the disconnect was then
    skipped silently and the station stayed glued to a proxy (22-minute
    outage behind a solid IoT icon). The callback must hand off via
    loop.call_soon_threadsafe (or equivalent threadsafe scheduling)."""
    fn = INIT.split("def _release_ble")[1].split("async def ")[0]
    assert "call_soon_threadsafe" in fn, (
        "_release_ble must schedule via loop.call_soon_threadsafe so the "
        "release survives being invoked off the event loop."
    )

"""Shared test fixtures.

The component imports `homeassistant` at module load; the test venv does
not ship HA. Install lightweight stubs BEFORE any test imports the
component. Real HA installations win if they exist.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

# make `custom_components.*` importable from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _stub(name: str, **attrs) -> types.ModuleType:
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


def _install_ha_stubs() -> None:
    try:  # prefer the real thing when present
        import homeassistant  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    class _Anything:  # generic placeholder for HA base classes
        def __init__(self, *a, **k):
            pass

        def __getattr__(self, item):
            return _Anything()

    _stub("bleak_retry_connector", establish_connection=lambda *a, **k: None)
    ha = _stub("homeassistant")
    comp = _stub("homeassistant.components")
    core = _stub("homeassistant.core", HomeAssistant=_Anything)
    cfg = _stub("homeassistant.config_entries", ConfigEntry=_Anything)
    exc = _stub("homeassistant.exceptions", ConfigEntryNotReady=Exception)
    helpers = _stub("homeassistant.helpers")
    _stub(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=_Anything,
        UpdateFailed=Exception,
    )
    _stub("homeassistant.helpers.event", async_call_later=lambda *a, **k: None)
    _stub(
        "homeassistant.helpers.entity",
        EntityCategory=types.SimpleNamespace(CONFIG="config", DIAGNOSTIC="diagnostic"),
    )
    _stub(
        "homeassistant.components.bluetooth",
        async_ble_device_from_address=lambda *a, **k: None,
    )
    const = _stub(
        "homeassistant.const",
        Platform=types.SimpleNamespace(
            SENSOR="sensor", SWITCH="switch", BUTTON="button",
            BINARY_SENSOR="binary_sensor", NUMBER="number",
        ),
        EVENT_HOMEASSISTANT_STOP="homeassistant_stop",
        UnitOfPower=types.SimpleNamespace(WATT="W"),
        UnitOfEnergy=types.SimpleNamespace(KILO_WATT_HOURS="kWh", WATT_HOUR="Wh"),
        UnitOfElectricCurrent=types.SimpleNamespace(AMPERE="A"),
        UnitOfElectricPotential=types.SimpleNamespace(VOLT="V"),
        UnitOfTemperature=types.SimpleNamespace(CESLIUS="°C"),
        UnitOfTime=types.SimpleNamespace(MINUTES="min"),
        PERCENTAGE="%",
        SIGNAL_RELOAD_SERVICE=None,
    )
    sensors = _stub("homeassistant.components.sensor")
    _stub(
        "homeassistant.components.sensor",
        SensorEntity=_Anything,
        SensorStateClass=_Anything,
        SensorDeviceClass=_Anything,
    )
    sw = _stub("homeassistant.components.switch", SwitchEntity=_Anything)
    btn = _stub("homeassistant.components.button", ButtonEntity=_Anything)
    _stub(
        "homeassistant.components.switch",
        SwitchEntity=_Anything,
    )
    _stub(
        "homeassistant.components.button",
        ButtonEntity=_Anything,
    )
    # wire attribute access too
    ha.components = comp
    ha.core = core
    ha.config_entries = cfg
    ha.exceptions = exc
    ha.helpers = helpers
    ha.const = const
    comp.bluetooth = sensors
    comp.sensor = sensors
    comp.switch = sw
    comp.button = btn
    helpers.update_coordinator = sys.modules["homeassistant.helpers.update_coordinator"]
    helpers.event = sys.modules["homeassistant.helpers.event"]


_install_ha_stubs()

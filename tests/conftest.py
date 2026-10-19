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

    class _AnythingMeta(type):
        def __getitem__(cls, item):  # support Generic[T] syntax at import time
            return cls

    _ANYTHING_NS: dict = {}

    def _anything_cls(name):
        # distinct class per requested HA base so class B(A1, A2) doesn't
        # collapse into duplicate-base errors under the stub regime
        if name not in _ANYTHING_NS:
            _ANYTHING_NS[name] = _AnythingMeta(name, (_Anything,), {})
        return _ANYTHING_NS[name]

    class _Anything(metaclass=_AnythingMeta):  # generic placeholder for HA base classes
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
        DataUpdateCoordinator=_anything_cls('DataUpdateCoordinator'),
        CoordinatorEntity=_anything_cls('CoordinatorEntity'),
        UpdateFailed=Exception,
    )
    _stub("homeassistant.helpers.event", async_call_later=lambda *a, **k: None)
    _stub("homeassistant.helpers.device_registry", DeviceInfo=dict)
    _stub(
        "homeassistant.helpers.entity_platform",
        AddEntitiesCallback=object,
    )
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
        UnitOfTemperature=types.SimpleNamespace(CESLIUS="°C", FAHRENHEIT="°F", KELVIN="K"),
        UnitOfTime=types.SimpleNamespace(MINUTES="min", SECONDS="s", HOURS="h"),
        PERCENTAGE="%",
        SIGNAL_RELOAD_SERVICE=None,
    )
    sensors = _stub("homeassistant.components.sensor")
    _stub(
        "homeassistant.components.sensor",
        SensorEntity=_anything_cls('SensorEntity'),
        SensorStateClass=_Anything,
        SensorDeviceClass=_Anything,
    )
    # dataclass __post_init__ in the real core validates device_class vs
    # state_class compatibility against these enum VALUES; stubs must carry
    # the same strings or the validation is vacuous (or explodes).
    import homeassistant.components.sensor as _sens_mod
    _sens_mod.SensorStateClass = types.SimpleNamespace(
        MEASUREMENT="measurement",
        TOTAL="total",
        TOTAL_INCREASING="total_increasing",
    )
    _sens_mod.SensorDeviceClass = types.SimpleNamespace(
        ENERGY="energy",
        POWER="power",
        BATTERY="battery",
        DURATION="duration",
        TEMPERATURE="temperature",
        VOLTAGE="voltage",
        CURRENT="current",
        FREQUENCY="frequency",
        POWER_FACTOR="power_factor",
        SIGNAL_STRENGTH="signal_strength",
        TIMESTAMP="timestamp",
        TEXT=None,
    )

    # sensor.py subclasses SensorEntityDescription as a @dataclass, so the
    # stub must BE a dataclass carrying every field descriptions set.
    import dataclasses as _dc

    @_dc.dataclass(frozen=True, kw_only=True)
    class SensorEntityDescription:
        key: str = ""
        translation_key: str | None = None
        name: str | None = None
        device_class: str | None = None
        state_class: str | None = None
        native_unit_of_measurement: str | None = None
        icon: str | None = None
        entity_category: str | None = None
        entity_registry_visible: bool = True
        entity_registry_enabled_default: bool = True
        suggested_display_precision: int | None = None
        suggested_unit_of_measurement: str | None = None

    _sens_mod.SensorEntityDescription = SensorEntityDescription
    sw = _stub("homeassistant.components.switch", SwitchEntity=_anything_cls('SwitchEntity'))
    btn = _stub("homeassistant.components.button", ButtonEntity=_anything_cls('ButtonEntity'))
    _stub(
        "homeassistant.components.switch",
        SwitchEntity=_anything_cls('SwitchEntity'),
    )
    _stub(
        "homeassistant.components.button",
        ButtonEntity=_anything_cls('ButtonEntity'),
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
    helpers.device_registry = sys.modules["homeassistant.helpers.device_registry"]
    helpers.entity_platform = sys.modules["homeassistant.helpers.entity_platform"]


_install_ha_stubs()

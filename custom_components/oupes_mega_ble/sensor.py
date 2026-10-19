"""Sensor entities for the OUPES Mega integration."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OUPESMegaCoordinator
from .protocol import (
    ATTR_MAP,
    average_pack_soc,
    battery_status as compute_battery_status,
    missing_energy_wh,
    runtime_estimate_minutes,
    stored_energy_wh,
    time_to_full_minutes,
    total_load_w,
)
from .const import series_from_product_id


def _device_info(coordinator: OUPESMegaCoordinator) -> DeviceInfo:
    """Build a DeviceInfo dict with dynamic model name from product_id."""
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.address)},
        name=coordinator.device_name,
        manufacturer="OUPES",
        model=coordinator.model_name,
        connections={("bluetooth", coordinator.address)},
    )


# -- Entity description -------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class OUPESSensorDescription(SensorEntityDescription):
    """Extends SensorEntityDescription with OUPES-specific fields."""

    # BLE attribute number for this sensor
    attr: int = 0
    # None -> main device; 1 or 2 -> external battery slot
    slot: int | None = None
    # Optional transform from raw integer to the value exposed to HA
    value_fn: Callable[[int], float | str] | None = None
    # Override the dict key used to look up the value in coordinator.data.
    # When set, this is used instead of `attr` for the data lookup.
    data_key: str | int | None = None
    # Re-declared so a description can ship disabled-by-default (real HA
    # honours it via EntityDescription; our import-stub test harness needs
    # the field to exist). True = normal. False = registered disabled,
    # still reachable under "show disabled entities".
    entity_registry_visible: bool = True


# -- Main device sensors ------------------------------------------------------

SENSOR_DESCRIPTIONS: tuple[OUPESSensorDescription, ...] = (
    OUPESSensorDescription(
        key="battery_pct",
        attr=3,
        name="Battery Charge",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
    OUPESSensorDescription(
        # Average over main + every external pack reporting this update.
        # attr=3 keeps the entity available on the plain main-device path;
        # the value branch below ignores it and calls protocol.average_pack_soc.
        key="battery_reserve",
        attr=3,
        name="Combined Battery Reserve",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
    OUPESSensorDescription(
        # Sum of (SoC x nameplate Wh) over main + reporting packs. Same
        # inclusion rules as battery_reserve (see protocol.stored_energy_wh),
        # so percent and watt-hours can never disagree about what counted.
        # WP-family only: nameplate capacity is known only for the guardian
        # series (4608 Wh main AND per G5 pack - owner-reported; no register
        # tells us), and this gate is what stops a Mega ever seeing it.
        key="stored_energy_wh",
        attr=3,
        name="Battery Energy Stored",
        device_class=SensorDeviceClass.ENERGY,
        # state_class=TOTAL: this is a stock LEVEL (goes up AND down), which
        # is exactly what TOTAL means in 2026 core - non-monotonic summable.
        # HISTORY: shipped once with MEASUREMENT (ENERGY+measurement was later
        # rejected by core), then demoted to None in v1.4.13 - which orphaned
        # the statistics already recorded and tripped the core repair floor
        # ("entity no longer has a state class"). TOTAL is the landing spot:
        # LTS resumes, energy-dashboard storage semantics, no lie about
        # monotonicity. Do not set it back to None while history exists.
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
    ),
    OUPESSensorDescription(
        # Energy stored / measured load, the honest replacement for the
        # firmware's remaining_runtime, which goes to nonsense values near
        # full charge. protocol.runtime_estimate_minutes owns the refusals
        # (idle load, >1-week answers report unknown instead of garbage).
        # "Load" is EVERY output register - AC + 12V + USB-C + USB-A - not
        # just AC (see protocol.total_load_w).
        key="runtime_estimate",
        attr=4,
        name="Estimated Runtime Left",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        # SECONDS, not minutes: the HA frontend renders duration sensors
        # human-readably only in its native duration unit - seconds give
        # "11 h 3 min" on the device page, while minute-based sensors get
        # rendered as "663m 12s" nonsense (owner-reported, verified).
        native_unit_of_measurement=UnitOfTime.SECONDS,
        icon="mdi:timer-sand",
    ),
    OUPESSensorDescription(
        # Mirror sensor: minutes of charging left at the CURRENT net charge
        # input. Net = Total Input Power (dpid 21, AC+DC combined - the
        # "either or both" answer) minus what the outputs are eating right
        # now, because passthrough power never reaches the battery. Refuses
        # when full, idle, discharging, or beyond a week.
        key="time_to_full",
        attr=21,
        name="Estimated Time To Full",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.SECONDS,  # see runtime_estimate
        icon="mdi:timer-plus",
    ),
    OUPESSensorDescription(
        # Plain-text companion of the two time sensors: when they rightly
        # refuse, this says why (Idle / Full / Discharging / Charging).
        # Deliberately a text sensor - minutes must stay numeric for graphs
        # and numeric_state automations.
        key="battery_status",
        attr=3,
        name="Battery Status",
        icon="mdi:battery-heart-variant",
    ),
    OUPESSensorDescription(
        key="total_output_power",
        attr=4,
        name="Total Output Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    OUPESSensorDescription(
        key="ac_output_power",
        attr=5,
        name="AC Output Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    OUPESSensorDescription(
        key="dc_12v_output",
        attr=6,
        name="DC 12V Output",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    OUPESSensorDescription(
        key="usb_c_output",
        attr=7,
        name="USB-C Output",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    OUPESSensorDescription(
        key="usb_a_output",
        attr=8,
        name="USB-A Output",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    OUPESSensorDescription(
        key="total_input_power",
        attr=21,
        name="Total Input Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    OUPESSensorDescription(
        key="grid_input_power",
        attr=22,
        name="Grid Input Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    OUPESSensorDescription(
        key="solar_input_power",
        attr=23,
        name="Solar Input Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    # --- Per-input power for the two DC / PV inputs ---------------------------------
    # The Guardian 6000 V2 reports both inputs inside the single dpid-23 field as
    # two uint16 halves (see WP_SPLIT_U16_DPIDS in protocol.py).  The parser puts
    # the aggregate back under dpid 23 (so "Solar Input Power" above stays right)
    # and publishes the individual inputs under pseudo-dpids 2301/2302, which are
    # only ever read back here via data_key and never sent to the device.
    OUPESSensorDescription(
        key="dc_input_1_power",
        attr=23,
        data_key=2301,
        name="DC Input 1 Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    OUPESSensorDescription(
        key="dc_input_2_power",
        attr=23,
        data_key=2302,
        name="DC Input 2 Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    # DC input voltages, dpid 115: one packed u16 pair at 0.1 V each (see
    # WP_ALWAYS_SPLIT_U16_DPIDS in protocol.py for the wire evidence and the
    # owner-run unplug test that pins low half = top XT60 port = DC Input 1).
    OUPESSensorDescription(
        key="dc_input_1_voltage",
        attr=115,
        data_key=11501,
        name="DC Input 1 Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        value_fn=lambda v: round(v / 10, 1),
        entity_registry_enabled_default=True,
    ),
    OUPESSensorDescription(
        key="dc_input_2_voltage",
        attr=115,
        data_key=11502,
        name="DC Input 2 Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        value_fn=lambda v: round(v / 10, 1),
        entity_registry_enabled_default=True,
    ),
    OUPESSensorDescription(
        key="remaining_runtime",
        attr=30,
        data_key="last_runtime_min",
        name="Remaining Runtime",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        icon="mdi:timer-outline",
        # Demoted, NOT disabled: firmware value goes to nonsense near full
        # charge and the derived Estimated Runtime Left is the one to read,
        # but this keeps collecting history in the device's collapsed
        # Diagnostic section for anyone who wants to compare.
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    OUPESSensorDescription(
        key="main_unit_temp",
        attr=32,
        name="Main Unit Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        value_fn=lambda v: round(v / 10, 1),
    ),
    OUPESSensorDescription(
        key="expansion_battery_count",
        attr=51,
        name="Expansion Battery Count",
        icon="mdi:battery-plus",
        state_class=SensorStateClass.MEASUREMENT,
    ),
)

# -- Per-series display names for attr-6 (car port power) --------------------
# Mirrors the naming used by the car port output switch - same port, same label.
_CAR_PORT_POWER_NAMES: dict[str, str] = {
    "mega_1":   "Car Port Power",
    "mega":     "Car & 12V Power",
    "guardian": "Car & 12V Power",
}


# -- Per-product display names ------------------------------------------------
# Keyed by product id, NOT by series, because these names make a claim about plastic on
# the case.  Renaming the whole `guardian` series would tell the owner of some other
# WP-model station that their inputs are XT60 when nobody has looked at their unit.
# Adding an entry here requires someone who has seen that station, and the attribution has
# to sit within a few lines of the shipped string - tests/test_connector_claims_are_
# attributed.py enforces that, which is the whole reason it is written this way.
#
# Only the name changes.  unique_id is built from `key`, so existing installs keep their
# entity_id (and therefore their dashboards) and pick up the new friendly name in place.
#
# These two names are bare (no "Power" suffix) because the watt unit and device_class
# already say what the number is.  The base descriptions in SENSOR_DESCRIPTIONS deliberately
# KEEP their "Power" suffix: those names are what a fresh install on some other WP-model
# station slugs into an entity_id, and docs elsewhere quote `dc_input_1_power`. Renaming
# them would move entity_ids on stations nobody has inspected, for a cosmetic reason.
_PRODUCT_SENSOR_NAMES: dict[str, dict[str, str]] = {
    "95haDY": {  # Guardian 6000 V2 / D5 V2 - connector is owner-reported, not wire-verified
        # attr 23 on this machine is the two XT60 inputs combined; "Solar"
        # is the firmware's word for the MPPT input, but the total is
        # honestly "all DC input", which is what this name now says.
        "solar_input_power": "DC Total Input Power",
        "dc_input_1_power": "DC XT60 Power 1",
        "dc_input_2_power": "DC XT60 Power 2",
        # owner-reported sockets (a human looked; the wire never names a connector)
        "dc_input_1_voltage": "DC XT60 Voltage 1",
        "dc_input_2_voltage": "DC XT60 Voltage 2",
    },
}


# -- Battery module sensors (created dynamically per slot) --------------------
# Attr 101 carries the slot index; attrs 78/79/80/53/54 carry the per-slot
# values. Entities are added the first time each slot number appears in
# coordinator data, so only the slots that actually exist on this unit are
# ever created in HA. Additional slots appear automatically if more batteries
# are connected later.


def _slot_descriptions(slot: int) -> list[OUPESSensorDescription]:
    """Return the five sensor descriptions for one ext-battery slot.

    Five per slot is what the live entity registry confirms on a three-pack unit
    (15 slot entities + 29 station entities = 44), which is also why the total entity
    count moves when a pack is added or removed.
    """
    display_name = f"External Battery {slot}"
    return [
        OUPESSensorDescription(
            key=f"ext_battery_{slot}_pct",
            attr=79,
            slot=slot,
            name=f"{display_name} Charge",
            device_class=SensorDeviceClass.BATTERY,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            # Raw value is direct battery % (0-100).
            # Confirmed: raw 15 = 15% after a few hours of charging.
        ),
        OUPESSensorDescription(
            key=f"ext_battery_{slot}_runtime",
            attr=78,
            data_key="last_runtime_min",
            slot=slot,
            name=f"{display_name} Runtime",
            device_class=SensorDeviceClass.DURATION,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            icon="mdi:timer-outline",
            # Only stores real runtime values; the 99h sentinel (5940 min) that
            # the firmware emits when charging/idle is filtered out in the
            # coordinator, so this sensor goes Unknown when not discharging.
        ),
        OUPESSensorDescription(
            key=f"ext_battery_{slot}_temp",
            attr=80,
            slot=slot,
            name=f"{display_name} Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
            value_fn=lambda v: round(v / 10, 1),
        ),
        OUPESSensorDescription(
            key=f"ext_battery_{slot}_output_power",
            attr=54,
            slot=slot,
            name=f"{display_name} Output Power",
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfPower.WATT,
            # Confirmed: attr 54 = B2 "OUTPUT W" in the app - total power
            # leaving the B2 (chain cable discharge to Mega + USB ports).
        ),
        OUPESSensorDescription(
            key=f"ext_battery_{slot}_input_power",
            attr=53,
            slot=slot,
            name=f"{display_name} Input Power",
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfPower.WATT,
            # Confirmed: attr 53 = B2 "INPUT W" in the app - power entering
            # the B2 via its secondary MPPT/DC port (solar panel or DC source).
        ),
    ]


# -- Entity class -------------------------------------------------------------

class OUPESMegaSensor(CoordinatorEntity[OUPESMegaCoordinator], SensorEntity):
    """A single numeric sensor reading from an OUPES Mega device."""

    entity_description: OUPESSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OUPESMegaCoordinator,
        description: OUPESSensorDescription,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        # SensorEntity does NOT mirror description.native_unit_of_measurement
        # into _attr_native_unit_of_measurement (unlike device_class/name -
        # the unit property only reads the _attr). Without this line every
        # sensor reports with no unit at all; owner-verified in 2026.10.
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(coordinator)

    @property
    def available(self) -> bool:
        """Stay available for STALE_TIMEOUT after the last successful poll.

        This prevents flickering during transient BLE failures while still
        correctly marking entities unavailable if the device is off long-term.
        Ext battery slots go unavailable only if that slot has never had data.
        Voltage entities go unavailable if the firmware has never emitted a
        voltage reading for that slot (e.g. slot 1 on current Mega 1 firmware).
        """
        last = self.coordinator.last_successful_poll
        if last is None:
            return False  # never had a successful poll yet
        if datetime.now() - last > self.coordinator.stale_timeout:
            return False  # data is too old to be trustworthy
        desc = self.entity_description
        if desc.slot is not None:
            slot_data = self.coordinator.data["ext_batteries"].get(desc.slot)
            if not slot_data:
                return False  # slot never seen
            return True
        if split_key_never_reported(desc, self.coordinator.data["attrs"]):
            return False
        return True

    @property
    def native_value(self) -> float | str | None:
        if self.coordinator.data is None:
            return None
        desc = self.entity_description
        if desc.key == "battery_reserve":
            return average_pack_soc(
                self.coordinator.data["attrs"],
                self.coordinator.data.get("ext_batteries"),
            )
        if desc.key == "stored_energy_wh":
            return stored_energy_wh(
                self.coordinator.product_series,
                self.coordinator.data["attrs"],
                self.coordinator.data.get("ext_batteries"),
            )
        if desc.key == "runtime_estimate":
            energy = stored_energy_wh(
                self.coordinator.product_series,
                self.coordinator.data["attrs"],
                self.coordinator.data.get("ext_batteries"),
            )
            load = total_load_w(self.coordinator.data["attrs"])
            # TOTAL load, not net drain: the number answers "if the input
            # stopped right now, how long does the house run?" — which is
            # meaningful while charging too, and the owner wants a time
            # always, not a refusal. Owner decision 2026-10-19.
            minutes = runtime_estimate_minutes(energy, load)
            return None if minutes is None else round(minutes * 60)
        if desc.key == "time_to_full":
            deficit = missing_energy_wh(
                self.coordinator.product_series,
                self.coordinator.data["attrs"],
                self.coordinator.data.get("ext_batteries"),
            )
            # True charge power = internal pack meter PLUS every external
            # pack's input meter. On a stacked Guardian the internal meter
            # sits at 0 while 1.7 kW pours into the external packs (owner-
            # verified 2026-10-19) - reading only attr 24 said 'not
            # charging' mid-charge. Sum every path power can arrive by.
            charge_w = self.coordinator.data["attrs"].get(24)
            exts = self.coordinator.data.get("ext_batteries") or {}
            ext_in = 0.0
            any_ext = False
            for ed in exts.values():
                # Raw slot dicts are keyed by firmware attr numbers: 53 is
                # the pack's INPUT W (string keys like "input_power" live
                # only in sensor descriptions, never in these dicts).
                w = ed.get(53)
                if isinstance(w, (int, float)) and not isinstance(w, bool):
                    ext_in += w
                    any_ext = True
            total_charge = (charge_w or 0) + (ext_in if any_ext else 0)
            if charge_w is None and not any_ext:
                charge_w = None
            else:
                charge_w = total_charge
            minutes = time_to_full_minutes(deficit, charge_w)
            return None if minutes is None else round(minutes * 60)
        if desc.key == "battery_status":
            return compute_battery_status(
                self.coordinator.product_series,
                self.coordinator.data["attrs"],
                self.coordinator.data.get("ext_batteries"),
            )
        if desc.slot is not None:
            lookup = desc.data_key if desc.data_key is not None else desc.attr
            raw = self.coordinator.data["ext_batteries"].get(desc.slot, {}).get(
                lookup
            )
        else:
            lookup = desc.data_key if desc.data_key is not None else desc.attr
            raw = self.coordinator.data["attrs"].get(lookup)

        if raw is None:
            if desc.key == "expansion_battery_count":
                return _derive_ext_count(self.coordinator.data.get("ext_batteries"))
            return None
        return desc.value_fn(raw) if desc.value_fn is not None else raw


# -- Expansion pack count -----------------------------------------------------

def _derive_ext_count(ext_batteries: dict | None) -> int | None:
    """Number of expansion packs that reported telemetry in the current update.

    The firmware exposes a pack count on dpid 51, but only answers it when that dpid
    is queried explicitly, and the coordinator queries just the settings dpids of the
    detected series -- so on this model the value never arrives and the entity would
    stay unknown.  The per-pack telemetry (dpids 53/54/78-80, slot-tagged by dpid 101)
    does arrive, so count the slots that carry data instead.

    This tracks hardware changes on its own: a third pack shows up as slot 2 on the
    next poll and the count becomes 3, and a pack that is switched off stops filling
    its slot dict (the coordinator rebuilds ``ext_batteries`` from scratch every
    update) so the count falls back.  Slot 1 is pre-seeded as an empty dict by the
    coordinator, which is why empty slots are not counted; an empty result is reported
    as unknown rather than a misleading zero.
    """
    if not ext_batteries:
        return None
    count = 0
    for slot, slot_data in ext_batteries.items():
        try:
            slot_no = int(slot)
        except (TypeError, ValueError):
            continue
        if slot_no >= 0 and slot_data:
            count += 1
    return count or None


# -- Platform setup -----------------------------------------------------------

# Sensors that only make sense on the "WP" firmware family (Guardian / D5 V2),
# where attr 23 packs the power of both DC inputs.  On every other model attr 23
# is a single wattage, so these two entities would sit unavailable forever.
# The two voltage sensors join the ban for the same reason and a sharper one:
# their data keys (11501/11502) are produced ONLY by the WP sequence reader's
# split of a packed dpid 115, so on a Mega the lookup can never hit - the
# entities would not merely sit idle, they would render `unknown` forever.
# On the ORIGINAL Guardian 6000 (oB6OKs, one Anderson input) dpid 115 is
# uncaptured: if it does not report 115 the pair is invisible (missing dpid);
# whether it reports one input's voltage or a packed pair is an open field
# question - see the V1 field-test checklist.
_WP_ONLY_SENSOR_KEYS = frozenset(
    {
        "dc_input_1_power",
        "dc_input_2_power",
        "dc_input_1_voltage",
        "dc_input_2_voltage",
        # nameplate Wh is only known for the guardian series (see protocol
        # .WH_PER_BATTERY_UNIT); a Mega would compute from a capacity we
        # never verified, so the trio must not exist there at all
        "stored_energy_wh",
        "runtime_estimate",
        "time_to_full",
        "battery_status",
    }
)


def split_key_never_reported(desc, attrs: dict) -> bool:
    """True for a derived (split pseudo) data key the station never reported.

    dpid 23/115 splits produce synthetic keys (2301/2302, 11501/11502) that only
    exist when THIS product's firmware actually packs the pair. A Guardian 6000
    V1 with one Anderson input, or any firmware that never sends the packed
    dpid, would otherwise carry a permanent `unknown` entity - a sensor for a
    connector the machine does not have. Missing beats lying.
    """
    if desc.slot is not None or desc.data_key is None or desc.attr is None:
        return False
    if desc.data_key == desc.attr:
        return False
    return desc.data_key not in attrs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OUPES Mega sensor entities."""
    coordinator: OUPESMegaCoordinator = hass.data[DOMAIN][entry.entry_id]
    series = series_from_product_id(coordinator.product_id)

    def _resolve(desc: OUPESSensorDescription) -> OUPESSensorDescription:
        if desc.key == "dc_12v_output" and series in _CAR_PORT_POWER_NAMES:
            return replace(desc, name=_CAR_PORT_POWER_NAMES[series])
        rename = _PRODUCT_SENSOR_NAMES.get(coordinator.product_id, {})
        if desc.key in rename:
            return replace(desc, name=rename[desc.key])
        return desc

    # Add main device sensors immediately.
    wp_family = series == "guardian"
    async_add_entities(
        OUPESMegaSensor(coordinator, _resolve(desc), entry)
        for desc in SENSOR_DESCRIPTIONS
        if wp_family or desc.key not in _WP_ONLY_SENSOR_KEYS
    )

    # Ext-battery entities are created on-demand the first time each slot
    # number appears in coordinator data.  This way only batteries that are
    # actually connected to THIS unit are ever registered in HA.
    seen_slots: set[int] = set()

    def _add_new_slots() -> None:
        if not coordinator.data:
            return
        new_slots = set(coordinator.data["ext_batteries"].keys()) - seen_slots
        if not new_slots:
            return
        new_entities = [
            OUPESMegaSensor(coordinator, desc, entry)
            for slot in sorted(new_slots)
            for desc in _slot_descriptions(slot)
        ]
        seen_slots.update(new_slots)
        async_add_entities(new_entities)

    # Run once immediately (first refresh already completed by this point)
    # then re-run on every subsequent coordinator update.
    _add_new_slots()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_slots))

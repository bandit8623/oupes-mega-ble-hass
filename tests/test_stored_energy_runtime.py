"""Stored-energy and estimated-runtime math (protocol layer, bare interpreter).

The firmware's own `remaining_runtime` goes to nonsense numbers near full
charge (observed: the user's unit). These two derived sensors replace it
with honest arithmetic: nameplate Wh x measured SoC, divided by measured
load - and they REFUSE to answer rather than print garbage.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "oupes_mega_ble"))

import protocol  # noqa: E402
from protocol import (  # noqa: E402
    WH_PER_BATTERY_UNIT,
    runtime_estimate_minutes,
    stored_energy_wh,
)

UNIT = 4608  # nameplate Wh, main AND every G5 pack (owner-reported)


def _ext(*socs):
    """slot dicts keyed from 1, each with dpid 79 SoC, like the coordinator."""
    return {i + 1: {79: s} for i, s in enumerate(socs)}


# ---------------------------------------------------------------- stored Wh

def test_main_only_full():
    assert stored_energy_wh("guardian", {3: 100}, None) == UNIT


def test_main_and_three_packs_all_full():
    got = stored_energy_wh("guardian", {3: 100}, _ext(100, 100, 100))
    assert got == 4 * UNIT  # the user's exact rig: main + 3 G5 = 18,432 Wh


def test_mixed_socs_sum_individually_not_averaged():
    # main 50% + pack 100% + pack 0%  = 0.5U + 1U + 0U
    got = stored_energy_wh("guardian", {3: 50}, _ext(100, 0))
    assert got == round(UNIT * 1.5, 1)


def test_zero_soc_counts_silent_slot_does_not():
    got = stored_energy_wh("guardian", {3: 0}, {1: {79: 0}, 2: {}, 3: None})
    assert got == 0.0  # two real 0% units -> 0 Wh, not unknown
    assert stored_energy_wh("guardian", {}, {2: {}, 3: None}) is None  # nothing reported


def test_no_main_no_packs_is_unknown_not_zero():
    assert stored_energy_wh("guardian", {}, {}) is None


def test_unknown_series_refuses_to_invent_capacity():
    """A Mega must never get Guardian nameplate numbers - and must not even
    reach this function, since sensor.py gates creation at the WP-only set.
    If the gate is ever loosened, the math layer still refuses."""
    assert "mega" not in WH_PER_BATTERY_UNIT
    assert stored_energy_wh("mega", {3: 100}, None) is None


def test_out_of_range_soc_clamped():
    assert stored_energy_wh("guardian", {3: 137}, None) == UNIT   # clamp to 100%
    assert stored_energy_wh("guardian", {3: -5}, None) == 0.0     # clamp to 0%


def test_pack_count_changes_track_hardware():
    """Add/remove a G5: next poll's ext_batteries has more/less slots; the
    capacity ceiling follows with zero configuration."""
    three = stored_energy_wh("guardian", {3: 100}, _ext(100, 100, 100))
    two = stored_energy_wh("guardian", {3: 100}, _ext(100, 100))
    assert three - two == UNIT


# --------------------------------------------------------- runtime estimate

def test_runtime_basic():
    # full stack (18,432 Wh) at a 1200 W load -> 15.36 h = 921.6 min
    assert runtime_estimate_minutes(4 * UNIT, 1200) == round(4 * UNIT / 1200 * 60, 1)


def test_idle_load_refuses():
    """The exact firmware failure: light load -> 'crazy number'. Refuse."""
    assert runtime_estimate_minutes(4 * UNIT, 0) is None
    assert runtime_estimate_minutes(4 * UNIT, 4.9) is None


def test_absurd_horizon_refuses():
    # past one week of runway the answer is technically true and
    # informationally zero -> unknown (the firmware's "crazy number", fixed)
    thresh = 4 * UNIT / (protocol._MAX_MEANINGFUL_RUNTIME_MIN / 60)
    assert runtime_estimate_minutes(4 * UNIT, 5.0) is None  # ~9.5 days -> refuse
    assert runtime_estimate_minutes(4 * UNIT, thresh - 1) is None
    assert runtime_estimate_minutes(4 * UNIT, thresh + 1) is not None


def test_missing_or_nan_inputs_refuse():
    assert runtime_estimate_minutes(None, 1200) is None
    assert runtime_estimate_minutes(4 * UNIT, None) is None
    assert runtime_estimate_minutes(4 * UNIT, float("nan")) is None
    assert runtime_estimate_minutes(4 * UNIT, "1200") is None


# --------------------------------------------------------------- integration

def test_sensors_gated_to_the_series_with_known_capacity():
    """sensor.py must not even CREATE these for other series."""
    src = (
        Path(__file__).resolve().parents[1]
        / "custom_components" / "oupes_mega_ble" / "sensor.py"
    ).read_text(encoding="utf-8")
    block = src.split("_WP_ONLY_SENSOR_KEYS = frozenset")[1]
    block = block[: block.rindex("}")]
    for key in ("stored_energy_wh", "runtime_estimate"):
        assert f'"{key}"' in block, (
            f"{key} missing from _WP_ONLY_SENSOR_KEYS - a model with unknown "
            "nameplate capacity would get invented watt-hours"
        )


def test_firmware_runtime_demoted_not_removed():
    """The firmware's remaining_runtime must survive (history!) but sit in
    the Diagnostic section - seen, comparable, visibly not the one to use."""
    src = (
        Path(__file__).resolve().parents[1]
        / "custom_components" / "oupes_mega_ble" / "sensor.py"
    ).read_text(encoding="utf-8")
    block = src.split('key="remaining_runtime"')[1].split("),")[0]
    assert "EntityCategory.DIAGNOSTIC" in block, (
        "firmware Remaining Runtime is back in the main sensor list next to "
        "Estimated Runtime Left; two runtimes side by side re-litigates the "
        "trust question on every glance"
    )
    assert "entity_registry_visible=False" not in block, (
        "demote means DE-EMPHASISE; disabling the firmware sensor deletes its "
        "comparability and the owner asked for it kept"
    )


# ------------------------------------------------- total load & time-to-full

from protocol import missing_energy_wh, time_to_full_minutes, total_load_w  # noqa: E402


def test_total_load_sums_every_output_register():
    # AC 800 + 12V 60 + USB-C 20 + USB-A 0 ; unreported registers count 0
    assert total_load_w({4: 800, 6: 60, 7: 20, 8: 0}) == 880
    assert total_load_w({4: 800}) == 800           # partial report fine
    assert total_load_w({}) is None                # nothing reported at all


def test_total_load_includes_dc_because_attr4_is_ac_only():
    """CSV-proven (8 packs with live DC load): dpid 4 ignored DC/USB watts.
    A load helper of just dpid 4 would inflate runtime-left whenever anyone
    charges a phone."""
    attrs = {4: 100, 6: 100, 7: 60, 8: 40}
    assert total_load_w(attrs) == 300  # not 100!


def test_missing_energy_is_storeds_mirror():
    full = {3: 100}
    assert missing_energy_wh("guardian", full, None) == 0.0
    assert missing_energy_wh("guardian", {3: 75}, _ext(50)) == UNIT * 0.5 + UNIT * 0.25
    assert missing_energy_wh("mega", {3: 50}, None) is None


def test_time_to_full_net_of_passthrough_load():
    # solar pouring 2000 W in while the house eats 1200 of it: only 800 W
    # actually charges. deficit 4608 Wh at 800 W = 345.6 min
    assert time_to_full_minutes(UNIT, 2000 - 1200) == round(UNIT / 800 * 60, 1)


def test_time_to_full_refusals():
    assert time_to_full_minutes(0.0, 3000) is None      # already full
    assert time_to_full_minutes(None, 3000) is None     # nothing reported
    assert time_to_full_minutes(UNIT, None) is None     # no input reading
    assert time_to_full_minutes(UNIT, 0) is None        # idle input
    assert time_to_full_minutes(UNIT, -500) is None     # net DISCHARGE
    assert time_to_full_minutes(UNIT, True) is None     # bool nonsense
    # trickle so slow full charge is beyond a week
    assert time_to_full_minutes(4 * UNIT, 4 * UNIT / (7 * 24 * 60 / 60) - 1) is None


def test_time_to_full_sensor_registered_and_gated():
    src = (
        Path(__file__).resolve().parents[1]
        / "custom_components" / "oupes_mega_ble" / "sensor.py"
    ).read_text(encoding="utf-8")
    assert 'key="time_to_full"' in src
    block = src.split("_WP_ONLY_SENSOR_KEYS = frozenset")[1]
    assert '"time_to_full"' in block[: block.rindex("}")]

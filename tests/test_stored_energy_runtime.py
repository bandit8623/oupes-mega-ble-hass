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


# ------------------------------------------------------------ battery status

from protocol import battery_status  # noqa: E402


def test_status_matrix():
    # charging: 2000 W in, house eats 800, net +1200
    assert battery_status("guardian", {3: 60, 21: 2000, 4: 800}, None) == "Charging"
    # discharging: no input, AC load 1500
    assert battery_status("guardian", {3: 60, 21: 0, 4: 1500}, None) == "Discharging"
    # idle: quiet on both sides
    assert battery_status("guardian", {3: 60, 21: 0, 4: 0}, None) == "Idle"
    # full outranks a still-warm input gauge
    assert battery_status("guardian", {3: 100, 21: 2000, 4: 10}, None) == "Full"
    # a pack at 99 keeps it out of Full (deficit is over ALL counted units)
    assert battery_status("guardian", {3: 100, 21: 0, 4: 0}, _ext(99)) == "Idle"


def test_status_refuses_when_nothing_reported_or_capacity_unknown():
    assert battery_status("guardian", {}, {}) is None
    assert battery_status("mega", {3: 60, 21: 0}, None) is None


def test_status_never_contradicts_the_time_sensors():
    """Same net-input math: if Time To Full answers a number, status must
    say Charging; if Runtime Left answers, status must say Discharging."""
    cases = [
        ({3: 50, 21: 3000, 4: 500}, None),   # net +2500 -> charging, deficit > 0
        ({3: 50, 21: 0, 4: 900}, None),      # net -900  -> discharging
    ]
    for attrs, ext in cases:
        status = battery_status("guardian", attrs, ext)
        net = attrs.get(21, 0) - total_load_w(attrs)
        if net >= 5 and missing_energy_wh("guardian", attrs, ext) > 0:
            assert status == "Charging"
            assert time_to_full_minutes(missing_energy_wh("guardian", attrs, ext), net)
        if net <= -5:
            assert status == "Discharging"
            assert runtime_estimate_minutes(
                stored_energy_wh("guardian", attrs, ext), total_load_w(attrs)
            )


def test_battery_status_sensor_registered_and_gated():
    src = (
        Path(__file__).resolve().parents[1]
        / "custom_components" / "oupes_mega_ble" / "sensor.py"
    ).read_text(encoding="utf-8")
    assert 'key="battery_status"' in src
    block = src.split("_WP_ONLY_SENSOR_KEYS = frozenset")[1]
    assert '"battery_status"' in block[: block.rindex("}")]


# ------------------------- runtime must use NET drain (house > charge case)

def test_runtime_uses_net_drain_not_gross_load():
    """Solar 1000 W into a 1500 W house: battery loses ~500 W, not 1500.
    Dividing by gross load would understate the time left 3x. And when PV
    covers the house outright the question is void -> refuse, never count
    down while `Battery Status` says Charging."""
    full = 4 * UNIT
    assert runtime_estimate_minutes(full, 1500 - 1000) == round(full / 500 * 60, 1)
    assert runtime_estimate_minutes(full, 500 - 2000) is None   # net charging
    assert runtime_estimate_minutes(full, 800 - 800) is None    # PV covers house


def test_runtime_branch_answers_the_owners_question():
    """POLICY (owner, 2026-10-19): Runtime Left = stored Wh / TOTAL load —
    'if the input stopped right now, how long does the house run?' It must
    answer in every state, charging included; a number that vanishes next
    to a Charging status read as a malfunction. Do NOT reintroduce net-drain
    subtraction here without the owner asking for it."""
    src = (
        Path(__file__).resolve().parents[1]
        / "custom_components" / "oupes_mega_ble" / "sensor.py"
    ).read_text(encoding="utf-8")
    branch = src.split('desc.key == "runtime_estimate"')[1].split("if desc.key")[0]
    assert "runtime_estimate_minutes(energy, load)" in branch, (
        "runtime branch must divide by total load (blackout-time semantics)"
    )
    assert "net_drain" not in branch, (
        "net-drain subtraction was removed by owner decision; the question "
        "is 'how long would this battery last', not 'how fast is it falling'"
    )


def test_runtimes_speak_words_not_raw_durations():
    """The seconds-unit duration doctrine is DEAD (owner screenshot
    2026-10-20: HA 2026.10 renders 'Estimated Runtime Left' as the literal
    '69,138.00 s' on the device page, and external-pack durations as
    '1,158m'). Every duration the device page shows is now a WORDS sensor
    ('19h 11m') via _hm_text - same decision as time-to-full. If this test
    fails because someone re-added DURATION/MEASUREMENT to a runtime
    description, read the screenshot comment in sensor.py first."""
    src = (
        Path(__file__).resolve().parents[1]
        / "custom_components" / "oupes_mega_ble" / "sensor.py"
    ).read_text(encoding="utf-8")
    block = src.split('key="runtime_estimate"')[1].split("),")[0]
    assert "device_class" not in block, "runtime_estimate must be a TEXT sensor"
    assert "state_class" not in block
    assert "_hm_text(minutes)" in src, "runtime_estimate must render words"
    ext = src.split('key=f"ext_battery_{slot}_runtime"')[1].split("\n        ),")[0]
    assert "_hm_text(v)" in ext, "external pack runtime must render words"
    assert "state_class" not in ext
    helper = src.split("def _hm_text")[1].split("def ")[0]
    assert 'f"{h}h {m:02d}m"' in helper, "words format must be 'Xh YYm'"


def test_time_to_full_speaks_words_not_unknown():
    """'unknown' on a device page is not UX (owner 2026-10-20). The entity
    refuses NUMBERS with WORDS: Not charging / Full / Nearly full, and
    formats real durations itself ('Xh YYm') since it lost the duration
    device-class needed for text states."""
    src = (
        Path(__file__).resolve().parents[1]
        / "custom_components" / "oupes_mega_ble" / "sensor.py"
    ).read_text(encoding="utf-8")
    block = src.split('key="time_to_full"')[1].split("),")[0]
    assert "UnitOfTime" not in block, "duration unit would forbid text states"
    branch = src.split('minutes = time_to_full_minutes')[1]
    for word in ("Not charging", "Full", "Nearly full", "h {m:02d}m"):
        assert word in branch, f"refusal vocabulary lost: {word}"


def test_stored_energy_is_a_total_not_a_bare_gauge():
    """Stored energy is a LEVEL: rises charging, falls discharging.

    Policy history (do not re-litigate by trial and error - the repair floor
    keeps the receipts):
      MEASUREMENT  -> 2026 core rejects ENERGY+measurement, entity errored.
      None (v1.4.13) -> LTS that already existed got orphaned; core raised
                        'entity no longer has a state class' as a repair issue.
      TOTAL        -> correct: summable but NON-monotonic; LTS resumes and
                      the energy dashboard treats it as a storage quantity.
    Guards: measurement would have errored at registration; total_increasing
    would lie (and clamp/reset-loop on every discharge).
    """
    from homeassistant.components.sensor import SensorStateClass
    from custom_components.oupes_mega_ble.sensor import SENSOR_DESCRIPTIONS
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "stored_energy_wh")
    assert desc.state_class is SensorStateClass.TOTAL, (
        "stored energy must be TOTAL: None orphans existing statistics "
        "(repair floor issue) and MEASUREMENT/TOTAL_INCREASING are rejected "
        "or dishonest for a battery level"
    )


# ------------------------------------------------- awake-idle draw (1.4.15)
# 2026-10-20 measured no-load day: Guardian V2 burns ~57 W just being awake,
# invisible to every output register.  Dividing runtime by OUTPUT load alone
# both flatters the answer AND (light loads) exceeds the refusal ceiling so
# the entity shows unknown while a correct number was one addition away.

def test_awake_idle_draw_constant_measured_value():
    assert protocol.AWAKE_IDLE_DRAW_W["guardian"] == 57.0
    assert protocol.awake_idle_draw_w("guardian") == 57.0

def test_unknown_series_gets_zero_not_a_guess():
    assert protocol.awake_idle_draw_w("mega1") == 0.0

def test_output_only_divisor_is_the_refusal_bug():
    # real 2026-10-20 window: 17188 Wh stored, 65 W filter
    assert runtime_estimate_minutes(17188, 65.0) is None  # >1 week -> refused
    with_idle = runtime_estimate_minutes(17188, 65.0 + 57.0)
    assert with_idle is not None
    assert 8400 < with_idle < 8700  # ~142 h, inside the honest ceiling

def test_idle_draw_never_negative_or_absurd():
    for w in protocol.AWAKE_IDLE_DRAW_W.values():
        assert 5.0 <= w <= 200.0  # plausible inverter-stage idle range


# --------------------------------------------------------------------------
# v1.4.16: AC Output + Inverter - measured loss curve
# --------------------------------------------------------------------------
from protocol import inverter_overhead_w  # noqa: E402


def test_overhead_curve_hits_every_anchor_exactly():
    """Anchors are measurements or owner decisions; interpolation may never
    drift them (2026-10-20 Guardian V2; see protocol provenance comment)."""
    for x, y in [(0, 57), (65, 57), (500, 120), (2100, 225), (4000, 450), (6000, 1059)]:
        assert abs(inverter_overhead_w(x) - y) < 0.01, f"anchor {x} W moved"


def test_overhead_curve_endpoints_clamp():
    """Beyond the measured range the curve holds - no invented slope."""
    assert inverter_overhead_w(-500) == 57.0     # floor: idle, never negative
    assert inverter_overhead_w(99999) == 1059.0  # ceiling: 85% pin, no runaway


def test_overhead_curve_monotonic_and_bounded():
    """Overhead never decreases with load, and total stays physical
    (between the register and register+2000 W anywhere on the curve)."""
    prev = -1.0
    for w in range(0, 6001, 25):
        oh = inverter_overhead_w(w)
        assert oh >= prev - 1e-9, f"overhead dipped at {w} W"
        assert 0 <= oh <= 2000, f"overhead unphysical at {w} W: {oh}"
        prev = oh


def test_filter_day_reproduced_end_to_end():
    """The 2026-10-20 ground truth: 64 W AC register -> battery paid 121 W
    (BMS odometer route). The curve must reproduce its own origin."""
    assert abs((64 + inverter_overhead_w(64)) - 121) < 1.0


def test_legacy_entry_gets_product_id_from_advertisement():
    """Owner-hit 2026-10-20: an entry paired before product_id was persisted
    ('' in entry data) resolved series=unknown at setup, so EVERY series-
    gated entity (stored energy, both ETAs, battery status) was silently
    refused - they simply did not exist after reload, and HA's orphan sweep
    made the absence permanent. Setup must fall back to the live
    advertisement (same source the config flow trusts) and self-heal the
    entry."""
    src = (
        Path(__file__).resolve().parents[1]
        / "custom_components" / "oupes_mega_ble" / "__init__.py"
    ).read_text(encoding="utf-8")
    assert "_extract_product_id_for_address(hass, address)" in src, \
        "advertisement fallback lost - legacy entries lose all computed sensors"
    assert "async_update_entry" in src, \
        "self-heal lost: learned id must be persisted, not re-learned per boot"
    # import must stay deferred (voluptuous must not ride every import)
    head = src.split("async def ")[0]
    assert "from .config_flow import" not in head, "config_flow import must stay lazy"

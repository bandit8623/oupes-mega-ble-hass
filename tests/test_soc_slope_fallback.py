"""SoC-slope fallback for a silent main-pack input register (bare interpreter).

Field case 2026-10-21, Guardian 6000 V2 + 3 external packs: during a 4 kW
solar charge every external pack reported its input watts while the MAIN
unit's battery-input register (dpid 24) sat at 0 with its SoC climbing
71->73%.  Time-to-full divides by measured charge watts, so the ETA
overstated the wait by whatever the main pack was quietly absorbing.
protocol.soc_slope_w infers pack-side watts from the SoC climb - and must
refuse rather than believe a BMS recalibration jump.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "oupes_mega_ble"))

import protocol  # noqa: E402
from protocol import soc_slope_w  # noqa: E402

UNIT = 4608


def _s(a, b, span=1800):
    """two samples, `span` seconds apart."""
    return [(0.0, a), (float(span), b)]


def test_honest_climb_becomes_watts():
    # +2% of 4608 Wh over 30 min = 92.16 Wh / 0.5 h = 184.3 W
    assert soc_slope_w(_s(71, 73), UNIT) == 184.3


def test_needs_at_least_ten_minutes_of_span():
    # 1% = 46 Wh; a 2-minute window is quantisation noise pretending to be a rate
    assert soc_slope_w([(0.0, 71), (120.0, 72)], UNIT) is None


def test_flat_soc_is_not_charging():
    assert soc_slope_w(_s(80, 80), UNIT) is None


def test_falling_soc_is_refused_not_negative_watts():
    assert soc_slope_w(_s(80, 78), UNIT) is None


def test_bms_recalibration_jump_is_refused():
    # 30% in under a minute: physics says no (would imply ~12 kW into one pack)
    assert soc_slope_w([(0.0, 60), (700.0, 90)], UNIT) is None


def test_stale_history_is_refused():
    # older than the 45-min window describes a charge rate that is already gone
    assert soc_slope_w([(0.0, 70), (4000.0, 71), (4200.0, 72)], UNIT) is None


def test_uses_oldest_sample_inside_the_window():
    # warm-up sample outside the window must not flatten the measured slope
    pts = [(0.0, 60), (2000.0, 70), (3500.0, 72)]  # span 2000->3500 = 25 min, +2%
    assert soc_slope_w(pts, UNIT) == round(2 / 100 * UNIT / (1500 / 3600), 1)


def test_no_capacity_no_math():
    assert soc_slope_w(_s(71, 73), None) is None
    assert soc_slope_w(_s(71, 73), 0) is None


def test_short_history_refuses():
    assert soc_slope_w([(0.0, 71)], UNIT) is None
    assert soc_slope_w([], UNIT) is None


def test_bool_soc_is_not_a_percentage():
    # True is an int in Python; a firmware glitch emitting bools must not count
    assert soc_slope_w([(0.0, True), (1800.0, True)], UNIT) is None


def test_sensor_layer_wires_the_fallback_into_time_to_full():
    """The register-0 case is detected at the ETA site, not inside the math:
    sensor.py must add the slope only while externals prove a real charge
    window and dpid 24 reports <= 0."""
    src = (Path(__file__).resolve().parents[1] / "custom_components" /
           "oupes_mega_ble" / "sensor.py").read_text(encoding="utf-8")
    assert "soc_slope_w(" in src
    seg = src[src.index("ext_in > 0 and ("):src.index("charge_w += slope")]
    assert "soc_slope_w" in seg and "soc_samples" in seg


def test_coordinator_keeps_the_sample_history():
    src = (Path(__file__).resolve().parents[1] / "custom_components" /
           "oupes_mega_ble" / "coordinator.py").read_text(encoding="utf-8")
    assert "soc_samples" in src
    assert "_record_soc" in src


def test_sample_history_is_throttled_to_outrun_the_deque():
    """Regression: live push is 1-2s; an unthrottled deque(240) holds <10 min
    and soc_slope_w's minimum span never arms (observed live 2026-10-21:
    ETA stayed at the externals-only value through a whole charge climb).
    Recording must be throttled so 240 samples span well past 10 minutes."""
    src = (Path(__file__).resolve().parents[1] / "custom_components" /
           "oupes_mega_ble" / "coordinator.py").read_text(encoding="utf-8")
    seg = src[src.index("def _record_soc"):src.index("def _record_soc") + 1200]
    assert "< 30.0" in seg, "_record_soc must throttle sampling or history starves"

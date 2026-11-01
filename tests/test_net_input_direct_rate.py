"""v1.4.23: owner-math primary - ETA from net inlet watts, no window.

Owner directive 2026-11-01, watching a correct ~6 h charge render as
`8h 48m -> 22h 41m`: "it should be simple. base it off usage and total
input. we don't need an hour of data to calculate this."  Correct:
dpid 21 (everything in) minus dpid 4 (house out) IS the charge rate;
one measured constant (charge-path efficiency, fitted from the stored-Wh
tank slope on two Guardian sessions: 0.85 and 0.93) makes it pack-side
watts.  Instant on the first update of a session; no windows to poison it.

These tests pin the direct rate, its refusal rules, the calibration, and
that the old meter/chord path still answers for series without a
measured efficiency.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "oupes_mega_ble"))

from protocol import (  # noqa: E402
    CHARGE_PATH_EFFICIENCY,
    missing_energy_wh,
    net_input_charge_rate_w,
    time_to_full_minutes,
)

NET = 3100.0  # 2026-11-01 05:05 UTC field: dpid21 4006 - dpid4 907


def test_direct_rate_is_net_input_times_measured_efficiency():
    # calibration window: the two fitted sessions (0.85, 0.93) must both
    # land inside +/-10% of what the constant produces
    rate = net_input_charge_rate_w(NET, "guardian")
    assert rate == round(NET * CHARGE_PATH_EFFICIENCY["guardian"], 1)
    tank_085 = NET * 0.85
    tank_093 = NET * 0.93
    assert abs(rate - tank_085) / tank_085 <= 0.10
    assert abs(rate - tank_093) / tank_093 <= 0.10


def test_morning_field_case_eta_is_six_hours_not_eightforty():
    """2026-11-01 05:06 UTC truth: stored 1106 Wh, net input 3100 W, tank
    visibly climbing ~2.6 kW -> honest ETA ~6 h.  The display was 8h 48m."""
    stored = 1105.9
    soc = round(stored / (4 * 4608.0) * 100)
    deficit = missing_energy_wh("guardian", {3: 5}, {i: {79: 5} for i in (1, 2, 3)})
    # deficit from SoC percentages (5% x 4 packs): use it directly
    rate = net_input_charge_rate_w(NET, "guardian")
    minutes = time_to_full_minutes(deficit, rate)
    hours = minutes / 60.0
    assert 5.0 < hours < 7.5, hours   # ~6.3 h; old display said 8.8 h
    assert soc >= 0


def test_refuses_when_not_charging():
    assert net_input_charge_rate_w(0.0, "guardian") is None
    assert net_input_charge_rate_w(-500.0, "guardian") is None  # on battery
    assert net_input_charge_rate_w(None, "guardian") is None
    assert net_input_charge_rate_w(True, "guardian") is None    # bool guard


def test_unknown_series_falls_back():
    """Series without a MEASURED efficiency must return None so the sensor
    keeps the meter/chord machinery - an unmeasured constant must not
    silently enter anyone's ETA (same rule as AWAKE_IDLE_DRAW_W)."""
    assert net_input_charge_rate_w(3000.0, "mega") is None
    assert net_input_charge_rate_w(3000.0, "") is None


def test_direct_rate_arms_instantly_on_first_update():
    """The whole point: no history.  A charge session's first update with
    net input > 0 already answers - cold start by construction."""
    rate = net_input_charge_rate_w(2700.0, "guardian")  # 2026-10-25 cold-start field numbers
    minutes = time_to_full_minutes(15000.0, rate)
    assert minutes is not None
    assert 5.0 * 60 < minutes < 8 * 60


def test_sensor_uses_direct_rate_first():
    """Source pin: the time_to_full site must try the direct rate BEFORE
    touching meters/chord, and keep the chord inside a `charge_w is None`
    fallback (never silently outranking owner math on a measured series)."""
    src = (Path(__file__).resolve().parents[1] / "custom_components" /
           "oupes_mega_ble" / "sensor.py").read_text(encoding="utf-8")
    seg = src[src.index('desc.key == "time_to_full"'):]
    assert seg.index("net_input_charge_rate_w") < seg.index("absorption_chord_w")
    assert "if charge_w is None:" in seg

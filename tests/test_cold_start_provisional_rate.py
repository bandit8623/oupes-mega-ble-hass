"""Cold-start provisional ETA rate from AC net input (bare interpreter).

Owner review 2026-10-25, minutes after side-loading 1.4.21:
`estimated_runtime_left` showed `7h 08m` immediately while time-to-full sat
at `Measuring` with dpid 21 - dpid 4 plainly reading ~2.7 kW flowing in.
The asymmetry was structural: runtime divides by ONE always-present
register (main AC output); time-to-full divides by FOUR pack-side charge
meters polled asynchronously, and after a full restart the stored-Wh
chord has no window yet either.  protocol.cold_start_rate_w fills exactly
that hole with the main unit's AC net input - provisional-grade, outranked
by the chord or a complete meter set the moment either exists.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "oupes_mega_ble"))

from protocol import (  # noqa: E402
    ABSORPTION_MAX_W,
    absorption_chord_w,
    cold_start_rate_w,
    meter_priority_w,
    time_to_full_minutes,
)


def test_cold_start_accepts_a_real_charge():
    # restart 2026-10-25 08:18: dpid21 3596 W - dpid4 899 W = 2697 W in.
    assert cold_start_rate_w(2697.0) == 2697.0


def test_cold_start_refuses_no_charge_and_discharge():
    assert cold_start_rate_w(None) is None
    assert cold_start_rate_w(0.0) is None
    assert cold_start_rate_w(-1500.0) is None  # net export = discharging


def test_cold_start_refuses_register_glitch():
    assert cold_start_rate_w(ABSORPTION_MAX_W + 1) is None


def test_cold_start_eta_is_sane_on_field_numbers():
    # rack at ~57%, ~43% of a 4608 Wh unit still needed.
    eta = time_to_full_minutes(0.43 * 4608, cold_start_rate_w(2697.0))
    assert eta is not None
    assert 35 < eta < 60  # ~46 min honest answer; old code said "Measuring"


def test_chord_outranks_cold_start_when_window_fills():
    # ~10 min after boot the chord exists again; the provisional rate must
    # never override it.  Modelled at the pure-function level: the sensor
    # only calls cold_start_rate_w when absorption_chord_w returned None,
    # and a filled window is not None.
    now = 1_000_000.0
    # coordinator's real cadence: one stored-Wh sample per ~60 s poll, a
    # steady 2 kW of stored fill over 15 min.
    samples = [(now - 900 + i * 60, 40_000 + i * 33) for i in range(16)]
    assert absorption_chord_w(samples) is not None  # gate in sensor.py holds


def test_meter_priority_still_hammers_clamped_slopes():
    # 1.4.21 behaviour untouched by the 1.4.21 addition.
    assert meter_priority_w(450.0, 4000.0) == 4000.0

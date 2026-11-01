"""v1.4.22: the chord must never measure across a discharge->charge V.

Field case 2026-10-31 (owner screenshot `21h 29m` at 21:45 CDT): the rack
discharged for 70+ min (house on battery, stored-Wh tank FALLING ~1.5 kW),
then transferred to charging at ~4 kW.  absorption_chord_w's 30-min window
spanned the transition, so a tank genuinely climbing at 2.9 kW produced
`dWh = newest - oldest` across the V: a few hundred Wh over 28 min = a fake
~750 W rate.  The ETA ladder replayed `5h 54m (true) -> 86h 42m -> 21h 29m
-> 19h 03m -> 17h 09m` and only crawled back as the downhill samples aged
out of the window - 30+ minutes of a 3-16x-too-long ETA on every transfer.

Fix: when the window holds a real fall (> ABSORPTION_DROP_TOL_WH), clamp the
oldest endpoint forward to the trough; the chord then integrates the RISE
only.  Pure-downhill windows still return None.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "oupes_mega_ble"))

from protocol import (  # noqa: E402
    ABSORPTION_CHORD_MIN_SPAN_S,
    ABSORPTION_DROP_TOL_WH,
    ABSORPTION_MAX_SPAN_S,
    absorption_chord_w,
)

POLL = 30.0
STEP = 46.08  # 1% of one 4608 Wh pack: the stored-Wh quantisation size


def _session(discharge_w, charge_w, before_s, after_s, quantised=False, start_wh=3100.0):
    """Tank: fall at discharge_w for before_s, then rise at charge_w for after_s.
    Piecewise-exact at the bottom so slope assertions are unambiguous."""
    bottom_t = float(before_s)

    def raw(t):
        if t <= bottom_t:
            return start_wh - discharge_w * t / 3600.0
        base = start_wh - discharge_w * bottom_t / 3600.0
        return base + charge_w * (t - bottom_t) / 3600.0

    out = []
    t = 0.0
    while t <= before_s + after_s + 1e-9:
        v = raw(t)
        if quantised:
            v = round(v / STEP) * STEP
        out.append((t, v))
        t += POLL
    return out, bottom_t


def test_v_window_reports_the_rise_not_the_net():
    """The field replay: 60 min downhill + 12 min of 2.9 kW rise (the exact
    moment the chord first armed on 2026-10-31).  Old code: ~450 W across the
    V -> 86h ETA.  Fixed code: the rise's own slope."""
    samples, _ = _session(1500.0, 2900.0, 60 * 60, 12 * 60)
    rate = absorption_chord_w(samples)
    assert rate is not None
    assert abs(rate - 2900.0) < 50.0, rate


def test_v_window_quantised_staircase():
    """Same V with real integer-percent quantisation (46 Wh steps): the clamp
    lands on a step, so allow one step of slack over the 7-min chord span."""
    samples, _ = _session(1500.0, 2900.0, 60 * 60, 16 * 60, quantised=True)
    rate = absorption_chord_w(samples)
    assert rate is not None
    span = samples[-1][0] - samples[0][0]
    tol = STEP / (min(span, ABSORPTION_MAX_SPAN_S) / 3600.0) + 60.0
    assert abs(rate - 2900.0) <= tol, rate


def test_pure_discharge_window_still_refuses():
    """Tank only falling: the trough IS the newest point, no clamp applies,
    and the chord must keep returning None (meters/Measuring decide)."""
    out = []
    wh, t = 9000.0, 0.0
    for _ in range(120):
        out.append((t, wh))
        wh -= 1500.0 * POLL / 3600.0
        t += POLL
    assert absorption_chord_w(out) is None


def test_valley_too_fresh_defers_to_meters():
    """If the bottom is younger than the chord's 7-min minimum span the rise
    is not yet measurable: refuse rather than divide a short leg."""
    samples, _ = _session(1500.0, 2900.0, 60 * 60, ABSORPTION_CHORD_MIN_SPAN_S - 120)
    assert absorption_chord_w(samples) is None


def test_quantiser_jitter_does_not_trigger_the_clamp():
    """A window with NO real fall (flat line wobbling +/-1 step) must behave
    exactly as before the fix: endpoint-to-endpoint chord, no clamp."""
    import random
    random.seed(7)
    out = []
    t = 0.0
    for i in range(80):
        out.append((t, 6000.0 + random.choice([-STEP, 0.0, STEP])))
        t += POLL
    # precondition: no sub-window dip exceeds the tolerance -> clamp must not arm
    lowest = min(p[1] for p in out)
    assert out[0][1] - lowest <= ABSORPTION_DROP_TOL_WH
    window = [p for p in out if out[-1][0] - p[0] <= ABSORPTION_MAX_SPAN_S]
    dwh = window[-1][1] - window[0][1]
    span = window[-1][0] - window[0][0]
    expect = None if dwh <= 0.0 else round(dwh / (span / 3600.0), 1)
    assert absorption_chord_w(out) == expect


def test_dip_below_tolerance_does_not_trigger_the_clamp():
    """Pack-blip noise (a few hundred Wh < tolerance) inside a steady climb:
    unchanged behaviour - the chord still reads the whole-window slope."""
    out = []
    wh, t = 5000.0, 0.0
    for i in range(80):
        w = wh
        if i == 40:
            w = wh - (ABSORPTION_DROP_TOL_WH - 50.0)  # sub-tolerance blip
        out.append((t, w))
        wh += 2500.0 * POLL / 3600.0
        t += POLL
    rate = absorption_chord_w(out)
    assert rate is not None
    assert abs(rate - 2500.0) < 120.0, rate


def test_old_code_would_have_failed_this():
    """Regression pin for the bug itself: the net-across-V slope (what the
    pre-fix chord returned) is materially smaller than the true rise rate."""
    samples, _ = _session(1500.0, 2900.0, 60 * 60, 12 * 60)
    window = [p for p in samples if samples[-1][0] - p[0] <= ABSORPTION_MAX_SPAN_S]
    net = (window[-1][1] - window[0][1]) / ((window[-1][0] - window[0][0]) / 3600.0)
    assert net < 900.0 < abs(absorption_chord_w(samples) or 0.0) / 3.0

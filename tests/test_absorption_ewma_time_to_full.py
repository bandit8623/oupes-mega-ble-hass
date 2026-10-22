"""Stored-energy EWMA as the primary time-to-full rate (bare interpreter).

Field case 2026-10-22, Guardian 6000 V2 + 3 external packs, 03:48 charge
start at 88% (3594.2 Wh short of the 18432 Wh tank):
  - instantaneous meters summed ~1858 W -> ETA said 1h56m
  - the stored-Wh sensor filled at 2903 Wh/h -> real CC leg, Full at 84 min
  - last 15 min the firmware tapered (4.0 kW -> 1.6 kW in, 922 Wh/h absorbed)
The tank's own slope sees all of this without trusting any single register,
so protocol.absorption_ewma_w feeds the ETA and the meters became fallback.
Numbers below are the actual soak-CSV rows (60 s cadence), downsampled to
the 30 s recording throttle.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "oupes_mega_ble"))

from protocol import (  # noqa: E402
    ABSORPTION_MAX_W,
    absorption_ewma_w,
    missing_energy_wh,
    time_to_full_minutes,
)

UNIT = 4608  # guardian: WH_PER_BATTERY_UNIT, one rack battery = 4.608 kWh


def _ramp(watts, n, step_s=30.0, start_wh=14837.8, t0=0.0):
    """n samples of a constant-`watts` fill of the Wh tank, 30 s apart."""
    per = watts * step_s / 3600.0
    return [(t0 + i * step_s, start_wh + i * per) for i in range(n)]


# ---------------------------------------------------------------- unit math

def test_constant_fill_measures_the_true_rate():
    # 2900 W for 20 min (40 samples) must read back as ~2900, not meter-noise
    assert abs(absorption_ewma_w(_ramp(2900, 40)) - 2900) < 5


def test_needs_five_minutes_of_history():
    assert absorption_ewma_w(_ramp(2900, 5)) is None     # 4 x 30 s = 2 min
    assert absorption_ewma_w(_ramp(2900, 12)) is not None  # 11 x 30 s = 5.5 min


def test_needs_three_samples_no_matter_the_clock():
    assert absorption_ewma_w([(0.0, 100.0), (30.0, 110.0)]) is None
    assert absorption_ewma_w([]) is None


def test_discharge_is_reported_negative_letting_the_eta_refuse():
    drain = [(i * 30.0, 18000.0 - 500 * i * 30.0 / 3600.0) for i in range(40)]
    w = absorption_ewma_w(drain)
    assert w is not None and w < 0  # time_to_full_minutes rejects <threshold


def test_noise_is_smoothed_but_signal_survives():
    pts = [(i * 30.0, 15000.0 + 2000 * 30 / 3600.0 * i + (5 if i % 2 else -5))
           for i in range(40)]
    w = absorption_ewma_w(pts)
    # per-slope noise here is +/-1.2 kW; EWMA keeps the answer within ~25% of
    # truth - an EWMA is a lag filter, not a median, and the ETA moves in
    # minutes, not sample periods.  What must NOT happen is a faked rate.
    assert 1700 < w < 2500


def test_cv_taper_is_tracked_not_flattered():
    """30 min at 2900 W then the newest stretch at 900 W: the EWMA must sit
    nearer the NEW rate - the whole point of weighting recent slopes.  A flat
    average over the window would say ~2100 and promise a full charge that
    never lands (the 05:04-05:12 'estimate got worse' flapping, inverted)."""
    hot = _ramp(2900, 50)                      # 25 min CC
    cold = _ramp(900, 20, start_wh=hot[-1][1], t0=hot[-1][0])  # 10 min CV
    w = absorption_ewma_w(hot + cold)
    assert w < 1600, f"EWMA stuck in the constant-current leg: {w}"
    assert w > 900, f"EWMA overshot past the taper: {w}"


def test_glitch_beyond_physics_is_refused():
    pts = [(i * 30.0, 15000.0 + ABSORPTION_MAX_W * 2 * i * 30 / 3600.0)
           for i in range(40)]
    assert absorption_ewma_w(pts) is None  # 16 kW into a 5 kW rack: counter lie


def test_hot_swapped_pack_beyond_the_window_cannot_pollute():
    old = _ramp(50, 20)                                   # ancient trickle
    new = _ramp(3000, 40, start_wh=1000.0, t0=2000.0)     # real charge, fresh
    w = absorption_ewma_w([(t - 2000.0, wh) for t, wh in old] + new)
    assert w is not None and abs(w - 3000) < 300          # window: last 30 min only


def test_bool_wh_is_not_energy():
    assert absorption_ewma_w([(0.0, True), (60.0, 1.0), (120.0, 2.0)]) is None


# ------------------------------------------------- tonight's charge, in full

# stored_wh sampled from the 60 s soak CSV, 03:48 -> 05:12 (CC ~2903 W avg,
# taper last 15 min).  Reconstructed at 60 s cadence from the logged deltas.
_TANK = [14837.8, 14929.9, 15160.3, 15436.8, 15667.2, 15897.6, 16220.2,
         16450.6, 16727.0, 17003.5, 17233.9, 17464.3, 17740.8, 17971.2,
         18155.5, 18293.8, 18385.9, 18432.0]
_T = [(i * 240.0, wh) for i, wh in enumerate(_TANK)]  # ~4 min per logged row


def test_tonights_charge_would_have_been_forecast_under_90_minutes():
    """The owner's complaint, as an assertion: at 03:48 the ETA said 1h56m;
    the truth was 84 min.  Mid-CC the EWMA (fed the real tank curve) sees
    ~3.9 kW of absorption and forecasts ~55 min for the remaining deficit;
    the lying meters said 115.9.  Both bounds below fail with the old code."""
    deficit = 18432.0 - 14837.8                       # == 3594.2 Wh, 88%
    mid_charge_rate = absorption_ewma_w(_T[:13])      # before the CV taper begins
    assert mid_charge_rate is not None and mid_charge_rate > 2500
    minutes = time_to_full_minutes(deficit, mid_charge_rate)
    assert minutes is not None
    assert minutes <= 90, f"regression: ETA {minutes:.0f} min, real charge 84"
    # and strictly better than what the summed instantaneous meters produced
    assert minutes < time_to_full_minutes(deficit, 1858.0)
    # late in the taper the EWMA honestly drops toward the CV rate, which is
    # the 'estimate gets worse near the end' behaviour - correct, not flapping
    assert 1500 < absorption_ewma_w(_T) < 3200


def test_deficit_side_still_uses_the_single_inclusion_rule():
    # absorption replaces the RATE only; deficit stays nameplate x SoC across
    # main + externals (4 units at 88% combined)
    ext = {i: {79: 88} for i in (1, 2, 3)}
    d = missing_energy_wh("guardian", {3: 88}, ext)
    assert d == round((100 - 88) / 100 * UNIT * 4, 1)


# ------------------------------------------------------------ wiring (grep)

def test_sensor_prefers_absorption_behind_the_charging_gate():
    src = (Path(__file__).resolve().parents[1] / "custom_components" /
           "oupes_mega_ble" / "sensor.py").read_text(encoding="utf-8")
    seg = src[src.index("absorption = absorption_ewma_w"):src.index("minutes = time_to_full_minutes(deficit, charge_w)")]
    assert "energy_samples" in seg
    assert "absorption > 0.0" in seg
    assert "ext_in > 0 or net_input_w > 0" in seg   # same evidence gate as soc_slope
    assert src.count("absorption = absorption_ewma_w") == 1


def test_coordinator_records_and_throttles_energy_samples():
    src = (Path(__file__).resolve().parents[1] / "custom_components" /
           "oupes_mega_ble" / "coordinator.py").read_text(encoding="utf-8")
    assert "self.energy_samples: deque = deque(maxlen=120)" in src
    body = src[src.index("def _record_energy"):src.index("def _record_energy") + 1200]
    assert "stored_energy_wh(" in body
    assert "< 30.0" in body                          # throttled like _record_soc
    assert src.count("self._record_energy(data)") == 2  # both push + poll paths


def test_absorption_imported_where_used():
    base = Path(__file__).resolve().parents[1] / "custom_components" / "oupes_mega_ble"
    assert "absorption_ewma_w" in (base / "sensor.py").read_text(encoding="utf-8")
    assert "def absorption_ewma_w" in (base / "protocol.py").read_text(encoding="utf-8")

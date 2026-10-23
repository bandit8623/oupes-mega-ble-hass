"""Wh-tank artifacts must not be allowed to choose the time-to-full source.

Field case 2026-10-23, Guardian 6000 V2 + 3 external packs, 4 h solar charge
recorded from the HA recorder (248 samples, 237 min, least-squares absorption
2671 W).  The displayed ETA read 10h42m against a measured 2h42m truth, and 25%
of consecutive updates moved by two hours or more.  Neither symptom came from
the charge: it came from two properties of stored_energy_wh().

  1. It sums only the packs that ANSWERED the poll.  A pack that skipped a cycle
     reads as several hundred Wh vanishing, and the reply arriving again reads as
     the same Wh reappearing.
  2. It is derived from integer-percent SoC, so it advances in ~46 Wh stairs;
     two resyncs inside one 30 s pair imply more than 10 kW.

Both used to end the same way: a big positive EWMA tripped the ABSORPTION_MAX_W
guard, which returned None, and the ETA fell to the instantaneous meters -
main-pack register pinned at 0-67 W while charging, plus often one of three
external packs reporting ~800 W total.  Measured over that window: 59% of
samples refused, median rate used 5025 W (impossible), median ETA error 133 min.
Now: 13% refused (only true cold starts), median rate 2940 W, median error 50 min.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "oupes_mega_ble"))

from protocol import (  # noqa: E402
    ABSORPTION_MAX_W,
    absorption_ewma_w,
    ttf_rate_hysteresis,
)

BASE = Path(__file__).resolve().parents[1] / "custom_components" / "oupes_mega_ble"
RATE = 2900.0  # the recorded CC-leg absorption, W


def _steady(n, step_s=30.0, start_wh=6000.0, watts=RATE):
    return [(i * step_s, start_wh + watts * i * step_s / 3600.0) for i in range(n)]


def test_dropped_pack_reply_does_not_invert_the_estimate():
    """A pack going quiet mid-window is a reporting hole, not a discharged rack."""
    pts = _steady(30)
    pts[15] = (pts[15][0], pts[15][1] - 700.0)      # one cycle summed fewer packs
    got = absorption_ewma_w(pts)
    assert got is not None
    assert 0.75 * RATE <= got <= 1.25 * RATE, got     # was: pulled down / refused


def test_resync_stair_step_does_not_blind_the_estimator():
    """Two integer-SoC steps in one pair imply >8 kW; the honest answer is still 2.9 kW."""
    pts = _steady(30)
    pts[20] = (pts[20][0], pts[20][1] + 4000.0)      # BMS re-estimate / double step
    got = absorption_ewma_w(pts)
    assert got is not None, "a single spike must not throw the window away"
    assert 0.75 * RATE <= got <= 1.35 * RATE, got


def test_whole_window_beyond_physics_is_still_refused():
    """Clamping is for samples; a window that is ALL 16 kW is a lying counter."""
    pts = [(i * 30.0, 15000.0 + ABSORPTION_MAX_W * 2 * i * 30 / 3600.0)
           for i in range(40)]
    assert absorption_ewma_w(pts) is None


def test_hysteresis_holds_through_one_bad_sample_then_adopts():
    """A rate must survive a single artifact and still follow a real taper."""
    rate, streak = ttf_rate_hysteresis(None, 2900.0, 0)
    assert (rate, streak) == (2900.0, 0)              # nothing held yet: take it
    for expected in (1, 2):                           # hold 1st, 2nd disagreement
        rate, streak = ttf_rate_hysteresis(2900.0, 500.0, streak)
        assert rate == 2900.0 and streak == expected
    rate, streak = ttf_rate_hysteresis(2900.0, 500.0, streak)
    assert (rate, streak) == (500.0, 0)               # 3rd: it is a real change
    rate, _ = ttf_rate_hysteresis(2900.0, None, 1)
    assert rate is None                               # a gap resets the hold


def test_partial_pack_set_cannot_drive_the_eta():
    """sensor.py may only divide the deficit by a COMPLETE pack set."""
    src = (BASE / "sensor.py").read_text(encoding="utf-8")
    assert "ext_reported == len(ext_known)" in src     # completeness gate exists
    assert "if meters_complete else None" in src        # incomplete => no meter rate
    assert '"Measuring"' in src                         # and says so, not 'Nearly full'


def test_energy_history_survives_a_coordinator_rebuild():
    """A reload must not reopen the 5-minute absorption blind window."""
    src = (BASE / "coordinator.py").read_text(encoding="utf-8")
    assert "_SAMPLE_MEMORY" in src
    body = src[src.index("_SAMPLE_MEMORY.get"):src.index("_SAMPLE_MEMORY.get") + 400]
    assert "self.soc_samples, self.energy_samples" in body

"""v1.4.20: the ETA rate must survive a quantized (staircase) SoC series.

Night of 2026-10-23/24 owner soak, charging rack, 426 samples: every SoC
register is an INTEGER percent, so total stored Wh moves in 46 Wh steps a
few minutes apart and is dead flat in between.  The old
absorption_ewma_w averaged 30 s pairwise slopes; on a staircase those are
mostly exactly zero, and the time_to_full sensor then doubled once per
poll until the next step landed.  The recorder capture: 468 state changes
with perfect ladders `2h -> 4h -> 8h -> 16h -> 34h -> 65h -> 99h -> snap
back to 2h 50m`, spikes every ~30 s, exactly at the poll cadence.

absorption_chord_w integrates over a 7-30 min window instead, which reads
the true average rate whatever the step phase.  These tests replay the
soak pattern itself.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "oupes_mega_ble"))

from protocol import (  # noqa: E402
    ABSORPTION_MAX_W,
    absorption_chord_w,
    absorption_ewma_w,
)

STEP = 46.1          # Wh in one 1% SoC step of one pack (x4608/100)
POLL = 30.0          # _record_energy throttle, seconds


def _staircase(rate_w=1700.0, polls=60, jitter=True):
    """Stored-Wh samples at the soak's exact rhythm: flat 30 s polls,
    +46 Wh steps every ~165 s, +/-1-step quantization jitter."""
    out = []
    wh = 12000.0
    t = 0.0
    step_every = STEP / (rate_w / 3600.0)            # seconds per 46 Wh step
    acc = 0.0
    for i in range(polls):
        out.append((t, wh))
        acc += POLL
        while acc >= step_every:
            acc -= step_every
            wh += STEP
            if jitter and i % 7 == 0:
                wh -= STEP                            # register bounce, -1%
        t += POLL
    return out


def test_chord_reads_true_rate_through_the_stairs():
    rate = absorption_chord_w(_staircase(1700.0))
    assert rate is not None
    assert abs(rate - 1700.0) / 1700.0 < 0.20        # soak truth +-20%


def test_the_old_ewma_is_the_measured_artifact():
    """The regression that shipped the bug: on the SAME staircase the old
    EWMA lands far below truth (or None).  If one day it doesn't, the
    function changed and this note is stale - not a failure to fear."""
    pts = _staircase(1700.0)
    old = absorption_ewma_w(pts)
    if old is not None:
        assert old < 1700.0 * 0.75 or old > 1700.0 * 1.25


def test_flat_series_is_not_invented_into_a_charge():
    pts = [(i * POLL, 12000.0) for i in range(40)]   # 20 min, dead flat
    assert absorption_chord_w(pts) is None           # <= 0 rate -> None


def test_short_history_measures_not():
    pts = _staircase(1700.0, polls=8)                # 4 min < 7 min window
    assert absorption_chord_w(pts) is None


def test_counter_reset_refused():
    pts = _staircase(1700.0)
    pts = pts + [(pts[-1][0] + POLL, pts[-1][1] - 5000.0)]
    assert absorption_chord_w(pts) is None           # implausible drop


def test_implausible_climb_refused():
    pts = [(0.0, 5000.0), (600.0, 5000.0 + 40000.0)]  # 240 kW pretend
    assert absorption_chord_w(pts) is None


def test_negative_soc_jitter_alone_never_flips_the_sign():
    # soak histogram truth: -46 Wh jitter appears 60x against 48x +46
    pts = []
    wh, t = 12000.0, 0.0
    for i in range(40):
        pts.append((t, wh if i % 3 else wh - STEP))
        if i % 2 == 0:
            wh += STEP                                # net positive
        t += POLL
    rate = absorption_chord_w(pts)
    assert rate is not None and 0 < rate < ABSORPTION_MAX_W

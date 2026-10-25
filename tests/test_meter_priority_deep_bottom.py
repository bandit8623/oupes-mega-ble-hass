"""Meter-over-slope priority when SoC/Wh registers are clamped (bare interpreter).

Field case 2026-10-25 (Guardian V2 + 3 externals, owner report): below ~5%
SoC the ETA read `9h` while 4.0 kW was demonstrably going into the rack -
the BMS freezes its SoC/stored-Wh registers through the bottom
pre-charge/balance hold, so the v1.4.20 chord rate was a trickle while the
pack-side watt meters told the truth.  Same staircase blindness produced
the recorded `97h 40m` bootstrap reading at 05:08 while 3 kW+ filled the
packs (468-row history capture, converging 97h -> 3h23m over three hours).

protocol.meter_priority_w: a COMPLETE meter set that out-runs the inferred
slope by >2x + 400 W wins; everything else keeps the chord primary,
including the 2026-10-22 partial-set case (incomplete meters never
override - enforced by the caller passing None, tested here).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "oupes_mega_ble"))

from protocol import (  # noqa: E402
    meter_priority_w,
    missing_energy_wh,
    time_to_full_minutes,
)


def test_deep_bottom_4kw_beats_clamped_slope():
    # 2026-10-25 field: meters 4000 W vs held-register chord 450 W.
    assert meter_priority_w(450.0, 4000.0) == 4000.0


def test_bootstrap_staircase_3kw_beats_trickle():
    # 2026-10-25 05:08: one quantized Wh step -> chord reads ~350 W.
    assert meter_priority_w(350.0, 3035.0) == 3035.0


def test_normal_cc_keeps_chord_primary():
    # v1.4.20 field (2026-10-22): true rate 2.9 kW, chord 2900, meters
    # 3035 (inverter loss) - chord stays king, meters are the noisier pair.
    assert meter_priority_w(2900.0, 3035.0) == 2900.0


def test_mild_disagreement_keeps_chord():
    # 2x + 400 guard: 900 slope vs 1200 meters => threshold 2200, chord wins.
    assert meter_priority_w(900.0, 1200.0) == 900.0


def test_partial_meters_never_override():
    # Caller passes None when a pack skipped its poll (meters_complete
    # False): the 2026-10-22 under-read case must keep the slope.
    assert meter_priority_w(2900.0, None) == 2900.0


def test_slope_none_falls_back_to_meters():
    assert meter_priority_w(None, 2500.0) == 2500.0


def test_both_none_refuses():
    assert meter_priority_w(None, None) is None
    assert meter_priority_w(0.0, -5.0) is None


def test_zero_slope_still_rescued_by_meters():
    # Deep-bottom hold with the chord reading ZERO Wh movement per window:
    # any real meter reading must win outright.
    assert meter_priority_w(0.0, 4000.0) == 4000.0


def test_eta_from_field_numbers_now_honest():
    # Guardian V2 rack, main 3% / externals ~5%: deficit ~0.9*4608 Wh.
    deficit = 0.93 * 4608
    bad = time_to_full_minutes(deficit, 450.0)      # clamped-slope ETA
    good = time_to_full_minutes(deficit, 4000.0)    # metered truth
    assert bad is not None and good is not None
    assert bad > 8 * 60 > good * 2  # the 9h artifact vs a ~1.3h answer

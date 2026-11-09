"""The state-of-charge plausibility guard (v1.4.23).

Field evidence, owner's Guardian 6000 V2, 2026-10-29 through 2026-11-08: once
every one or two days a single BLE frame decodes to an impossible SoC. The
recorder's raw history still holds the samples - 226,575,051 %, 159,418,385 %,
88,162,978 % and four separate 134,300,3xx % values, one poisoned sample per
affected hour, normal value on the next poll.

Two wrong behaviours are pinned against here, because the fork previously had
both:
  * Combined Battery Reserve averaged the garbage in (a tap-through graph
    auto-scaled its axis to 226 million percent and the real 0-100 trace
    became a flat line nobody could read).
  * Battery Energy Stored CLAMPED it with max(0, min(100, soc)), which turned
    one corrupt frame into a whole 4,608 Wh pack counted as full - the Wh tank
    jumped, fell back, and every runtime/ETA derived from the difference lied.

The rule being pinned: a value that cannot be true carries no information, so
it is dropped exactly like a pack that did not answer. Never clamped, never
averaged, never allowed to become "100% full".
"""

import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "custom_components/oupes_mega_ble")
)

import protocol  # noqa: E402

# Values actually observed in the owner's recorder, plus the two boundary
# failures a misaligned 4-byte field also produces.
CORRUPT = (
    226_575_051, 159_418_385, 134_300_363, 134_300_341, 134_300_324,
    88_162_978, 352_651_776, -1, 101, 100_000,
)


def _ext(**slots):  # slot -> SoC or None (None = slot present but silent)
    return {s: ({79: v} if v is not None else {}) for s, v in slots.items()}


def test_real_values_are_untouched():
    assert protocol.average_pack_soc({3: 60}, _ext(slot1=60, slot2=60)) == 60
    assert protocol.average_pack_soc({3: 40}, _ext(slot1=50)) == 45


def test_boundaries_are_real_data_not_corruption():
    # A discharged pack at 0% and a full one at 100% must keep counting, or the
    # guard would hide the two states the owner actually cares about.
    assert protocol.average_pack_soc({3: 0}, _ext(slot1=0)) == 0
    assert protocol.average_pack_soc({3: 100}, _ext(slot1=100)) == 100
    assert protocol.average_pack_soc({3: 100}, _ext(slot1=0)) == 50


def test_corrupt_main_soc_cannot_move_the_average():
    # Main reads corrupt while both packs are honestly at 40: the answer is 40,
    # not the 75 million the average used to be.
    assert protocol.average_pack_soc({3: 226_575_051}, _ext(slot1=40, slot2=40)) == 40


def test_corrupt_pack_soc_cannot_move_the_average():
    assert protocol.average_pack_soc({3: 40}, _ext(slot1=134_300_363, slot2=40)) == 40


def test_every_corrupt_shape_is_refused():
    for bad in CORRUPT:
        vals, dropped = protocol.pack_soc_samples({3: bad}, _ext(slot1=50))
        assert vals == [50], f"{bad} was accepted"
        assert dropped == 1


def test_all_impossible_yields_none_so_the_sensor_can_hold():
    # None is the signal the sensor needs: publish nothing and hold the last
    # good reading, rather than publish a fabrication.
    assert protocol.average_pack_soc({3: 226_575_051}, {}) is None
    assert protocol.average_pack_soc({3: 226_575_051}, _ext(slot1=None)) is None


def test_absence_is_not_counted_as_corruption():
    # A silent slot is absence, not a bad decode. Counting it as corruption
    # would make the rejection counter lie about how often BLE misbehaves.
    vals, dropped = protocol.pack_soc_samples({3: 55}, _ext(slot1=None, slot2=None))
    assert vals == [55] and dropped == 0


def test_bool_is_not_a_state_of_charge():
    # isinstance(True, int) is True in Python; a naive guard accepts it as 1%.
    assert protocol.soc_is_plausible(True) is False
    assert protocol.soc_is_plausible(False) is False
    assert protocol.soc_is_plausible(40.0) is False
    assert protocol.soc_is_plausible(None) is False


def test_rejection_counter_sees_every_bad_sample():
    vals, dropped = protocol.pack_soc_samples(
        {3: 226_575_051}, _ext(slot1=134_300_363, slot2=40)
    )
    assert vals == [40] and dropped == 2


def test_stored_energy_drops_instead_of_clamping():
    unit = protocol.WH_PER_BATTERY_UNIT["guardian"]
    # The old clamp made this return unit (a full pack). It must return None:
    # nothing plausible was reported, so nothing may be claimed.
    assert protocol.stored_energy_wh("guardian", {3: 226_575_051}, {}) is None
    # Half a main pack + a full pack = 1.5 units, and the corrupt third slot
    # contributes exactly nothing rather than another whole pack.
    got = protocol.stored_energy_wh("guardian", {3: 50}, _ext(slot1=100, slot2=134_300_363))
    assert got == round(unit * 1.5, 1)


def test_stored_energy_agrees_with_the_percent_sensor():
    # The two aggregate sensors must never disagree about what counted, so the
    # same guard has to govern both. 0% is real and counts as 0 Wh, while a
    # corrupt 0-adjacent value counts as nothing at all.
    assert protocol.stored_energy_wh("guardian", {3: 0}, {}) == 0.0
    assert protocol.stored_energy_wh("guardian", {3: -1}, {}) is None

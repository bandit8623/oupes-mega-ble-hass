"""Scale tests for the whole-station average SoC (main + up to 8 ext packs).

The owner's stated deployment goal: one number that is right with NO external
packs, with the 3 he has tonight, and with a fully-stacked 8-pack wall. The
coordinator rebuilds ext_batteries every update, so "pack switched off" is
modeled here as "slot missing or empty dict", and the pre-seeded {1: {}}
placeholder from the coordinator is a real shape that must not poison output.
"""

import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "custom_components/oupes_mega_ble")
)

import protocol  # noqa: E402


def _ext(**slots):  # slot -> SoC or None
    return {s: ({79: v} if v is not None else {}) for s, v in slots.items()}


def test_main_only_no_packs():
    assert protocol.average_pack_soc({3: 64}, {1: {}}) == 64          # pre-seeded slot ignored
    assert protocol.average_pack_soc({3: 64}, None) == 64
    assert protocol.average_pack_soc({3: 64}, {}) == 64


def test_three_packs_real_tonight():
    # 2026-10-16 live values: main 77, ext 79/82/74 -> (77+79+82+74)/4 = 78
    attrs = {3: 77}
    ext = _ext(slot1=79, slot2=82, slot3=74)
    assert protocol.average_pack_soc(attrs, ext) == 78


def test_eight_packs_full_stack():
    attrs = {3: 100}
    ext = _ext(**{f"s{i}": v for i, v in enumerate(range(0, 80, 10), start=1)})
    # packs read 0,10,...,70 (mean 35) plus main 100 -> (280+100)/9 = 42.22 -> 42
    assert protocol.average_pack_soc(attrs, ext) == 42


def test_zero_is_data_not_absence():
    # one dead pack at true 0% must drag the average, not be skipped
    assert protocol.average_pack_soc({3: 100}, _ext(slot1=0)) == 50


def test_silent_slots_and_garbage_skipped():
    ext = {1: {}, 2: {79: 80}, 3: {79: None}, 4: {78: 12}, 5: {79: 90}}
    # main absent entirely; slots 2 and 5 report -> 85
    assert protocol.average_pack_soc({}, ext) == 85


def test_nothing_reports_is_none():
    assert protocol.average_pack_soc({}, {}) is None
    assert protocol.average_pack_soc({3: "junk"}, _ext(slot1=None)) is None


def test_rounding_half_up_on_banker_risk():
    # 3 and 4 -> 3.5: python round() is banker's -> 4; pin the behaviour so the
    # gauge never flickers between implementations
    assert protocol.average_pack_soc({3: 3}, _ext(slot1=4)) == 4


if __name__ == "__main__":
    import traceback

    failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception:
            failed += 1
            print(f"  FAIL  {name}")
            traceback.print_exc()
    print("\nsome tests failed" if failed else "\nall tests passed")
    raise SystemExit(1 if failed else 0)

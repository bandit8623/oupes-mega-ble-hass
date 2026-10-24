"""v1.4.20: a pack that skips a BLE answer must not delete its ~3 kWh.

Owner's overnight soak 2026-10-24 (426 samples, charging): Combined Battery
Reserve / Battery Energy Stored jumped +-8847 Wh when a pack answered the
common dpid 3/4/21/24/28 block but NOT its dpid 79 in the same poll -
the slot vanished from `ext_batteries`, and `stored_energy_wh` silently
summed three packs where four exist.  The same holes poisoned the ETA's
sample series.  merge_held_pack_socs() now keeps the last known SoC per
slot for PACK_SOC_HOLD_S so aggregates ride out single missed answers;
a pack silent longer than the hold window is dropped (a real disconnect
must leave the average).  The function is pure - tests thread the hold
exactly like the coordinator does.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "oupes_mega_ble"))

from protocol import (  # noqa: E402
    PACK_SOC_HOLD_S,
    merge_held_pack_socs,
    stored_energy_wh,
)


def _ext(*socs):
    return {i + 1: {79: s, 53: 300} for i, s in enumerate(socs)}


def test_silent_pack_holds_last_soc_and_stored_energy_is_steady():
    held = {}
    full = _ext(68, 68, 64)
    merged, held = merge_held_pack_socs(full, held, 1000.0)
    base = stored_energy_wh("guardian", {3: 68}, merged)
    # slot 2 answers nothing this cycle (it is simply absent from the dict)
    partial = {1: full[1], 3: full[3]}
    merged, held = merge_held_pack_socs(partial, held, 1001.0)
    assert merged[2][79] == 68                       # held value, not gone
    assert stored_energy_wh("guardian", {3: 68}, merged) == base
    # fresh answers always win over the hold
    merged, held = merge_held_pack_socs(_ext(69, 69, 65), held, 1002.0)
    assert merged[1][79] == 69


def test_genuine_disconnect_expires_after_the_hold_window():
    _, held = merge_held_pack_socs(_ext(68, 68, 64), {}, 1000.0)
    merged, _ = merge_held_pack_socs({1: {79: 68}}, held,
                                     1000.0 + PACK_SOC_HOLD_S + 1.0)
    assert 2 not in merged and 3 not in merged       # expired -> really gone
    assert 1 in merged


def test_held_slot_exposes_only_soc():
    merged, held = merge_held_pack_socs(_ext(68, 68, 64), {}, 1000.0)
    merged, _ = merge_held_pack_socs({}, held, 1001.0)
    assert merged[1] == {79: 68}                     # no stale 53 W meter


def test_hold_survives_coordinator_style_address_reset():
    # the coordinator clears the per-poll dict but not the hold across polls
    _, held = merge_held_pack_socs(_ext(68, 68, 64), {}, time.monotonic())
    merged, _ = merge_held_pack_socs({1: {79: 68}}, held, time.monotonic())
    assert set(merged) == {1, 2, 3}


def test_reported_zero_beats_the_hold():
    _, held = merge_held_pack_socs(_ext(68, 68, 64), {}, 1000.0)
    merged, _ = merge_held_pack_socs({2: {79: 0}}, held, 1001.0)
    assert merged[2][79] == 0                        # 0% is real data

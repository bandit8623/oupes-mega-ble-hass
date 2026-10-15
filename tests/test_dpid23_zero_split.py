"""dpid 23 is a packed pair on 95haDY, so a zero reading must split into 0 W + 0 W.

Before this fix the two DC input sensors read Unknown whenever the station produced no
solar, because the split was gated on the combined value looking too large to be plain
watts (>= 65536 W).  Zero is not too large, so the halves were never published while the
aggregate reported 0 W - one field described by three sensors, two of which declined to
answer.  Note the invariant being restored is `aggregate == dc1 + dc2`; the two inputs
are independent and usually unequal.

The fixtures below are the bytes off the wire, not synthetic packets.  They come from a
Guardian 6000 V2 (product id 95haDY) captured 2026-10-14 while idle, and they include the
annoying part: the record for dpid 23 straddles a packet boundary, so `... 0a 05` ends one
packet and `17 00000000` starts the next.  Anyone tempted to grep a capture instead of
replaying it through the parser should note that such a grep finds nothing.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def protocol():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "oupes_protocol_dpid23",
        ROOT / "custom_components" / "oupes_mega_ble" / "protocol.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Captured 2026-10-14 23:12:17 local, Guardian 6000 V2, no solar input.
IDLE_SEQUENCE = [
    bytearray.fromhex("03000a0505640300000a0506000000000a0507f3"),
    bytearray.fromhex("0301000000000a0508000000000a050900000044"),
    bytearray.fromhex("0302000a0515000000000a0516000000000a05ba"),
    bytearray.fromhex("038317000000000a0573800596050000000000a1"),
]


def test_capture_really_does_carry_dpid_23_as_zero(protocol):
    """If this ever stops holding, the fixture is stale, not the code."""
    parsed = protocol._parse_packet_sequence_impl(list(IDLE_SEQUENCE))
    assert parsed.get(23) == 0
    assert 2301 not in parsed and 2302 not in parsed, (
        "the raw reader must not pre-split; splitting is _split_packed_power's job"
    )


def test_idle_zero_splits_into_two_zero_readings_for_a_known_packed_product(protocol):
    parsed = protocol.parse_packet_sequence(list(IDLE_SEQUENCE), packed_certain=True)
    assert parsed[2301] == 0, "DC Input 1 must report 0 W, not stay Unknown"
    assert parsed[2302] == 0, "DC Input 2 must report 0 W, not stay Unknown"
    assert parsed[23] == 0, "the aggregate must stay lo + hi"


def test_aggregate_equals_the_sum_of_the_halves(protocol):
    """The invariant is `aggregate == lo + hi`.  It is NOT `lo == hi`.

    Named explicitly because "make the sensors agree" is ambiguous and the wrong reading
    of it would produce a split that averages or duplicates the two inputs.
    """
    parsed = protocol.parse_packet_sequence(list(IDLE_SEQUENCE), packed_certain=True)
    assert parsed[23] == parsed[2301] + parsed[2302]
    assert 2301 in parsed and 2302 in parsed


def test_the_two_inputs_are_independent_not_a_duplicated_value(protocol):
    """Halves are routinely unequal, so a fix must not treat them as one number twice.

    Captured pairs include 1999/2001 and, more starkly, 647/2002 - two strings at very
    different power.  Zero happening to be equal on both sides at night is arithmetic,
    not a property of the field.
    """
    unequal = protocol._split_packed_power({23: 0x07D20287}, packed_certain=True)
    assert unequal[2301] == 647 and unequal[2302] == 2002
    assert unequal[2301] != unequal[2302], "halves must not be forced equal"
    assert unequal[23] == 647 + 2002 == 2649

    proven = protocol._split_packed_power({23: 573}, packed_certain=True)
    assert (proven[2301], proven[2302]) == (573, 0), (
        "one string producing and the other at zero must stay 573 + 0, not 286.5 each"
    )


def test_unknown_product_keeps_the_old_magnitude_only_behaviour(protocol):
    """No evidence about the device means no split at zero - even though it looks tidy."""
    parsed = protocol.parse_packet_sequence(list(IDLE_SEQUENCE), packed_certain=False)
    assert parsed.get(23) == 0
    assert 2301 not in parsed and 2302 not in parsed


@pytest.mark.parametrize(
    "raw,lo,hi",
    [
        (0x07D107CF, 1999, 2001),  # 4000 W, cross-checked against dpid 21 on the wire
        (0x07D007CE, 1998, 2000),  # 3998 W
        (0x07D20287, 647, 2002),  # 2649 W
    ],
)
def test_daytime_packed_values_are_unaffected_by_the_fix(protocol, raw, lo, hi):
    """The magnitude gate already handled these; the fix must not disturb them."""
    for certain in (True, False):
        parsed = protocol._split_packed_power({23: raw}, packed_certain=certain)
        assert parsed[2301] == lo, f"raw {raw:#x}, packed_certain={certain}"
        assert parsed[2302] == hi, f"raw {raw:#x}, packed_certain={certain}"
        assert parsed[23] == lo + hi


def test_small_packed_value_splits_only_when_the_product_proves_it(protocol):
    """This is the whole fix in one case: 573 cannot be told from 573 W by looking at it.

    A proven product reads it as 573 W + 0 W.  Any other product must keep it as one
    plain wattage reading, because the alternative is inventing a second input.
    """
    proven = protocol._split_packed_power({23: 573}, packed_certain=True)
    assert (proven[23], proven[2301], proven[2302]) == (573, 573, 0)

    unproven = protocol._split_packed_power({23: 573}, packed_certain=False)
    assert unproven == {23: 573}


def test_plain_wattage_field_on_an_unproven_model_is_never_split(protocol):
    """Mega/TT dpid 23 really is one wattage.  Splitting it would invent a second input."""
    for watts in (0, 1, 500, 6000, 65535):
        parsed = protocol._split_packed_power({23: watts}, packed_certain=False)
        assert parsed == {23: watts}, f"{watts} W got rewritten"


def test_split_is_idempotent(protocol):
    once = protocol._split_packed_power({23: 0}, packed_certain=True)
    twice = protocol._split_packed_power(dict(once), packed_certain=True)
    assert once == twice


def test_every_coordinator_parse_call_carries_the_flag():
    """A call site that forgets `packed_certain` silently reintroduces the Unknown sensors.

    Checked on the AST rather than by importing: coordinator.py imports homeassistant,
    which is not installed here, so an import-based test could not run in CI.
    """
    import ast

    src = (
        ROOT / "custom_components" / "oupes_mega_ble" / "coordinator.py"
    ).read_text(encoding="utf-8")
    calls = [
        node
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "parse_packet_sequence"
    ]
    assert calls, "no parse_packet_sequence() calls found - did the coordinator change?"
    missing = [
        node.lineno
        for node in calls
        if not any(k.arg == "packed_certain" for k in node.keywords)
    ]
    assert not missing, (
        f"parse_packet_sequence() calls without packed_certain at lines {missing}: "
        "those paths will leave the DC input sensors Unknown whenever solar input is 0"
    )


def test_product_gate_is_exactly_the_proven_set(protocol):
    assert protocol.product_uses_packed_power("95haDY") is True
    assert protocol.product_uses_packed_power("oB6OKs") is False  # Guardian 6000, uncaptured
    assert protocol.product_uses_packed_power("LtQmdj") is False  # HP2500, uncaptured
    assert protocol.product_uses_packed_power("") is False
    assert protocol.product_uses_packed_power("TT") is False


def test_gate_is_not_a_family_test():
    """Guard against someone 'helpfully' widening this to a whole series.

    The packing is proven per product id.  Every extra id needs its own capture, because
    a wrong entry writes a wrong number onto someone's energy dashboard forever.
    """
    src = (ROOT / "custom_components" / "oupes_mega_ble" / "protocol.py").read_text(
        encoding="utf-8"
    )
    line = [l for l in src.splitlines() if l.startswith("PACKED_U16_POWER_PRODUCT_IDS")][0]
    ids = [p.strip().strip("\"'") for p in
           line.split("{", 1)[1].split("}", 1)[0].split(",")]
    assert ids == ["95haDY"], f"product ids without a capture proving the packing: {ids}"

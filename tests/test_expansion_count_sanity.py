"""dpid 51 (expansion pack count) must never reach the dashboard raw.

Field evidence 2026-10-22, Guardian V2 + 3 expansion packs: the unit pushed
dpid 51 as 167,772,160 == 0x0A000000 - byte-order/field-layout garbage that
landed straight on the owner's dashboard where the honest derived count had
sat at 3 for weeks.  The gate accepts only possible firmware answers
(0..8); everything else falls through to the slot-counting fallback that
already proved itself trustworthy.
"""
from pathlib import Path

from custom_components.oupes_mega_ble.protocol import sane_expansion_count

SENSOR_SRC = (
    Path(__file__).parent.parent / "custom_components" / "oupes_mega_ble" / "sensor.py"
).read_text(encoding="utf-8")


# --- the gate itself ---------------------------------------------------------

def test_the_field_garbage_is_rejected():
    """The exact value from the field must die at the gate."""
    assert sane_expansion_count(167_772_160) is None


def test_endianness_shifted_variants_rejected():
    for junk in (0x0A << 24, 0x03 << 24, 3 << 8, 0x0100, -1, 9, 100):
        assert sane_expansion_count(junk) is None, junk


def test_possible_firmware_answers_pass():
    for real in (0, 1, 2, 3, 4, 8):
        assert sane_expansion_count(real) == real, real


def test_zero_is_a_real_answer_not_refused():
    """Packs switched off = honest 0 (session ruling: 0 IS truth)."""
    assert sane_expansion_count(0) == 0


def test_wrong_types_refused():
    assert sane_expansion_count(None) is None
    assert sane_expansion_count("3") is None
    assert sane_expansion_count(3.0) is None   # float: firmware doesn't speak float
    assert sane_expansion_count(True) is None  # bool is an int subclass; not an answer


# --- the sensor wiring (sensor.py imports HA, so this one greps) -------------

def test_sensor_falls_back_when_gate_refuses():
    assert "sane_expansion_count(raw)" in SENSOR_SRC
    assert "_derive_ext_count(self.coordinator.data.get(\"ext_batteries\"))" in SENSOR_SRC


def test_garbage_count_cannot_render():
    """No code path returns raw dpid 51 without the gate in between."""
    src = SENSOR_SRC
    idx = src.find('if desc.key == "expansion_battery_count":\n            # dpid 51')
    assert idx > -1, "gate wiring missing from sensor.py"
    # The gated block must resolve via sane/derived only, never `raw` itself.
    block = src[idx:src.find("return desc.value_fn", idx)]
    assert "return raw" not in block

"""Split-derived sensors must never haunt a machine that lacks the connector.

Measured lineage:
  * Guardian 6000 V2 (95haDY): dpid 23 and dpid 115 each pack TWO u16 readings
    (dual XT60 inputs). Splits are real; the four derived entities are honest.
  * Original Guardian 6000 (oB6OKs): ONE Anderson DC input, dpid 115 never
    captured. product_uses_packed_power() is False for it, so the synthetic
    keys 2301/2302/11501/11502 can never appear in its data.
  * Mega / TT family: attr 23 is a single wattage and dpid 115 is not a WP
    telemetry field at all; the WP sequence reader that performs the splits
    never runs.

Two independent guards, both caught live in v1.4.9:

1. _WP_ONLY_SENSOR_KEYS must list all four split sensors. Without the two
   voltage keys, every Mega install created two entities whose data key could
   not exist - permanent `unknown` rows on the devices page.

2. Even on the WP family, a sensor keyed to a synthetic split key must go
   unavailable when THIS station has never reported it. The V1's single
   connector must not be rendered as two `unknown` inputs.

sensor.py imports homeassistant, which is absent for the bare test run, so
constants are read from the AST and the pure helper is exec'd from its own
source - same trick as test_guardian_no_usb_switch.
"""

import ast
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SENSOR = ROOT / "custom_components/oupes_mega_ble/sensor.py"

SPLIT_KEYS = {
    "dc_input_1_power",
    "dc_input_2_power",
    "dc_input_1_voltage",
    "dc_input_2_voltage",
}
DERIVED_DATA_KEYS = {2301, 2302, 11501, 11502}


def _tree() -> ast.Module:
    return ast.parse(SENSOR.read_text(encoding="utf-8"))


def _assign(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return node
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return node
    raise AssertionError(f"{name} not found in sensor.py")


def _wp_only_keys() -> set[str]:
    node = _assign(_tree(), "_WP_ONLY_SENSOR_KEYS")
    # frozenset({ "a", "b", ... })
    call = node.value
    assert isinstance(call, ast.Call) and getattr(call.func, "id", "") == "frozenset"
    literal = call.args[0]
    assert isinstance(literal, ast.Set)
    return {ast.literal_eval(e) for e in literal.elts}


def _derived_sensors() -> dict[str, int]:
    """key -> data_key for every shipped description using a derived split key."""
    node = _assign(_tree(), "SENSOR_DESCRIPTIONS")
    out: dict[str, int] = {}

    def walk(obj: ast.AST) -> None:
        for sub in ast.walk(obj):
            if isinstance(sub, ast.Call):
                kw = {k.arg: k for k in sub.keywords}
                if "key" in kw and "data_key" in kw:
                    try:
                        key = ast.literal_eval(kw["key"].value)
                        dk = ast.literal_eval(kw["data_key"].value)
                    except ValueError:
                        continue
                    if isinstance(key, str) and dk in DERIVED_DATA_KEYS:
                        out[key] = dk

    walk(node.value)
    return out


def _helper():
    src = None
    for node in _tree().body:
        if isinstance(node, ast.FunctionDef) and node.name == "split_key_never_reported":
            src = ast.get_source_segment(SENSOR.read_text(encoding="utf-8"), node)
    assert src, "split_key_never_reported() missing from sensor.py"
    ns: dict = {}
    exec(compile(src, str(SENSOR), "exec"), ns)
    return ns["split_key_never_reported"]


# --- guard 1: the ban list ---------------------------------------------------

def test_all_four_split_sensors_are_wp_only():
    got = _wp_only_keys()
    missing = SPLIT_KEYS - got
    assert not missing, (
        f"{sorted(missing)} create derived data keys (2301/2302/11501/11502) that only "
        "the WP packed-power split can produce; on a Mega the entities would sit "
        "`unknown` forever, which is the v1.4.9 regression this guard kills"
    )


def test_no_shipped_split_sensor_escapes_the_ban():
    escaped = set(_derived_sensors()) - _wp_only_keys()
    assert not escaped, f"descriptions using derived keys but not WP-gated: {sorted(escaped)}"


# --- guard 2: never-render-a-connector-you-dont-have -------------------------

def test_derived_key_absent_hides_the_entity():
    f = _helper()
    desc = SimpleNamespace(slot=None, data_key=11501, attr=115)
    assert f(desc, {115: 937}) is True  # station never reported the split


def test_derived_key_present_shows_the_entity():
    f = _helper()
    desc = SimpleNamespace(slot=None, data_key=11501, attr=115)
    assert f(desc, {115: 937, 11501: 93.7}) is False


def test_plain_and_direct_keys_are_never_hidden_by_this_rule():
    f = _helper()
    assert f(SimpleNamespace(slot=None, data_key=None, attr=115), {}) is False
    assert f(SimpleNamespace(slot=None, data_key=115, attr=115), {}) is False
    # slot sensors keep their own existing rule and must not be double-handled
    assert f(SimpleNamespace(slot=1, data_key=79, attr=79), {}) is False

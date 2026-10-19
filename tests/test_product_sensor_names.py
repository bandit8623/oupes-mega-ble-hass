"""Guards for the per-product entity rename (DC Input 1 Power -> DC XT60 Input 1).

Three things have to stay true, none of which the interpreter can check for us:

  1. The override map is keyed by **product id**, never by series.  A series-wide rename
     would put a connector claim on the dashboard of an owner whose unit nobody has seen.
  2. `unique_id` keeps deriving from `description.key`.  That is the entire reason this
     rename is safe: entity_id survives, so existing dashboards and automations do not
     have to be rebuilt.  If someone bases unique_id on the name, a rename silently
     orphans every user's history.
  3. Every override targets a real sensor key.  A typo here does nothing at runtime, which
     is the worst possible failure mode for a test suite to miss.

`sensor.py` imports `homeassistant`, which is not installed here, so all of this is read
out of the AST and literals rather than imported.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SENSOR = ROOT / "custom_components/oupes_mega_ble/sensor.py"
CONST = ROOT / "custom_components/oupes_mega_ble/const.py"


def _src() -> str:
    return SENSOR.read_text(encoding="utf-8")


def _tree() -> ast.Module:
    return ast.parse(_src())


def _assign(tree, name):
    for node in tree.body:
        # Both forms: `X = {...}` and the annotated `X: dict = {...}` this map uses.
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return node
    return None


def _product_names(tree) -> dict:
    node = _assign(tree, "_PRODUCT_SENSOR_NAMES")
    assert node is not None, (
        "no `_PRODUCT_SENSOR_NAMES` map in sensor.py. Either the XT60 rename was dropped "
        "(say so in the docs) or it moved somewhere this guard no longer watches."
    )
    return ast.literal_eval(node.value)


def _model_catalog() -> dict:
    """const.MODEL_CATALOG: {product_id: (display name, series key)}.

    Imported from source via AST because `const.py` sits under a package that pulls in
    `homeassistant`. This is the single source of truth for both product ids and series
    names, so the two tests below cannot drift from the catalog on their own.
    """
    tree = ast.parse(CONST.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "MODEL_CATALOG" for t in targets):
                return ast.literal_eval(node.value)
    raise AssertionError("MODEL_CATALOG not found in const.py")


def _known_product_ids() -> set:
    return set(_model_catalog())


def _series_names() -> set:
    """Every series label the catalog can return, plus the 'unknown' fallback."""
    return {v[1] for v in _model_catalog().values()} | {"unknown"}


def _sensor_keys() -> set:
    return set(re.findall(r'key="([a-z0-9_]+)"', _src()))


def test_map_is_keyed_by_product_id_not_series():
    names = _product_names(_tree())
    assert names, "map is empty - remove it or fill it"
    overlap = set(names) & _series_names()
    assert not overlap, (
        f"{sorted(overlap)} are series names. Keying the connector name by series renames "
        "every model in the family, including units nobody has opened."
    )


def test_product_ids_are_real():
    known = _known_product_ids()
    assert len(known) > 5, f"read only {len(known)} product ids out of const.py - fix this"
    unknown = set(_product_names(_tree())) - known
    assert not unknown, f"{sorted(unknown)} are not product ids in MODEL_CATALOG"


def test_overrides_target_real_sensor_keys():
    keys = _sensor_keys()
    dead = {
        (pid, key)
        for pid, overrides in _product_names(_tree()).items()
        for key in overrides
        if key not in keys
    }
    assert not dead, (
        f"{sorted(dead)} match no sensor key, so they would silently do nothing"
    )


def test_unique_id_must_keep_using_the_key():
    """The safety property under the whole rename.  Read it as a contract, not a curiosity."""
    src = _src()
    assert '_attr_unique_id = f"{entry.entry_id}_{description.key}"' in src, (
        "unique_id no longer derives purely from description.key. Names are cosmetic and "
        "change between releases; binding identity to a name means the next rename wipes "
        "every existing user's entity_id and its history."
    )


def test_rename_is_applied_with_replace_not_mutation():
    """Descriptions are frozen shared singletons; in-place edits would leak across entries."""
    names = {n.id for n in ast.walk(_tree()) if isinstance(n, ast.Name)}
    assert "replace" in names, "expected dataclasses.replace for the rename"
    assert "_PRODUCT_SENSOR_NAMES" in names
    func = next(
        n
        for n in ast.walk(_tree())
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_setup_entry"
    )
    body = ast.unparse(func)
    assert "_PRODUCT_SENSOR_NAMES" in body, "map is defined but never consulted at setup"
    assert "replace(" in body, "rename must build a new description, not mutate one"


def test_xt60_names_are_latched_to_the_one_seen_product():
    """Exactly one product currently has an owner-reported connector: `95haDY`.

    No test can know whether somebody has looked at another station, so the latch is the
    number itself.  Widening it is allowed but must be deliberate: add the product, change
    this assertion, and name a person who has seen that case in the commit message.  Same
    shape as `test_gate_is_not_a_family_test` on the packed-power product set.
    """
    xt60_products = {
        pid
        for pid, overrides in _product_names(_tree()).items()
        if any("xt60" in v.lower() for v in overrides.values())
    }
    assert xt60_products == {"95haDY"}, (
        f"XT60 appears in the shipped names for {sorted(xt60_products)}. The connector is "
        "an owner-reported fact per product id - a new product needs an owner who has seen "
        "its sockets."
    )


def test_override_names_are_bare_base_names_are_not():
    """The shipped override is 'DC XT60 Input 1', not 'DC XT60 Input 1 Power'.

    Bare was the owner's call: the watt unit and device_class already say what the number
    is, and HA renders the unit next to the name anyway, so a "Power" suffix on a power
    sensor is noise on a dashboard tile.

    The base descriptions keep "Power" on purpose, and that asymmetry is the point of this
    test.  A name is what a FRESH install slugs into an entity_id, the base names apply to
    WP models nobody has opened, and docs elsewhere quote `dc_input_1_power`. Renaming them
    would move entity_ids on other people's stations for cosmetics. The XT60 rename already
    changes the slug on `95haDY`, and that one is documented.
    """
    src = _src()
    assert 'name="DC Input 1 Power",' in src, "base name lost its suffix - see docstring"
    assert 'name="DC Input 2 Power",' in src, "base name lost its suffix - see docstring"

    overrides = _product_names(_tree())["95haDY"]
    a = overrides["dc_input_1_power"]
    b = overrides["dc_input_2_power"]
    assert a.replace("1", "#") == b.replace("2", "#"), f"names do not match: {a!r} / {b!r}"
    assert (a, b) == ("DC XT60 Input 1", "DC XT60 Input 2"), f"got {a!r} / {b!r}"
    for name in (a, b):
        assert not name.endswith("Power"), f"{name!r} grew a unit suffix back on"


def test_voltage_overrides_share_the_xt60_vocabulary():
    """`DC XT60 Voltage 1/2` must speak the same connector word as the watts.

    A device page mixing 'DC Input 1 Voltage' next to 'DC XT60 Input 1' reads
    like two unrelated port families exist on the same machine. The voltages
    are WP-firmware-only (packed dpid 115), so `95haDY` is the sole latch here
    too - the same owner-reported-connector constraint as the watt sensors.
    """
    overrides = _product_names(_tree())["95haDY"]
    v1 = overrides.get("dc_input_1_voltage")
    v2 = overrides.get("dc_input_2_voltage")
    assert (v1, v2) == ("DC XT60 Voltage 1", "DC XT60 Voltage 2"), f"got {v1!r} / {v2!r}"
    assert v1.replace("1", "#") == v2.replace("2", "#")
    for name in (v1, v2):
        assert "XT60" in name, f"{name!r} does not use the owner-reported connector word"
        assert not name.endswith("Voltage"), f"{name!r} grew a redundant unit-ish suffix"

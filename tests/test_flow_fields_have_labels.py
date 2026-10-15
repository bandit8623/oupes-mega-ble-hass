"""Every step and every schema field in config_flow.py must have a label.

The older guard in test_strings_coverage.py checks step names against a hard-coded list of
nine names. That list is the flaw: add a tenth step and the guard does not notice, which is
how the v1.4.2 config-flow bug reached users as a form with an empty error line - the flow
raised a reason whose string did not exist in the right place.

This file reads config_flow.py with the AST instead of a list. It finds every
async_show_form() call, takes its step_id and the keys of its vol.Schema(...), works out
which flow class it belongs to (config or options), and requires:

  1. strings[flow].step.<step_id> to exist,
  2. every field in that schema to have a label under ...data.<field>,
  3. no label under ...data.<field> for a field the schema does not render.

Direction 3 matters as much as 2. A field with no label renders the raw key ("user_id") in
the UI; a label with no field is a row users never see and maintainers keep translating.

Field names are usually CONF_* constants, so const.py is parsed too and an unresolvable
key is a failure rather than a silent skip - a guard that quietly stops checking is worse
than no guard.
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "oupes_mega_ble"
CONFIG_FLOW = COMPONENT / "config_flow.py"
CONSTS = COMPONENT / "const.py"
STRINGS = COMPONENT / "strings.json"
EN = COMPONENT / "translations" / "en.json"


def _string_constants(path: pathlib.Path) -> dict[str, str]:
    """NAME -> "value" for every top-level string assignment in a module."""
    out: dict[str, str] = {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    out[target.id] = node.value.value
    return out


def _key_name(node: ast.expr, consts: dict[str, str]) -> str | None:
    """Resolve vol.Required(X) - a literal, a CONST, or const.CONST.

    In `vol.Schema({vol.Required(CONF_USER_ID): str})` the dict key is the *call*
    vol.Required(CONF_USER_ID), so unwrap vol.Required/vol.Optional first and read
    their first argument.
    """
    if isinstance(node, ast.Call):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in ("Required", "Optional") and node.args:
            return _key_name(node.args[0], consts)
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.Attribute):
        return consts.get(node.attr)
    return None


def _schema_fields(node: ast.expr, consts: dict[str, str]) -> tuple[list[str], list[str]]:
    """Return (fields, unresolvable) for a vol.Schema(...) expression."""
    fields: list[str] = []
    bad: list[str] = []
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return fields, bad
    if node.func.attr != "Schema" or not node.args:
        return fields, bad
    arg = node.args[0]
    items: list[ast.expr] = []
    if isinstance(arg, ast.Dict):
        items = list(arg.keys)
    elif isinstance(arg, ast.List):
        for elt in arg.elts:
            if isinstance(elt, ast.Tuple) and elt.elts:
                items.append(elt.elts[0])
            else:
                bad.append(ast.dump(elt)[:40])
    for key in items:
        if key is None:
            continue
        name = _key_name(key, consts)
        if name is None:
            bad.append(ast.unparse(key)[:40])
        else:
            fields.append(name)
    return fields, bad


def _flow_kind(bases: list[str]) -> str | None:
    joined = " ".join(bases)
    if "OptionsFlow" in joined:
        return "options"
    if "ConfigFlow" in joined:
        return "config"
    return None


def collect_forms(source: str, consts: dict[str, str]) -> tuple[dict, list[str]]:
    """{(flow, step_id): [field, ...]} plus a list of things it could not resolve."""
    tree = ast.parse(source)
    forms: dict[tuple[str, str], list[str]] = {}
    unresolved: list[str] = []

    for cdef in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        flow = _flow_kind([ast.unparse(b) for b in cdef.bases])
        if flow is None:
            continue
        for method in [n for n in cdef.body if isinstance(n, ast.AsyncFunctionDef)]:
            for call in [n for n in ast.walk(method) if isinstance(n, ast.Call)]:
                fname = (
                    call.func.attr
                    if isinstance(call.func, ast.Attribute)
                    else getattr(call.func, "id", "")
                )
                if fname != "async_show_form":
                    continue
                step_kw = next((k for k in call.keywords if k.arg == "step_id"), None)
                if step_kw is None:
                    unresolved.append(f"{flow}: async_show_form without step_id")
                    continue
                step = _key_name(step_kw.value, consts)
                if step is None:
                    unresolved.append(f"{flow}: unresolved step_id in {method.name}")
                    continue
                schema_kw = next((k for k in call.keywords if k.arg == "data_schema"), None)
                fields, bad = (
                    _schema_fields(schema_kw.value, consts) if schema_kw else ([], [])
                )
                unresolved += [f"{flow}.{step}: unresolvable field {b}" for b in bad]
                key = (flow, step)
                forms.setdefault(key, [])
                for f in fields:
                    if f not in forms[key]:
                        forms[key].append(f)
    return forms, unresolved


def _labels(strings: dict, flow: str, step: str) -> set[str]:
    body = strings.get(flow, {}).get("step", {}).get(step, {})
    return set(body.get("data", {})) | set(body.get("data_description", {}))


def _has_step(strings: dict, flow: str, step: str) -> bool:
    return step in strings.get(flow, {}).get("step", {})


CONSTS = _string_constants(CONSTS)
FORMS, UNRESOLVED = collect_forms(CONFIG_FLOW.read_text(encoding="utf-8"), CONSTS)
STR = json.loads(STRINGS.read_text(encoding="utf-8"))
ENJ = json.loads(EN.read_text(encoding="utf-8"))


def test_the_extractor_actually_found_the_flow():
    """A guard that finds nothing must not report success."""
    assert FORMS, "no async_show_form() calls extracted - the parser stopped working"
    if UNRESOLVED:
        raise AssertionError(
            "the extractor could not resolve these, so it cannot vouch for them:\n"
            + "\n".join(sorted(set(UNRESOLVED)))
        )


def check_missing_steps(strings: dict, forms=None) -> list[str]:
    forms = FORMS if forms is None else forms
    return [
        f"{flow}.step.{step}: missing translation block"
        for (flow, step) in forms
        if not _has_step(strings, flow, step)
    ]


def check_missing_labels(strings: dict, forms=None) -> list[str]:
    forms = FORMS if forms is None else forms
    out = []
    for (flow, step), fields in forms.items():
        labelled = _labels(strings, flow, step)
        for field in fields:
            if field not in labelled:
                out.append(f"{flow}.step.{step} renders {field!r} with no label")
    return out


def check_dead_labels(strings: dict, forms=None) -> list[str]:
    forms = FORMS if forms is None else forms
    out = []
    for flow in ("config", "options"):
        for step, body in strings.get(flow, {}).get("step", {}).items():
            rendered = {
                f
                for (f2, s), fs in forms.items()
                if f2 == flow and s == step
                for f in fs
            }
            for key in set(body.get("data", {})) | set(body.get("data_description", {})):
                if key not in rendered:
                    out.append(f"{flow}.step.{step} labels {key!r}, never rendered")
    return out


def _both_files():
    return (("strings.json", STR), ("translations/en.json", ENJ))


def test_every_step_in_code_has_strings_in_both_files():
    problems = sorted(f"{name}: {m}" for name, doc in _both_files() for m in check_missing_steps(doc))
    assert not problems, (
        "config_flow renders steps with no translation block:\n" + "\n".join(problems)
    )


def test_every_field_in_code_has_a_label():
    problems = sorted(
        f"{name}: {m}" for name, doc in _both_files() for m in check_missing_labels(doc)
    )
    assert not problems, (
        "these fields render as raw keys in the UI:\n" + "\n".join(problems)
    )


def test_no_label_points_at_a_field_that_is_not_rendered():
    problems = sorted(
        f"{name}: {m}" for name, doc in _both_files() for m in check_dead_labels(doc)
    )
    assert not problems, (
        "dead labels (or steps this file cannot see, e.g. flows that build schemas "
        "dynamically):\n" + "\n".join(problems)
    )


# --- sabotage: prove each direction can fail --------------------------------


SABOTAGE_STEP = """
class SabotageConfigFlow(config_entries.ConfigFlow, domain="oupes_mega_ble"):
    async def async_step_brand_new_thing(self, user_input=None):
        return self.async_show_form(
            step_id="brand_new_thing",
            data_schema=vol.Schema({
                vol.Required("field_with_no_label"): str,
            }),
        )
"""


def test_guard_notices_a_new_step_with_an_unlabelled_field():
    """The whole point: a step nobody added to a list is still checked."""
    forms, _ = collect_forms(CONFIG_FLOW.read_text(encoding="utf-8") + SABOTAGE_STEP, CONSTS)
    assert ("config", "brand_new_thing") in forms, "parser missed the planted step"
    missing_steps = [
        (flow, step)
        for (flow, step) in forms
        if not _has_step(STR, flow, step)
    ]
    assert ("config", "brand_new_thing") in missing_steps, "planted step passed as translated"
    planted = _labels(STR, "config", "brand_new_thing")
    assert "field_with_no_label" not in planted, "planted field appeared labelled"


def test_guard_notices_a_field_added_to_an_existing_step():
    """A field added to a live schema but not to strings must be named."""
    source = CONFIG_FLOW.read_text(encoding="utf-8")
    planted = source.replace(
        "vol.Required(CONF_DEBUG_RAW, default=False): bool,",
        "vol.Required(CONF_DEBUG_RAW, default=False): bool,\n"
        '                vol.Required("totally_new_option", default=False): bool,',
        1,
    )
    assert planted != source, "could not plant a field - config_flow.py changed shape"
    forms, _unresolved = collect_forms(planted, CONSTS)
    assert any("totally_new_option" in fs for fs in forms.values()), (
        "planted field was not extracted from the schema"
    )
    flagged = check_missing_labels(STR, forms)
    assert any("totally_new_option" in m for m in flagged), (
        "planted an unlabelled field and the guard said nothing"
    )
    # and the same check is calm about the real code:
    assert not check_missing_labels(STR), "the real files already fail this check"


def test_guard_does_not_cry_wolf_when_a_label_exists():
    """Adding the label must clear it - otherwise the guard cannot be satisfied."""
    patched = json.loads(json.dumps(STR))
    step = "account_number"
    assert "go_back" in FORMS[("config", step)], "go_back is not actually rendered there"
    patched["config"]["step"][step]["data"]["go_back"] = "Go back"
    assert f"config.step.{step} renders 'go_back' with no label" not in check_missing_labels(
        patched
    ), "the label was added and the guard still complains"


def test_guard_notices_a_label_for_a_field_that_is_not_rendered():
    """The dead-label direction, proven by inventing a field nobody renders."""
    patched = json.loads(json.dumps(STR))
    patched["options"]["step"]["init"]["data"]["a_field_nobody_renders"] = "Ghost field"
    assert any("a_field_nobody_renders" in m for m in check_dead_labels(patched)), (
        "invented a label for an unrendered field and the guard said nothing"
    )
    assert not any("a_field_nobody_renders" in m for m in check_dead_labels(STR)), (
        "the real files already carry this label - the check is stuck on"
    )


def test_guard_notices_a_missing_step_block():
    """Delete one step's strings and the step check must name it."""
    patched = json.loads(json.dumps(STR))
    flow, step = next(iter(sorted(FORMS)))
    del patched[flow]["step"][step]
    assert any(step in m for m in check_missing_steps(patched)), (
        "deleted a whole step's strings and the guard said nothing"
    )
    assert not check_missing_steps(STR), "the real files are already missing a step"


def test_strings_and_en_cover_the_same_fields():
    """Both files must agree, or an English-only miss hides behind strings.json."""
    diffs = []
    for flow in ("config", "options"):
        steps = set(STR.get(flow, {}).get("step", {})) | set(ENJ.get(flow, {}).get("step", {}))
        for step in steps:
            a = set(STR.get(flow, {}).get("step", {}).get(step, {}).get("data", {}))
            b = set(ENJ.get(flow, {}).get("step", {}).get(step, {}).get("data", {}))
            if a != b:
                diffs.append(f"{flow}.step.{step}: strings.json={sorted(a)} en.json={sorted(b)}")
    assert not diffs, "the two files disagree about which fields exist:\n" + "\n".join(diffs)


if __name__ == "__main__":
    failed = False
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as exc:
                failed = True
                print(f"FAIL  {name}\n{exc}")
    sys.exit(1 if failed else 0)

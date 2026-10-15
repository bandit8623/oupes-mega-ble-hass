"""strings.json / translations/en.json against Home Assistant's own schema.

Written after two consecutive releases shipped translation files that hassfest rejected,
both times because a check asserted the one defect I had already seen instead of the class
of defect:

  * round one: ``options.step.init.error`` (singular) - the upstream PR was red for it.
    Scanned for ``error``, hoisted it, wrote a test for ``error``.
  * round two: six steps also carried ``errors`` (plural), which the scan and the test both
    missed, because they were looking for the string from round one. Hassfest caught it on
    the push that was supposed to fix it.

So everything here is a whitelist taken from
``homeassistant/core:script/hassfest/translations.py`` (``gen_data_entry_schema``), which
is the file that produces the error message, plus that file's other validators. A last
test feeds deliberately broken copies through these checks to prove they can fail - a
checker that passes everything is what hid both rounds.

CI runs the real hassfest too; this is the fast layer, not a replacement for it.

Run standalone (no pytest, no Home Assistant) or under pytest.
"""

from __future__ import annotations

import ast
import copy
import json
import pathlib
import string
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "oupes_mega_ble"
CONFIG_FLOW = COMPONENT / "config_flow.py"
FILES = {
    "strings.json": COMPONENT / "strings.json",
    "translations/en.json": COMPONENT / "translations" / "en.json",
}
sys.path.insert(0, str(COMPONENT))  # component dir, not package: package __init__ needs HA

import cloud_identity as ci  # noqa: E402

FLOWS = ("config", "options")

# Exactly the keys gen_data_entry_schema permits inside step.<id>. Anything else - "error",
# "errors", anything - is rejected by hassfest and never rendered by the frontend.
ALLOWED_STEP_KEYS = frozenset(
    {
        "title",
        "description",
        "data",
        "data_description",
        "menu_options",
        "menu_option_descriptions",
        "submit",
        "sections",
    }
)

# Keys built at runtime rather than written as a literal next to `errors[...] =`:
#   errors["base"] = self._pairing_error
#   errors["cloud_email"] = f"cloud_identity_{identity.reason}"
# Derived from the real constants, so renaming a reason without adding its wording fails.
DYNAMIC_KEYS = {
    "pairing_device_not_found",
    "pairing_connection_failed",
    "pairing_timeout",
} | {
    f"cloud_identity_{reason}"
    for reason in (
        ci.REASON_LOGIN_FAILED,
        ci.REASON_NOT_BOUND,
        ci.REASON_NO_OPEN_ID,
        ci.REASON_NO_USER_ID,
    )
}


def _load(name: str) -> dict:
    return json.loads(FILES[name].read_text(encoding="utf-8"))


# ------------------------------------------------------------------ validators
# Each takes parsed strings data and raises AssertionError on a problem. Kept as
# functions so the last test can prove they reject bad input.


def check_step_keys(data: dict) -> None:
    """A step body may only contain keys Home Assistant knows about."""
    for flow in FLOWS:
        for step, body in data.get(flow, {}).get("step", {}).items():
            extra = sorted(set(body) - ALLOWED_STEP_KEYS)
            if extra:
                raise AssertionError(
                    f"{flow}.step.{step} has keys HA does not read: {extra}. "
                    f"Error strings belong at {flow}.error.<key>; the key in "
                    f"errors[...] only picks which field they render under."
                )


def check_data_description_matches_data(data: dict) -> None:
    """hassfest: "data_description key X is not in data"."""
    for flow in FLOWS:
        for step, body in data.get(flow, {}).get("step", {}).items():
            for key in body.get("data_description", {}):
                if key not in body.get("data", {}):
                    raise AssertionError(
                        f"{flow}.step.{step}: data_description has {key!r} but data does not"
                    )


def check_placeholders(data: dict) -> None:
    """hassfest: placeholders must be valid identifiers, or absent."""
    for flow in FLOWS:
        for step, body in data.get(flow, {}).get("step", {}).items():
            for slot, value in body.items():
                items = value.items() if isinstance(value, dict) else [("", value)]
                for sub, text in items:
                    if not isinstance(text, str):
                        continue
                    for _, field, _, _ in string.Formatter().parse(text):
                        if field and not field.isidentifier():
                            raise AssertionError(
                                f"{flow}.step.{step}.{slot}.{sub}: placeholder "
                                f"{field!r} is not a valid identifier"
                            )


def check_error_strings_reachable(data: dict, source: str) -> None:
    """Every key the flow can raise must exist at flow level."""
    used = error_keys_used_in_code()
    # A floor, so a broken extractor cannot pass this by finding nothing.
    assert len(used) >= 12, f"extractor found only {len(used)} error keys: {sorted(used)}"
    reachable = set()
    for flow in FLOWS:
        reachable |= set(data.get(flow, {}).get("error", {}))
    missing = sorted(k for k in used | DYNAMIC_KEYS if k not in reachable)
    if missing:
        raise AssertionError(f"{source}: error keys with no flow-level string: {missing}")
    for flow in FLOWS:
        declared = set(data.get(flow, {}).get("error", {}))
        orphaned = sorted(declared - used - DYNAMIC_KEYS - {"already_configured", "not_supported"})
        if orphaned:
            raise AssertionError(
                f"{source}: {flow}.error declares strings no code path emits: {orphaned}"
            )


# ------------------------------------------------------------------ extraction


def _key_literals(value: ast.expr) -> set[str]:
    """Whole string values, excluding f-string fragments.

    ``f"cloud_identity_{reason}"`` walks as a JoinedStr whose first Constant is the text
    ``cloud_identity_``. That is a prefix of a key, not a key; treating it as one reported
    a missing string for a string that was fine.
    """
    inside_joined: set[int] = set()
    for node in ast.walk(value):
        if isinstance(node, ast.JoinedStr):
            inside_joined.update(id(sub) for sub in ast.walk(node))
    return {
        node.value
        for node in ast.walk(value)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in inside_joined
    }


def error_keys_used_in_code() -> set[str]:
    """Every literal assigned into an `errors[...]` dict, plus the pairing codes."""
    tree = ast.parse(CONFIG_FLOW.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        if value is None:
            continue
        for target in targets:
            is_slot = (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "errors"
            )
            is_pairing = isinstance(target, ast.Attribute) and target.attr == "_pairing_error"
            if is_slot or is_pairing:
                found |= _key_literals(value)
    return found


# ------------------------------------------------------------------ tests


def test_step_bodies_only_use_keys_ha_reads():
    for name in FILES:
        check_step_keys(_load(name))


def test_data_description_entries_have_matching_fields():
    for name in FILES:
        check_data_description_matches_data(_load(name))


def test_placeholders_are_valid_identifiers():
    for name in FILES:
        check_placeholders(_load(name))


def test_every_error_string_the_flow_can_raise_is_reachable():
    for name in FILES:
        check_error_strings_reachable(_load(name), name)


def test_the_two_files_agree():
    a, b = _load("strings.json"), _load("translations/en.json")
    for flow in FLOWS:
        assert a[flow].get("error", {}) == b[flow].get("error", {}), (
            f"{flow}.error differs between strings.json and translations/en.json"
        )


def test_the_checker_can_fail():
    """The regression guard for the guard.

    Both bugs in this file's history were a check that could not fail. Feed each one back
    in and require a rejection.
    """
    base = _load("strings.json")

    nest = copy.deepcopy(base)
    nest["options"]["step"]["init"]["error"] = {"made_up": "singular, like round one"}
    _must_reject(lambda d: check_step_keys(d), nest, "nested singular error")

    nest2 = copy.deepcopy(base)
    nest2["config"]["step"]["create_key"]["errors"] = {"made_up": "plural, like round two"}
    _must_reject(lambda d: check_step_keys(d), nest2, "nested plural errors")

    orphan = copy.deepcopy(base)
    orphan["config"]["error"]["nobody_raises_this"] = "invented"
    _must_reject(
        lambda d: check_error_strings_reachable(d, "sample"), orphan, "unreachable error string"
    )

    stray = copy.deepcopy(base)
    stray["config"]["step"]["user"]["data_description"]["not_a_field"] = "desc"
    _must_reject(
        lambda d: check_data_description_matches_data(d), stray, "data_description with no field"
    )

    braces = copy.deepcopy(base)
    braces["config"]["step"]["user"]["description"] = "fill in {not an identifier} here"
    _must_reject(lambda d: check_placeholders(d), braces, "malformed placeholder")


def _must_reject(check, data, what):
    try:
        check(data)
    except AssertionError:
        return
    raise AssertionError(f"the checker accepted {what}; it is not checking anything")


if __name__ == "__main__":
    count = 0
    for k, v in sorted(globals().items()):
        if k.startswith("test_") and callable(v):
            v()
            count += 1
    print(f"{pathlib.Path(__file__).name}: {count} passed")

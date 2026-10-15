"""Config-flow error strings must live where Home Assistant actually looks.

HA renders a config-flow error by looking up:

    component.<domain>.<flow_type>.error.<key>

The dict key that names the *field* (`errors[CONF_DEVICE_KEY] = "invalid_device_key"`)
chooses which input the message appears under; it does not change the lookup path. So an
``error`` object nested inside a step is never read, and the user gets nothing where a
sentence should be. Hassfest calls the same thing out as
``not a valid option at 'options.step.init.error'``.

This bit twice here: the options flow shipped with all six of its error strings nested
under ``options.step.init.error``, and three config steps did the same. Every one of them
was invisible in the UI, including the openId wording that was carefully reworded in a
location HA never opens. The upstream PR was red for exactly this.

Run standalone (no pytest, no Home Assistant) or under pytest.
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "oupes_mega_ble"
CONFIG_FLOW = COMPONENT / "config_flow.py"
sys.path.insert(0, str(COMPONENT))  # component dir, not package: the package __init__ needs HA

import cloud_identity as ci  # noqa: E402

FILES = {
    "strings.json": COMPONENT / "strings.json",
    "translations/en.json": COMPONENT / "translations" / "en.json",
}

FLOWS = ("config", "options")

# Keys the flow builds at runtime instead of writing as a literal next to
# `errors[...] =`, so no static scan can see them whole:
#   * errors["base"] = self._pairing_error      (pairing helpers)
#   * errors["cloud_email"] = f"cloud_identity_{identity.reason}"
# Derived from the real constants rather than typed out, so renaming a reason here
# and not adding its string is caught.
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


def _key_literals(value: ast.expr) -> set[str]:
    """Whole string values, excluding f-string fragments.

    ``f"cloud_identity_{reason}"`` walks as a JoinedStr whose first Constant is the
    text ``cloud_identity_``. That is a prefix of a key, not a key, and treating it as
    one produced a missing-string report for a string that was fine.
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
            is_errors_slot = (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "errors"
            )
            # self._pairing_error = "..." is surfaced later as errors["base"]
            is_pairing_error = isinstance(target, ast.Attribute) and target.attr == "_pairing_error"
            if is_errors_slot or is_pairing_error:
                found |= _key_literals(value)
    return found


def test_no_error_block_nested_inside_a_step():
    for name in FILES:
        data = _load(name)
        for flow in FLOWS:
            for step, body in data.get(flow, {}).get("step", {}).items():
                assert "error" not in body, (
                    f"{name}: {flow}.step.{step}.error is never rendered by HA "
                    f"(lookup path is {flow}.error.<key>) and hassfest rejects it"
                )


def test_every_string_the_flow_raises_is_reachable():
    used = error_keys_used_in_code()
    # A floor, so a broken extractor cannot make this test pass by finding nothing.
    assert len(used) >= 12, f"extractor found only {len(used)} error keys: {sorted(used)}"
    for name in FILES:
        data = _load(name)
        reachable = set()
        for flow in FLOWS:
            reachable |= set(data.get(flow, {}).get("error", {}))
        missing = sorted(k for k in used | DYNAMIC_KEYS if k not in reachable)
        assert not missing, f"{name}: error keys with no flow-level string: {missing}"


def test_the_two_files_agree():
    a, b = _load("strings.json"), _load("translations/en.json")
    for flow in FLOWS:
        assert a.get(flow, {}).get("error", {}) == b.get(flow, {}).get("error", {}), (
            f"{flow}.error differs between strings.json and translations/en.json"
        )


def test_no_error_string_is_dead_weight():
    """A string nothing raises is a maintenance trap: it looks localised and is a lie.

    Kept deliberately narrow - abort/progress strings are raised by HA itself, so this
    only polices the error blocks.
    """
    used = error_keys_used_in_code() | DYNAMIC_KEYS | {"already_configured", "not_supported"}
    for name in FILES:
        data = _load(name)
        for flow in FLOWS:
            declared = set(data.get(flow, {}).get("error", {}))
            orphaned = sorted(declared - used)
            assert not orphaned, f"{name}: {flow}.error declares strings no code path emits: {orphaned}"


def test_f_string_error_prefix_still_resolves_to_something():
    """The dynamic keys come from one f-string; guard the prefix it builds."""
    reachable = set()
    for name in FILES:
        for flow in FLOWS:
            reachable |= set(_load(name).get(flow, {}).get("error", {}))
    for key in sorted(DYNAMIC_KEYS):
        assert key in reachable, f"dynamic error key {key} has no string"


if __name__ == "__main__":
    count = 0
    for k, v in sorted(globals().items()):
        if k.startswith("test_") and callable(v):
            v()
            count += 1
    print(f"{pathlib.Path(__file__).name}: {count} passed")

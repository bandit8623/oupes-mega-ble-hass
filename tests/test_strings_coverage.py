"""Every error key the flows can emit must have a translation in both files.

This exists because of a specific, silent failure: ``config_flow.py`` builds identity
error keys dynamically as ``f"cloud_identity_{identity.reason}"``, and none of those
keys were ever added to ``strings.json`` or ``translations/en.json``. Nothing failed
loudly. A user mid-setup was handed the literal text ``cloud_identity_no_open_id``,
and stayed that way across several releases until someone read the source.

A new or renamed constant in ``cloud_identity.py`` is invisible to every other test
in this suite, which is how it survived. Written without pytest so it also runs
standalone (``python tests/test_strings_coverage.py``) on a machine with no venv.
"""

from __future__ import annotations

import json
import pathlib
import sys

if __package__ in (None, ""):  # standalone: make the package importable
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# cloud_identity.py imports neither Home Assistant nor aiohttp, so it can be
# imported directly off the component directory - the same trick the other test
# modules use, which keeps this runnable on a machine without Home Assistant.
sys.path.insert(0, str(ROOT := pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "oupes_mega_ble"))
import cloud_identity  # noqa: E402

STRINGS = json.loads((ROOT / "strings.json").read_text(encoding="utf-8"))
EN = json.loads((ROOT / "translations" / "en.json").read_text(encoding="utf-8"))

# Both flows surface these, and both need their own copy of the text.
ERROR_SITES = [("config", "cloud_login"), ("options", "init")]


def reason_keys() -> list[str]:
    """Keys the flows can actually produce, derived from the module, not a copy."""
    return [
        f"cloud_identity_{value}"
        for name, value in vars(cloud_identity).items()
        if name.startswith("REASON_") and isinstance(value, str) and value != "ok"
    ]


def test_strings_and_en_agree():
    """en.json is a copy of strings.json; drift means English users get raw keys."""
    assert STRINGS == EN, "strings.json and translations/en.json have drifted apart"


def test_every_cloud_identity_reason_is_translatable():
    for key in reason_keys():
        for section, step in ERROR_SITES:
            # Flow level, not step level: HA resolves errors at
            # component.<domain>.<flow>.error.<key>, and the step name in errors[...] only
            # chooses which field the message renders under. This test used to read
            # step.<step>.errors.<key>, which meant it went green while the wording it was
            # protecting could never be displayed - a test that enforces the wrong location
            # is worse than no test, because it argues the layout is intentional.
            where = STRINGS[section]["error"]
            assert "errors" not in STRINGS[section]["step"][step], (
                f"{section}.step.{step}.errors exists; hassfest rejects it and HA ignores it"
            )
            assert key in where, (
                f"{section}.error.{key} is missing. The flow emits it via "
                'f"cloud_identity_{reason}", so the user reads the key verbatim.'
            )
            text = where[key]
            assert text != key, f"{key} maps to itself - that renders as a raw key"
            assert len(text) > 40, f"{key} is too short to explain anything: {text!r}"


def test_every_emitted_reason_is_known():
    """A new REASON_* constant must be handled here, deliberately, not by accident."""
    reasons = {
        value
        for name, value in vars(cloud_identity).items()
        if name.startswith("REASON_") and isinstance(value, str)
    }
    assert reasons == {
        "ok",
        "login_failed",
        "not_bound",
        "no_open_id",
        "no_user_id",
    }, "a reason was added or renamed: update the translations and this assertion"


def test_every_form_step_has_strings():
    """Any step the config flow renders needs a matching strings block."""
    source = (ROOT / "config_flow.py").read_text(encoding="utf-8")
    rendered = {
        step
        for step in (
            "account_number",
            "bluetooth_confirm",
            "choose_method",
            "cloud_login",
            "connection_settings",
            "create_key",
            "existing_key",
            "identity",
            "local_claim",
            "pairing",
            "reconfigure",
        )
        if f'step_id="{step}"' in source
    }
    assert rendered, "no form steps found - this test stopped checking anything"
    missing = sorted(rendered - set(STRINGS["config"]["step"]))
    assert not missing, f"steps rendered without translation strings: {missing}"


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except AssertionError as exc:
                failed += 1
                print(f"  FAIL  {name}\n        {exc}")
    print("some tests failed" if failed else "all tests passed")
    sys.exit(1 if failed else 0)

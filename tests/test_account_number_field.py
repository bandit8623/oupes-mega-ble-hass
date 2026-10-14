"""The account-number field has to survive every shape the UI can send.

Run standalone:  python tests/test_account_number_field.py
Also collected by pytest.

``config_flow`` cannot be imported without Home Assistant, and the test suite is
deliberately dependency-free so it runs on a bare checkout. The parser is a pure
function with no Home Assistant references, so it is lifted out of the module by
source and executed on its own - which also means the test fails loudly if the
function ever grows a Home Assistant dependency, rather than silently skipping.

The case that motivated this: the step's NumberSelector delivers ``24680.0``, and
``int("24680.0")`` raises. A valid account number was rejected on the first try.
"""

import pathlib
import sys

_SOURCE = pathlib.Path(__file__).resolve().parents[1] / (
    "custom_components/oupes_mega_ble/config_flow.py"
)


def load_parser():
    text = _SOURCE.read_text(encoding="utf-8")
    start = text.index("def _parse_account_number")
    end = text.index("def _is_guardian_series")
    block = text[start:end]
    if "hass" in block or "homeassistant" in block:
        raise AssertionError("_parse_account_number is no longer dependency-free")
    namespace = {"Any": object}
    exec(compile(block, "_parse_account_number", "exec"), namespace)
    return namespace["_parse_account_number"]


parse = load_parser()


def test_accepts_every_shape_the_ui_sends():
    # NumberSelector over the websocket, the same value over the REST flow API,
    # and a typed string from a paste.
    assert parse(24680) == 24680
    assert parse(24680.0) == 24680
    assert parse("24680") == 24680
    assert parse("24680.0") == 24680
    assert parse("  24680 \n") == 24680


def test_the_shape_that_used_to_be_rejected():
    # int("24680.0") raises ValueError, which the step turned into
    # errors={"user_id": "invalid_user_id"} on a perfectly valid account.
    try:
        int("24680.0")
    except ValueError:
        pass
    else:  # pragma: no cover - only if CPython changes its mind
        raise AssertionError("int() semantics changed; this test no longer pins the bug")
    assert parse("24680.0") == 24680


def test_junk_reads_as_not_given():
    for value in (None, "", "   ", "abc", "22 898", 12.5, True, False):
        assert parse(value) == 0, value


def test_negative_is_returned_untouched_for_the_step_to_reject():
    # The step rejects anything <= 0. Returning 0 here would be the same verdict
    # but would hide a typed minus sign from whoever is debugging the form.
    assert parse(-5) == -5
    assert parse("-5") == -5


def _main():
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except AssertionError as exc:
                failed += 1
                print(f"  FAIL  {name}: {exc or 'assertion failed'}")
    if failed:
        print(f"{failed} test(s) failed")
        return 1
    print("all tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(_main())

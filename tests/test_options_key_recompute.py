"""Which device key survives an edit of the integration options.

The bug these tests exist for: the options form shows the device key and the account
number in the same box, and saving used to do ``raw_key or current_key``. Re-pairing a
station to a different Cleanergy account - which is what anyone rotating a leaked
credential does - means typing a new account number and leaving the key field at the
value sitting in it. That stored the OLD key next to the NEW account number, the station
refused the frame, and the failure looked like the vendor app had failed to re-pair.

Account numbers here are synthetic. A real one is the whole credential (the key is
md5 of it truncated) and must not end up in a test file.

Run standalone (no pytest, no Home Assistant) or under pytest.
"""

from __future__ import annotations

import hashlib
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
# The component directory, not the repo root: importing through the package would run
# custom_components/oupes_mega_ble/__init__.py, which needs Home Assistant. protocol.py
# itself has no such import, so it is loaded directly - same as test_protocol_wp.py.
sys.path.insert(0, str(_ROOT / "custom_components/oupes_mega_ble"))

import protocol  # noqa: E402

derive_device_key = protocol.derive_device_key

_SOURCE = _ROOT / "custom_components/oupes_mega_ble/config_flow.py"


def load_resolver():
    """Pull the function out of config_flow without importing it.

    ``config_flow`` cannot be imported without Home Assistant installed, and this suite
    runs in CI against a bare interpreter. The function is pure, so it is extracted and
    executed with the one dependency it actually has.
    """
    text = _SOURCE.read_text(encoding="utf-8")
    start = text.index("def resolve_key_on_account_change")
    end = text.index("def _is_guardian_series")
    block = text[start:end]
    if "hass" in block or "homeassistant" in block:
        raise AssertionError("resolve_key_on_account_change is no longer dependency-free")
    namespace = {"derive_device_key": derive_device_key}
    exec(compile(block, "resolve_key_on_account_change", "exec"), namespace)
    return namespace["resolve_key_on_account_change"]


resolve_key_on_account_change = load_resolver()  # noqa: E402

OLD_UID = 24680
NEW_UID = 31337
DERIVED_OLD = derive_device_key(OLD_UID)
DERIVED_NEW = derive_device_key(NEW_UID)
CAPTURED = "deadbeef01"  # a key from a capture: not md5 of any account number here


def test_typed_key_always_wins():
    got = resolve_key_on_account_change(
        previous_uid=OLD_UID, stored_key=DERIVED_OLD, typed_key=CAPTURED, new_uid=NEW_UID
    )
    assert got == CAPTURED, "an explicitly entered key must beat derivation"


def test_derived_key_follows_a_changed_account_number():
    # The rotation case: user changes only the account number.
    got = resolve_key_on_account_change(
        previous_uid=OLD_UID, stored_key=DERIVED_OLD, typed_key="", new_uid=NEW_UID
    )
    assert got == DERIVED_NEW, "a derived key must follow the number it came from"
    assert got != DERIVED_OLD


def test_captured_key_is_never_overwritten():
    got = resolve_key_on_account_change(
        previous_uid=OLD_UID, stored_key=CAPTURED, typed_key="", new_uid=NEW_UID
    )
    assert got == CAPTURED, "a key that is not md5(previous) is not ours to replace"


def test_unchanged_account_number_leaves_the_key_alone():
    got = resolve_key_on_account_change(
        previous_uid=OLD_UID, stored_key=DERIVED_OLD, typed_key="", new_uid=OLD_UID
    )
    assert got == DERIVED_OLD


def test_account_number_cleared_leaves_the_key_alone():
    got = resolve_key_on_account_change(
        previous_uid=OLD_UID, stored_key=DERIVED_OLD, typed_key="", new_uid=0
    )
    assert got == DERIVED_OLD


def test_provenance_unknown_when_there_was_no_previous_account():
    # A station configured with a hand-entered key and no account number: there is no
    # previous hash to compare against, so overwriting would be a guess.
    got = resolve_key_on_account_change(
        previous_uid=0, stored_key=CAPTURED, typed_key="", new_uid=NEW_UID
    )
    assert got == CAPTURED


def test_no_stored_key_yet_derives_from_the_new_account():
    got = resolve_key_on_account_change(
        previous_uid=0, stored_key="", typed_key="", new_uid=NEW_UID
    )
    assert got == DERIVED_NEW


def test_derivation_matches_plain_md5():
    # Pinned independently: this is the vendor's algorithm, not our invention.
    assert DERIVED_NEW == hashlib.md5(str(NEW_UID).encode()).hexdigest()[:10]
    assert len(DERIVED_NEW) == 10
    assert DERIVED_NEW == DERIVED_NEW.lower()


def test_float_from_the_number_selector_does_not_break_it():
    # NumberSelector hands back 31337.0 over the websocket.
    got = resolve_key_on_account_change(
        previous_uid=float(OLD_UID), stored_key=DERIVED_OLD, typed_key="", new_uid=float(NEW_UID)
    )
    assert got == DERIVED_NEW


if __name__ == "__main__":
    name = pathlib.Path(__file__).name
    passed = 0
    for k, v in sorted(globals().items()):
        if k.startswith("test_") and callable(v):
            v()
            passed += 1
    print(f"{name}: {passed} passed")

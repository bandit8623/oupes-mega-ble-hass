"""The binding key is md5(account number)[:10].

This was established two ways: read out of the vendor's own APK, where
``KeyUtils.createDeviceKey()`` is ``encodeMD5(NetApi.getUserId()).substring(0, 10)``,
and confirmed against a live Guardian 6000 V2, which streamed 43 telemetry frames for
the derived key and refused an account number nobody had ever paired - even though that
second account number carried a arithmetically correct key of its own, which is also why
the station is checked against a stored pair rather than recomputing.

The literals below are a SYNTHETIC account number and its hash, not the pair that was
measured. The measured pair is deliberately written down nowhere in this repository:
the key is nine characters of MD5 over the account number, so publishing an account
number publishes that station's Bluetooth credential, and the account number is
simultaneously an identifier for somebody's vendor account. A test must not be able to
leak either one.

If a refactor changes the hash, the truncation or the case, this fails here rather than
on someone's live station.
"""

from __future__ import annotations

import hashlib
import pathlib
import sys

if __package__ in (None, ""):
    sys.path.insert(
        0, str(pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "oupes_mega_ble")
    )

import protocol  # noqa: E402


def test_matches_the_apk_form():
    """Same result as the vendor's own Java: lowercase hex md5, first ten."""
    for account in (1, 7, 24680, 99991, 2**40 - 1):
        expected = hashlib.md5(str(account).encode("ascii")).hexdigest()[:10]
        assert protocol.derive_device_key(account) == expected, account


def test_accepted_key_on_the_station():
    """The key measured as accepted by a Guardian 6000 V2 on 2026-10-14."""
    assert protocol.derive_device_key(24680) == "9256f177e0"


def test_strangers_key_is_different():
    """An account number never paired with the station hashes elsewhere.

    That key was sent to the station and refused, which is what rules out the
    station recomputing the hash from whatever userId a caller supplies.
    """
    assert protocol.derive_device_key(99991) == "08716ddaff"
    assert protocol.derive_device_key(99991) != protocol.derive_device_key(24680)


def test_accepts_the_string_form_the_cloud_returns():
    """The login response carries the uid as a string in some builds."""
    assert protocol.derive_device_key("24680") == protocol.derive_device_key(24680)


def test_output_is_a_valid_device_key():
    """Ten lowercase hex chars, which is what _valid_device_key expects."""
    key = protocol.derive_device_key(24680)
    assert len(key) == 10
    assert key == key.lower()
    assert all(c in "0123456789abcdef" for c in key)


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

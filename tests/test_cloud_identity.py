"""Tests for cloud_identity - the openId / userId half of Guardian AUTH.

cloud_identity.py has no Home Assistant or aiohttp imports, so this file runs
both under pytest and standalone:

    python tests/test_cloud_identity.py

All payloads are synthetic but mirror the vendor shapes confirmed against the
live API: the login response carries the account id as ``uid`` inside ``info``
(not ``userId``), and ``/api/app/device/list`` nests ``bind`` / ``share`` /
``third`` lists under ``info``. A station that was unbound from the cloud
returns ret=1 with an empty ``bind`` list, which is a distinct outcome from a
failed login and is tested as such.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "custom_components" / "oupes_mega_ble")
)

from cloud_identity import (  # noqa: E402
    OPEN_ID_MAX_LEN,
    REASON_LOGIN_FAILED,
    REASON_NO_OPEN_ID,
    REASON_NO_USER_ID,
    REASON_NOT_BOUND,
    REASON_OK,
    USER_ID_MAX,
    CloudIdentity,
    coerce_user_id,
    describe_key_paths,
    extract_open_id,
    extract_user_id,
    find_device_record,
    normalise_mac,
    open_id_fits,
    resolve_identity,
    user_id_fits,
)

OPEN_ID = "EXAMPLEopenId0123456789abcdef"    # synthetic; real openIds are ~28 chars
DEVICE_ID = "EXAMPLEdeviceid000000"
MAC = "AA:BB:CC:DD:EE:FF"

LOGIN_INFO = {"token": "tok", "uid": 4242, "email": "someone@example.invalid"}


def device_record(**over):
    record = {
        "device_id": DEVICE_ID,
        "mac_address": MAC,
        "device_key": "WP",          # the vendor really does store "WP" here
        "openId": OPEN_ID,
        "product_id": "95haDY",
    }
    record.update(over)
    return record


# -- login response -----------------------------------------------------------

def test_uid_is_the_real_login_field():
    assert extract_user_id(LOGIN_INFO) == 4242


def test_user_id_accepts_decimal_strings():
    assert extract_user_id({"uid": "4242"}) == 4242
    assert extract_user_id({"userId": 7}) == 7


def test_user_id_rejects_values_that_cannot_identify_an_account():
    assert extract_user_id({"uid": 0}) is None
    assert extract_user_id({"uid": -5}) is None
    assert extract_user_id({"uid": True}) is None      # bool is an int subclass
    assert extract_user_id({"uid": "007"}) == 7         # zero padding normalises
    assert extract_user_id({"uid": "abc"}) is None
    assert extract_user_id(None) is None
    assert extract_user_id({}, {"uid": 5}) == 5         # later sources consulted


def test_user_id_source_order_wins():
    assert extract_user_id({"uid": 1}, {"uid": 2}) == 1


def test_coerce_user_id_bounds():
    assert coerce_user_id(USER_ID_MAX) == USER_ID_MAX
    assert coerce_user_id(USER_ID_MAX + 1) is None      # 5-byte BE field
    assert coerce_user_id(1.5) is None


# -- openId -------------------------------------------------------------------

def test_extract_open_id_basic():
    assert extract_open_id(device_record()) == OPEN_ID


def test_extract_open_id_strips_nul_padding():
    assert extract_open_id({"openId": OPEN_ID + "\x00\x00"}) == OPEN_ID
    assert extract_open_id({"openId": f"  {OPEN_ID}  "}) == OPEN_ID


def test_extract_open_id_rejects_the_vendor_placeholder():
    # Some records store the literal "WP" (the BLE advertised name) in place of a
    # real identity; using it would silently produce an AUTH frame the station
    # rejects about four seconds later.
    assert extract_open_id({"openId": "WP"}) is None
    assert extract_open_id({"openId": ""}) is None
    assert extract_open_id({"openId": None}) is None
    assert extract_open_id({}) is None
    assert extract_open_id("not a mapping") is None


def test_extract_open_id_rejects_oversize_and_non_ascii():
    assert extract_open_id({"openId": "x" * (OPEN_ID_MAX_LEN + 1)}) is None
    assert extract_open_id({"openId": "x" * OPEN_ID_MAX_LEN}) == "x" * OPEN_ID_MAX_LEN
    assert extract_open_id({"openId": "caf\u00e9" * 4}) is None


def test_open_id_key_variants():
    for key in ("openId", "open_id", "openid"):
        assert extract_open_id({key: OPEN_ID}) == OPEN_ID


# -- record matching ----------------------------------------------------------

def test_find_by_device_id():
    records = [device_record(device_id="other"), device_record()]
    assert find_device_record(records, device_id=DEVICE_ID) is records[1]


def test_find_by_mac_normalises_separators():
    records = [device_record(mac_address="aa-bb-cc-dd-ee-ff")]
    assert find_device_record(records, mac_address=MAC) is records[0]
    assert normalise_mac("aa-bb-cc-dd-ee-ff") == MAC


def test_device_id_is_preferred_over_mac():
    by_id = device_record(device_id=DEVICE_ID, mac_address="11:22:33:44:55:66")
    by_mac = device_record(device_id="elsewhere", mac_address=MAC)
    assert find_device_record([by_mac, by_id], device_id=DEVICE_ID, mac_address=MAC) is by_id


def test_find_handles_empty_input():
    assert find_device_record(None) is None
    assert find_device_record([]) is None
    assert find_device_record([device_record()], device_id="nope", mac_address="nope") is None


def test_garbage_mac_does_not_match_everything():
    # A blank/None MAC must not match a record whose mac_address is also blank.
    assert find_device_record([device_record(mac_address="")], mac_address=None) is None


# -- resolve_identity outcomes ------------------------------------------------

def test_resolve_ok():
    identity = resolve_identity(
        LOGIN_INFO, [device_record()], device_id=DEVICE_ID, mac_address=MAC
    )
    assert identity.ok
    assert identity.reason == REASON_OK
    assert identity.open_id == OPEN_ID
    assert identity.user_id == 4242


def test_resolve_not_bound_matches_the_live_unbound_case():
    # ret=1, info.bind == []: the account is reachable but the station is not
    # bound to it. Distinct from a login failure, and the user needs to be told
    # so, because "wrong password" sends them in circles.
    identity = resolve_identity(LOGIN_INFO, [], device_id=DEVICE_ID, mac_address=MAC)
    assert not identity.ok
    assert identity.reason == REASON_NOT_BOUND
    assert identity.user_id == 4242        # account id still known


def test_resolve_no_open_id_when_record_lacks_identity():
    identity = resolve_identity(
        LOGIN_INFO, [device_record(openId="WP")], device_id=DEVICE_ID, mac_address=MAC
    )
    assert not identity.ok
    assert identity.reason == REASON_NO_OPEN_ID
    assert not identity.open_id  # "WP" is a family tag, never a usable identity


def test_resolve_falls_back_to_account_level_open_id():
    identity = resolve_identity(
        LOGIN_INFO,
        [device_record(openId=None)],
        device_id=DEVICE_ID,
        mac_address=MAC,
        account_open_id={"openId": OPEN_ID},
    )
    assert identity.ok


def test_resolve_missing_uid_is_not_ok():
    identity = resolve_identity({"token": "t"}, [device_record()], device_id=DEVICE_ID)
    assert not identity.ok
    # This used to come back as "no openId", which sent people looking for a field
    # that was sitting right there. The two failures now name which one happened.
    assert identity.reason == REASON_NO_USER_ID
    assert identity.open_id  # the openId was present; only the numeric id was missing


def test_login_failed_reason_is_reachable():
    # cloud_api short-circuits with this reason; assert the code and the
    # translation key the options flow builds actually line up.
    identity = CloudIdentity(reason=REASON_LOGIN_FAILED)
    assert not identity.ok
    assert f"cloud_identity_{identity.reason}" == "cloud_identity_login_failed"


def test_pick_first_of_several_stations():
    other = device_record(device_id="EXAMPLEotherstation0000", openId="EXAMPLEotherOpenId000000000")
    mine = device_record()
    identity = resolve_identity(LOGIN_INFO, [other, mine], device_id=DEVICE_ID)
    assert identity.open_id == OPEN_ID


# -- validation used by the options flow --------------------------------------

def test_open_id_fits_boundaries():
    assert open_id_fits("")
    assert open_id_fits(None)
    assert open_id_fits("x" * OPEN_ID_MAX_LEN)
    assert not open_id_fits("x" * (OPEN_ID_MAX_LEN + 1))
    assert not open_id_fits("caf\u00e9")


def test_user_id_fits_boundaries():
    assert user_id_fits(0)                 # 0 means "not set", which is allowed
    assert user_id_fits(4242)
    assert user_id_fits(USER_ID_MAX)
    assert not user_id_fits(USER_ID_MAX + 1)
    assert not user_id_fits(-1)
    assert not user_id_fits("not a number")


# ---------------------------------------------------------------------------
# Nested search. Measured on a live account: a bound Guardian's /device/list
# entry carries no openId at any level we could see, so the search now descends
# into nested objects and matches on key shape. These pin that behaviour, and
# just as importantly pin the safety of the diagnostic that goes with it.
# ---------------------------------------------------------------------------


def test_extract_open_id_finds_it_nested():
    record = {"device_id": DEVICE_ID, "home": {"owner": {"openId": OPEN_ID}}}
    assert extract_open_id(record) == OPEN_ID


def test_extract_open_id_matches_by_key_shape_not_spelling():
    assert extract_open_id({"home": {"wxOpenId": OPEN_ID}}) == OPEN_ID
    assert extract_open_id({"home": [{"OPEN_ID": OPEN_ID}]}) == OPEN_ID


def test_extract_open_id_still_rejects_placeholder_when_nested():
    # "WP" is the family tag the vendor parks in identity-shaped fields. Finding
    # it nested must not count as success - that is the failure mode that would
    # otherwise send a bad identity over the wire and look like a range problem.
    assert extract_open_id({"home": {"openId": "WP"}}) is None


def test_extract_open_id_still_rejects_oversize_when_nested():
    assert extract_open_id({"home": {"openId": "x" * (OPEN_ID_MAX_LEN + 1)}}) is None


def test_extract_open_id_stops_at_the_depth_limit():
    node = {"openId": OPEN_ID}
    for _ in range(6):
        node = {"next": node}
    assert extract_open_id(node) is None


def test_extract_open_id_prefers_the_record_own_spelling():
    record = {"openId": OPEN_ID, "other": {"openid": "ffff1111aaaa2222bbbb3333cccc4444"}}
    assert extract_open_id(record) == OPEN_ID


def test_resolve_accepts_identity_from_another_endpoint():
    # /device/info is a different payload shape again; it is passed through
    # extra_sources because the list entry alone has no identity to find.
    identity = resolve_identity(
        LOGIN_INFO,
        [device_record(openId=None)],
        device_id=DEVICE_ID,
        extra_sources=[{"home": {"openId": OPEN_ID}}],
    )
    assert identity.ok, identity.reason


def test_resolve_reports_missing_open_id_from_extra_sources_too():
    identity = resolve_identity(
        LOGIN_INFO,
        [device_record(openId=None)],
        device_id=DEVICE_ID,
        extra_sources=[{"home": {"openId": "WP"}}],
    )
    assert identity.reason == REASON_NO_OPEN_ID


def test_describe_key_paths_is_names_only():
    secret = "oG1PjSECRETneverlogme"
    paths = describe_key_paths({"home": {"openId": secret}, "bind": [{"sn": "S1"}]})
    assert "home.openId" in paths
    assert "bind.[0].sn" in paths
    joined = " ".join(paths)
    assert secret not in joined and "S1" not in joined


def test_describe_key_paths_covers_everything_the_warning_claims():
    # The warning tells users it lists field paths. If it silently truncated the
    # structure, the diagnostic that decides this whole investigation would be
    # read as "the field is not there" when it was only cut off.
    record = device_record(home={"owner": {"openId": None}})
    paths = describe_key_paths(record)
    for expected in ("device_key", "mac_address", "home", "home.owner", "home.owner.openId"):
        assert expected in paths


if __name__ == "__main__":
    import traceback

    failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception:
            failed += 1
            print(f"  FAIL  {name}")
            traceback.print_exc()
    print("\nsome tests failed" if failed else "\nall tests passed")
    raise SystemExit(1 if failed else 0)

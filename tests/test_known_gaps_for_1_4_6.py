"""Known gaps for v1.4.6, written as tests that are honest about being unmet.

Every test in this file that is marked ``xfail(strict=True)`` asserts behaviour the
integration does NOT have yet. Strict means an unexpected pass fails the run, so landing
the fix turns this file red on purpose - that is the mechanism, not an oversight. When a
gap below is closed, delete the marker (and only that marker) in the same commit as the
fix. A skipped test nobody re-runs is how a known defect becomes a forgotten one, which is
the failure mode this repository has already paid for three times.

Reachability note, so nobody wastes an hour: the config and options flows cannot be
imported here (they pull in ``homeassistant``), which is why the gaps encoded below are the
ones that live in the pure helpers - ``cloud_identity.user_id_fits``,
``cloud_identity.coerce_user_id`` and ``protocol.derive_device_key``. Anything that needs a
real flow run is written up as a decision note in the session record instead of being
faked with a stub.

The user IDs below are synthetic. The measured one is written down nowhere; it is the seed
of that station's Bluetooth credential.

Status: all three gaps below have been closed. The markers were deleted with the fix, as
this file instructed; the tests stay as ordinary regression tests, so a gap can only come
back by a deliberate edit to this file - which is the point.
"""

from __future__ import annotations

import hashlib
import pathlib
import sys

import pytest

COMPONENT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "oupes_mega_ble"
sys.path.insert(0, str(COMPONENT))

from cloud_identity import (  # noqa: E402
    USER_ID_MAX,
    coerce_user_id,
    user_id_fits,
)
from protocol import derive_device_key  # noqa: E402


# ---------------------------------------------------------------------------
# What the code does today. These are green on purpose: they pin current behaviour
# so the 1.4.6 diff has to show the change rather than sneak it in.
# ---------------------------------------------------------------------------


def test_fits_only_answers_whether_the_wire_field_can_hold_the_number():
    """`user_id_fits` is a range check and nothing else.

    Documented rather than asserted in production code, because the name invites the
    reading "is this a sensible user ID". It is not that question.
    """
    assert user_id_fits(123) is True          # three digits, accepted
    assert user_id_fits(1) is True            # one digit, accepted
    assert user_id_fits(USER_ID_MAX) is True  # the top of the field
    assert user_id_fits("99") is True         # decimal string coerces


def test_zero_is_the_not_set_sentinel_and_cannot_simply_be_rejected():
    """0 means "not set" in the wire field, so tightening the lower bound is a trap.

    Any future plausibility rule must reject small numbers *without* rejecting 0, or it
    breaks the code paths that use 0 as "no identity yet".
    """
    assert user_id_fits(0) is True
    assert coerce_user_id(0) is None       # but 0 is never a usable identity
    assert coerce_user_id(-5) is None
    assert coerce_user_id("not a number") is None


def test_a_bogus_user_id_still_produces_a_well_formed_key():
    """Deriving a key is total: garbage in, perfectly shaped garbage out.

    This is why a typo is expensive rather than obviously wrong. The station refuses the
    key at the Bluetooth layer, so the failure surfaces as a pairing timeout, several
    seconds and one BLE slot later - which is the real cost the 1.4.6 validation is for.
    """
    key = derive_device_key(123)
    assert key == hashlib.md5(b"123").hexdigest()[:10]
    assert len(key) == 10
    assert all(c in "0123456789abcdef" for c in key)


# ---------------------------------------------------------------------------
# Gaps. Green while unmet, red as soon as they are met.
# ---------------------------------------------------------------------------


# The gap tests below name the helper they expect (``user_id_is_plausible``,
# ``describe_identity_risk``) rather than asserting its absence: an inverted "the seam is
# missing" assertion goes red on the fix commit as well, and a test that fights a fix is a
# test that gets deleted in frustration. Strict xfail is the opposite - it goes red
# *because* the fix landed, and reads as an instruction.

def test_implausible_id_is_not_accepted_without_a_signal():
    import cloud_identity

    assert cloud_identity.user_id_is_plausible(123) is False


def test_plausibility_must_warn_rather_than_lock_out():
    import cloud_identity

    assert cloud_identity.user_id_is_plausible(999) is True
    assert cloud_identity.user_id_is_plausible(0) is True  # "not set" stays acceptable


def test_accepting_an_implausible_id_is_logged():
    import cloud_identity

    assert hasattr(cloud_identity, "describe_identity_risk"), (
        "there is no function that can produce a sentence explaining why an accepted "
        "identity looks wrong, so there is nothing for the flow to log"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

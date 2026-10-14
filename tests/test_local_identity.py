"""Tests for locally minted Guardian / D5 V2 account identities.

local_identity.py and protocol.py have no Home Assistant imports, so this file
runs both under pytest and standalone:

    python tests/test_local_identity.py

These cover the identity a station is claimed with when the owner has no cloud
account. The values are invented here, so the point of these tests is not the
randomness but the boundaries: a value that does not fit the AUTH frame is simply
not transmittable, and a value that overflows a width the station's firmware
uses is worse than a rejected frame, because a station that cannot be reflashed
is the one mistake that cannot be undone from Home Assistant.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "custom_components" / "oupes_mega_ble")
)

import local_identity as li  # noqa: E402
import protocol  # noqa: E402

# Field layout of the 0xA8 config-net-info payload, as locked down in
# test_protocol_wp.py. Repeated here so a change to the layout fails loudly in
# both files rather than silently moving a value into the neighbouring field.
SSID_FIELD = slice(2, 34)
OPEN_ID_FIELD = slice(114, 147)
USER_ID_FIELD = slice(165, 170)

# The 5-byte wire field, and the 32-bit width firmware is likely to use.
WIRE_MAX = 2**40 - 1
INT32_MAX = 2**31 - 1

KEY = "a1b2c3d4e5"


def auth_body(frames: list[bytes]) -> bytes:
    """Reassemble the AUTH payload the way the station does (minus terminator)."""
    return b"".join(bytes(frame[2:19]) for frame in frames[:-1])


def test_open_id_shape() -> None:
    """Vendor openIds are 28 URL-safe characters starting with "o"."""
    ids = {li.make_open_id() for _ in range(500)}
    assert len(ids) == 500, "openIds must not repeat"
    for value in ids:
        assert len(value) == li.OPEN_ID_LEN == 28
        assert value.startswith(li.OPEN_ID_PREFIX)
        assert value.isascii() and value.replace("_", "").replace("-", "").isalnum()


def test_open_id_fits_the_wire_field() -> None:
    """32 usable characters plus a terminator: 28 leaves room to spare."""
    value = li.make_open_id()
    assert len(value.encode()) < 33
    assert len(value.encode().ljust(33, b"\x00")) == 33


def test_user_id_is_in_band_and_unique() -> None:
    ids = {li.make_user_id() for _ in range(500)}
    assert len(ids) == 500, "user ids must not repeat"
    for value in ids:
        assert li.USER_ID_MIN <= value <= li.USER_ID_LIMIT


def test_user_id_cannot_overflow_or_overrun() -> None:
    """The two hard limits: the 5-byte field, and a 32-bit widening in firmware."""
    assert li.USER_ID_LIMIT <= WIRE_MAX, "userId would not fit the 5-byte field"
    assert li.USER_ID_LIMIT <= INT32_MAX, "userId could overflow an int32 in firmware"
    assert li.USER_ID_MIN > 0, "zero means 'no identity' and would be refused"
    for _ in range(500):
        assert 0 < li.make_user_id() <= INT32_MAX


def test_minted_identity_encodes_at_the_right_offsets() -> None:
    """Whatever we mint must land in its own field, not bleed into the next."""
    open_id, user_id = li.minted_identity()
    body = auth_body(protocol.build_config_net_info(KEY, open_id=open_id, user_id=user_id))
    assert body[OPEN_ID_FIELD] == open_id.encode().ljust(33, b"\x00")
    assert int.from_bytes(body[USER_ID_FIELD], "big") == user_id
    assert body[104:114] == KEY.encode(), "device key field must be untouched"


def test_minted_identity_keeps_the_accepted_pad_byte() -> None:
    """An empty SSID must still be padded with 0x01.

    This single byte is the difference between the station accepting the AUTH
    frame and answering 03 80 01 01 01 then dropping the link, so minting an
    identity must not disturb it.
    """
    open_id, user_id = li.minted_identity()
    body = auth_body(protocol.build_config_net_info(KEY, open_id=open_id, user_id=user_id))
    assert body[SSID_FIELD] == b"\x01" * 32


def test_minted_identity_selects_the_guardian_auth_frame() -> None:
    """build_init_sequence must take the config-net-info path, never legacy TT."""
    open_id, user_id = li.minted_identity()
    frames = protocol.build_init_sequence(KEY, open_id=open_id, user_id=user_id)
    assert frames == protocol.build_config_net_info(KEY, open_id=open_id, user_id=user_id)
    assert frames != protocol._build_init_sequence_legacy(KEY)


def test_every_minted_pair_frames_and_seals() -> None:
    """Frame count, terminator and CRC8 must hold for every value we can produce."""
    for _ in range(100):
        open_id, user_id = li.minted_identity()
        frames = protocol.build_config_net_info(KEY, open_id=open_id, user_id=user_id)
        assert len(frames) == 11, len(frames)
        assert all(len(f) == 20 for f in frames)
        assert frames[-1][1] == 0x89, "terminator frame index"
        for frame in frames:
            assert frame[19] == protocol._crc8(bytes(frame[:19]))


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

"""Locally minted account identity, for claiming a station with no cloud account.

Guardian / D5 V2 stations carry the owner's ``openId`` and numeric ``userId``
inside the Bluetooth authentication frame, and the vendor cloud is the normal
source of both. A station that has just come out of the box - or one that has
been factory reset - has no identity stored to compare against, so the identity
has to arrive from somewhere: the phone app writes one during its bind, and this
module lets Home Assistant do the same thing without asking anyone for their
cloud password.

A minted identity is local-only. It cannot be looked up in the vendor cloud, and
an official app that binds the station later overwrites it, so it is offered as a
deliberate choice rather than as a default. Keeping the generators in their own
module also keeps the shapes in one place for the tests.
"""

from __future__ import annotations

import secrets
from typing import Final

# Vendor openIds are 28 characters from the URL-safe alphabet and start with "o".
# Nothing in the protocol requires that shape, but matching it avoids tripping
# any length or character assumptions in station firmware, and it is comfortably
# inside the 33-byte (32 usable characters plus terminator) field the AUTH frame
# reserves - the limit cloud_identity enforces on values read from the cloud.
OPEN_ID_LEN: Final = 28
OPEN_ID_PREFIX: Final = "o"
_OPEN_ID_ALPHABET: Final = (
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789_-"
)

# Kept well above the ids real accounts use (observed in the low five digits), so
# a minted id is recognisable in a log and will not be mistaken for a
# vendor-assigned one.
USER_ID_MIN: Final = 100_000_000

# Deliberately below 2**31 even though the field is five bytes wide. Firmware
# almost certainly widens this field through a 32-bit int somewhere, and an
# overflow on a station that cannot be reflashed is the one mistake here that
# could not be undone from Home Assistant.
USER_ID_LIMIT: Final = 2_000_000_000


def make_open_id() -> str:
    """Return a random openId in the shape the vendor app produces."""
    body = "".join(
        secrets.choice(_OPEN_ID_ALPHABET) for _ in range(OPEN_ID_LEN - len(OPEN_ID_PREFIX))
    )
    return OPEN_ID_PREFIX + body


def make_user_id() -> int:
    """Return a random account id: fits the wire field, and cannot overflow int32."""
    return secrets.randbelow(USER_ID_LIMIT - USER_ID_MIN) + USER_ID_MIN


def minted_identity() -> tuple[str, int]:
    """Return a fresh ``(open_id, user_id)`` pair for a local claim."""
    return make_open_id(), make_user_id()


__all__ = [
    "OPEN_ID_LEN",
    "OPEN_ID_PREFIX",
    "USER_ID_LIMIT",
    "USER_ID_MIN",
    "make_open_id",
    "make_user_id",
    "minted_identity",
]

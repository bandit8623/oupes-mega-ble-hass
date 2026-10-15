"""Connector-type claims about the DC inputs must say where the knowledge came from.

Nothing in the BLE stream names a connector.  The only reason the docs may say the two
packed halves are the station's dual XT60 PV inputs is that the owner of the tested unit
looked at the case.  Write that as plain fact and the next reader assumes the wire said
so, which is how the firmware-version claim and the per-device-key claim both started.

Deliberately narrow: it watches `xt60`, because that is the unverifiable input-side claim.
XT90 / Anderson appear throughout the codebase as *output* port groups whose bit semantics
are read straight off the device, so they need no attribution and this file must not start
flagging them.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCAN = [
    "README.md",
    "custom_components/oupes_mega_ble/README.md",
    "docs/GUARDIAN-WP-BLE.md",
    "custom_components/oupes_mega_ble/protocol.py",
    "custom_components/oupes_mega_ble/sensor.py",
]

ATTRIBUTION = (
    "owner",
    "not measured",
    "unverified",
    "has seen",
)


def _lines():
    """Yield (rel, lineno, line, window); window is `line` plus the two above it.

    Proximity for the attribution, not for the trigger: a dict of shipped strings needs one
    attribution over the block, and demanding it on every entry invites someone to satisfy
    the test with junk comments. Two lines each way is close enough that deleting or moving
    the attribution breaks it, and prose gets to put the caveat after the claim instead of
    being twisted into knots to put it before. The trigger stays the line itself, or every
    closing brace under an XT60 dict becomes an "offender".
    """
    for rel in SCAN:
        path = ROOT / rel
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for n, line in enumerate(lines, start=1):
            yield rel, n, line, "\n".join(lines[max(0, n - 3) : n + 2])


def test_xt60_lines_are_attributed():
    offenders = [
        f"{rel}:{n}: {line.strip()[:100]}"
        for rel, n, line, window in _lines()
        if re.search(r"xt60", line, re.I)
        and not any(word in window.lower() for word in ATTRIBUTION)
    ]
    assert not offenders, (
        "XT60 stated without provenance. The wire never names a connector, so the "
        "sentence has to say a human looked at the case:\n" + "\n".join(offenders)
    )


def test_the_claim_actually_exists():
    """If someone deletes the XT60 notes entirely, the guard above goes quiet by accident."""
    hits = [line for _, _, line, _ in _lines() if re.search(r"xt60", line, re.I)]
    assert hits, "no XT60 mention found anywhere - did the DC input docs get rewritten?"


def test_does_not_flag_output_connectors():
    """XT90 / Anderson are output-port groups read off the device bitfield.  No attribution
    needed, and a guard that cries wolf here gets ignored, which is worse than no guard."""
    outputs = [
        f"{rel}:{n}"
        for rel, n, line, window in _lines()
        if re.search(r"xt90|anderson", line, re.I)
        and not any(word in window.lower() for word in ATTRIBUTION)
    ]
    assert outputs, (
        "expected un-attributed XT90/Anderson mentions to exist and stay untouched; "
        "if this fails, the guard's scope has drifted"
    )


def test_attribution_vocabulary_is_not_hollow():
    """"verified" is not an attribution.  Naming the source is."""
    assert "verified" not in ATTRIBUTION
    assert "confirmed" not in ATTRIBUTION

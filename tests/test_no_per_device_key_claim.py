"""No shipped text may claim the device key is unique to one device.

Three places asserted it, in slightly different words:

    "10-character hex key unique to your device (e.g. bd236b1695)"   (field help, twice)
    "Keys are per-device: a key that works on one unit will not work on another"  (README)
    "the device doesn't enforce this derivation - any 10-character hex string works
     as a key"                                                        (README)

Two of those are the same mistake and the third is the mistake turned inside out. On a
Guardian / D5 V2 station the key is md5(userId)[:10] - verified against the live entry,
which stores a 5-digit user ID and the 10-character hex key its MD5 prefix produces - so
every station on an account shares one key. Meanwhile the station does check the value:
saving a wrong user ID re-derives the key and the station drops the link within seconds,
which is the opposite of "any hex string works".

Why the wording matters and is not pedantry: "unique to your device" tells a reader the
key cannot be known, so they hunt for a way to capture it - adb logcat, a rooted phone, a
BLE PCAP - for a value that is one command away. "Any hex string works" tells them a wrong
key is harmless, when a wrong key is exactly what kills the connection.

Scope note: code comments are not scanned. This guard defends people who act on what they
read in the UI or the docs; internal comments are corrected as a matter of taste, not
enforcement.
"""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent

FILES = [
    "custom_components/oupes_mega_ble/strings.json",
    "custom_components/oupes_mega_ble/translations/en.json",
    "README.md",
    "custom_components/oupes_mega_ble/README.md",
    "docs/GUARDIAN-WP-BLE.md",
]

FORBIDDEN = re.compile(
    r"(?i)"
    r"unique to (?:your|the) device"          # the field help, verbatim
    r"|unique per device"
    r"|keys? are per-device"
    r"|works on one unit will not work on another"
    r"|any 10-character hex\s+string works as a key"
)

# What the corrected text is allowed to say, and must keep saying. The negated form is the
# whole point of the fix, so a guard that flagged it would be worse than no guard.
ALLOWED = (
    "not unique to one device",
    "not unique to a device",
)


def _offenders(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    found = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for match in FORBIDDEN.finditer(line):
            # A negation in the same line turns the claim into its correction.
            if any(word in line.lower() for word in ALLOWED):
                continue
            found.append(f"{path}:{lineno}: {line.strip()[:110]}")
    return found


def test_no_text_claims_the_key_is_per_device():
    problems = [off for path in FILES for off in _offenders(path)]
    assert not problems, (
        "the WP key is md5(userId)[:10] and shared by every station on the account, so "
        "text may not call it per-device or unique to a device:\n" + "\n".join(problems)
    )


def test_the_correction_is_still_there():
    """The fix is required, not merely permitted: readers must be told the truth plainly."""
    help_texts = []
    for rel in ("custom_components/oupes_mega_ble/strings.json",):
        data = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        for section in ("config", "options"):
            dd = data[section]["step"]
            for step in dd.values():
                for text in (step.get("data_description") or {}).values():
                    help_texts.append(text)
    joined = " ".join(help_texts).lower()
    assert "not unique to one device" in joined, (
        "the device_key field help should say the key is shared across the account, not "
        "unique to a device"
    )


def test_guard_detects_a_planted_claim_in_ui_text():
    """Proves this guard can fail on shipped strings, so a green run means something."""
    rel = "custom_components/oupes_mega_ble/strings.json"
    target = ROOT / rel
    original = target.read_text(encoding="utf-8")
    planted = original.replace(
        '"device_key": "Device Key"',
        '"device_key": "Device Key (unique to your device)"',
        1,
    )
    assert planted != original, "could not plant a violation - strings.json changed shape"
    try:
        target.write_text(planted, encoding="utf-8", newline="\n")
        try:
            test_no_text_claims_the_key_is_per_device()
        except AssertionError:
            return
        raise AssertionError("guard accepted a planted 'unique to your device' claim")
    finally:
        target.write_text(original, encoding="utf-8", newline="\n")


def test_guard_detects_a_planted_claim_in_docs():
    """Same proof for the documentation half of the scan."""
    rel = "custom_components/oupes_mega_ble/README.md"
    target = ROOT / rel
    original = target.read_text(encoding="utf-8")
    planted = original.replace(
        "### How the key is derived (Cleanergy app convention)",
        "Keys are per-device: a key that works on one unit will not work on another.\n\n"
        "### How the key is derived (Cleanergy app convention)",
        1,
    )
    assert planted != original, "could not plant a violation - README changed shape"
    try:
        target.write_text(planted, encoding="utf-8", newline="\n")
        try:
            test_no_text_claims_the_key_is_per_device()
        except AssertionError:
            return
        raise AssertionError("guard accepted a planted 'Keys are per-device' claim")
    finally:
        target.write_text(original, encoding="utf-8", newline="\n")


def test_guard_does_not_cry_wolf_on_the_correction():
    """The negated wording must pass, or the guard would block its own fix."""
    clean = (
        "so every station on your account shares the same key - it is not unique to one "
        "device. Settings entities are configurable per device.\n"
    )
    target = ROOT / "docs/GUARDIAN-WP-BLE.md"
    original = target.read_text(encoding="utf-8")
    try:
        target.write_text(original + "\n" + clean, encoding="utf-8", newline="\n")
        test_no_text_claims_the_key_is_per_device()
    finally:
        target.write_text(original, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    import sys

    failed = False
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as exc:
                failed = True
                print(f"FAIL  {name}\n{exc}")
    sys.exit(1 if failed else 0)

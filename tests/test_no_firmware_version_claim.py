"""No doc may quote a firmware number as if it identified this station's build.

The guide used to open with "one Guardian 6000 V2 (firmware 1.2.0)" and then scope several
claims to that version. The number came from one place - the vendor cloud record, field
`firmware_version`, for the same MAC as the live entry, checked against
`C0:5D:89:3E:B3:72`. The Cleanergy app displays `0.0.4` for that same station, and the
vendor does not bump the string on every over-the-air update (reported by the owner of the
unit, who has taken updates). So the two vendor surfaces disagree and neither names a
build.

That makes a quoted version worse than useless in a scope statement: a reader who checks
their app, sees something that does not match, and concludes "not my firmware, skip this
integration" has been turned away by a number that does not mean what the sentence used it
for.

Hence: say the model, the BLE name, the product id, or the behaviour. If a version has to
be mentioned at all, mention that there are two of them and where each came from - which
is the only phrasing this guard permits, and it never puts the digits right after the word
"firmware".

Excluded on purpose: debug_info/ (upstream's own capture data for other people's devices,
where a firmware field is a fact about that capture, not a scope claim of ours) and
CHANGELOG.md (historical record; see the reasoning in test_terminology.py).
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent

PATTERNS = [ROOT / "README.md", ROOT / "custom_components" / "oupes_mega_ble" / "README.md"]
PATTERNS += sorted((ROOT / "docs").glob("*.md"))
PATTERNS += sorted((ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml"))

# "firmware 1.2.0", "on firmware 2.0", "running firmware 1.2.0".
# Deliberately does NOT match `firmware_version": "1.2.0"` (a quoted field, no space) or
# "the firmware version the app shows" (no digits), both of which are correct sentences.
CLAIM = re.compile(r"(?i)\bfirmware\s+\d+(?:\.\d+)+")


def _files():
    for path in PATTERNS:
        if path.exists():
            yield path


def test_no_doc_quotes_a_firmware_number_as_a_label():
    problems = []
    for path in _files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if CLAIM.search(line):
                problems.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()[:110]}")
    assert not problems, (
        "the vendor reports two different firmware strings for the same station and does "
        "not bump them reliably, so scope claims must use model / BLE name / product id / "
        "behaviour instead:\n" + "\n".join(problems)
    )


def test_guard_detects_a_planted_version_claim():
    """Proves this guard can fail, so a green run means something."""
    target = ROOT / "docs" / "GUARDIAN-WP-BLE.md"
    original = target.read_text(encoding="utf-8")
    planted = original.replace(
        "## 12. How much of this is actually known",
        "Tested on firmware 1.2.0 and known good.\n\n## 12. How much of this is actually known",
        1,
    )
    assert planted != original, "could not plant a violation - guide changed shape"
    try:
        target.write_text(planted, encoding="utf-8", newline="\n")
        try:
            test_no_doc_quotes_a_firmware_number_as_a_label()
        except AssertionError:
            return
        raise AssertionError("guard accepted a planted 'firmware 1.2.0' claim")
    finally:
        target.write_text(original, encoding="utf-8", newline="\n")


def test_guard_lets_the_honest_version_sentence_through():
    """The correction names both strings; the guard must not force it back out."""
    honest = (
        "\nThe app displays `0.0.4` while the cloud record carries "
        '`"firmware_version": "1.2.0"`; the firmware version the app shows is not a '
        "build label.\n"
    )
    target = ROOT / "docs" / "GUARDIAN-WP-BLE.md"
    original = target.read_text(encoding="utf-8")
    try:
        target.write_text(original + honest, encoding="utf-8", newline="\n")
        test_no_doc_quotes_a_firmware_number_as_a_label()
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

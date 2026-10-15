"""No shipped string may send a user to a screen that does not exist.

Two error strings used to say the Cleanergy app shows the account's numeric user ID -
one claimed an "account screen", the other the "device's settings screen". Neither
screen exists. The app never displays this number, which is the whole reason the
integration derives the key itself, so anyone following that advice would sit in the
app looking for the value that Home Assistant already has.

The rule is broader than that one pair of strings, because UI text accretes these
claims easily: never name a place to look unless it has been checked. Anything of the
form "the app shows X" or "X screen" is rejected here.
"""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
STRINGS = ROOT / "custom_components" / "oupes_mega_ble" / "strings.json"
EN = ROOT / "custom_components" / "oupes_mega_ble" / "translations" / "en.json"

# "the app shows it", "the vendor app displays", "the account screen", "settings screen",
# "device page" - all of them are pointers at places we have not verified.
PHANTOM = re.compile(
    r"(?i)(?:app|page|screen)\s+(?:shows|displays|will show|contains it)"
    r"|(?:account|settings|device)\s+screen"
    r"|device\s+page"
    r"|\bthe app\b[^.]{0,40}\b(shows|display|displayed)\b"
)


def _strings(path):
    data = json.loads(path.read_text(encoding="utf-8"))

    def walk(node, path_=""):
        if isinstance(node, dict):
            for k, v in node.items():
                yield from walk(v, f"{path_}.{k}")
        elif isinstance(node, str):
            yield path_, node

    yield from walk(data)


def test_no_shipped_string_points_at_a_screen_nobody_checked():
    problems = [
        f"{path.name}{key}: {text}"
        for path in (STRINGS, EN)
        for key, text in _strings(path)
        if PHANTOM.search(text)
    ]
    assert not problems, (
        "shipped UI text names a place to look that has not been verified; "
        "say what actually works instead:\n" + "\n".join(problems)
    )


def test_guard_detects_a_planted_claim():
    """Proves this guard can fail, so a green run means something."""
    original = STRINGS.read_text(encoding="utf-8")
    planted = original.replace(
        '"invalid_user_id": "',
        '"invalid_user_id": "The Cleanergy app shows it on the account screen. ',
        1,
    )
    assert planted != original, "could not plant a violation - strings.json changed shape"
    try:
        STRINGS.write_text(planted, encoding="utf-8", newline="\n")
        try:
            test_no_shipped_string_points_at_a_screen_nobody_checked()
        except AssertionError:
            return
        raise AssertionError("guard accepted a planted 'the app shows it' claim")
    finally:
        STRINGS.write_text(original, encoding="utf-8", newline="\n")


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

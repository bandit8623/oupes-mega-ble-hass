"""The user-facing name for the pairing value is "user ID", not "account number".

Rationale: these are account *names* (email addresses) and numeric *user IDs*. There is
no such thing as an account number, and shipping that phrase invents a concept readers
then look for in the Cleanergy app without finding it.

Two shipped selector labels still contain the phrase, because renaming them changes the
UI and belongs in a release with its own tests:

    "Use my Cleanergy account number"   (config flow, pairing-method selector)
    "Account number"                    (options flow field label)

Until that release, those exact strings may appear in documentation, but only inside a
Markdown bold span - i.e. only where the text is quoting the control a reader will see.
Everywhere else the phrase is banned, in code comments as well as prose.

When 1.4.4 renames the controls, tighten this test: delete ALLOWED_LABELS and let the
phrase be banned outright.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

BANNED = re.compile(r"account\s+number", re.IGNORECASE)

# Verbatim control labels as shipped in 1.4.3 (config_flow.py methods dict, strings.json).
# Keep in sync with strings.json; test_labels_still_match_code below fails if they drift.
ALLOWED_LABELS = (
    "Use my Cleanergy account number",
    "Account number",
)

# Only these label strings are permitted, and only when bolded.
BOLD = re.compile(r"\*\*([^*]+)\*\*")

DOCS = [
    "README.md",
    "custom_components/oupes_mega_ble/README.md",
    "docs/GUARDIAN-WP-BLE.md",
]


def _quoted_spans(line: str):
    """Character ranges covered by **bold** spans, i.e. verbatim UI quotes."""
    return [(m.start(), m.end()) for m in BOLD.finditer(line)]


def _bold_spans(text: str):
    """Bold spans, scoped per paragraph and ignoring fenced code.

    Pairing the markers across the whole document is wrong: Markdown scopes bold to a
    paragraph, so one unbalanced ** early in a file would shift every later pairing and
    make the checker mislabel correct text - which it did. Code fences are blanked to
    length so the offsets still line up with the original text.
    """
    flat = re.sub(r"```.*?```", lambda m: " " * len(m.group(0)), text, flags=re.S)
    spans = []
    pos = 0
    for chunk in re.split(r"(\n[ \t]*\n)", flat):
        if chunk.startswith("\n"):
            pos += len(chunk)
            continue
        for m in re.finditer(r"\*\*([^*]+?)\*\*", chunk):
            spans.append((pos + m.start(), pos + m.end(), m.group(1)))
        pos += len(chunk)
    return spans


def _violations(path: pathlib.Path):
    """Scan the whole document, not line by line.

    Prose in these files is hard-wrapped at ~79 columns, so "account\nnumber" is common.
    A line-based scan misses every wrapped occurrence, which is how the first version of
    this guard silently passed a violation it had been written to catch.
    """
    text = path.read_text(encoding="utf-8")
    spans = _bold_spans(text)
    out = []
    for match in BANNED.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        inside = [
            (s, e, body)
            for s, e, body in spans
            if s <= match.start() and match.end() <= e
        ]
        snippet = " ".join(text.splitlines()[line - 1 : line]).strip()[:100]
        if not inside:
            out.append((line, "unquoted prose", snippet))
            continue
        quoted = " ".join(inside[0][2].split()).rstrip(" .:;,")
        # Exact match only. "Write down the account number" is not a control label,
        # and a substring test would let any bolded prose past this guard.
        if quoted.lower() not in {label.lower() for label in ALLOWED_LABELS}:
            out.append((line, "bolded but not a shipped label", snippet))
    return out


def test_docs_use_user_id_not_account_number():
    problems = []
    for rel in DOCS:
        p = ROOT / rel
        assert p.exists(), f"expected documentation file {rel} to exist"
        for n, why, text in _violations(p):
            problems.append(f"{rel}:{n} [{why}]: {text}")
    assert not problems, "use 'user ID' in prose; the phrase 'account number' may only " \
        "appear inside **bold** quotes of a shipped control label:\n" + "\n".join(problems)


def test_guard_detects_a_planted_violation():
    """Proves this guard can fail.

    Without this, an edit that broke the rule - or broke the checker - would still let
    the suite pass, and a green result would mean nothing. Three planted defects, one
    per way the rule can be evaded: plain prose, a bolded phrase that merely contains
    the words, and a bolded phrase naming a control the code no longer ships.
    """
    src = (ROOT / DOCS[0]).read_text(encoding="utf-8")
    doc = ROOT / DOCS[0]
    try:
        for planted, why in [
            ("\nThe account number is printed on the label.\n", "plain prose"),
            ("\nWrapped prose escapes a line-based scanner: the account\nnumber is here.\n",
             "phrase split across a line break"),
            ("\n**Write down the account number**\n", "bolded phrase that is not a label"),
            ("\n**Legacy Account Number field**\n", "bolded non-shipped label"),
        ]:
            doc.write_text(src + planted, encoding="utf-8", newline="\n")
            try:
                test_docs_use_user_id_not_account_number()
            except AssertionError:
                continue
            raise AssertionError(f"guard accepted {why}: {planted!r}")
    finally:
        doc.write_text(src, encoding="utf-8", newline="\n")


def test_guard_does_not_cry_wolf():
    """A guard that reports clean text as dirty gets switched off, so test the other way too.

    An unbalanced ** in an earlier paragraph must not shift the pairing of a correct
    label quote in a later one, and a label quote split over a line wrap is still a
    label quote. Both were real false positives in earlier revisions of this file.
    """
    src = (ROOT / DOCS[0]).read_text(encoding="utf-8")
    doc = ROOT / DOCS[0]
    clean = (
        src
        + "\n\nAn intentionally unbalanced bold ** marker here.\n\n"
        + "Pick **Fetch key from Cleanergy cloud account** or\n**Use my Cleanergy\naccount number**, which are controls.\n"
    )
    try:
        doc.write_text(clean, encoding="utf-8", newline="\n")
        test_docs_use_user_id_not_account_number()
    except AssertionError as exc:
        raise AssertionError(f"guard reported clean text as a violation:\n{exc}")
    finally:
        doc.write_text(src, encoding="utf-8", newline="\n")


def test_allowed_labels_are_still_what_the_code_ships():
    """The exemption list must match reality, or it becomes a way to hide stale text."""
    flow = (ROOT / "custom_components/oupes_mega_ble/config_flow.py").read_text(encoding="utf-8")
    strings = (ROOT / "custom_components/oupes_mega_ble/strings.json").read_text(encoding="utf-8")
    for label in ALLOWED_LABELS:
        assert label in flow or label in strings, (
            f"{label!r} is exempted by this test but no longer appears in the code; "
            "the control was renamed - remove it from ALLOWED_LABELS and ban the phrase"
        )


if __name__ == "__main__":
    failed = False
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as exc:
                failed = True
                print(f"FAIL  {name}\n{exc}")
    if failed:
        sys.exit(1)
    print("\nall tests passed")

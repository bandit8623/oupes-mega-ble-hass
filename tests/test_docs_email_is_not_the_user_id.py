"""The README must keep the email / user ID distinction, in the section that matters.

Prompted on 2026-10-15 by a request to document that "the user ID is the email you use for
the Cleanergy app". That sentence is false, and the repository is full of proof:

* `cloud_identity.coerce_user_id()` returns `int | None` and rejects non-numeric input;
* `protocol.derive_device_key(user_id: int)` is `md5(str(userId))[:10]` — an MD5 over a
  *number*, so an email address derives a key the station refuses;
* the user ID form refuses anything that is not a number, so the README could not send
  someone to type an address there even if it wanted to;
* what IS the email is the *login*: `strings.json` describes `cloud_email` as "The email
  address you use to log in to the Cleanergy app."

The real problem behind the request is that the two values are never defined side by side,
so a reader fills the wrong one into the wrong field. The fix is the definitions table, and
the guard is this file: the distinction must survive the next edit, and the specific wrong
sentence must fail the check.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"

# How wide a window counts as "said in the same breath".
WINDOW = 300

# Sentences that assert the two values are the same thing. If one of these ever lands in
# the README, the document is wrong no matter how good the rest of it is.
EQUATIONS = [
    r"user\s+id\s+is\s+the\s+email",
    r"user\s+id\s*=\s*email",
    r"account\s+number\s+is\s+the\s+email",
    r"email\s+address\s+is\s+the\s+user\s+id",
]

NUMERIC = r"numeric|number,|five digits|decimal"
DENIAL = r"not\s+your\s+email|not\s+the\s+email|is\s+not\s+an\s+email"
EMAIL_IS_LOGIN = r"log\s+in|sign\s+in|login"


def guardian_section(text: str) -> str:
    """The Guardian / D5 V2 subsection of the Quick Start, where a stuck reader lands."""
    match = re.search(r"^### Guardian / D5 V2 .*$", text, re.M)
    if not match:
        return ""
    rest = text[match.end():]
    nxt = re.search(r"^### ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def _near(text: str, needle_re: str, context_re: str) -> bool:
    """True when some match of needle_re has context_re within WINDOW characters."""
    for match in re.finditer(needle_re, text, re.I):
        window = text[max(0, match.start() - WINDOW): match.end() + WINDOW]
        if re.search(context_re, window, re.I):
            return True
    return False


def identity_definition_problem(section: str) -> str | None:
    """The section must define both values and deny that they are the same.

    Markdown emphasis is stripped before matching: the README writes **not** your email, and a
    checker that only matches the unemphasised spelling would fail correct prose and pass
    sloppier prose, which is the worst possible trade.
    """
    if not section.strip():
        return "no Guardian subsection to check"

    section = section.replace("*", "")

    for pattern in EQUATIONS:
        if re.search(pattern, section, re.I):
            return (
                f"the README equates the two values ({pattern!r}). The user ID is a number and "
                "the key is md5 of that number; the email only logs in. Publishing the "
                "equation sends people to type an address into a numeric field."
            )

    if not _near(section, r"user\s+id", NUMERIC):
        return (
            "the README never says the user ID is numeric. That property is the whole reason "
            "the field rejects an email address, so it has to be written down."
        )

    if not _near(section, r"user\s+id", DENIAL):
        return (
            "the README never says the user ID is NOT the email address. Someone who has only "
            "the app in front of them has an email and nothing else; that is the assumption to "
            "correct explicitly, not by omission."
        )

    if not _near(section, r"email", EMAIL_IS_LOGIN):
        return "the README never says the email is what you log in to the app with"

    return None


# ---------------------------------------------------------------------------
# The real document.
# ---------------------------------------------------------------------------


def test_guardian_section_defines_both_values():
    problem = identity_definition_problem(guardian_section(README.read_text(encoding="utf-8")))
    assert problem is None, problem


def test_the_repository_itself_says_the_user_id_is_a_number():
    """Guard the guard: if the code ever starts accepting an email, this test must break."""
    src = (ROOT / "custom_components" / "oupes_mega_ble" / "cloud_identity.py").read_text(encoding="utf-8")
    assert "def coerce_user_id(raw: Any) -> int | None" in src, (
        "coerce_user_id no longer returns int | None; if the user ID can hold an email, the "
        "README wording and every test here need rewriting, not patching"
    )
    proto = (ROOT / "custom_components" / "oupes_mega_ble" / "protocol.py").read_text(encoding="utf-8")
    assert "def derive_device_key(user_id: int) -> str" in proto, (
        "derive_device_key no longer takes an int — re-check whether md5 of an email could "
        "now be a valid key before trusting the README's account of the derivation"
    )


# ---------------------------------------------------------------------------
# Sabotage, against invented text only.
# ---------------------------------------------------------------------------


GOOD = """### Guardian / D5 V2 (`WP`) — needs the user ID, once

The **Email address** is what you log in to the Cleanergy app with. The **User ID** is a
numeric id the vendor stores — five digits on the account measured here. The user ID is a
number, **not** your email address, and the field refuses anything that is not a number.
"""


def test_checker_rejects_the_exact_wrong_sentence():
    bad = GOOD + "\nThe user ID is the email you use to log in to the Cleanergy app.\n"
    problem = identity_definition_problem(bad)
    assert problem and "equates the two values" in problem, problem


def test_checker_rejects_the_banned_old_term_equating_them():
    bad = GOOD + "\nYour account number is the email address.\n"
    assert "equates the two values" in identity_definition_problem(bad)


def test_checker_rejects_a_section_that_never_calls_it_a_number():
    bad = (
        "### Guardian / D5 V2 (`WP`) — needs the user ID, once\n\n"
        "Enter the user ID from the app. It is not your email address, and you log in with "
        "the email.\n"
    )
    assert "never says the user ID is numeric" in identity_definition_problem(bad)


def test_checker_rejects_a_definition_that_omits_the_denial():
    bad = (
        "### Guardian / D5 V2 (`WP`) — needs the user ID, once\n\n"
        "The user ID is a numeric id; you log in to the app with your email address.\n"
    )
    assert "is NOT the email address" in identity_definition_problem(bad)


def test_checker_rejects_a_section_that_never_says_what_the_email_is_for():
    bad = (
        "### Guardian / D5 V2 (`WP`) — needs the user ID, once\n\n"
        "The user ID is a numeric id and is not your email address.\n"
    )
    assert "what you log in to the app with" in identity_definition_problem(bad)


def test_checker_accepts_the_reference_wording():
    assert identity_definition_problem(GOOD) is None


def test_missing_section_is_reported_not_silently_passed():
    assert "no Guardian subsection" in identity_definition_problem("")


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
    sys.exit(1 if failed else 0)

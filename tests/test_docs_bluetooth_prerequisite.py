"""The README must state the Bluetooth prerequisite where a newcomer will hit it.

Found by hand on 2026-10-15, while writing install notes for someone setting up for the
first time. Two defects in `## Installation`, none of them visible to a reviewer reading
for prose quality:

1. The Bluetooth requirement existed only in the feature list ("just a Bluetooth adapter on
   your HA server (or an ESPHome BLE proxy)") and in the WiFi section. A first-time reader
   cannot satisfy a requirement from a bullet about what the integration does, and this
   integration has no non-Bluetooth path at all: no radio means no discovery card and no
   address to type, so it is the one prerequisite worth a heading of its own.
2. The install steps told a Guardian owner to pick **Use my Cleanergy user ID** and "enter
   the user ID the app paired the station with" — on a first install there is no such
   screen. The app never displays the user ID (verified 2026-10-15, and the flow's own step
   description says so). The instruction was unusable, and the correct route was already
   documented 60 lines away in the Quick Start, which is how it survived review.

Like `test_docs_numbers_match_code.py`, the checkers take text, so the sabotage cases
below run against invented strings rather than mutating the repository.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
COMPONENT = ROOT / "custom_components" / "oupes_mega_ble"
CONFIG_FLOW = COMPONENT / "config_flow.py"

# How close a caveat about the user ID has to sit to be read with it (characters).
CAVEAT_WINDOW = 400


def installation_section(text: str) -> str:
    """The `## Installation` block, up to the next `## ` heading."""
    match = re.search(r"^## Installation\s*$", text, re.M)
    if not match:
        return ""
    rest = text[match.end():]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def bluetooth_prerequisite_problem(section: str) -> str | None:
    """Installation must name both ways Home Assistant can get Bluetooth."""
    if not section.strip():
        return "no '## Installation' section to check"

    low = section.lower()
    if "bluetooth" not in low:
        return "the Installation section never says Bluetooth is required"

    has_adapter = "adapter" in low or "radio" in low or "dongle" in low
    has_proxy = "proxy" in low or "esp32" in low
    if not (has_adapter and has_proxy):
        missing = [name for name, ok in (("an adapter", has_adapter), ("a proxy", has_proxy)) if not ok]
        return (
            "the Installation section mentions Bluetooth but not %s; a reader with no local "
            "adapter needs to know a proxy counts, and one with no proxy at all needs to know "
            "there is no network fallback" % " and ".join(missing)
        )
    return None


def first_install_identity_route_problem(section: str) -> str | None:
    """A first install must be sent to cloud sign-in, not to a number nobody can read."""
    if not section.strip():
        return "no '## Installation' section to check"

    mentions_cloud = "cleanergy cloud" in section.lower()
    mentions_uid = "cleanergy user id" in section.lower()

    if not mentions_cloud:
        return (
            "the Installation section does not name the cloud sign-in option, which on the "
            "Guardian family is the only route that can actually obtain the user ID"
        )

    if not mentions_uid:
        return None  # not mentioning the dead end at all is fine

    # If the user ID option IS mentioned, say why it is not the starting point.
    for match in re.finditer(r"cleanergy user id", section, re.I):
        window = section[max(0, match.start() - CAVEAT_WINDOW): match.end() + CAVEAT_WINDOW]
        if not re.search(r"does not display|not displayed|nowhere|never display", window, re.I):
            return (
                "the Installation section points at the user ID field without saying, within "
                "%d characters, that the Cleanergy app does not display that number. A first "
                "time reader will go looking for a screen that does not exist." % CAVEAT_WINDOW
            )
    return None


def pairing_method_labels() -> set[str]:
    """The exact strings the pairing-method dropdown renders.

    Read out of the `methods = {...}` dict in config_flow.py, because that mapping *is* the
    label — the flow uses `vol.In(methods)`, so what the user sees is what the dict holds.
    """
    src = CONFIG_FLOW.read_text(encoding="utf-8")
    match = re.search(r"methods\s*=\s*\{(.*?)\n\s*\}", src, re.S)
    assert match, "the pairing-method dropdown definition is missing from config_flow.py"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


# "pick **X**" / "choose **X**" / "do not start with **X**" — an instruction naming a control.
METHOD_INSTRUCTION = re.compile(r"(?:pick|choose|start with)\s+\*\*([^*]+)\*\*", re.I)


def method_label_problem(section: str) -> str | None:
    """Every pairing-method the Installation section tells you to pick must be verbatim.

    This one is personal: the first draft of the new Installation text said pick **Fetch Key
    from Cleanergy Cloud**, which is the *title of the screen you land on after* choosing, not
    the label in the dropdown ("Fetch key from Cleanergy cloud account"). Two different
    strings, one invented instruction, written by an assistant that had just read the right
    label 60 lines away. A screen title is not a menu item, and a reader scanning a dropdown
    for words that are not there concludes the docs are for another version.
    """
    labels = pairing_method_labels()
    for match in METHOD_INSTRUCTION.finditer(section):
        name = match.group(1).strip()
        if not re.search(r"cleanergy|device key", name, re.I):
            continue  # not one of ours (HA's own UI labels, etc.)
        if name in labels:
            continue
        return (
            f"the Installation section tells the reader to pick '{name}', which is not a label "
            f"this integration offers. The dropdown says: {sorted(labels)}. Quote the dropdown, "
            f"not the step title."
        )
    return None


def readme_problems() -> list[str]:
    text = README.read_text(encoding="utf-8")
    section = installation_section(text)
    out = []
    for checker in (
        bluetooth_prerequisite_problem,
        first_install_identity_route_problem,
        method_label_problem,
    ):
        problem = checker(section)
        if problem:
            out.append(problem)
    return out


# ---------------------------------------------------------------------------
# The real document.
# ---------------------------------------------------------------------------


def test_readme_installation_states_the_bluetooth_prerequisite():
    section = installation_section(README.read_text(encoding="utf-8"))
    problem = bluetooth_prerequisite_problem(section)
    assert problem is None, problem


def test_readme_installation_does_not_dead_end_a_first_time_guardian_owner():
    section = installation_section(README.read_text(encoding="utf-8"))
    problem = first_install_identity_route_problem(section)
    assert problem is None, problem


def test_readme_quotes_the_dropdown_labels_not_the_step_titles():
    section = installation_section(README.read_text(encoding="utf-8"))
    problem = method_label_problem(section)
    assert problem is None, problem


def test_the_four_method_labels_are_still_there_to_be_quoted():
    labels = pairing_method_labels()
    assert len(labels) == 4, labels
    assert any("user id" in l.lower() for l in labels), labels
    assert any("cloud" in l.lower() for l in labels), labels


# ---------------------------------------------------------------------------
# Sabotage: prove the checkers can fail. Invented text, repository untouched.
# ---------------------------------------------------------------------------


def test_checker_fails_when_bluetooth_is_not_mentioned_at_all():
    section = "### HACS\n\n1. Add the custom repository.\n2. Restart.\n"
    assert "never says Bluetooth is required" in bluetooth_prerequisite_problem(section)


def test_checker_fails_when_only_an_adapter_is_offered():
    section = "You need a Bluetooth adapter on the HA host. Pick **Fetch Key from Cleanergy Cloud**.\n"
    problem = bluetooth_prerequisite_problem(section)
    assert problem and "a proxy" in problem, problem


def test_checker_fails_when_only_a_proxy_is_offered():
    section = "You need an ESPHome Bluetooth proxy (an ESP32). Pick **Fetch Key from Cleanergy Cloud**.\n"
    problem = bluetooth_prerequisite_problem(section)
    assert problem and "an adapter" in problem, problem


def test_checker_fails_when_the_user_id_field_is_named_without_the_caveat():
    section = (
        "You need a Bluetooth adapter or an ESPHome Bluetooth proxy (ESP32).\n"
        "Pick **Fetch key from Cleanergy cloud account**, or choose **Use my Cleanergy user "
        "ID** and enter the number from the app.\n"
    )
    problem = first_install_identity_route_problem(section)
    assert problem and "does not display that number" in problem, problem


def test_checker_passes_the_caveat_version_of_the_same_sentence():
    section = (
        "You need a Bluetooth adapter or an ESPHome Bluetooth proxy (ESP32).\n"
        "Pick **Fetch Key from Cleanergy Cloud**. Do not start with **Your Cleanergy User "
        "ID**: the Cleanergy app does not display that number on any screen.\n"
    )
    assert first_install_identity_route_problem(section) is None


def test_checker_fails_when_cloud_sign_in_is_never_named():
    section = (
        "You need a Bluetooth adapter or an ESPHome Bluetooth proxy (ESP32).\n"
        "Pick **Enter Existing Device Key**.\n"
    )
    assert (
        "does not name the cloud sign-in option"
        in first_install_identity_route_problem(section)
    )


def test_missing_installation_section_is_reported_not_silently_passed():
    assert "no '## Installation' section" in bluetooth_prerequisite_problem("")
    assert "no '## Installation' section" in first_install_identity_route_problem("")


def test_checker_fails_on_a_step_title_passed_off_as_a_menu_label():
    section = (
        "You need a Bluetooth adapter or an ESPHome Bluetooth proxy (ESP32).\n"
        "Pick **Fetch Key from Cleanergy Cloud** and sign in.\n"
    )
    problem = method_label_problem(section)
    assert problem and "not a label" in problem, problem


def test_checker_ignores_home_assistant_ui_labels_it_does_not_own():
    section = (
        "Open HACS and choose **Custom repositories**, then pick **Integration**.\n"
        "You need a Bluetooth adapter or an ESPHome Bluetooth proxy (ESP32).\n"
        "Then pick **Fetch key from Cleanergy cloud account**.\n"
    )
    assert method_label_problem(section) is None


if __name__ == "__main__":
    problems = readme_problems()
    failed = False
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as exc:
                failed = True
                print(f"FAIL  {name}\n{exc}")
    if problems:
        print("\nREADME problems found:")
        for p in problems:
            print(f"  - {p}")
    else:
        print("\nREADME: no problems found")
    sys.exit(1 if failed else 0)

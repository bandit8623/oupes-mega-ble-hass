"""Docs that quote a tunable's default must quote what const.py actually ships.

Found by hand once already: the component README told users entities hold their last
value "for up to 10 minutes" while const.py has STALE_TIMEOUT = 15 minutes, and the same
file said "default 15 minutes" 100 lines later. Two sentences, one file, one of them
wrong - which is the shape of bug a human reviewer skims past.

The checker takes text, so the sabotage cases below run against invented strings instead
of mutating the repository.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "oupes_mega_ble"
CONSTS = COMPONENT / "const.py"

# Only the user-facing docs: debug_info/README.md is a protocol notebook, and its
# "USB standby timeout 10 minutes" / "~5 s handshake polling" notes are device register
# documentation, not claims about this integration's defaults.
DOC_PATHS = [
    ROOT / "README.md",
    COMPONENT / "README.md",
    ROOT / "docs" / "GUARDIAN-WP-BLE.md",
]

# sentences about the station's own timers or the pairing handshake are not about ours
_EXCLUDE = re.compile(r"standby|handshake|dpid|probe|pairing|captive|mqtt", re.IGNORECASE)

# timedelta(minutes=15) / timedelta(seconds=30)
_INTERVALS = re.compile(
    r"^(?P<name>[A-Z0-9_]+)\s*=\s*timedelta\((?P<unit>minutes|seconds)=(?P<n>\d+)\)",
    re.MULTILINE,
)

# "stale timeout ... 15 minutes", "15 minutes by default", "hold ... 15 minutes"
_STALE = re.compile(r"(\d+)\s*min(ute)?s?\b", re.IGNORECASE)
# a sentence is *about* the stale timeout if it talks about data going stale or entities
# going unavailable; without this the guard flags every unrelated minute in the docs
_STALE_CONTEXT = re.compile(
    r"stale|unavailable|unreachable|hold|last known|last reading|timeout", re.IGNORECASE
)
# "every 30 seconds", "poll ... 30 s", "default: 30"
_POLL = re.compile(r"poll[^\n]{0,60}?(\d+)\s*(?:s|sec|seconds)\b", re.IGNORECASE)


def constants() -> dict[str, int]:
    """Interval constants from const.py, normalised to seconds."""
    text = CONSTS.read_text(encoding="utf-8")
    out = {}
    for m in _INTERVALS.finditer(text):
        n = int(m.group("n"))
        out[m.group("name")] = n * 60 if m.group("unit") == "minutes" else n
    if not out:
        raise AssertionError(f"no timedelta constants parsed out of {CONSTS.name}")
    return out


def check_docs(text_by_path: dict[str, str]) -> list[str]:
    """Return complaints; empty means every quoted default matches the code."""
    secs = constants()
    stale_s = secs.get("STALE_TIMEOUT")
    poll_s = secs.get("UPDATE_INTERVAL")
    problems = []
    for name, text in text_by_path.items():
        # join wrapped lines so a sentence split across three lines is still one sentence
        flat = re.sub(r"\s+", " ", text)
        for sentence in re.split(r"(?<=[.!?])\s+", flat):
            low = sentence.lower()
            if _EXCLUDE.search(sentence):
                continue
            if stale_s is not None and _STALE_CONTEXT.search(sentence):
                for m in _STALE.finditer(sentence):
                    if int(m.group(1)) * 60 != stale_s:
                        problems.append(
                            f"{name}: quotes a {m.group(1)}-minute figure where const.py "
                            f"sets STALE_TIMEOUT to {stale_s // 60}: {sentence[:110].strip()}"
                        )
            if poll_s is not None and "poll" in low and "minute" not in low:
                for m in _POLL.finditer(sentence):
                    if int(m.group(1)) != poll_s:
                        problems.append(
                            f"{name}: quotes a {m.group(1)}s poll interval, "
                            f"const.py says {poll_s}: {sentence[:110].strip()}"
                        )
    return problems


def test_the_constants_are_what_this_file_assumes():
    secs = constants()
    assert "STALE_TIMEOUT" in secs and "UPDATE_INTERVAL" in secs, (
        f"const.py renamed something (found {sorted(secs)}) - update this guard, "
        "do not delete it"
    )


def test_shipped_docs_quote_the_real_defaults():
    docs = {str(p.relative_to(ROOT)): p.read_text(encoding="utf-8") for p in DOC_PATHS}
    missing = [k for k in docs if not p_exists(ROOT / k)]
    assert not missing, f"this guard stopped finding its own inputs: {missing}"
    problems = check_docs(docs)
    assert not problems, "docs contradict const.py:\n" + "\n".join(problems)


def p_exists(rel: pathlib.Path) -> bool:
    return rel.exists()


# --- sabotage ---------------------------------------------------------------


def test_guard_notices_a_stale_number():
    planted = {"README.md": "Entities hold their last reading for up to 10 minutes. "}
    hits = check_docs(planted)
    assert hits, "wrote a 10-minute stale timeout against a 15-minute constant "
    "and the guard said nothing"

    # the same guard must stay quiet about the true number
    assert not check_docs({"README.md": "The stale timeout is 15 minutes by default. "})


def test_guard_notices_a_wrong_poll_interval():
    planted = {"README.md": "It polls every 45 seconds when not continuous. "}
    assert check_docs(planted), "planted a 45-second poll claim and the guard said nothing"
    assert not check_docs({"README.md": "It polls every 30 seconds. "})


def test_guard_ignores_device_timers_not_ours():
    """The station's own standby timeout is not the stale timeout."""
    assert not check_docs(
        {"x": "Set USB/Car standby timeout to 10 minutes (600 seconds). "}
    ), "the guard flagged the station's standby setting"
    assert not check_docs({"x": "Phase 2 - Handshake polling (~5 s). "}), (
        "the guard flagged the pairing handshake"
    )


def test_guard_ignores_unrelated_minutes():
    """'Retries for 3 minutes' is not a default; do not cry wolf on every number."""
    text = (
        "The first attempt takes 15 seconds. We waited 3 minutes and retried, "
        "then closed the app."
    )
    assert not check_docs({"README.md": text}), f"false positive: {text}"
    # a poll interval mentioned without the word "stale" is still checked,
    # and a minute figure with no stale/unavailable context is not
    assert not check_docs({"README.md": "The app syncs every 5 minutes. "})


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

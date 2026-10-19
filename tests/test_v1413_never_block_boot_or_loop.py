"""v1.4.13 guards: no blocking file I/O, never block HA boot on BLE.

Production incident 2026-10-18: a wedged BLE proxy made the config-entry
first refresh loop forever, Home Assistant bootstrap stalled ("Waiting for
integrations to complete setup"), and the whole dashboard was unreachable -
including the automations designed to alert on exactly that. Separately HA
2026 logged blocking file opens from our debug-CSV path inside the event
loop. These tests lock both fixes in.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
COMPONENT = REPO / "custom_components" / "oupes_mega_ble"


def _src(name: str) -> str:
    return (COMPONENT / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- coordinator

def test_debug_csv_never_opens_files_on_the_event_loop():
    """All debug-CSV file opens must live inside the executor helper.

    Every `open(` in coordinator.py must appear inside `_csv_append`'s
    `_write()` closure (the only part handed to async_add_executor_job).
    """
    src = _src("coordinator.py")
    opens = [m.start() for m in re.finditer(r"\.open\(", src)]
    helper = re.search(
        r"def _csv_append\(.*?(?=\n    (?:@staticmethod|async def |def ))",
        src,
        re.S,
    )
    assert helper, "_csv_append() helper is missing from coordinator.py"
    start, end = helper.span()
    outside = [pos for pos in opens if not (start <= pos < end)]
    assert not outside, (
        f"{len(outside)} file open(s) outside _csv_append - debug CSV I/O "
        "must run in the executor, not on the event loop"
    )


def test_constructor_does_not_touch_the_filesystem():
    """__init__ used to open() debug CSVs during config-entry setup."""
    src = _src("coordinator.py")
    init = re.search(r"def __init__\(\s*self.*?(?=\n    (?:@staticmethod|async def |def ))", src, re.S)
    assert init, "coordinator __init__ not found"
    body = init.group(0)
    assert ".open(" not in body, "coordinator __init__ opens files (blocks event loop)"
    assert "_init_debug_files" not in body, (
        "__init__ still calls _init_debug_files (blocking FS work during setup)"
    )


def test_csv_append_defers_header_and_appends_rows(tmp_path):
    """_csv_append writes the header lazily, then appends - executor-safe."""
    from custom_components.oupes_mega_ble.coordinator import OUPESMegaCoordinator

    calls: list = []

    class _Hass:
        def async_add_executor_job(self, fn, *args):
            calls.append(fn)
            fn(*args)  # run synchronously to observe the effect

    coord = OUPESMegaCoordinator.__new__(OUPESMegaCoordinator)  # skip __init__
    coord.hass = _Hass()

    path = tmp_path / "oupes_mega_ble_AABB_attrs.csv"
    coord._csv_append(path, [["2026-10-19 07:00:00", "RX", "cmd1", "0", "N"]])
    coord._csv_append(path, [["2026-10-19 07:00:05", "RX", "cmd1", "0", "Y"]])

    rows = list(csv.reader(path.open(encoding="utf-8")))
    assert rows[0] == OUPESMegaCoordinator._ATTR_CSV_HEADER, "header must be written once, lazily"
    assert len(rows) == 3
    assert all(r[1] == "RX" for r in rows[1:])
    assert len(calls) == 2


def test_csv_append_swallows_bad_paths(tmp_path):
    """Debug logging must never crash the BLE pipeline."""
    from custom_components.oupes_mega_ble.coordinator import OUPESMegaCoordinator

    class _Hass:
        def async_add_executor_job(self, fn, *args):
            fn(*args)

    coord = OUPESMegaCoordinator.__new__(OUPESMegaCoordinator)
    coord.hass = _Hass()
    coord._csv_append(None, [["x"]])  # None path: silent no-op
    coord._csv_append(tmp_path / "x.csv", [])  # empty rows: silent no-op
    # directory that cannot exist -> OSError inside the writer, swallowed
    bogus = tmp_path / "nope" / "sub" / "oupes_mega_ble_FF_attrs.csv"
    (tmp_path / "nope").write_text("not a dir")  # blocks mkdir/open
    coord._csv_append(bogus, [["row"]])  # must not raise


# --------------------------------------------------------------------- boot

def test_first_refresh_is_hard_capped():
    """Setup must never await the first BLE poll indefinitely."""
    src = _src("__init__.py")
    assert re.search(r"asyncio\.wait_for\(\s*coordinator\.async_config_entry_first_refresh\(\)", src), (
        "first refresh must be wrapped in asyncio.wait_for(...)"
    )
    assert "ConfigEntryNotReady" in src, "timeout must defer via ConfigEntryNotReady"
    assert "_FIRST_REFRESH_TIMEOUT" in src


def test_first_refresh_timeout_releases_ble():
    """On timeout the coordinator is shut down so no half-open link leaks."""
    src = _src("__init__.py")
    timeout_block = src[src.index("asyncio.TimeoutError"):]
    assert "async_shutdown" in timeout_block[:800], (
        "timeout path must call coordinator.async_shutdown() to release GATT"
    )


def test_cancelled_error_still_propagates():
    """The 2026-10-17 lesson: never convert CancelledError on the shutdown path."""
    src = _src("__init__.py")
    m = re.search(r"except asyncio\.CancelledError:(.*?)(?=\n    except)", src, re.S)
    assert m and re.search(r"^\s*raise\s*$", m.group(1), re.M), (
        "CancelledError must re-raise bare"
    )

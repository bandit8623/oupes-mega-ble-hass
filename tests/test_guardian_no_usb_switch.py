"""The Guardian must not ship a switch its firmware ignores.

Field test 2026-10-15, Guardian 6000 V2 (product 95haDY, owner-volunteered
voltmeter): two BLE enable-writes for the USB-group bit (bit2) left the station
state unchanged and the USB ports measured dead while the writes were in
flight.  The cigarette/12V group (bit1) was verified working the same night -
12.5 V on the socket when enabled, decaying to 0 on the off command.  The case
itself carries ONE physical DC button; bit1 mirrors that button, bit2 controls
nothing anyone can observe.

A switch the firmware ignores is worse than no switch: it teaches the owner
that HA lies.  These guards keep the phantom from creeping back, and keep the
other series (whose USB/Anderson behaviour was never tested) untouched.

switch.py imports homeassistant, which is not installed for the bare test run,
so everything is read from the AST - same trick as test_product_sensor_names.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWITCH = ROOT / "custom_components/oupes_mega_ble/switch.py"


def _tree() -> ast.Module:
    return ast.parse(SWITCH.read_text(encoding="utf-8"))


def _assign(tree, name):
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return node
    return None


def test_guardian_excluded_from_usb_switch():
    node = _assign(_tree(), "_SERIES_WITHOUT_USB_SWITCH")
    assert node is not None, (
        "_SERIES_WITHOUT_USB_SWITCH is gone. If Guardian's USB bit really became "
        "switchable, delete the field-test note in switch.py too - do not just "
        "drop the set and keep the claim."
    )
    assert "guardian" in ast.literal_eval(node.value)


def test_no_xt90_label_anywhere():
    src = SWITCH.read_text(encoding="utf-8")
    assert "XT90" not in src, (
        "The Guardian 6000 V2 has no XT90 OUTPUT port (it is an XT60 INPUT unit); "
        "the label was removed 2026-10-15 after the owner pointed at the actual case."
    )


def test_usb_names_and_dc_rename():
    tree = _tree()
    usb = ast.literal_eval(_assign(tree, "_USB_OUTPUT_NAMES").value)
    assert "guardian" not in usb, "guardian must have no USB display name while filtered out"
    dc = ast.literal_eval(_assign(tree, "_DC_OUTPUT_NAMES").value)
    assert dc["guardian"] == "DC Output", (
        "bit1 is the front-panel DC group on the V2; name it after the case, "
        "not after one socket of the group"
    )


def test_setup_filters_the_usb_switch():
    src = SWITCH.read_text(encoding="utf-8")
    assert 'desc.key == "usb_output_switch"' in src and "_SERIES_WITHOUT_USB_SWITCH" in src, (
        "the entities list comprehension must actually apply the exclusion set; "
        "a set nobody consults is decorative"
    )

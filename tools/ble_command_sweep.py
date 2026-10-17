#!/usr/bin/env python3
"""One-shot, HA-independent BLE command sweep for the Guardian 6000 V2.

Run INSIDE the HA container (bleak + BlueZ available there) with the HA
integration DISABLED so the station's single BLE slot is free:

    docker exec homeassistant python3 /config/.deploy_backups/sweep/ble_command_sweep.py

What it does
  1. Connects + authenticates exactly like the integration (config-net-info).
  2. Records every notification for a settle window (baseline).
  3. Sweeps unknown COMMAND bytes in query-frame shape:
        01 80 <cmd> 07 <known dpids...> pad crc8
  4. Sweeps Cmd2 (known-good command) over dpid 160..255  -- the range the
     earlier integration scan never asked about.
  5. Appends every notification raw (hex) to a log tagged with the probe
     that was in flight, then disconnects.

Read-only: writes ONLY query-shaped frames. Never sends Cmd3 setting writes.
"""
import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------- setup ---
ADDRESS = "C0:5D:89:3E:B3:72"
INTEGRATION_DIR = "/config/custom_components/oupes_mega_ble"
LOG_PATH = "/config/.deploy_backups/sweep/sweep_raw.txt"
ENTRY_FILE = "/config/.storage/core.config_entries"

def load_protocol():
    """Load protocol.py without executing the HA package __init__."""
    pkg_root = Path(INTEGRATION_DIR).parent          # custom_components/
    import types
    pkg = types.ModuleType("oupes_mega_ble")
    pkg.__path__ = [INTEGRATION_DIR]
    sys.modules["oupes_mega_ble"] = pkg
    spec = importlib.util.spec_from_file_location(
        "oupes_mega_ble.protocol", f"{INTEGRATION_DIR}/protocol.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["oupes_mega_ble.protocol"] = mod
    spec.loader.exec_module(mod)
    return mod

def load_identity():
    d = json.loads(Path(ENTRY_FILE).read_text())
    for e in d["data"]["entries"]:
        if e["domain"] == "oupes_mega_ble":
            opt = e["options"]
            return (
                opt.get("open_id", ""),
                int(opt.get("user_id", 0)),
                e["data"].get("device_key") or opt.get("device_key", ""),
            )
    raise SystemExit("oupes_mega_ble entry not found")

def probe_packet(proto, cmd_byte: int, dpids) -> bytes:
    """Query-shaped packet: 01 80 <cmd> <n> <dpids> ... pad, crc8."""
    pkt = bytearray(20)
    pkt[0] = 0x01
    pkt[1] = 0x80
    pkt[2] = cmd_byte & 0xFF
    ids = list(dpids)[:15]
    pkt[3] = len(ids)
    for i, d in enumerate(ids):
        pkt[4 + i] = d & 0xFF
    pkt[19] = proto._crc8(bytes(pkt[:19]))
    return bytes(pkt)

# --------------------------------------------------------------- sweep ---
async def main() -> None:
    from bleak import BleakClient

    proto = load_protocol()
    open_id, user_id, device_key = load_identity()
    if not user_id:
        raise SystemExit("user_id missing from entry options")

    log = open(LOG_PATH, "a", buffering=1)
    tag = {"t": "boot"}
    rx = []

    def on_notify(_, data: bytearray):
        rx.append(data)
        log.write(f"{time.strftime('%H:%M:%S')} [{tag['t']}] {data.hex(' ')}\n")

    init = proto.build_init_sequence(
        device_key=device_key or proto.derive_device_key(user_id),
        open_id=open_id,
        user_id=user_id,
    )

    client = BleakClient(ADDRESS, timeout=30)
    await client.connect()
    print("connected", flush=True)
    try:
        await asyncio.sleep(1.8)
        await client.start_notify(proto.NOTIFY_CHAR_UUID, on_notify)
        await asyncio.sleep(0.3)

        tag["t"] = "auth"
        for pkt in init:
            await client.write_gatt_char(proto.WRITE_CHAR_UUID, pkt, response=False)
            await asyncio.sleep(0.01)
        await asyncio.sleep(2.0)          # baseline telemetry burst

        known = [41, 45, 46, 47, 48, 49, 58, 63, 105][:7]
        # Pass 1: unknown command bytes in query-frame shape
        for cmd in list(range(0x01, 0x03)) + list(range(0x04, 0x20)) + [0x70, 0x71, 0xF0]:
            tag["t"] = f"cmd{cmd:02X}"
            await client.write_gatt_char(
                proto.WRITE_CHAR_UUID, probe_packet(proto, cmd, known), response=False
            )
            await asyncio.sleep(0.5)

        # Pass 2: known-good Cmd2, dpid 160..255 (never swept before)
        for start in range(160, 256, 7):
            batch = list(range(start, min(start + 7, 256)))
            tag["t"] = f"dpid{start}"
            await client.write_gatt_char(
                proto.WRITE_CHAR_UUID, probe_packet(proto, 0x02, batch), response=False
            )
            await asyncio.sleep(0.5)

        tag["t"] = "tail"
        await asyncio.sleep(2.0)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
    print(f"done: {len(rx)} notifications -> {LOG_PATH}", flush=True)

asyncio.run(main())

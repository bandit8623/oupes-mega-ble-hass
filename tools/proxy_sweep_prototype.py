#!/usr/bin/env python3
"""Proxy sweep prototype (seed for v1.4.12 self-heal).

Queries ESPHome bluetooth proxies for their allocated BLE connections and flags
a target device (default: the Guardian). Optionally requests a disconnect.

Usage:
  python3 proxy_sweep_prototype.py \
      --mac C0:5D:89:3E:B3:72 \
      --proxy 192.168.2.195:6053:noise:<psk-or-> \
      --proxy 192.168.2.196:6053:noise:<psk-or-> \
      [--release]

macOS note: run this from a machine that can reach the proxies (e.g. inside the
HA container). aioesphomeapi required.
"""
from __future__ import annotations

import argparse
import asyncio
import sys


def parse_proxy(spec: str) -> tuple[str, int, str, str]:
    host_port, kind, secret = spec.rsplit(":", 2)
    host, _, port = host_port.partition(":")
    return host, int(port or 6053), kind, "" if secret in ("-", "") else secret


async def sweep(host: str, port: int, kind: str, secret: str, mac: int, release: bool) -> dict:
    from aioesphomeapi import APIClient

    kwargs = {"client_info": "oupes-proxy-sweep"}
    if kind == "noise":
        kwargs["noise_psk"] = secret
    elif kind == "password":
        kwargs["password"] = secret
    cli = APIClient(host, port, **kwargs)
    out = {"host": host, "ok": False}
    try:
        await asyncio.wait_for(cli.connect(), 15)
        box: dict = {}

        def cb(free, limit, allocated):
            box.update(free=free, limit=limit, allocated=list(allocated or []))

        cli.subscribe_bluetooth_connections_free(cb)
        await asyncio.sleep(3)
        out.update(used=(box.get("limit", 0) or 0) - (box.get("free", 0) or 0),
                   allocated=[hex(a) for a in box.get("allocated", [])])
        out["holds_target"] = mac in box.get("allocated", [])
        if out["holds_target"] and release:
            try:
                await cli.bluetooth_device_disconnect(mac)
                out["release"] = "requested"
            except Exception as exc:  # timeouts are common; non-fatal, see docs
                out["release"] = f"no-ack ({type(exc).__name__})"
        out["ok"] = True
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            await cli.disconnect()
        except Exception:
            pass
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mac", default="C0:5D:89:3E:B3:72")
    ap.add_argument("--proxy", action="append", required=True,
                    help="host:port:noise|password:secret  (repeatable)")
    ap.add_argument("--release", action="store_true")
    a = ap.parse_args()

    mac = int(a.mac.replace(":", ""), 16)
    results = await asyncio.gather(*(sweep(*parse_proxy(p), mac, a.release) for p in a.proxy))
    culprit = False
    for r in results:
        print(r)
        culprit = culprit or r.get("holds_target", False)
    print("VERDICT:", "target is held by a proxy" if culprit else "no proxy holds the target")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

# Draft issue for home-assistant/core — paste at https://github.com/home-assistant/core/issues/new/choose

**Title:** `bluetooth`: peripherals already connected to a proxy are invisible to HA — an existing proxy-side link can never be reclaimed, leaving the device permanently unreachable until someone power-cycles a proxy or the peripheral

## The problem

> **Scope note:** the *confusing signature* seen here — "HA reports the device nowhere and its own proxies show free slots, while some other proxy is silently holding the connection" — requires **two or more bluetooth proxies that can both reach the peripheral** (proxy A holds the device; HA's integration waits on advertisements that A will never show it). A single-proxy install shares the underlying "proxy keeps the link across an HA restart" hazard, but there is no second radio that can hold the device out of sight, so the misleading 0-of-3 free-slot red herring cannot occur. (Single-proxy reproduction of the reclaim gap itself: untested by this reporter.)

Home Assistant's `bluetooth` integration discovers devices **only from live advertisements** and chooses a proxy per advertisement. Meanwhile, BLE peripherals are point-to-point: once linked to a proxy they **stop advertising**, and ESPHome `bluetooth_proxy` (by design) **keeps serving that link even after HA's API connection goes away** — e.g. across an HA restart.

Result: after an HA restart, a peripheral that is healthy and still linked to a proxy becomes **permanently invisible** to HA. HA never asks any proxy "what do you already have attached?", never reclaims or reuses that session, and any integration waiting for the device hangs forever (e.g. `ConfigEntry` stuck in first refresh). No log line is ever produced; it fails silently.

The information exists: `BluetoothConnectionsResponse.free` / the connections-free subscription reports the **allocated addresses** per proxy. HA already receives the list of devices a proxy is holding — it simply doesn't surface them as connectable or offer a reclaim path.

## Reproduction (deterministic)

Environment: HA Supervised 2026.10.2; two ESPHome ESP32-C5 `bluetooth_proxy` nodes (ESPHome 2026.7.1 and 2026.9.1, `noise_psk` enabled); any integration that connects to a specific peripheral via `bleak` over HA's Bluetooth backend.

1. Peripheral (BLE MAC `X`) advertises; HA connects via proxy A. Link healthy for hours.
2. HA restarts (`ha core restart`, graceful — the `homeassistant_stop` event fires).
3. Proxy A **keeps the BLE link alive** (documented proxy behavior).
4. Peripheral stops advertising (it is in a live connection with A).
5. HA's integration waits for advertisements of `X`; none ever arrive from any proxy; it never attempts `bluetooth_device_connect` via proxy A for the already-held session.
6. Device is dead to HA indefinitely. Recovery requires power-cycling proxy A or toggling the peripheral's radio — a physical act.

## Observed evidence (production capture)

```
proxy A (kitchen):  subscribe_bluetooth_connections_free → free=2 limit=3 allocated=[0xC05D893EB372]   # the peripheral IS here
proxy B (office):   free=3 limit=3 allocated=[]                                                        # HA integration waiting on this side
HA:                 no connection attempt logged, no timeout, no error for 20+ minutes
aioesphomeapi bluetooth_device_disconnect(X) against proxy A: TimeoutError
                    (no BluetoothDeviceConnectionResponse within 20 s; link remains allocated)
```

Secondary issue: the API-initiated **disconnect** against the holding proxy is also unanswered/times out, so even a deliberate reclaim attempt from a custom component can't reliably clear the stale session.

## Expected behavior

Either:
1. **Reclaim:** when a proxy reports an allocated connection for an address an integration is trying to reach, reuse the existing session (`bluetooth_device_connect` on an already-connected address should return the existing session) — or
2. **Release:** expose a supported "release peripheral" path that reliably lands (`bluetooth_device_disconnect` ack), and surface per-proxy allocated connections in `bluetooth` config/registry so integrations can act on them.

## Why current workarounds don't close it

- Per-proxy adapter selection isn't exposed to integration consumers — integrations can't pin `adapter=<proxy>`.
- A custom component *can* open its own `aioesphomeapi` connections to proxies and probe `subscribe_bluetooth_connections_free` (this is how the capture above was produced), but it needs each proxy's noise key, and the disconnect call it does have (`bluetooth_device_disconnect`) didn't ack — so a custom component cannot robustly self-heal this either.

## Suggested fix surface

- `homeassistant/components/bluetooth`: track `allocated` addresses per proxy; treat "device connected on proxy A" as a first-class known state (diagnostics + an event or registry entry).
- `bleak_retry_connector` / HA bleak backend: on connect, if a proxy reports the target address allocated, route the connect to that proxy (session reuse) rather than scanning into the void.

## Environment summary

- HA 2026.10.2 (Supervised, Docker container on Debian, host `x86_64`)
- ESPHome proxies: 2026.9.1 (ESP32-C5) and 2026.7.1 (ESP32-C5), `bluetooth_proxy: active: true`, `noise_psk`
- Peripheral: OUPES Guardian 6000 V2 (BLE-only), MAC redacted
- aioesphomeapi: HA-bundled version (used to capture the telemetry above)

# v1.4.12 candidate — Proxy Sweep self-heal (design note)

## Problem (observed live 2026-10-17, two incidents)
After an HA restart, the Guardian can be found **still linked to an ESPHome bluetooth proxy**
that HA's Bluetooth layer isn't currently using for the integration. The station, being in a
live connection, stops advertising; HA's scan-based connect never targets the holding proxy;
the integration's first refresh hangs forever. Physical intervention was required both times.

## Fix in our lane (no HA core dependency)
On `ConfigEntry` first-connect failure (and optionally on a slow timer while disconnected):

1. Read a new **optional** config/repair-flow field: list of proxy endpoints
   (`host:port` + `noise_psk` or `password`). Defaults: none — feature is opt-in.
2. For each proxy, open a short `aioesphomeapi` session and call
   `subscribe_bluetooth_connections_free`.
3. If any proxy reports our station MAC in `allocated`:
   - log a repair-issue: "Proxy <host> is holding the station from a previous session"
   - attempt `bluetooth_device_disconnect` (may not ack — treat timeout as non-fatal, retry once)
   - if still held, offer a one-click service `oupes_mega_ble.proxy_release` and, failing that,
     instruct the user (power-cycle that one proxy).
4. Once released, normal connect proceeds; station re-advertises within seconds.

## Known caveats
- `bluetooth_device_disconnect` against a holding proxy timed out unacknowledged twice in the
  field (see docs/HA-CORE-BLUETOOTH-RECLAIM-ISSUE.md). Retries + clear issue text are the
  fallback. If HA core lands a reclaim API, switch to it.
- Keep the dependency optional: import `aioesphomeapi` lazily; if absent, the sweep is a no-op
  and the repair issue explains how to enable it.
- Never sweep a proxy that HA's own bluetooth is actively using for our client (avoid releasing
  our own healthy link): compare with `client.connected` state before acting.

## Field-test script (already proven)
`tools/proxy_sweep_prototype.py` — connects each configured proxy, prints allocated list,
flags our MAC. This is the seed for the integration feature.

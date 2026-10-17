# Field test: original Guardian 6000 (product id `oB6OKs`)

This repo's Guardian code path was measured end-to-end on a **Guardian 6000 V2**
(`95haDY`). The **original Guardian 6000** shares the `guardian` series and should
work — but three specific things about it are *uncaptured*, and an owner with that
machine can settle all three in about ten minutes. If you own one, this page is for
you; your data is the only way the table in `GUARDIAN-WP-BLE.md` grows past one row.

## The three open questions

| # | Question | Why it matters | What settles it |
| --- | --- | --- | --- |
| 1 | Does dpid **115** appear at all, and is it one voltage or a packed pair? | The V2 packs two XT60 input voltages into it. The V1 has **one Anderson input**, so it either sends one value, sends nothing, or surprises us | Steps A–B |
| 2 | Does dpid **23** pack two DC input powers, or a single wattage? | Drives `DC Input 1/2 Power`; the split is currently *not* enabled for `oB6OKs` | Step B (one look) |
| 3 | Does the station answer the same **9 settings dpids** (41, 45, 46, 47, 48, 49, 58, 63, 105)? | Decides whether the config entities (timeouts, ECO) are real on V1 | Step C |

Everything else (auth with `md5(userId)[:10]`, the telemetry stream, keepalive) was
already confirmed to be family-wide.

## Step A — pair it (5 min)

Same as the V2: **Add integration → Fetch key from Cleanergy cloud account**, the email
and password the app uses. The user ID is the five-digit number on the app's
**Settings** (cog) screen if you prefer the manual route. Phone Bluetooth **off**
while HA pairs (one BLE client at a time; this is firmware, not a bug).

## Step B — capture the telemetry (2 min)

1. HA → **Settings → Devices & Services → OUPES** → three dots → **Configure**, tick
   **Debug: log every received attribute id/value** (exact wording may differ) and
   **restart Home Assistant** (the option is read at startup).
2. Let it run **2–3 minutes** with normal load. Note what was plugged at the time
   (one PV input? which connector? battery percentage?).
3. Download the log: it lands under `/config` as an `oupes_mega_ble` attrs CSV (the
   first header line names the columns), or grab it from the HA file editor.
4. Turn the debug option back off and restart, or just delete the file afterwards —
   it appends forever while enabled.

In the file, look for the rows with `attr` (or first column) `23` and `115`:
- a value **above 65535** at either one = a packed pair is being sent raw (a bug, tell us),
- a plausible single wattage/voltage = the V1 reports one input, exactly as expected,
- **no rows at all** = that dpid does not exist on this model — also a complete answer.

## Step C — the settings check (3 min)

With the integration connected, open HA **Developer tools → Actions → `system_log`**
after enabling debug logging as above, or simply report **which config entities
appeared** on the device page (standby timeouts, ECO thresholds, etc.) and whether
changing one in the **app** moved the corresponding HA entity within a minute.

## What to send

Open an issue with:
- product id (device page → **Model**), HA version, integration version (the
  **manifest** line under the integration),
- the attrs CSV from Step B (redact nothing — it contains no personal data; the user
  ID does not appear in it),
- one sentence on what was plugged into the DC input(s) during the capture.

## What the integration will show you — and what it will not

- **No phantom DC input sensors.** If your V1 never reports dpid 23/115, the split
  entities (`DC Input 1/2 Power/Voltage`) do not exist on your device — by design,
  since v1.4.10. A missing entity is honest; a permanent `unknown` is not.
- **Energy Management (charge limits, backup policy) will not appear.** That is not
  a V1 gap; the V2's radio never carries those values either — §13 of
  `GUARDIAN-WP-BLE.md` has the full sweep evidence. Nobody can fix this over BLE.

# OUPES Guardian 6000 V2 & Mega BLE — Home Assistant Integration

Custom Home Assistant integration for **OUPES Guardian** and **OUPES Mega**
power stations over **Bluetooth (BLE)** — fully local, no cloud dependency
required. This build is maintained and tested against the
**Guardian 6000 V2**.

> **About this repository.** This is a maintained fork of
> [`acalcutt/oupes-mega-ble-hass`](https://github.com/acalcutt/oupes-mega-ble-hass)
> (MIT, © Andrew Calcutt), which carries the original license and copyright
> unchanged. It is labelled for and maintained against the
> **Guardian 6000 V2** (`D5 V2`, BLE name `WP`, product ID `95haDY`) — the model
> it is tested on — and ships that support in tagged releases rather than from a
> floating branch. Mega, Exodus and LP stations keep working as upstream has them
> (same integration domain, `custom_components/oupes_mega_ble`, so this is a
> drop-in replacement rather than a second integration), but they are not the
> model this fork is verified against.
>
> See [Provenance and changelog](#provenance-and-changelog) for exactly what
> differs, and
> [`pull/13`](https://github.com/acalcutt/oupes-mega-ble-hass/pull/13) for the
> upstream pull request; if that merges, this fork becomes redundant and the
> upstream repo should be preferred.

> **WiFi does not work on Guardian / D5 V2 / D5 6000 Plus stations.** A separate
> [WiFi integration](https://github.com/acalcutt/oupes-mega-wifi-hass) exists - HACS
> requires one integration per repository, so the two halves of that project were
> split - but on the `WP` firmware family these units have no usable network data
> path. Reported by the vendor's own app developer, and confirmed here in practice:
> the station will not carry local telemetry over WiFi by any route, and the vendor
> cloud (plain HTTP, no local API) is the only thing it speaks to on the network.
> **Bluetooth, relayed by an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy),
> is the supported path** - it is what this page is for, and it is how every figure
> on this page was obtained. Do not lose an afternoon to the WiFi option.
>
> The `wifi_ssid` / `wifi_psk` fields during setup are not a workaround either: they
> only hand your credentials to the station so the vendor app and cloud can reach
> it. Home Assistant still talks to the station over Bluetooth afterwards.

---

## Provenance and changelog

**Derived from** [`acalcutt/oupes-mega-ble-hass`](https://github.com/acalcutt/oupes-mega-ble-hass)
(MIT). The BLE protocol reverse engineering this build stands on is the upstream
authors' work — `@acalcutt` and `@HeedfulCrayon` are both listed as code owners
upstream for that reason. Anything in the protocol documentation that pre-dates
v1.3.0 is theirs; the differences below are ours.

Maintainers: releases are cut by the checklist in
[`docs/RELEASING.md`](docs/RELEASING.md) - pushing a `v*` tag auto-creates the
GitHub Release via `release-on-tag.yml`, because a tag without a release object
is invisible to HACS "Last release" tracking (this bit us at v1.4.6/v1.4.7).

### v1.4.0

- **Your user ID is the whole credential.** The binding key is
  `md5(user ID)[:10]`, which is how the vendor's own APK generates it, so pairing
  is one number rather than a captured key.
- **The openId turned out not to be a requirement.** Measured: real key and user ID
  with that field zero-filled streams 43 telemetry frames; the same frame with a
  wrong user ID is refused. Everything in this project that insisted on an openId
  was wrong, including a page that told people to capture one with a rooted phone.
- **Never remove the station from the vendor app.** Removing it wipes the stored pair.
  To hand the radio to the app, disable the HA entry instead - that was measured
  end-to-end, including the return.
- New pairing method **Use my Cleanergy user ID**; cloud login derives the key.
- A `WP` station that answers and hangs up now logs the reason instead of a `DEBUG` line
  nobody reads.
- Docs corrected where they were actively misleading, and a section added on which
  claims rest on which evidence.

### v1.3.0 (based on upstream 1.2.0 / `266d14b`)

- **Guardian / D5 V2 (`WP`) stations can be added at all** — `WP` added to the
  advertisement filter, which previously made HA discard these devices before
  the config flow ever saw them.
- **AUTH with the owner's cloud identity**, as those stations require: a
  `0xA8`-long config-net-info frame carrying openId and userId, with the empty
  SSID field padded `0x01`. The identity is entered in the integration options.
- **Packed TLV telemetry** (`[0x02][0x05][dpid][uint32 LE]`, prefix `0x03`,
  entries straddling packet boundaries) decoded by a dedicated reader, with the
  existing parsers left as the fallback path.
- **Attr 23 unpacked** into per-input DC power, behind a guard that leaves other
  models' wattage readings untouched.
- **Expansion Battery Count** derived from reported slots on units that never
  answer dpid 51 unless queried.
- **Tests** (`tests/test_protocol_wp.py`) and a protocol reference for the `WP`
  variant in [`debug_info/README.md`](debug_info/README.md), including a test
  asserting a TT station's init sequence stays byte-for-byte identical.

Not present upstream, and not claimed here: the Mega, Exodus and LP families
were not re-tested on hardware — the `TT` path is defended by tests instead.

---

## What it does

**Direct Bluetooth connection** — the simplest setup. Connects to your OUPES
device over BLE and exposes sensors, switches, and settings entities.

- No network infrastructure needed — just a Bluetooth adapter on your HA server
  (or an ESPHome BLE proxy)
- Continuous or polled connection modes
- Supports BLE pairing (no Cleanergy app/cloud needed)
- Device control: toggle AC/DC/USB outputs, adjust settings

**[Full documentation →](custom_components/oupes_mega_ble/README.md)**

---

## Installation

### Before you install: can Home Assistant see Bluetooth?

This is a Bluetooth integration. Home Assistant needs a Bluetooth radio it can use,
and it has to be able to hear the station:

- an adapter on the machine running Home Assistant, **or**
- an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy) — any
  ESP32 — on the same Home Assistant instance, within range of the station.

Whichever exists is used automatically, and a proxy is not a compromise: the install this
README was written against runs in a Hyper-V VM with no Bluetooth adapter at all
(`/sys/class/bluetooth` empty) and reaches the station through two ESP32 proxies. **BLE is
the only path**, so before anything else in this document, check **Settings → Devices &
Services → Bluetooth**: no adapter and no proxy there means no discovery card, no address to
type, and no workaround, because the station exposes no local network protocol (see *WiFi:
not an option on these models* below). Stations are commonly in garages and outbuildings, so
the question is usually range rather than availability — an ESP32 near the unit solves it for
less than the cost of a cable run.

### HACS (custom repository)

1. Open **HACS → Integrations**.
2. Open the three-dot menu and select **Custom repositories**.
3. Enter `https://github.com/bandit8623/oupes-mega-ble-hass`.
4. Select **Integration**, click **Add**, and install **OUPES Guardian 6000 V2 BLE**.
5. Restart Home Assistant — required, HACS only swaps the files on disk.
6. Add the station: accept the Bluetooth discovery card (or add it manually), then
   follow **Choose pairing method** and **Connection settings**. On a Guardian /
   D5 V2 pick **Fetch key from Cleanergy cloud account** and sign in with the same email
   address and password the app uses. That single request fetches the account's numeric user
   ID and Home Assistant derives the binding key from it - there is no key to capture and no
   openid to hunt for. Do **not** start with **Use my Cleanergy user ID** on a first install
   unless you already know the number. You can read it in the Cleanergy app under
   **Settings** (the cog) — a five-digit user ID — but the fetch above gets it
   without the hunting. An existing entry also shows the value it fetched under
   **Configure** (the cog), which is where that field is useful later.
7. Check the entities. Telemetry normally appears within ~20 s. If it does not,
   the station is almost certainly still being held by the phone: force-stop the
   Cleanergy app or switch the phone's Bluetooth off, because the station answers
   one Bluetooth client at a time.

> **Living with the Cleanergy app.** The one-client rule applies to the *Bluetooth*
> radio only. Once the phone's BLE is off (or the app stays in cloud mode), the
> app keeps working over the station's Wi-Fi uplink while Home Assistant keeps
> its BLE stream — the two have been observed side by side indefinitely. If the
> dashboard suddenly goes `unavailable` while someone is in the app standing next
> to the station, it is the phone borrowing the BLE slot; close the app (or
> toggle Bluetooth off) and the integration reconnects on its own.

Releases are tagged, so HACS installs a specific version rather than a moving
branch. Installing over an existing copy of this integration is fine — the domain
is unchanged, so entities and the config entry survive.

### Manual

1. Copy `custom_components/oupes_mega_ble/` into your HA config directory.
2. Restart Home Assistant.

### Migrating from another copy of this integration

If HACS already tracks `acalcutt/...` or `HeedfulCrayon/...`, the switch is:

1. Add this repository as a custom repository and install it. It overwrites the
   same `custom_components/oupes_mega_ble/` directory — expect the entities to go
   unavailable for one restart.
2. Restart Home Assistant.
3. If you are on a `WP` station, re-enter the user ID during the re-add; the
   key is derived from it.
4. Check the entities are live again, then **untrack** the old repository so its
   update entity cannot offer to overwrite these files.

HACS distinguishes *untracking* a repository from *removing its files*. Removing
the files deletes `custom_components/oupes_mega_ble/` while the integration is
still loaded, so Home Assistant errors until you restart and reinstall. Do the
untrack, not that.

### Keeping HACS from overwriting local edits

The `OUPES … Update` entity never installs anything by itself, but "Update all" on
the dashboard will. If you patch these files by hand, either disable that update
entity or point HACS at your own fork — otherwise the next "update" silently
reverts your changes.

### Upstream

The protocol work is also submitted upstream as
[acalcutt/oupes-mega-ble-hass#13](https://github.com/acalcutt/oupes-mega-ble-hass/pull/13).
If it is ever merged, upstream wins and this fork becomes redundant — that is the
intended outcome, not a rivalry.

## Quick Start

> **Read [docs/GUARDIAN-WP-BLE.md](docs/GUARDIAN-WP-BLE.md) before you fight with a
> `WP` station.** It is the full guide: where each pairing value comes from, how the
> device key is derived, what the station's Bluetooth frames mean when it refuses you,
> and why the Cleanergy app and Home Assistant cannot both hold the station.

> **Before you start — do these in this order.**
>
> 1. **Add the station in the Cleanergy app first**, by Bluetooth, phone next to the
>    unit. Home Assistant does not pair these stations; it reuses the pairing your
>    phone already made, and the credential it uses is derived from *your* Cleanergy
>    account. A station that has never been added to the app under your account has
>    no key for Home Assistant to derive, and it will refuse every connection.
> 2. **Use the same account here as in the app.** During setup, choose **Fetch key
>    from Cleanergy cloud account** and sign in with that email address. It is a
>    one-time request and the password is not stored.
> 3. **Never remove the station from the app afterwards.** Re-pairing is only
>    possible from the app, and a factory reset means starting over there. Deleting the
>    Home Assistant entry can be undone, but it is the wrong tool: it takes the entry's
>    entities with it, so **Disable** is how you hand the station to the app. Removing
>    the station from the app is the one action you cannot take back from here.
> 4. **Turn the phone's Bluetooth off, or force-stop the Cleanergy app, before Home
>    Assistant connects.** The station answers one Bluetooth client at a time, so a
>    phone that still holds it does not merely slow Home Assistant down - it blocks
>    the connection entirely. The entry loads and the entities stay *unavailable*
>    until the phone lets go, and retrying changes nothing. Leave the app installed;
>    it just cannot be the one holding the station.
>
> What to expect once you submit: about 15 seconds to connect, then a few dozen
> entities. The unit used for testing came up with 44. It is not a fixed number: this
> family creates about 29 entities for the station itself plus five for every expansion
> battery pack that reports (charge, input power, output power, runtime, temperature),
> and the test unit has three packs fitted. The two DC input sensors read **0 W** while
> there is no solar input. If you are on 1.4.4 or older they read *unknown* at zero
> instead - that disagreement with the aggregate sensor was a real gap in this
> integration, fixed after 1.4.4, and never a wiring fault. And while Home Assistant
> holds the connection the app cannot reach the station over Bluetooth: its cloud
> figures keep updating, but live control from the app will not work.

The two OUPES families need different things, so pick the row that matches your
station. If you do not know: the app calls it a **Guardian / D5 V2**, and it
advertises the BLE name `WP`. A **Mega** advertises `TT`.

### Guardian / D5 V2 (`WP`) — needs the user ID, once

**Just want it working? Two steps:**

1. **First time:** at the pairing screen choose **Fetch key from Cleanergy cloud
   account** and type the **same email and password you use in the Cleanergy app**.
   That is all. It pairs, and the number it looked up is saved in the integration.
2. **Any time after:** if you ever have to re-add the station, it needs only the
   **five-digit number — that number is the "user ID"**, and it goes in the field
   that says so. The Cleanergy app shows it under **Settings** (the cog), and the
   integration's **Configure** screen shows it too.

Two things that genuinely break pairing, both avoidable: **removing the station
from the Cleanergy app** after pairing — that erases what the app wrote into the
station, and nothing can pair it except the app again — and **leaving the phone's
Bluetooth on** while Home Assistant tries to connect: the station serves exactly
one Bluetooth client, so turn off the phone's Bluetooth (or force-stop the app)
while HA pairs and stays connected. Typing your email into the user ID field does
not break anything - the field refuses it, and that refusal is the field telling
you it wants the number.

**Two values, one job each.** The **user ID** is a number — five digits, shown
on the **Settings** (cog) screen of the Cleanergy app — and it is **not your email
address**; the field that asks for it refuses an email because it wants the number.
The **email address** is only what you *log in* to the Cleanergy app with, and it is
all the fetch screen needed earlier. The station authenticates Bluetooth against the
account that paired it; with the wrong account it answers once, then drops Bluetooth
about four seconds later — which looks exactly like a range problem, and is not one.

A second Guardian 6000 V2 was set up from scratch by a different user with nothing
but the app's email and password at the fetch screen: paired on the first attempt.

For the curious rather than the stuck — why the user ID alone is enough, why the
`openId` people once believed required turned out to be decoration, and why a station
the app has never paired cannot be set up from Home Assistant at all — is written
up in [docs/GUARDIAN-WP-BLE.md](docs/GUARDIAN-WP-BLE.md). Pairing does not need any
of it.

So the order of operations is fixed by the hardware, not by preference:

1. **Power on and wake the station.** The IoT indicator should be lit. A station that
   has been sitting idle goes to sleep, and it will not answer a handshake in its
   sleep - which is indistinguishable from being out of range. Press the IoT button
   once immediately before you start.
2. **Add it in the Cleanergy app first**, by Bluetooth with the phone next to the
   unit. That is what writes the pair into the station. Skip if it is already in the
   app.
3. **Do not remove it from the app afterwards.** Closing the app is enough to free
   the radio. Removing the station also wiped the pairing Home Assistant authenticates
   with on the unit tested here, and re-adding rewrote it. The vendor's unbind behaviour
   was flaky in testing (the same removal did not always unbind - see the confidence
   table in [the WP guide](docs/GUARDIAN-WP-BLE.md)), so the safe assumption is that it
   wipes and you would have to pair again.
4. **Use the same account in Home Assistant that the app paired with.** The number to
   check is your five-digit Cleanergy user ID — the app shows it on the **Settings**
   (cog) screen. You normally do not need to look it up at all, because
   the cloud login in step 7 reads it for you. If you do want it: an existing entry
   also shows it (**cog on the OUPES card → Configure**, the `Cloud userId` field) - but
   only if that entry was set up through the email login, because that is the request
   that fetches the number. An entry built by typing a device key by hand shows `0`
   there, since nothing ever told Home Assistant the value. From scratch, a vendor
   login request returns it as `info.uid` - see
   [docs/GUARDIAN-WP-BLE.md](docs/GUARDIAN-WP-BLE.md).
5. **Switch the phone's Bluetooth off** — or force-close the app. One Bluetooth
   client at a time, and an app still holding the station produces a pairing
   failure that looks like a broken integration.
6. Bring up the setup form. There are two ways in, and they meet at the same screen:
   - **If something nearby can hear Bluetooth**, the station turns up under
     **Discovered** on **Settings → Devices & Services**. Click **Add**, then **Submit**
     on the "Found *name* (address) nearby" confirmation. A station that has never been
     added here can absolutely show up as discovered - it is paired with the *app*, and
     Home Assistant has simply not met it yet.
   - **If it does not appear**, go to **Add Integration → OUPES** and type the address
     into **Bluetooth MAC Address**. The station advertises as `WP`; your proxy's device
     list gives you the address. A nearby station is pre-filled into that field when an
     adapter saw it.
7. On **How would you like to provide the device key?**, choose one of:
   - **Fetch key from Cleanergy cloud account** — sign in with the email and password
     you use in the app. Home Assistant reads your user ID out of the vendor's own
     login response and derives the key from it. One request, and the password is not
     stored. Take this one if you are unsure.
   - **Use my Cleanergy user ID** — type the user ID (the five-digit number on the
     Cleanergy app's **Settings** screen) and the key is derived locally. No sign-in,
     no network request.

   On a recognised Guardian the second option is already selected for you. Do not pick
   **Create a new device key** here.
8. Fill in **Connection settings** and submit. Neither path writes anything to the
   station; it simply turns up with the credentials the app already left there.
9. **Wait about fifteen seconds.** Roughly 44 entities appear. The two DC input
   sensors read *unknown* while nothing is plugged in, and that is correct. If they
   stay *unavailable*, the phone is almost certainly still holding the station or it has gone
   back to sleep - both are fixed outside Home Assistant, not in it.
10. Understand what that costs: **Home Assistant now holds the station's single
   Bluetooth connection**, so Cleanergy stops reporting it while the entry is loaded.
   Its cloud figures keep updating, but live control from the app does not work. That
   is the arrangement, not a malfunction.
11. When you want the app back - to change a setting, or to take an over-the-air
   firmware update, which only the app can do - **disable the entry, do not delete it**.
   Disabling releases the Bluetooth connection, keeps the entry and its entities, and
   reconnects on its own when you switch it back on **provided the app has let go of the
   radio** - the station serves one Bluetooth client, so force-close Cleanergy, or switch
   the phone's Bluetooth off, before you re-enable. Deleting throws the entry's
   entities away, so every dashboard card and automation pointed at them goes dead and
   the whole setup has to be done again. Nothing about the station changes either way,
   so you can go back and forth between HA and the app as often as you like. The
   sequence is written up in
   [docs/GUARDIAN-WP-BLE.md](docs/GUARDIAN-WP-BLE.md#when-a-firmware-update-needs-the-app).

**Do not use "Create a new device key" on a station that is already paired.** That
path claims the station and overwrites what it holds, and on this firmware family it
does not complete at all - measured twice, once immediately after a factory reset.
Claiming works on the older `TT` stations, and on a `WP` unit only if the vendor has
never bound it.

Would rather not hand this integration your password? The user ID path needs
none. It is one number, and the key follows from it.

### Mega (`TT`) — no identity needed

1. Power on and press the IoT button (indicator flashes).
2. HA auto-discovers the device — click the notification to set up.
3. Choose **Create a new device key** (factory-reset first: hold IoT 5 s), or
   enter a key you already have.

### If it pairs and then goes stale every few seconds

That is the missing identity, not a range problem. Open **Options** on the entry
and either fetch the values from your cloud account or enter them.

---

### WiFi: not an option on these models

The upstream project offers a companion
[WiFi integration](https://github.com/acalcutt/oupes-mega-wifi-hass), and for the
older `TT` models it is the better choice at distance: push-based, real-time, and
range-free. **It does not work on Guardian / D5 V2 / D5 6000 Plus (`WP`) stations.**

Do not try to reach them over WiFi, and do not troubleshoot it:

- the unit exposes no local network protocol on this firmware — the vendor's own
  app developer says so, and hands-on testing here agrees
- the firmware talks to a hardcoded vendor cloud over **plain HTTP**, which is not
  a local API and not something to proxy into your LAN
- the `wifi_ssid` / `wifi_psk` fields in setup configure the *station's* connection
  for the vendor app. They do not connect Home Assistant to the station, and
  nothing breaks if you leave them blank

If the station is out of Bluetooth range, the fix is a second
[ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy) nearer to
it - an ESP32 on the desk next to the station costs less than the cable you would
need for any wired alternative, and this integration uses whichever proxy can hear
the station. **BLE is the only path**, so that is the one to make reliable.

---

## Tuning (Settings → Devices & Services → your OUPES entry → **Configure**, the cog)

Every field below lives in that one dialog; saving reloads the entry and applies
immediately — nothing on the station is touched.

| Field | What it does |
|---|---|
| **Live update throttle (seconds)** | Continuous mode only: the shortest gap between two state pushes to Home Assistant. Notifications always arrive when the station sends them (~2–3 s while values change); this only coalesces bursts. **If you don't want fast updates, raise this to your liking** — e.g. `5` or `10` gives the cards a calmer cadence; nothing else changes, and it can be adjusted any time from the same cog dialog. Measured on a live station: 1 s and 2 s are indistinguishable in CPU (≈0.25 % of the HA core either way). Range 1–30, default 1. |
| **Poll interval (seconds)** | Non-continuous mode only: how often HA connects, pulls, and disconnects. Range 10–600, default 30. Ignored while continuous mode is up. |
| **Continuous BLE connection** | Keep the link open and receive the station's notification stream, vs. poll-and-release. Continuous blocks the vendor app from connecting at the same time. |
| **Stale timeout (minutes)** | How long the last known values keep showing after a failed poll before entities go `unavailable`. Range 1–120, default 15. |
| **Runtime noise filter (minutes)** | Clamp ceiling for the firmware's sometimes-silly `time_to_full` values. Raise above 99 h only if your stack genuinely runs that long. |
| **Cloud openId / userId** | Guardian / D5 V2 (`WP`) stations only — see [the identity section](#guardian--d5-v2-wp--needs-the-user-id-once). Changing either re-pairs the station. |
| **Debug CSV toggles** | Attribute / raw-packet logging to files in your HA config folder, for diagnosis sessions. Leave off in daily use. |

---

## Supported Models

| Series | Models | Evidence |
|--------|--------|----------|
| **Mega** | Mega 1, Mega 2, Mega 3, Mega 5 | measured upstream (`TT` family, long-stable) |
| **Exodus** | Exodus 1200, Exodus 1500, Exodus 2400, S024 Lite, S1 Lite | product-ID mapping only — no capture by anyone here |
| **Guardian** | **Guardian 6000 V2** ← maintained & tested here | **measured here, exhaustively** — full wire capture, command sweep, auth matrix |
| | Guardian 6000 (V1), HP2500, D5 V2, D5 6000 Plus | `guardian`-series mapping only — **never captured**; V1 has a [field-test checklist](docs/FIELD-TEST-ORIGINAL-GUARDIAN.md) |
| **Other** | S2 V2, DC 800, LP350, LP700, PB300, UPS 1200, UPS 1800 | product-ID mapping only — no capture by anyone here |

**Read the Evidence column, not the Series column.** "Mapping" means the vendor
cloud reports that product ID and it is routed to a series' code path — it is a
prediction, not a result. The Guardian / `WP` family's actual BLE behaviour — the
`md5(userId)[:10]` derivation, the auth sequence, the packed-telemetry quirks that
make `parse_wp_stream()` miss everything — was established by **this fork's**
measurements on a Guardian 6000 V2; before it, no public implementation paired one.
If your station carries an untested product ID and this integration works (or
doesn't), that is a data point nobody has — see the compatibility note below.

Model-specific features (settings, entity names) are applied automatically
based on the BLE product ID.

> **Guardian / D5 V2 stations** (e.g. the Guardian 6000 V2) advertise the BLE name
> **`WP`** rather than `TT`, and they authenticate against the Cleanergy account the
> station was paired with. You give the integration that **user ID** and it
> derives the key - see
> [Guardian / D5 V2 stations](custom_components/oupes_mega_ble/README.md#guardian--d5-v2-stations-ble-name-wp).
> Add the station in the vendor app first, and never remove it afterwards.
>
> **Scope of that claim:** everything about the `WP` family here was measured on a
> single Guardian 6000 V2. Do not check that against a firmware number: the vendor reports
> two different versions for that one unit (the app shows `0.0.4`, its cloud record says
> `1.2.0`), and the string is not bumped on every update. Other `WP` models and other
> builds are untested, not known-bad. See
> [how much is actually known](docs/GUARDIAN-WP-BLE.md#12-how-much-of-this-is-actually-known)
> and, if your station is not that one, please file the compatibility report.
> Owners of the **original Guardian 6000** (`oB6OKs`, one Anderson DC input): a
> ten-minute checklist exists at
> [FIELD-TEST-ORIGINAL-GUARDIAN.md](docs/FIELD-TEST-ORIGINAL-GUARDIAN.md) — it
> settles the three dpid questions that machine still has.

---

## Protocol Documentation

See [`debug_info/README.md`](debug_info/README.md) for the complete
reverse-engineered protocol reference, covering:

- BLE GATT profile, pairing/claiming protocol, packet format
- WiFi TCP broker protocol, streaming activation sequence
- Telemetry attribute map (shared across BLE and WiFi)
- Cloud API endpoints (HTTP REST + SiBo)
- Device firmware boot sequence

## Debug Tools


The [`debug_info/`](debug_info/) directory contains standalone tools:

| Script | Purpose |
|--------|---------|
| `pair_device.py` | BLE pairing + WiFi provisioning |
| `scan_ble.py` | Live BLE telemetry scanner |
| `parse_btsnoop.py` | Parse Android btsnoop HCI logs |
| `probe_key.py` | Test candidate device keys |
| `ble_diag.py` | BLE GATT diagnostics |
| `ble_confignet.py` | Send WiFi credentials to a paired device |
| `scan_wifi_ports.py` | Scan device for open network ports |
| `analyze_attr_csv.py` | Analyze BLE attribute debug logs |

---

## License

MIT — see [LICENSE](LICENSE) for the original copyright notice, which this fork
retains unmodified. Contributions here are offered under the same terms.

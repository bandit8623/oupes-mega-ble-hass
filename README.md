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

### v1.3.0 (this release, based on upstream 1.2.0 / `266d14b`)

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

### HACS (custom repository)

1. Open **HACS → Integrations**.
2. Open the three-dot menu and select **Custom repositories**.
3. Enter `https://github.com/bandit8623/oupes-mega-ble-hass`.
4. Select **Integration**, click **Add**, and install **OUPES Guardian 6000 V2 BLE**.
5. Restart Home Assistant — required, HACS only swaps the files on disk.
6. Add the station: accept the Bluetooth discovery card (or add it manually), then
   follow **Choose pairing method** and **Connection settings**. A Guardian / D5 V2
   will connect and drop again after about four seconds at this point; that is
   expected, and the next step is why.
7. **Guardian / D5 V2 stations only:** with the entry now added, go to
   **Settings → Devices & Services → OUPES Guardian 6000 V2 BLE → Configure** (the
   gear icon) and fill in **Cloud openId** and **Cloud userId**
   ([how to find them](custom_components/oupes_mega_ble/README.md#finding-your-openid-and-userid)).
   These fields exist only in the options dialog, so this step has to come after
   step 6 — there is nothing to fill in until the entry exists. Telemetry normally
   appears within ~20 s of saving. Mega / Exodus / LP users skip this step.

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
3. Enter openId/userId in the integration options if you are on a `WP` station.
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

The two OUPES families need different things, so pick the row that matches your
station. If you do not know: the app calls it a **Guardian / D5 V2**, and it
advertises the BLE name `WP`. A **Mega** advertises `TT`.

### Guardian / D5 V2 (`WP`) — needs an account identity

These stations put the owner's `openId` and numeric `userId` *inside* the
Bluetooth authentication frame. Without them the station answers the AUTH packet
and then drops Bluetooth about four seconds later, which looks exactly like a
range problem. You get those two values one of three ways:

| Your situation | Do this |
| --- | --- |
| Fresh or factory-reset station, you want Home Assistant only, no vendor cloud | **Claim with a local identity — no cloud account.** Home Assistant mints the identity and the key itself. Needs no account, no password, no internet. |
| Station is already added to the Cleanergy app and you want the app to keep working | **Fetch key from Cleanergy cloud account.** One-time sign-in recovers the key *and* the identity. Credentials are never stored (see [security](SECURITY.md)); the vendor API is plain HTTP. |
| Vendor cloud unreachable, station bound to someone else's account, or you simply refuse to give this integration your password | **Enter an existing device key**, then type `openId` and `userId` yourself. |

Then: power on, put the station in pairing mode (**hold IoT 5 s until it flashes
rapidly**), and let HA auto-discover it. Only one Bluetooth client can be
attached at a time, so keep the phone app closed during setup.

A locally claimed station is deliberately **absent from every vendor cloud
account**, and if the official app binds it afterwards the app overwrites the
identity — undoing the local claim needs another factory reset. The setup screen
says this before it writes anything, and **Options** tells you which kind of
identity a station carries.

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

## Supported Models

| Series | Models |
|--------|--------|
| **Mega** | Mega 1, Mega 2, Mega 3, Mega 5 |
| **Exodus** | Exodus 1200, Exodus 1500, Exodus 2400, S024 Lite, S1 Lite |
| **Guardian** | **Guardian 6000 V2** ← maintained & tested here, Guardian 6000, HP2500, D5 V2 |
| **Other** | S2 V2, DC 800, LP350, LP700, PB300, UPS 1200, UPS 1800 |

Model-specific features (settings, entity names) are applied automatically
based on the BLE product ID.

> **Guardian / D5 V2 stations** (e.g. the Guardian 6000 V2) advertise the BLE name
> **`WP`** rather than `TT`, and their AUTH frame must carry the **openId** and
> **userId** of the Cleanergy account that owns the station — without both the
> station rejects the connection and drops it after a few seconds. See
> [Guardian / D5 V2 stations](custom_components/oupes_mega_ble/README.md#guardian--d5-v2-stations-ble-name-wp).

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

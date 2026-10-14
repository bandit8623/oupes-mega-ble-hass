# Changelog

All notable changes to this fork. Versions are published as [GitHub
Releases](https://github.com/bandit8623/oupes-mega-ble-hass/releases); HACS users
get them as soon as the tag exists.

This fork tracks
[`acalcutt/oupes-mega-ble-hass`](https://github.com/acalcutt/oupes-mega-ble-hass)
(MIT) and keeps its integration domain, so releases are drop-in upgrades.

## Unreleased

### Added

- **openId / userId can now be fetched from the vendor cloud instead of typed.**
  The options dialog gained two optional cloud-account fields: supply them and
  the integration logs in, reads `uid` and your station's `openId`, and fills the
  two identity fields. The password is used for that one request and is not part
  of the options that get written — the options dict is assembled field by field
  and the credential fields are deliberately excluded. If you pair using the
  existing **cloud login** method, the same lookup runs automatically during
  setup, so a Guardian bound to your account needs no typing at all.
- Distinct failure messages for "wrong credentials" and "this station is not in
  that account's device list". They need different fixes, and a station that was
  unbound from the cloud is a normal state, not an error.

### Fixed

- `strings.json` had fallen behind `translations/en.json`: the `go_back` and
  `runtime_max_minutes` labels were missing from it entirely, and the pairing
  instructions were an older revision (missing the "the IoT module turns off,
  press it back on" step). Anything generated from `strings.json` — including
  future translations — could not have had those strings.

### Tests

- 27 new tests in `tests/test_cloud_identity.py` for the vendor-response parsing,
  including the two shapes confirmed against the live API (`uid` rather than
  `userId` at login, and the empty-`bind` response an unbound station returns).
  CI now runs every test file standalone, not just the protocol one.

## v1.3.0

Guardian / D5 V2 stations (BLE name `WP`) — the reason this fork exists.
Verified end-to-end on a Guardian 6000 V2 (`product_id` `95haDY`) running
Home Assistant OS 2026.10.1 with HACS 2.0.5: 39 entities, all reporting live data.

### Added

- `WP` in the Bluetooth advertisement filter. Without it Home Assistant discards
  these advertisements and the station can never be added.
- AUTH via the owner's cloud identity: the `0xA8` config-net-info frame carrying
  `openId` + `userId` with an empty, `0x01`-padded SSID. These units reject the
  Mega-style key AUTH.
- Packed TLV telemetry reader for the `[0x02][0x05][dpid][uint32-le]` stream with
  prefix `0x03`, including entries that straddle 17-byte notification slices.
- Per-DC-input power (`dc_input_1_power`, `dc_input_2_power`) derived from the two
  uint16 halves of attribute 23.
- Expansion battery count derived from populated telemetry slots, for units that do
  not answer `dpid` 51 unless polled.
- `openId` / `userId` as integration options (not code), read from
  *Integrations → OUPES → Configure*.
- `tests/test_protocol_wp.py` — 13 tests over synthetic packets, including one that
  pins a Mega/TT initialisation sequence to byte-identical.

### Fixed

- "Solar Input Power" reporting ~131,000,000 W on WP units: attribute 23 was read
  as a single uint32 where it is two 16-bit watt halves.
- Stations titled `WP` after discovery: the advertised family tag was used verbatim
  as the entry name. Discovery now titles Guardian stations `OUPES Guardian`,
  Mega stations `OUPES Mega`, and keeps a real advertised name when there is one.

### Changed

- Display name is now **OUPES Guardian 6000 V2 BLE**; integration domain, directory
  and entity ids are unchanged.
- Issues and documentation links point at this fork.

### Not re-tested on hardware

Mega, Exodus and LP units. They are unchanged from upstream and protected by tests,
but this fork is verified against the Guardian 6000 V2 only.

## Upstream 1.2.0 and earlier

See the [upstream repository](https://github.com/acalcutt/oupes-mega-ble-hass/releases)
for the history this fork was built on (`266d14b`).

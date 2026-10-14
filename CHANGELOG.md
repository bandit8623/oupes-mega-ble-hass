# Changelog

All notable changes to this fork. Versions are published as [GitHub
Releases](https://github.com/bandit8623/oupes-mega-ble-hass/releases); HACS users
get them as soon as the tag exists.

This fork tracks
[`acalcutt/oupes-mega-ble-hass`](https://github.com/acalcutt/oupes-mega-ble-hass)
(MIT) and keeps its integration domain, so releases are drop-in upgrades.

## Unreleased

- **The cloud identity search now descends into nested objects, and reads
  `/device/info` as well as `/device/list`.** Measured on a live bound Guardian:
  the list entry exposes `addtime, device_id, device_key, device_product_id,
  firmware_version, home, id, mac_address, name, online, pic, sku, sn, system,
  title` and the login response exposes `api_host, avatar, email, is_update,
  mark, nickname, tcp_host*, token, udp_*, uid` — no openId at the top level of
  either. Matching is therefore by key shape rather than a copied spelling list,
  the search walks nested values (the unexamined `home` object being the one
  plausible owner container), and the per-station `/device/info` payload — which
  was being discarded after one field was read from it — is searched too. The
  failure warning now lists dotted field *paths* instead of flat key lists, for
  every endpoint searched.

- **Identity search now opens JSON documents hidden inside strings, and accepts
  list-shaped responses.** `/device/info` exposes `detail.config`; a walk that
  treats every string as a leaf cannot see an identity filed inside such a blob,
  and stringified JSON is how vendor config fields usually arrive. Separately,
  `extract_open_id` returned `None` for any response that was not an object while
  the key extractor beside it has always accepted a list — so the same payload
  was readable for a device key and invisible for an account identity. The field
  report marks opened blobs (`detail.config~json`) so "was empty" and "was never
  examined" are no longer the same line.

### Measured and removed

- **"Claim with a local identity" is no longer offered.** The premise was that a
  factory-reset station accepts any well-formed identity, because that is how the
  official app binds one. Tested on a Guardian 6000 V2 on 2026-10-14: two factory
  resets, each followed immediately by a claim with the minted identity confirmed
  present in the AUTH frame, both timed out with the claim uncompleted. The same
  frame carrying the real cloud identity is accepted by the same station, so the
  identity is the single variable that decides it, and the station checks it. The
  module, its tests and the plumbing around it stay, so this is revisitable by
  whoever reverses what the station actually verifies; the menu stops inviting
  people to spend a factory reset finding out.
- **Method order was inverted for the family that needs it most.** "Create a new
  device key" led, and on a `WP` station that option cannot finish without an
  identity sourced elsewhere first. Cloud recovery now leads for Guardian; the old
  order is kept for `TT`, where generating a key genuinely is the short route.
- **A failed pairing handed the user a different screen than the one they were on.**
  Failure routing was hardcoded to the create-key form, so a local-claim timeout
  rendered under a heading reading "Create New Device Key", with instructions for a
  procedure that had not just been attempted. It now returns to whichever method
  started the pairing.
- **Pairing instructions omitted the two things that actually break it.** The form
  now says to switch the phone's Bluetooth off first, and says out loud that a
  successful claim overwrites the key the app stored, so Cleanergy stops reporting
  the station until it is re-added.
- **Version bumped to `1.4.0.dev0`.** Home Assistant's frontend caches an
  integration's translations keyed by manifest version, so every dev build shipped
  under `1.3.0` left users reading strings from the original release - observed
  directly, two releases of wording changes after those strings were merged.

### Fixed

- **Fresh Guardian setups could not authenticate.** The setup flow ran the claim
  sequence without ever passing an account identity, so a Guardian / D5 V2 station
  ended up correctly paired to its key and then dropped Bluetooth four seconds
  later on every connection. `openId` / `userId` now reach
  `ble_pairing.async_pair_device()`, which lets `build_init_sequence()` emit the
  station's own config-net-info AUTH frame instead of the legacy Mega one. Only
  first-time setup was affected: stations already running were fine because the
  identity got typed into Options afterwards.
- **Setup no longer dead-ends when the cloud has no usable key.** On this firmware
  family the cloud record stores the family tag (`"WP"`) in `device_key` instead of
  a real key, so the cloud method reported a login failure after a login that had
  worked. The identity is the half a Guardian cannot do without, and it *does* come
  back, so setup now continues with a locally generated key instead of stopping.
- **"Optional" WiFi credentials broke Guardian pairings.** The pairing form offers
  optional WiFi fields, marked "leave blank to skip". On `WP` firmware the frame that
  carries WiFi settings and the frame that carries the account identity are different
  packets, and the station only accepts the identity one, so anything typed into a
  field labelled optional swapped in a frame the station answers and then drops - and
  the pairing then fails with a timeout that does not mention WiFi anywhere. The form
  now refuses that combination on Guardian / D5 V2 stations and says why, and the
  field descriptions say what the values are actually for (the vendor app's
  connection, never Home Assistant's).
- **Documentation pointed new Guardian owners at a transport that cannot work here.**
  The README recommended the companion WiFi integration for stations out of Bluetooth
  range. On this firmware family there is no local network protocol at all, so that
  advice sends the exact reader this fork exists for down a dead end. It now says the
  opposite, with the reasoning, and points at an ESPHome Bluetooth proxy instead.
- **Manual setup could not suggest a Guardian.** The manual add screen listed only
  stations advertising `TT`, so anyone adding a `WP` station by hand got an empty
  address field with no hint that the station was sitting right there in the
  discovery list. Both families are offered now.
- `strings.json` had fallen behind `translations/en.json`: the `go_back` and
  `runtime_max_minutes` labels were missing from it entirely, and the pairing
  instructions were an older revision (missing the "the IoT module turns off,
  press it back on" step). Anything generated from `strings.json` — including
  future translations — could not have had those strings.

### Added

- **Claim with a local identity - no cloud account.** For a factory-reset station,
  Home Assistant now mints the openId, the account id and the device key itself and
  writes them over Bluetooth: no OUPES / Cleanergy account, no password, no
  internet. A minted account id stays inside the 5-byte wire field *and* below
  2<sup>31</sup>, because an integer overflow in station firmware is the one
  mistake here that Home Assistant could not undo. Not yet verified against a
  physical station; the README spells out what trying it costs.
- **An identity step in setup.** When a Guardian's identity could not be recovered
  from the cloud, setup asks for it there and then, instead of creating an entry
  that silently drops the connection and leaving the fix for the options dialog.
- **Identity provenance is recorded, not guessed.** A locally minted openId is
  indistinguishable from a vendor-assigned one - same length, same alphabet, same
  `o` prefix - so where it came from is stored with the entry and the options dialog
  states it. That is the difference between "this station is missing from my cloud
  account" being an explanation and being an afternoon of debugging.

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

### Tests

- 8 new tests in `tests/test_local_identity.py`: minted openIds keep the vendor
  shape and land at the correct offsets in the AUTH frame, the accepted `0x01` SSID
  pad byte survives minting, and minted account ids are proven to fit both the
  5-byte wire field and a signed 32-bit int.

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

# Changelog

All notable changes to this fork. Versions are published as [GitHub
Releases](https://github.com/bandit8623/oupes-mega-ble-hass/releases); HACS users
get them as soon as the tag exists.

This fork tracks
[`acalcutt/oupes-mega-ble-hass`](https://github.com/acalcutt/oupes-mega-ble-hass)
(MIT) and keeps its integration domain, so releases are drop-in upgrades.

## 1.4.17 - 2026-10-21

### Fixed

- **`soc_slope_w` no longer reports 0 W while the battery is charging**
  when the firmware lies on the main-pack charge dpid (24): the main
  pack's share is now inferred from total input power minus the externals
  that are visibly charging. Verified against rack-scale field captures
  (0/1/3/6/8 expansion packs, main unit once).

- **SoC slope fallback for main-unit-only installs**: with no externals
  reporting, the fallback now gates on net input power instead of a
  non-zero charge register, so a lying zero no longer suppresses the
  runtime/charge-rate estimates.

### Changed

- **SoC sample recording throttled to one sample per 30 s.** The 1-2 s
  live-push cadence starved the 240-sample ring buffer below its own
  10-minute slope window, making the fallback fire on micro-movements.
  Live sensor pushes are untouched; only the slope history de-noises.

### Verified

- Live soak 2026-10-21: grid→battery transition and the full 100→99→…→70
  descent (8 h, ~13 min/%, monotonic, no adjacent-value jitter) on a
  Guardian v2 + 3-pack rack.

## 1.4.16 - 2026-10-20

### Added

- **`AC Output + Inverter` sensor** - the AC register plus the inverter's
  own appetite, from a piecewise loss curve anchored on measurements
  (57 W awake-idle from the 2026-10-20 BMS no-load day; owner-observed
  500/2100/4000 W points; 6000 W pinned at 85% efficiency by owner
  decision). AC switched off returns the raw register; an ECO-sleeping
  inverter has no overhead to report.

- **All device-page durations speak words now**: Estimated Runtime Left
  rendered as '69,138.00 s' on HA 2026.10 (the seconds-unit duration trick
  the frontend was supposed to prettify no longer is), and External
  Battery Runtime as raw '1,158m'. Both - and every slot runtime - now
  emit '19h 11m' text themselves. The numeric diagnostic 'Remaining
  Runtime' (raw firmware dpid 30, collapsed section) intentionally stays
  numeric history.

### Fixed

- **A blank `product_id` no longer silently loses every computed
  sensor.** Re-pairing a freshly power-cycled unit can discover it before
  its advertisement carries manufacturer data - the flow then correctly
  stores `product_id=''`, which resolves to series "unknown" at setup, so the series-gated entities (stored energy, both
  ETAs, battery status) were refused at creation - and HA's orphan sweep
  then deleted their registry entries permanently. Setup now falls back to
  the live BLE advertisement (the same source the config flow trusts) and
  self-heals the entry with the learned id. (Owner-hit 2026-10-20 after a
  device repair + entry reload; also required an active boot scan to warm
  the discovery cache, which is why the fallback persists what it learns.)

### Changed

- **`Estimated Time To Full` answers in words when it refuses numbers**
  (Not charging / Full / Nearly full) and formats real durations itself.
  Device-page `unknown` is not UX (owner rule 2026-10-20).

## 1.4.15 - 2026-10-20

### Fixed

- **Estimated runtime no longer refuses to exist at light loads.** Runtime
  math divided by output-register load only, which excludes the station's
  own awake-idle draw (measured: 57 W on Guardian V2, 8 h no-load day,
  BMS-energy route; invisible to every watt sensor). At filter-class loads
  that omission pushed the answer past the one-week honesty ceiling, so the
  sensor reported unknown while a correct number was one addition away.
  The measured idle draw is now a per-series constant (unknown series get
  0.0 - an unmeasured number never silently enters the math).

## 1.4.13 - 2026-10-19

### Fixed

- **Home Assistant can no longer be frozen by an unreachable station.**
  Config-entry setup used to await the first BLE poll with no deadline;
  when a proxy held a stale session the poll looped forever, bootstrap
  parked on "Waiting for integrations to complete setup", and the entire
  dashboard - including the automations meant to alert on it - never
  loaded. The first poll now gets a 90-second cap; past that the entry
  defers with `ConfigEntryNotReady`, HA finishes booting normally, and
  the integration retries in the background.
- **Debug CSV logging never touches the event loop.** All attr/raw log
  writes moved to Home Assistant's executor via a single `_csv_append`
  helper; file headers are created lazily on first write instead of at
  coordinator construction. HA 2026 was logging blocking-file-open
  warnings against the old code path.

- **Guardian 6000 V2 / D5 V2 DC sensors are named for the connector the
  owner actually has.** On `95haDY` the DC input sensors now read **DC XT60
  Power 1/2** (was "DC XT60 Input 1/2") and **DC XT60 Voltage 1/2** (was
  "DC Input 1/2 Voltage", renamed when dpid 115 shipped in v1.4.9) - one
  consistent vocabulary per device page. Other models keep the generic
  "DC Input …" names: no product ID gets a connector name unless someone
  has looked at its case. Entity IDs and history are untouched (identity
  derives from the sensor key, not the name).

### Added

- **Three honest battery-intelligence sensors (Guardian / D5 family).**
  `Battery Energy Stored` (Wh) sums SoC × 4,608 Wh nameplate over the main
  unit and every expansion pack reporting - the ceiling follows the
  hardware as packs are added or switched off. `Estimated Runtime Left`
  divides it by the **net battery drain** - all measured outputs (AC + 12 V + USB-C + USB-A; dpid 4
  alone is AC-only, proven from 170k logged packets), and `Estimated Time
  To Full` divides the deficit by *net* charge input (dpid 21 minus live
  load, so passthrough watts never flatter the answer). Both time sensors
  refuse rather than lie: idle loads, already-full, net-discharging and
  beyond-a-week horizons all report unknown - the failure mode that makes
  the firmware's own runtime read nonsense near full charge. Series with
  unverified nameplate capacity (Mega) get none of the three.
- **`Battery Status` text sensor** (Guardian family): Charging / Discharging / Full / Idle, computed from the
  same net-input math as the time sensors - so when they rightly report `unknown`, this one says why instead of shrugging., not removed.** It now lives in
  the device's Diagnostic section - still enabled, still logging history
  for comparison - but no longer sits next to the estimate that replaced
  it.

## 1.4.12 - 2026-10-17

### Fixed

- **The stop-time BLE release is now thread-safe.** Home Assistant can fire
  its stop signal while our listener callback runs on an executor thread;
  `hass.async_create_task` from a non-loop thread is rejected by HA 2026's
  frame guard, which silently skipped the disconnect. The visible stall
  this caused needs **two or more Bluetooth proxies within reach of the
  station**: observed in the wild when two overlapping restarts left the
  station linked to a *second* proxy, stopped advertising, and unreachable
  for 22 minutes (an HA-core reclaim gap - see
  `docs/HA-CORE-BLUETOOTH-RECLAIM-ISSUE.md`). Single-proxy installs share
  the skipped-farewell race but did not show this stall in practice;
  recovery there is normally prompt. The release now hands off via
  `loop.call_soon_threadsafe`, which is valid from any thread.

## 1.4.11 - 2026-10-17

### Fixed

- **The integration now says goodbye to the station before Home Assistant
  dies.** BLE is released at the very first moment HA begins shutting down
  (the stop bus event), instead of whenever the config-entry unload queue
  reaches us. On hosts with a short stop grace (the ~10 seconds a `docker
  restart` gives), the old timing could be outrun by the kill signal - the
  ESP32 Bluetooth proxy then kept a zombie GATT link, answered nothing, and
  every later connection failed with GATT errors until the proxy was power-
  cycled. Field-confirmed twice on 2026-10-17; the fix makes the restart
  race unreachable regardless of host grace settings.

## 1.4.10 - 2026-10-17

### Fixed

- **Mega installs no longer get two phantom voltage entities.** The DC input
  voltage sensors added in 1.4.9 keyed themselves to synthetic data keys
  (11501/11502) that only the Guardian/WP packed-power split can produce, but
  the sensors were not gated to that family - every Mega install created them
  and every Mega install watched them sit `unknown` forever. They are now in
  `_WP_ONLY_SENSOR_KEYS` alongside the two power sensors that got this gating
  in 1.4.7.
- **No sensor for a connector you do not have.** Any entity keyed to a derived
  split key (2301/2302/11501/11502) now stays unavailable until THIS station
  has actually reported that data. On the original Guardian 6000 (`oB6OKs`,
  one Anderson input, dpid 23/115 behaviour uncaptured) the split entities
  will be absent rather than permanent `unknown` rows.

### Added

- `docs/FIELD-TEST-ORIGINAL-GUARDIAN.md`: a ten-minute owner checklist that
  settles the three open dpid questions for the original Guardian, plus a
  draft path for the compatibility report it produces.
- Three regression guards (203 tests total) that fail the build if a derived
  key ships without family gating or a split entity renders on a station that
  never sent the data.

## 1.4.9 - 2026-10-16

### Added

- **DC input voltage sensors** (Guardian V2): the packed input-voltage field
  (dpid 115) is now split unconditionally into `dc_input_1_voltage` and
  `dc_input_2_voltage` — two unpowered inputs are a meaningful 0.0 V + 0.0 V,
  so there is no absurd-value gate and no misleading sum. Which half is which
  physical XT60 was established by the owner's unplug test on one unit; the
  wire itself never names a connector, and the docs say so.
- **Combined Battery Reserve** (`battery_reserve`): one sensor averaging main
  pack plus every external pack reporting this update (0-8 packs, silent
  slots skipped, zero treated as data). The math lives in the HA-free
  `protocol.average_pack_soc()` so it is unit-tested, not YAML-template
  per-house math.

### Changed

- **Guardian no longer publishes a USB/XT90 output switch.** Field testing
  (two enable-writes, multimeter across the USB ports) showed the firmware
  ignores group bit 2 on this series; publishing a control the device refuses
  teaches users the integration lies. The 12 V/car switch is labeled
  **DC Output** to match the single physical DC button on the front panel.
  Orphaned entities are filtered from setup; remove stale registry entries via
  Settings → Devices → remove service entries if present.

### Documentation

- README: app/cloud + HA/BLE coexistence — the one-client rule is Bluetooth
  only; the app over Wi-Fi and HA over BLE run side by side indefinitely.

## 1.4.8 - 2026-10-15

### Fixed

- **BLE proxy wedge after Home Assistant restarts.** Every config-entry
  reload or HA restart leaked the station's GATT connection onto the ESP32
  Bluetooth proxy: `async_unload_entry` never stopped the continuous task
  nor disconnected its BLE client, and the task's `finally:
  await client.disconnect()` was being cancelled before the disconnect
  could reach the radio. Two or three leaked slots exhaust a proxy's tiny
  connection pool and wedge BLE for *every* device on it (field-observed:
  station and two Yale locks all failing with `ESP_GATT_ERROR` /
  connect timeouts until the proxies were power-cycled). The coordinator
  now tracks the open client, `async_shutdown()` cancels the task *and*
  disconnects it with `asyncio.shield()` so the goodbye survives
  cancellation, and unload awaits it. Setup-cancellation also propagates
  unchanged instead of being converted to `ConfigEntryNotReady`, which had
  been holding a reload task past HA's shutdown final-write stage.

### Tests

- 3 new tripwire tests for the teardown contract (185 total).

## 1.4.7 - 2026-10-15

Live speed. On a continuous connection, Home Assistant now hears from the
station when the *station* speaks, instead of when this integration gets around
to asking. Field-tested on a live Guardian 6000 V2 against the running 1.4.5
install on the same box before a single tag moved.

- **Notification-driven pushes replace the 10-second heartbeat.** Every value
  the station sends over the open BLE link is published to HA within a short
  throttle window. Measured on the live station: entity updates that arrived
  every ~8-10 s now land every ~2-3 s - the station's own telemetry cadence,
  which is the floor no software can beat. Polled (non-continuous) mode is
  unchanged.
- **New user option: Live update throttle.** *Settings → Devices & Services →
  your OUPES entry → Configure (the cog)*, right under Poll interval. Range
  1-30 s, default 1, per entry. Field measurement: 1 s and 2 s cost the same
  HA-core CPU to two decimals (~0.25 %), so pick by feel.
- **Fixed: live pushes could run off the event loop.** The field test caught
  HA's own frame check warning that state writes were happening on an executor
  thread - a latent bug the heartbeat design had been living with. The push
  path now verifies its thread and hops to the event loop, with a one-time
  WARNING carrying the real caller stack. Zero violations since on the test
  box.
- **Fixed: `AttributeError: 'HomeAssistant' object has no attribute
  'async_call_later'`** in the deferred-push path (it lives in
  `homeassistant.helpers.event`). Caught during the same field test; it only
  bit the throttled pushes, which is exactly the kind of thing field tests are
  for.
- **README: Tuning section.** Every options-dialog field in one table, with
  the navigation written the way the UI shows it - including the cog.

## 1.4.6 - 2026-10-15

One behavioural change, warn-only: a hand-typed user ID that looks like a typed
placeholder now says so in the log at the moment it is accepted, instead of failing
later as a Bluetooth mystery. Nothing else moves; v1.4.5 installs upgrade in place.

- **Placeholder-shaped user IDs are named in the log.** The binding key is
  `md5(user ID)` truncated to ten characters, so a wrong typed ID still derives a
  perfectly well-formed key - the station refuses it about four seconds after AUTH,
  which reads exactly like a range problem. Now all three places that accept a
  hand-typed user ID (the account-number step, the manual identity step, and
  Configure/options) emit one WARNING explaining the shape problem and how to fix
  it. Cloud-fetched IDs are not judged: the vendor supplied those.
- **The check can warn; it cannot lock out.** Only strictly ascending or descending
  digit runs (`123`, `4321`) are flagged. Repeated digits (`999`) and short IDs stay
  plausible, and `0` keeps its "not set" meaning - a hard reject would be an account
  lockout for whoever holds the earliest account on the platform, which is the
  failure mode the v1.4.6 gap file argued about in advance.
- **The warning never echoes the number.** The user ID is the seed of that
  station's Bluetooth credential, so the log line describes the shape (`4-digit
  descending run`) and not the value - the same discipline as the field-name-only
  diagnostics in the cloud identity code. Pinned by a test.
- Docs: the second-user field test is recorded in the pairing section - a Guardian
  6000 V2 installed from scratch by a different user, over Bluetooth, authenticating
  with the same credentials they use to log into the official OUPES/Cleanergy app,
  paired on the first attempt.
- The three strict-xfail gap tests that drove this release were deleted with the
  fix, as `tests/test_known_gaps_for_1_4_6.py` instructed; they now stand as
  ordinary regression tests.

## 1.4.5 - 2026-10-15

Two behavioural fixes to the solar input data, both on the Guardian 6000 V2 / D5 V2
(product id `95haDY`). Nothing changes for other models.

- **Both DC inputs now report 0 W when nothing is producing, instead of `unknown`.**
  The split of attr 23 into two uint16 halves used to fire only when the combined value
  looked too large to be plain watts (>= 65536). Zero is not too large, so at night, on a
  cloudy day, or with nothing plugged in, the aggregate sensor published 0 W while both
  per-input sensors went Unknown. If your energy dashboard recorded gaps or a zero that
  disagreed with its own two halves, this was the cause - it was never a wiring fault.
  Once a field is known to be packed, 0 has exactly one decomposition, so the split is
  now driven by the product id, never by the reading. It is enabled for `95haDY` alone:
  the other WP-family ids have no capture proving their attr 23 is packed, and a wrong
  entry here writes a wrong number onto someone's energy dashboard permanently.
- **The two inputs are renamed on that product to `DC XT60 Input 1` and `DC XT60 Input 2`.**
  The connector type is reported by the owner of the unit tested here, not read off the
  wire, and it is attributed as such in the docs. Your `entity_id` does **not** change -
  identity is derived from the sensor key, not the name - so dashboards, templates and
  automations keep working and no history is orphaned. Only the display name changes, and
  a fresh install will slug its entity_id from the new name, so copy entity ids from your
  own Home Assistant rather than from a document. The two halves are independent readings
  that usually differ (captured pairs include 1999 W / 2001 W and 647 W / 2002 W); the
  only guarantee is that they sum to Solar Input Power. Which of the two identical XT60
  sockets is Input 1 is still unverified - shade one string and watch which entity drops.
- Docs: entity count is now stated as a rule (about 29 for the station plus five per
  expansion pack that reports) instead of one unit's number; a stale "10 minutes" stale
  timeout corrected to 15; claims about removing the station from the app, pairing
  timings, and firmware versions scoped to what was actually observed; the wire-format
  finding recorded (continuous telemetry uses TLV tag `0x0A`, so grepping a hex capture
  for a dpid finds matches that are not real).
- Shipped help: the `Cloud userId` route corrected to the entry's cog, then Configure;
  an unreachable orphaned string block deleted; the "go back" checkbox given the label it
  was missing.
- New guards, all sabotage-verified: flow steps and fields must have real labels in both
  string files; docs may not quote a stale timeout or poll interval; any line naming
  XT60 must carry its provenance; the per-product rename must stay keyed by product id
  and must not move `unique_id` off the sensor key.

## 1.4.4 - 2026-10-15

Text and defaults only. No stored key, step id, or config key changes, so existing
entries are untouched and nothing on a running station is affected.

- The pairing control that asked for an "account number" now calls it what it is: the
  **Cleanergy user ID**. Renamed in the pairing-method option, the screen title, the
  field label, and the surrounding help text, plus the log lines and issue templates
  that used the old phrase. There is no such thing as an account number in this system,
  and readers went looking for one in an app that never showed it.
- That field's help text now says where the number actually comes from, instead of
  leaving people hunting through the app for a screen that does not exist.
- Four error messages across the config and options flows told people the Cleanergy app
  shows the value "on the device's settings screen" or "in the account screen". Neither
  screen exists on the app as shipped, so the advice could not be followed by anyone. The
  affected strings are `cloud_identity_no_open_id` and `invalid_user_id` in both flows.
  They now name the two routes that were checked on a real install: the `Cloud userId`
  field under the entry's Configure dialog, and the vendor login response field `uid`.
- Quick Start: setup steps expanded to cover waking the station before the first connect,
  the cloud-login route to the user ID, what a successful setup looks like (about fifteen
  seconds, roughly 44 entities, DC inputs reading unknown while nothing is plugged in),
  and why entities can come up *unavailable*. The before-you-start box now includes
  turning the phone's Bluetooth off, since the first reconnect after the phone let go took
  18 seconds against 12 - not a malfunction, but a real effect worth knowing about.
- Documentation claimed a pairing route called "Specify manually" leading to an "Other /
  already-paired device" choice. Neither string exists in the integration. Replaced with
  the two real routes, checked against `config_flow.py`: add from the discovered device
  card, or type the Bluetooth MAC address into the manual dialog. Every control named in
  the docs is now one that ships.
- Front page: a new step telling you to **disable** the entry rather than delete it when
  you want the app back for a setting change or an over-the-air firmware update.
  Disabling releases Bluetooth and keeps the entities, so dashboards and automations
  survive the round trip; deleting costs them.
- Documented that `Cloud userId` only holds a value when the entry came through the
  email-login path. An entry made by typing a device key shows `0` there, which is not a
  fault.
- The terminology guard no longer exempts any shipped label. It previously allowed the
  two controls that carried the old phrase inside bold quotes; that exemption list is now
  empty and the phrase is banned across docs, shipped strings, `config_flow.py` and the
  issue templates. The test also asserts the renamed labels still exist, so the ban cannot
  be satisfied by quietly deleting the control that needed renaming. Both it and
  `tests/test_no_phantom_screen_claims.py` are shown failing on planted violations, and the
  phantom-screen test was verified against the exact string that shipped in 1.4.3.


## 1.4.3 - 2026-10-14

### The error strings were filed where Home Assistant never looks

Home Assistant resolves a config-flow error at
`component.<domain>.<flow>.error.<key>`. The key inside `errors[...]` names the *field* the
message renders under; it does not move the lookup path. Error blocks nested under a step are
therefore dead text, and hassfest rejects them as
`not a valid option at 'options.step.init.error'` - the failure that was red on the upstream
PR all day.

Twenty-five strings across eight steps were in that state, in **two spellings**: `error`
(singular: three config steps plus the options flow) and `errors` (plural: six steps). So the
wording written for a failed cloud login, an unusable account number, a refused key and an
unconfirmed local claim had never displayed once - including the openId sentence reworded in
1.4.1, which went into a location no code path opens.

- Where nested and flow-level wording collided, **nested wins deliberately**: the flow-level
  text still told people to "enter openId and userId manually", the myth this work disproved,
  while the nested text reflected what the station actually does.
- `wifi_unsupported_guardian` was raised from two steps with two different texts. HA allows one
  string per key per flow, so they are merged instead of one losing quietly.
- `no_device_key` and `required` carried translations for messages no code path emits. Deleted.
- `validate.yml` now runs on `push` to `main`/`release`, not only `pull_request`. A branch that
  opens no PR was never hassfest-validated - which is how this survived a release cycle with a
  green tests workflow. The workflow was right; it was asked the wrong question.
- Issues were disabled on the fork since its creation. That, not the code, is what HACS
  validation was failing on, and it also meant the compatibility-report template other owners
  need could not be reached. Enabled.

### Added: `tests/test_strings_against_hassfest.py`

A local subset of Home Assistant's own `script/hassfest/translations.py` schema - the file that
emits the rejection message. Asserts step bodies contain only keys HA reads (whitelist, not a
list of the spellings already noticed), every `data_description` key has a matching field,
placeholders are valid identifiers, and every key the flow can raise resolves at flow level in
both `strings.json` and `translations/en.json`. Runtime-built keys
(`f"cloud_identity_{reason}"`, `self._pairing_error`) are derived from the real constants.

### Tooling
- `scripts/preflight.py`: one command to run before any commit or push. Tests (both pytest and
  the standalone CI path), module compilation, JSON validity, manifest version against the newest
  changelog header, secret scan of **tracked** files against a list kept outside the repository,
  tracked build junk, workflow triggers, and `--remote` for the repository settings HACS validates
  (which is what its failure was actually about). It refuses with exit 1 and named failures.

  Verified by sabotage rather than by optimism: nested `error`, nested `errors`, a version bump
  with no changelog entry, a committed credential, and a removed CI trigger all produce failures.

**The last test feeds both real bugs plus three invented ones back through the checkers and
requires rejection**, because round one fixed `error`, scanned for `error`, and wrote a test for
`error`; round two found `errors`, which neither the scan nor the test looked for. A checker that
cannot fail is the same failure as the diagnostic sensor that was documented but never existed.
`test_every_cloud_identity_reason_is_translatable` was itself reading `step.<step>.errors.<key>`
- a test enforcing the wrong location, which is affirmative evidence the layout was intentional.
Retargeted at flow level, and now asserts the nested block is absent.

## 1.4.2 - 2026-10-14

### Editing the account number kept the stale device key

The options form shows the device key and the account number on the same screen, and saving did
`raw_key or current_key`. Type a new account number - which is what you do after re-pairing the
station to a different Cleanergy account - leave the key box at the value already in it, and you
stored the **old** key next to the **new** account number. The station authenticates against the
`(account number, key)` pair the vendor app wrote, so it refused the frame, and the failure looked
exactly like the app having failed to re-pair. Nothing in the UI said a second field was still
holding an old credential.

Extracted as `resolve_key_on_account_change()`: a typed key always wins; a stored key is replaced
**only** when it equals `md5(previous account number)[:10]`, the only way to know we made it; with
no previous account number its provenance is unknown, so it is kept rather than guessed about; and
with no stored key at all, deriving beats storing nothing. Nine tests, two of which exist to prove
something is *not* overwritten.

## 1.4.1 - 2026-10-14

### Stop shipping the claim we disproved, and mark what we do not know

Three things in 1.4.0 were wrong, found by reading the release against the measurements instead
against the earlier drafts.

- The coordinator tested `not (open_id and user_id)` and so warned on **every** account-number
  setup that the station "needs the cloud openId" - firing on the exact path that proves openId is
  irrelevant. Now tests `not user_id` only, and instead warns when a WP station connects and drops
  immediately, which is the signature of a rejected identity.
- `docs/GUARDIAN-WP-BLE.md` described a diagnostic sensor with frame counters **that has never
  existed**. Removed. Two other doc claims were wrong the same way: expansion count is derived from
  the packs that report rather than read from a register, and the aggregate solar register is the
  *sum* of the two DC inputs, not a suppressed duplicate.
- The README stated openId as a requirement, contradicting the same release's headline finding.

### Added

- `docs/GUARDIAN-WP-BLE.md` **section 12, "How much of this is actually known"**: every claim, how
  it was established, and where it stops being safe - naming the n=1 scope (one Guardian 6000 V2,
  firmware 1.2.0, one account) instead of letting confident prose imply generality.
- A **compatibility-report issue template**, the only way the verified-models table grows past one
  row: model, firmware, product id, BLE name, how it was set up, whether the derived key was
  accepted, whether openId was needed.

## 1.4.0 - 2026-10-14

### The station never checked the openId, and the key is a hash of the account number

Two claims that had been repeated through the docs, the READMEs and the setup flow
turned out to be wrong, and both were blocking setups that would have worked.

**The openId is not verified.** A Guardian 6000 V2 was sent its real key and real
account number with the openId field zero-filled: accepted, 43 telemetry frames.
The same frame with a foreign account number: refused. So the station reads the key
and the userId and ignores the openId, which is the value the setup flow insisted on
and which the vendor's email-and-password API has never returned. The identity step
now asks for the account number alone, `CloudIdentity.ok` no longer requires an
openId, and the guide stopped sending people to hunt for one.

**The binding key is `md5(userId)[:10]`.** Read out of the Cleanergy APK
(`KeyUtils.createDeviceKey`), and confirmed against the station. That makes the
account number the only credential a setup needs, so there is a new pairing method,
**Use my Cleanergy account number**, which derives the key and writes nothing to the
station. Cloud login uses the same derivation instead of falling back to a claim the
station refuses.

Also documented from measurement, having been given the opposite advice earlier:
removing a station in the Cleanergy app wipes the pair that Home Assistant
authenticates with, while force-stopping the app only releases the radio. Nothing in
Home Assistant's own UI can write to a station; pairing is the only path that does.

Tests: `tests/test_key_derivation.py` pins the derivation to the two keys this
station actually accepted and refused, so a refactor cannot quietly change the hash.


### Added

- **`docs/GUARDIAN-WP-BLE.md`** — a complete pairing guide for `WP` stations, written
  from measurement rather than guesswork: where `openId` and `userId` come from and
  which of them the vendor API will not give you, how the device key is derived, what
  each of the station's refusal frames actually means, the app-versus-Home-Assistant
  single-connection conflict, and the privacy properties of the vendor's plain-HTTP
  API. Linked from the top of the README.

### Fixed

- **The `WP` device key is `md5(userId)` truncated to ten characters**, matching
  `KeyUtils.createDeviceKey()` in the vendor APK. This had been measured before and
  written off as not working: the probe that "disproved" it was run against a station
  still bound to the phone, and a bound station refuses every outsider whatever key it
  is offered. Both facts are now in the guide, along with the frame that tells the two
  cases apart, because the symptom of a wrong key and the symptom of a bound station
  are otherwise indistinguishable.

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

## 1.3.0 - 2026-10-13

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

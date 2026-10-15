# OUPES / Cleanergy "WP" stations — the complete pairing guide

Covers the **Guardian 6000 V2** and every other station whose Bluetooth name starts with
`WP-` rather than `TT-` (the OUPES **Mega** units). These are not the same firmware:
they authenticate differently, and the pairing screens in this integration look
different because of it.

Everything here was established by measurement against a Guardian 6000 V2
(firmware 1.2.0), not by reading vendor documentation, which does not exist.

---

## 1. What you need before you start

| Requirement | Why |
| --- | --- |
| A Bluetooth proxy within a few metres of the station | Home Assistant on a Pi/VM usually has no radio. The station answers ~15 s after the last app contact and then sleeps. |
| The Cleanergy (or OUPES) app installed, and an account | The identity values you need only exist after the station has been paired by that app. |
| The station powered, on a wall socket, not in "storage" mode | A sleeping station is not advertising. |
| Nothing else connected to the station | **It serves exactly one Bluetooth client at a time.** |

The last row is the one people get caught by, so it is worth stating as a rule:

> **The app and Home Assistant cannot share the station.** When HA holds the
> connection, Cleanergy sits on "connecting" forever, and vice versa.

---

## 2. What the pairing actually asks for

Two values. That is all.

| Value | Example | Where it comes from |
| --- | --- | --- |
| **Bluetooth address** | `AA:BB:CC:DD:EE:FF` | The station's own MAC. Your proxy's device list, or Home Assistant's discovered-device list. The station advertises as `WP`. |
| **User ID** | `24680` | Numeric id of the Cleanergy account that paired the station. The app does not show it anywhere - §3 gives two ways that do. |

The device key is not a third thing to hunt for. It is `md5(user ID)`
truncated to ten characters, which this integration computes for you (§4). The
station was written with exactly that pair when the app paired it.

**There is no openId requirement.** This was measured rather than assumed: a
Guardian 6000 V2 received its real key and real user ID with the openId
field **zero-filled**, and answered with 43 telemetry frames. The same frame with
the *user ID* wrong was refused. So the station checks the key and the
user ID and ignores the openId completely.

That is worth stating bluntly, because the openId is the value that made this
station look un-supportable for months. It looks like a WeChat openid, it is
returned by no email-and-password API, and it was never needed.

## 3. Getting your user ID

**The Cleanergy app does not display this number.** There is no account screen, no
device page, nothing that shows it - so do not spend an evening hunting for one. Two
ways that do work:

* **From an entry you already have working.** The cog on the OUPES card →
  **Configure**, and read the **Cloud userId** field, which comes pre-filled. It only
  holds a real number if that entry went through the **Fetch key from Cleanergy cloud
  account** login at some point - that request is what looks the value up. An entry
  built by typing a device key directly never supplied one, and shows `0`.
* **From the vendor API**, which is the same call the app itself makes, and which the
  integration runs for you when you pick the cloud login above:

```
POST http://api.upspowerstation.top/api/app/user/login
Content-Type: application/json

{"mail": "you@example.com", "passwd": "your password",
 "lang": "en", "platform": "android", "systemVersion": 34}
```

The response carries it as `info.uid`. Three things about that call will
otherwise cost you an hour:

* the password is sent as **plaintext**, not hashed;
* the field is **`uid`**, not `userId`;
* the endpoint is plain **HTTP**. There is no TLS. Do not run this from a network
  you do not trust, and do not paste a response into a public issue.

You normally never need to make this call. Home Assistant's **Use my Cleanergy
user ID** option asks for the number directly, and **Fetch key from Cleanergy
cloud account** (§5) logs in and reads it for you.

### Why there used to be a second value here

Earlier revisions of this guide told you to find an `openId` as well, and warned
that a WeChat-provisioned account would never yield one. Both statements were
wrong in the way that matters: the advice was unnecessary and the blocker was
imaginary. The value was carried forward from an old pairing into later
experiments, always in the same frame as the two values that do get checked, so
no test had ever been able to tell that it was decoration. It has now been
removed from the frame and the station streams without it.

If your entry already has an openId stored, leave it: the station ignores it
either way.

## 4. The device key

The app's own generator, taken verbatim from the Cleanergy APK:

```kotlin
fun createDeviceKey(userId: String) = encodeMD5(userId).substring(0, 10)
fun createDeviceKey() = createDeviceKey(NetApi.getUserId())
```

`encodeMD5` is ordinary lower-case hex MD5. So for a userId of `24680`:

```
md5("24680") = 9256f177e0...      -> device key: 9256f177e0
```

That single line is worth underlining, because it is the opposite of what a
"device key" suggests:

> **The key is derived entirely from your account id.** It is not secret per station,
> it is not rotatable by the vendor, and it is the same for every station on your
> account.

Practical consequences:

* You can compute it in one command:
  `python -c "import hashlib;print(hashlib.md5(b'24680').hexdigest()[:10])"`
* If you buy a second-hand station, the previous owner's userId — and therefore the
  key — is all that stands between you and it, until you claim it with your own
  identity.
* **Pairing the station in the app overwrites the key** with one derived from whichever
  account did the pairing. See §6.

---

## 5. Which pairing screen to use

**Settings → Devices & Services.** If an adapter or proxy in range can hear the
station, it sits under **Discovered**: click **Add**, then **Submit** on the "Found
*name* (address) nearby" confirmation. If it is not listed there, use **Add
Integration → OUPES Mega BLE** and type the address into **Bluetooth MAC Address** -
when a nearby adapter did see the station, that field arrives pre-filled.

Either route lands on **How would you like to provide the device key?**. Pick **Use my
Cleanergy user ID** and enter the user ID from §3, or pick **Fetch key from
Cleanergy cloud account** and sign in, which looks the number up for you. Either way
the key is derived from the number, and nothing is written to the station: the app
already left the matching pair there.

The other options on that screen, honestly described:

* **Fetch key from Cleanergy cloud account** — same result, fewer things to look up.
  It logs in with your email and password, reads your user ID out of the login
  response and derives the key. It needs the station to be in that account's
  device list. Your password is used once and is never written to disk.
* **Enter an existing device key** — the field takes **10 hex characters**, and that is
  checked before anything reaches the station. On this family the value is
  `md5(user ID)[:10]`, so the command in §4 produces it:

  ```
  python -c "import hashlib;print(hashlib.md5(b'24680').hexdigest()[:10])"   -> 9256f177e0
  ```

  **Your user ID does not go in this field.** It is a short decimal number - five digits
  on the account measured here - and a decimal user ID is not 10 hex characters, so the
  form rejects it. Put it in **Use my Cleanergy user ID**, which derives the key itself.
  This option is for the rarer cases: a key you captured from a Bluetooth log, or a
  station whose key is not the derivation, which has not been observed on this family.
* **Create a new device key (requires factory reset)** — claims a blank station
  with a generated identity. **This does not work on this firmware family.**
  Measured twice on a Guardian 6000 V2, once on 2026-10-14 and once after a
  factory reset: the station refuses an identity it did not receive from the
  vendor's app. Choosing this option costs you a factory reset and ends in a
  timeout. It stays in the list because the same code path works on the older
  `"TT"` stations.

Whatever you pick, leave the WiFi fields alone. These stations have no WiFi
integration path, and any text in the SSID field silently switches the frame
format to one the Guardian rejects outright.

## 6. The app and Home Assistant fight over the station

Both want the single Bluetooth connection, and the station only grants one.

| Situation | Result |
| --- | --- |
| HA entry loaded, app open | App never gets past "connecting" |
| App holds the link | HA reports connection failures until the app releases it |
| **You remove the station in the app** | The station forgets the `(user ID, key)` pair it was written with. HA's credentials are now stale and it cannot get back in |
| You re-add the station in the app | The app writes a pair derived from that account's number, which is the same pair if it is the same account |

> **Add the station in the app once, then never remove it.** To stop the app
> competing for the radio, force-stop it or switch the phone's Bluetooth off. The
> app only has to be off the radio, not off the account. Removing it wipes the
> pairing Home Assistant depends on, and the failure looks nothing like its cause:
> HA keeps a connected-looking entity and stale values until you try to re-pair.

Because the key is a pure function of the user ID, re-adding the station to
the **same** account restores the same key, and an entry written with that number
recovers on its own after a reload. Re-adding to a **different** account changes
it, and the old entry is then simply wrong.

If you want the app back for a while: **disable the HA entry first** (Settings,
Devices & Services, the ⋮ menu on the OUPES entry, Disable). That releases the
radio and keeps every stored value.

Disabling and removing are **not** the same thing, and the difference is not what they
do to the station. Neither one writes to it - nothing in Home Assistant's own UI can -
so you can disable, re-enable, even delete and re-add an entry without changing what
the station holds. Only pairing writes.

The difference is what they do to Home Assistant:

| Action | Station's stored pair | The entry | Its entities | Your dashboards and automations |
|---|---|---|---|---|
| **Disable** | untouched | kept | kept, marked *unavailable* | go quiet, come straight back on re-enable |
| **Re-enable** | untouched | reconnects with stored credentials | back on their own | back |
| **Remove (delete)** | untouched | **gone** | removed with it, **or left behind** to clean up by hand | dead until you redo the whole pairing screen |

One rule when handing the radio back: the station serves **one** Bluetooth client, so
force-close the app - or switch the phone's Bluetooth off - **before** re-enabling. If the
entities come back *unavailable*, the app is almost certainly still holding the link.

So a removed entry really can be rebuilt - the key is `md5(user ID)[:10]`, so nothing is
lost that you cannot retype - but you are throwing away the entry and its entities to
release a radio that disabling releases for free, and the cleanup is not even guaranteed
tidy: on the machine writing this guide, entity entries outlived the config entry they
belonged to and had to be deleted separately. Remove only when you actually want the
entry gone, such as replacing a broken setup.

### Measured, not inferred

Both directions were tried on a Guardian 6000 V2 with two ESPHome Bluetooth
proxies, on 2026-10-14:

* **HA loaded, app opened:** the app sat on "connecting" and never reached the
  station, while HA kept streaming (910 W at the moment of the attempt). One link,
  and the app does not get to negotiate for it.
* **HA entry disabled, app opened:** the app still could not connect on the first
  attempt. The likely reason is worth knowing, because it makes you think the
  station is broken: while HA holds a continuous connection the station never
  sleeps, and when you release it, it goes back to sleeping quickly. Wake it with
  the power button and try again immediately.

### When a firmware update needs the app

Over the air updates are the vendor app's job, so this day may come. The sequence:

1. **Disable** the HA entry (Settings, Devices & Services, the ⋮ menu on the OUPES
   entry, Disable). Do not remove it, and do not remove the station in the
   app. Disabling frees the radio while keeping the entry and its entities, so the
   dashboards and automations built on those entities are merely unavailable and come
   back on re-enable. Removing the entry deletes them, and the setup has to be done
   again from the pairing screen.
2. Wake the station, connect the app, update, and let the station reboot.
3. **Force-close the Cleanergy app** before you touch Home Assistant again. Kill it, do
   not just background it or leave it sitting on the update screen. Switching the phone's
   Bluetooth off works too, and works even when the app is wedged.

   The station serves **one** Bluetooth client at a time. Measured above: while HA held
   the link the app could not reach the station at all. The limit is symmetric, so the
   reverse holds too - if the app still has the link, Home Assistant cannot get it, the
   entities sit *unavailable*, and it looks like the update broke the integration.
4. **Re-enable** the HA entry. It reconnects with the credentials it already has. If it
   comes up *unavailable*, the app still owns the radio: close it and reload the entry.
   Nobody has measured what an update does to the station's stored pair, so if the link
   still will not come back with the app definitely closed, work through
   [Troubleshooting](#6-troubleshooting) rather than guessing - and do not "fix" it by
   removing the station in the app, which is the one step here that really can cost you
   the pairing.

If the update rotates the key, the symptom after step 3 is HA connecting and then
getting no telemetry. Fix it by re-adding the station to the same account in the app
and re-running the setup with that user ID - or just re-enable first and see,
because the key is derived from the user ID and an update that changes it
would have to change that derivation too. Nobody has seen this happen; the reason to
write it down is that the failure looks like a broken integration and is not.

---

## 7. Bound, unbound, and what the station actually says

The station's behaviour on the wire is legible if you know the frames, and it settles
most "why won't it pair" arguments in one reading.

| What the station sends | Meaning |
| --- | --- |
| `03 00 00 20 00 <device id> …` | Acknowledged you. Good. |
| `01 80 01 01 00 …` | Your identity was accepted. |
| `03 80 01 01 00 …` | Your **claim** was accepted. |
| `03 80 01 01 01 …` arriving **unsolicited**, right after you subscribe | The station is announcing that it already holds a key — it is **bound**, and it will drop you about two seconds later whatever you send. |

That last row is the trap. It looks exactly like a rejection of your identity frame and
is frequently mistaken for one. It is not a verdict on your key; it is a statement
about the station's state. Testing keys against a bound station tells you nothing,
because a bound station refuses every outsider regardless of the key.

To get a station into the state where an outside claim can succeed you need it
**unbound**, and:

* Removing the device from the app is supposed to unbind it. On firmware 1.2.0 it
  did not reliably do so, which is what made key-probing experiments read as
  "every candidate rejected" when the real reason was that the station was still
  bound to somebody and refuses all outsiders regardless of key.
* The button combination on the side of the unit is not documented for this model and
  behaves inconsistently: on the unit used here, a long press produced a slow blink
  and the combination that produced a fast blink turned the station **off** instead.
* A factory-reset station still refuses identities it did not get from the vendor, so
  "reset and claim with a key I invented" is not a working path. What it checks is
  the pair: it accepts the user ID and key the app wrote, and refuses an
  invented user ID carrying its own correct `md5`. That second measurement is
  what rules out the station simply recomputing the hash and comparing, so the pair
  really is stored in the station, and the app is the only thing that writes it.

If you need a claim rather than a pair, budget time for finding the real reset
behaviour, and prefer keeping one known-good pairing rather than experimenting on the
only station you have.

---

## 8. "It paired but has no data"

Usual causes, in the order they actually happen:

1. **The pair is stale.** The station was removed in the app since you paired. Re-add
   it to the same account and the pair matches your entry again (§4, §6).
2. **The station is asleep.** Wake it from the app, then work fast — or power-cycle
   and connect within the first couple of minutes.
3. **The proxy is too far.** The station only answers for a short window; a distant
   proxy misses it entirely.
4. **A WiFi field was filled in.** Clear the SSID field. On these stations it is not
   cosmetic — it changes the authentication frame.
5. **Something else holds the connection.** Another HA entry, a phone sitting on
   Bluetooth, a laptop that paired earlier.

What actually helps is the log. Turn on debug logging for the integration
(`Settings → System → Logs`, or `logger:` in `configuration.yaml` with
`custom_components.oupes_mega_ble: debug`) and read it against the table above:
no frames at all means the station never answered; frames with no accepted
authentication means it heard you and refused the identity.

The integration's options also offer **Log raw frames** and **Log attributes**, which
append to CSV files under the config directory. Reach for `raw` last: that file
contains the AUTH frame, so it holds your user ID in the clear.

---

## 9. Data you should expect to see

A Guardian 6000 V2 with two expansion batteries reports roughly 40 entities. The ones
people ask about:

* `dc_input_1_power`, `dc_input_2_power` — this family reports both DC inputs packed
  into one 32-bit field (dpid 23): two 16-bit halves. The parser splits them and puts
  their sum back where the aggregate was, so `solar_input_power` is the total of the
  two rather than a third, double-counted reading.
* `expansion_battery_count` — counted from the packs that actually reported telemetry
  this cycle, not read from a register. The firmware is supposed to answer a pack
  count on dpid 51 but does not on this model, so counting live slots is what works,
  and the number follows hardware changes on its own: unplug a pack and it falls.
* `main_unit_temperature` — the station reports in Fahrenheit; the integration converts.
* `remaining_runtime` — reported in minutes and clamped; a value pinned at the
  configured maximum means the station is telling you "no meaningful estimate".

---

## 10. Privacy, plainly

* The vendor API is HTTP. Your credentials cross the network unencrypted, and this
  integration cannot fix that — it is the vendor's endpoint.
* Your userId, openId and device key are stored in Home Assistant's config entry,
  which lives on disk in `.storage` in clear text. Anyone with access to your Home
  Assistant configuration has them.
* The user ID plus its `md5` prefix is enough to control the station over
  Bluetooth. The number is not a secret in the usual sense, since an app you own
  displays it, but it is the only input the key needs, so treat it as a username
  that must not leak rather than as a harmless integer. Do not post real values in
  issues, forums, or screenshots.
* Home Assistant does not store your Cleanergy password. It is used once, to read your
  identity out of the login response, and is never written to disk.

---

## 11. If you are writing tooling

The frame builders live in `protocol.py`:

* `build_init_sequence(device_key, open_id=…, user_id=…, product_id=…)` — the identity
  frames. The frame format is selected by which arguments you pass, so passing the
  product id and no SSID is what produces the frame a Guardian accepts.
* `build_config_net_info(...)` — the claim frame. Same format-selection rule.
* `WP_DEVICE_ID` is the fixed 11-byte device identifier that appears at offset 5 of
  every WP frame. It is not configurable and is not the station's device id.

The two rules that cost the most time to learn, stated once more:

> The frame format is chosen by which arguments you pass. An identity with **no
> `openId` and no `userId`** selects the legacy frame, which the Guardian rejects
> before killing the link. `userId` alone selects the WP frame, the openId field is
> zero-filled, and the station streams anyway - measured, not inferred.
> The device key is `md5(userId)[:10]`, always lower case, and
> `derive_device_key()` is the only implementation the rest of the code may use.

---

## 12. How much of this is actually known

Read this section before you tell someone else that their station will work.

Everything above came from **one Guardian 6000 V2**, firmware 1.2.0, product id
`95haDY`, one Cleanergy account, one phone, over about two weeks. That is a sample size
of one, and it is stated rather than hidden because the alternative - writing it up as
natural law - is how the openId myth survived as long as it did.

| Claim | How it is known | Where it stops being safe |
| --- | --- | --- |
| Key is `md5(userId)[:10]` | Read out of the vendor's own APK (`KeyUtils.createDeviceKey`), then confirmed against the station | It is the *app's* generator, so it should hold for anything this app pairs. A different app, an old app version, or a station provisioned some other way could differ |
| Station ignores the openId | One experiment: real key and userId, openId zero-filled, 43 telemetry frames back | One firmware version. An update could start checking it, and nothing here would predict that |
| Station compares a **stored** pair, not a recomputed hash | Invented userId carrying its own correct `md5` was refused | One unit. It is the best explanation of the data, not a disassembly of the check |
| Removing the station in the app wipes the pair | Observed directly | One unit. Firmware 1.2.0 also failed to unbind reliably in the other direction, which is the same experiment being flaky |
| Frame layout, `WP_DEVICE_ID`, packed dpid 23 | APK plus wire observation | These are on the wire, so they are the most solid things here |
| ~40 entities, DC input split, expansion count | Measured on a unit with two expansion packs | Your model may report different dpids. The integration degrades to "entity missing" rather than "value wrong", which is the safe direction |

**Not tested at all, so treat as unknown:**

* Every other `WP` model - the D5 6000 Plus and the other D5 V2 variants share the
  family tag but were never touched here.
* Any firmware other than 1.2.0.
* More than one station on an account. The key is per-account, not per-station, so the
  prediction is that a second station works the same way - a prediction, not a result.
* What a firmware update does to the stored pair.
* Stations bought second-hand, and whether the vendor will re-bind one to a new account.
* Mega / `TT` stations, which are a different family and never needed any of this.

If you get this working on a station that is not the one described above, that is a
 datapoint nobody else has. Opening an issue with the model, firmware version and what
you did takes two minutes and is the only way this table grows past one row. If it does
**not** work, that is worth filing too - a wrong claim in these docs is worse than a
missing one, and the openId chapter is the proof of that.


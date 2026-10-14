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

## 2. The four values the pairing asks for

| Value | Example shape | Where it comes from |
| --- | --- | --- |
| **Bluetooth address** | `AA:BB:CC:DD:EE:FF` | The station's own MAC. Easiest to get from your proxy's device list, or from the app's device page. |
| **openId** | 28 characters, usually starting `o` | Your account's identity on the vendor cloud. See §3. |
| **userId** | short decimal, e.g. `24680` | Your account id on the vendor cloud. See §3. |
| **device key** | 10 hex characters | `md5(userId)` truncated to 10 characters — see §4. |

The station authenticates on the **device key**. openId and userId are sent in the
same identity frame and are stored by the station, but the key is what makes it talk.

One thing that has **not** been established: whether the station checks the openId it
receives alongside the key. Every successful pairing so far used the account's real
openId, so do not assume you can invent one. If you can test this on a spare unit, say
so on the issue tracker - it decides whether first-time setup can ever be openId-free.

---

## 3. Getting openId and userId

### userId — from the vendor cloud API

The same API the app uses:

```
POST http://api.upspowerstation.top/api/app/user/login
Content-Type: application/json

{"mail": "you@example.com", "passwd": "your password",
 "lang": "en", "platform": "android", "systemVersion": 34}
```

The response contains `info.uid` — that is the userId.

Notes that will save you an hour:

* The password is sent as **plaintext**, not hashed.
* The field is **`uid`**, not `userId`.
* The endpoint is plain **HTTP**. There is no TLS on this API. Do not run this from a
  network you do not trust, and do not paste the response into a public issue.

If you would rather not script it, `/api/app/user/login` is also what Home Assistant's
**Fetch key from your account** option calls internally — but read §5 first: that
option currently needs the openId to be present in the response, and for accounts that
registered through WeChat it is not.

### openId — the awkward one

`openId` is **not** returned by the email-and-password login on every account. On the
account used to write this guide it appears nowhere in the login response, nowhere in
`/device/list`, and nowhere in `/device/info` — searched recursively, including inside
the stringified-JSON fields. Its shape (`o` followed by 27 base64-ish characters) is a
**WeChat openid**, which is why it never appears in a password login: it belongs to a
different authorisation path.

What actually works today:

1. **Ask the vendor.** Support provisions stations and can state which account a unit
   is bound to.
2. **Capture it from the app.** The app sends the openId to the station inside the
   identity frame over Bluetooth. Capturing that needs a rooted phone or an ESP32 in
   the middle; Android's own Bluetooth log on modern OEM builds is not usable.
3. **Use an account that does return it.** If your login response does contain an
   openId-shaped value, use it.

Be careful reading this across the internet: the openId is your identity to the vendor
cloud. Anyone holding it plus the station's key can bind the station to their own
app. Treat it like a password, and never commit a real one to a public repository.

---

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

**Settings → Devices & Services → Add Connection → OUPES Mega BLE → Specify manually
→ Other / already-paired device → Enter an existing device key.**

Fill in the four values from §2. Leave WiFi alone: these stations have no WiFi
integration path, and any text in the SSID field silently switches the frame format to
one the Guardian rejects outright.

The other options on that screen, honestly described:

* **Create a new device key** — takes the station back from the app by claiming it with
  your own identity. Requires the station to be genuinely unbound. See §7 for how to
  tell, and why it is harder than the button on the side of the unit suggests.
* **Fetch key from your account** — needs the openId to be present in the cloud
  response. For WeChat-provisioned accounts it is not, and the flow says so rather
  than pretending the account is empty.

---

## 6. The app and Home Assistant fight over the station

Both want the single Bluetooth connection, and the station only grants one.

| Situation | Result |
| --- | --- |
| HA entry loaded, app open | App never gets past "connecting" |
| App holds the link | HA reports connection failures until the app releases it |
| You remove the station in the app | Station becomes **unbound**, HA's saved key stops working |
| You re-add the station in the app | App writes a **new** key derived from that account's userId; any key you saved earlier is dead |

So if you ever re-add the station in Cleanergy, recompute the key from that account's
userId and update the Home Assistant entry, or it will look broken for reasons that
have nothing to do with Home Assistant.

If you want the app back for a while: **delete the HA entry first** (or just unload
it), otherwise you are fighting for the radio and the app will appear broken too.

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

* Removing the device from the app **may** unbind it — it did not reliably do so on
  firmware 1.2.0.
* The button combination on the side of the unit is not documented for this model and
  behaves inconsistently: on the unit used here, a long press produced a slow blink
  and the combination that produced a fast blink turned the station **off** instead.
* A factory-reset station still refuses identities it did not get from the vendor, so
  "reset and claim with a key I invented" is not a working path.

If you need a claim rather than a pair, budget time for finding the real reset
behaviour, and prefer keeping one known-good pairing rather than experimenting on the
only station you have.

---

## 8. "It paired but has no data"

Usual causes, in the order they actually happen:

1. **The key is stale.** The station was re-added in the app since you paired.
   Recompute it (§4).
2. **The station is asleep.** Wake it from the app, then work fast — or power-cycle
   and connect within the first couple of minutes.
3. **The proxy is too far.** The station only answers for a short window; a distant
   proxy misses it entirely.
4. **A WiFi field was filled in.** Clear the SSID field. On these stations it is not
   cosmetic — it changes the authentication frame.
5. **Something else holds the connection.** Another HA entry, a phone sitting on
   Bluetooth, a laptop that paired earlier.

Useful check: the integration exposes a diagnostic sensor whose counters say which of
these you are hitting — frames sent, frames received, authentications accepted,
pairings accepted. `received = 0` means the station never answered (asleep, too far, or
wrong proxy). `received > 0` with `auth accepted = 0` means it heard you and refused the
identity — which, if the station is bound, is exactly what it should do.

---

## 9. Data you should expect to see

A Guardian 6000 V2 with two expansion batteries reports roughly 40 entities. The ones
people ask about:

* `dc_input_1_power`, `dc_input_2_power` — the two DC inputs are separate sensors on
  these units; the shared "solar input" register mirrors their sum and is suppressed
  when both inputs are present, so you do not see the same power counted twice.
* `expansion_battery_count` — parsed at byte 79 of the battery report on WP frames,
  which is a different offset than the Mega uses.
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
* openId plus device key is enough to control the station. Do not post real values in
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

> `openId` empty ⇒ legacy frame ⇒ the Guardian rejects it and kills the link.
> The device key is `md5(userId)[:10]`, always lower case.

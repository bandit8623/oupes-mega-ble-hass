# Security Policy

## What this integration touches

Everything runs inside Home Assistant. Telemetry never leaves your network: the
integration speaks Bluetooth Low Energy to the station (directly or through an
ESPHome Bluetooth proxy) and nothing else. The one exception is the optional
**"Fetch key from Cleanergy cloud"** step during setup, which contacts the vendor
cloud to look up a pairing key.

## Sensitive values — treat all of these as secrets

| Value | What it unlocks |
|---|---|
| **Device key** (10 hex chars) | Pairing/authentication with your station over BLE |
| **openId / userId** | On Guardian / D5 V2 units these *are* the BLE authentication identity. Together with the device key they allow whoever holds them to authenticate to the station from Bluetooth range and issue commands. |
| **Cleanergy / OUPES account password** | Your vendor cloud account: station list, ownership, keys |
| **Home Assistant long-lived access token** | Full Home Assistant API access |

Do not paste any of them into a public issue, screenshot or chat log. If you did,
rotate: re-pair the station to get a new device key, change the account password,
and delete the token under *Settings → People → Long-lived access tokens*.

## Before attaching a debug log to an issue

The `debug_raw_logging` option writes every transmitted and received frame to a CSV
as hex. **The AUTH frame is in there**, so on Guardian / D5 V2 stations that file
contains your `openId` and `userId` in a reversible form, and in some code paths
the pairing key. Either turn raw logging off and reproduce the problem with
attribute logging only, or delete the AUTH/`0xA8` rows first. If you are unsure,
open the file, search for `a8` and remove those lines.

## Vendor cloud is plain HTTP

`cloud_api.py` talks to `http://api.upspowerstation.top` — unencrypted, because that
is all the vendor offers. Anything typed into the cloud-login step (account email
and password) crosses your network in clear text and is not verifiable as to
destination. It is not required: choose **"Enter existing device key"** and get the
key from the vendor app instead. If you use the cloud step, prefer an account whose
password is not reused anywhere.

The station's own firmware uses the same cleartext endpoint, so this is a property
of the product, not of this integration — but you should not have to take that on
trust, so it is stated here.

## If you use the cloud lookup for openId / userId

The options dialog can read a Guardian's identity from the vendor cloud so you do
not have to poke the API yourself. What that does and does not do:

- Your Cleanergy password is passed into a single `async_fetch_cloud_identity`
  call and never assigned to anything that is persisted. The options dictionary
  the flow writes is built field by field, and the cloud credential fields are
  not on that list — so they cannot be stored in `.storage`, in the config entry,
  or in a Home Assistant backup *by this code*. Home Assistant may still echo
  form input in its own debug logs; if that matters to you, use the manual fields
  instead, which are functionally identical.
- It is a voluntary second credential exposure. The station does not need the
  cloud at run time: once openId/userId are in the entry options, everything
  happens over Bluetooth and the vendor servers are never contacted again.
- Deleting those two option fields does not unpair anything; it only removes
  stored identifiers.


## Reporting a vulnerability

Use [GitHub private security advisories](https://github.com/bandit8623/oupes-mega-ble-hass/security/advisories/new)
rather than a public issue. This is a hobby fork maintained by one person on their
own hardware; there is no embargo process, but you will get an honest answer about
whether something is fixable here or has to come from OUPES.

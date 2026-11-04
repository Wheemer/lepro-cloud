# Protocol reference

This document is the technical reference for the Lepro Cloud integration. It is useful when diagnosing account setup, device discovery, or MQTT communication.

## Regional API hosts

| Region | Host |
| --- | --- |
| North America | `api-na-iot.lepro.com` |
| Europe | `api-eu-iot.lepro.com` |
| Far East | `api-fe-iot.lepro.com` |

## Account and discovery

- Login: `POST /user/login` with `platform=2`, `account`, `password`, `mac`, `timestamp`, `language`, and `fcmToken`.
- Profile: `GET /user/profile` supplies MQTT `root`, `cert`, `host`, and `port`.
- Families: `GET /family/list/timestamp/{timestamp}`.
- Devices: `GET /v3/device/list/fid/{fid}/timestamp/{timestamp}`.
- Product effect configuration: `https://{regional-host}/pub/resources/config.series.json`.

## MQTT topics

For a device id of `{deviceId}`:

- Get state: `le/{deviceId}/prp/get`
- Set state: `le/{deviceId}/prp/set`
- State/report subscriptions: `le/{deviceId}/prp/rpt`, `le/{deviceId}/prp/getr`,  `le/{deviceId}/prp/setr`, and `le/{deviceId}/prp/dsr/app/getr`

## Common datapoints

| Datapoint | Purpose |
| --- | --- |
| `d1` | On/off |
| `d2` | Work mode |
| `d3` | Standard-light brightness |
| `d4` | Colour temperature |
| `d5` | HSV colour |
| `d6` | Standard-light scene with timed colour/white units |
| `d50` | RGBIC scene payload |
| `d52` | RGBIC brightness |
| `d53` | RGBIC strip length where used |
| `d100` | P1 Power Memory: enabled 2, disabled 0 |
| `d101` | P1 plug Indicator Light |
| `d102` | P1 plug Button Lock |

## Product-specific state

- RGBIC, RGBIC-length, and TV-backlight products use their respective state query sets.
- TV backlights also use `d157` for Status LED and `d172` for Auto-Toggle Lights.
- RGBIC table lamps can use multi-part effect payloads.
## Reports and recovery

Account actions arrive at `le/{secret}/act/app/exe`. A matching logout action
requires reauthentication; it must not cause an automatic password-login loop.
Application errors -203 and -900 are authentication failures. Permission -904,
throttling -905 and host migration -100 are handled separately.

Commands are published with the app's `id,d` envelope and QoS 0. Queue acceptance
does not confirm device state. A matching `setr` code `c=0` acknowledges a
command; rejection or a missing response triggers a state query. Entities follow
authoritative reports. Reconnection requires fresh per-device status.

Brightness changes preserve the active white, colour, scene, music or TV mode.
Standard d6 scenes rewrite unit brightness while retaining timing, hue and
temperature. RGBIC scenes retain their complete d50 payload and use d52.
The packaged product fallback and complete ordinary bulb presets come from
Lepro Home 1.0.9.269. Rhythm-mode parameter catalogs are not ordinary scenes.

# Protocol reference

This document is the technical reference for the Lepro Cloud integration. It is useful when diagnosing account setup, device discovery, or MQTT communication.

## Regional API hosts

| Region | Host |
| --- | --- |
| North America | `api-na-iot.lepro.com` |
| Europe | `api-eu-iot.lepro.com` |
| Asia | `api-fe-iot.lepro.com` |

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
- State/report subscriptions: `le/{deviceId}/prp/rpt`, `le/{deviceId}/prp/getr`, and `le/{deviceId}/prp/setr`

## Common datapoints

| Datapoint | Purpose |
| --- | --- |
| `d1` | On/off |
| `d2` | Work mode |
| `d3` | Standard-light brightness |
| `d4` | Colour temperature |
| `d5` | HSV colour or standard-light effect payload |
| `d50` | RGBIC scene payload |
| `d52` | RGBIC brightness |
| `d53` | RGBIC strip length where used |
| `d100` | P1 plug Power Memory |
| `d101` | P1 plug Indicator Light |
| `d102` | P1 plug Button Lock |

## Product-specific state

- RGBIC, RGBIC-length, and TV-backlight products use their respective state query sets.
- TV backlights also use `d157` for Status LED and `d172` for Auto-Toggle Lights.
- RGBIC table lamps can use multi-part effect payloads.
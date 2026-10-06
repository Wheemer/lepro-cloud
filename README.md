<p align="center">
  <img src="assets/lepro_logo.png" alt="Lepro Cloud for Home Assistant" width="420">
</p>

# Lepro Cloud for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://www.hacs.xyz/docs/faq/custom_repositories/)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.6%2B-41BDF5.svg)
![Platforms](https://img.shields.io/badge/platforms-light%20%7C%20switch-22C55E.svg)

Private clean-room Home Assistant custom integration for Lepro Wi-Fi cloud devices.

This repository is a private server-side integration derived from the user's supplied
Lepro APK evidence and is not for public redistribution or release.

Repository documentation: <https://github.com/Wheemer/lepro-cloud>

Brand assets: official Lepro logo and launcher icon extracted from the user-supplied Lepro Home APK.

## Scope

- Uses Lepro Cloud REST APIs and Lepro MQTT over TLS.
- Does not use Bluetooth.
- Does not use a local network protocol.
- Exposes verified Wi-Fi type `1` devices as Home Assistant lights with on/off and brightness.
- Exposes verified Wi-Fi type `2` devices as Home Assistant switches using the shared `d1` switch datapoint.
- Discovers Wi-Fi type `3` cameras but does not expose a `CameraEntity`; camera media transport is unsupported until the streaming protocol is verified.
- Omits RGB, effects, scenes, color temperature, energy telemetry, and camera media until those payloads and transports are fully verified.

## Current Support

| Lepro Wi-Fi type | Home Assistant platform | Status |
| --- | --- | --- |
| `1` light | `light` | On/off via `d1`, brightness via `d3` |
| `2` plug | `switch` | On/off via `d1` |
| `3` camera | None | Discovery only; media transport unsupported |

## Verified Protocol Summary

- Regional REST hosts:
  - North America: `api-na-iot.lepro.com`
  - Europe: `api-eu-iot.lepro.com`
  - Far East: `api-fe-iot.lepro.com`
- Login: `POST /user/login` with `platform=2`, `account`, `password`, `mac`, `timestamp`, `language`, and `fcmToken`.
- Profile: `GET /user/profile` supplies MQTT `root`, `cert`, `host`, and `port`.
- Discovery:
  - `GET /family/list/timestamp/{timestamp}`
  - `GET /v3/device/list/fid/{fid}/timestamp/{timestamp}`
- MQTT:
  - Publish get: `le/{deviceId}/prp/get`
  - Publish set: `le/{deviceId}/prp/set`
  - Subscribe: `le/{deviceId}/prp/rpt`, `le/{deviceId}/prp/getr`, `le/{deviceId}/prp/setr`
- Verified Wi-Fi device types:
  - `1`: light
  - `2`: plug
  - `3`: camera
- Shared light/plug datapoints:
  - `d1`: switch, `1` on and `0` off
- Basic light datapoints:
  - `d3`: brightness, Lepro scale `1..1000`
  - `d2`: work mode included with brightness commands as observed in the app model

## Roadmap

- Verify additional light datapoints for color temperature, RGB, scenes, and effects before exposing them.
- Verify plug telemetry datapoints before adding sensor entities.
- Verify camera authentication, signaling, and media transport before considering any Home Assistant camera platform.
- Keep private MQTT client key material outside git and outside distributable archives.

## MQTT Key Note

The Android app stores the login response `secret` as the Lepro IoT secret and uses a native `getMqttPrivateKey()` method when writing `private_key.key`. This private integration follows that path: the static app client private key is loaded from a private, gitignored runtime asset, while the login response `secret` is passed separately as the TLS private-key password where Paho supports it. The profile continues to provide the MQTT root CA, client certificate, host, and port.

Place the private APK-derived client key at `custom_components/lepro_cloud/_private/mqtt_client_key.pem`, `.lepro_private/mqtt_client_key.pem`, or point `LEPRO_MQTT_CLIENT_KEY_FILE` at the private file on the Home Assistant server. Do not commit or redistribute that key.

## Installation

Copy `custom_components/lepro_cloud` into your Home Assistant `custom_components` directory or install through HACS as a custom repository. Restart Home Assistant, then add **Lepro Cloud** from **Settings > Devices & services**.

## Development Validation

This repository includes focused protocol tests that do not require live Lepro credentials:

```bash
python3 -m pytest
python3 -m compileall custom_components tests
```

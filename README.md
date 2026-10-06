<p align="center">
  <img src="assets/lepro_logo.png" alt="Lepro Cloud for Home Assistant" width="300">
</p>

# Lepro Cloud for Home Assistant

<p align="center">
  <a href="https://www.hacs.xyz/docs/faq/custom_repositories/"><img src="https://img.shields.io/badge/HACS-CUSTOM-41BDF5?style=for-the-badge&logo=home-assistant&logoColor=white&labelColor=555555" alt="HACS Custom"></a>
  <a href="https://www.home-assistant.io/"><img src="https://img.shields.io/badge/HOME%20ASSISTANT-2024.6%2B-41BDF5?style=for-the-badge&logo=home-assistant&logoColor=white&labelColor=555555" alt="Home Assistant 2024.6 or newer"></a>
  <a href="https://github.com/Wheemer/lepro-cloud/releases"><img src="https://img.shields.io/github/downloads/Wheemer/lepro-cloud/total?style=for-the-badge&label=DOWNLOADS&labelColor=555555" alt="GitHub release downloads"></a>
  <img src="https://img.shields.io/badge/PLATFORMS-LIGHT%20%7C%20PLUG-22C55E?style=for-the-badge&logo=home-assistant&logoColor=white&labelColor=555555" alt="Light and plug platforms">
</p>

Private clean-room Home Assistant custom integration for Lepro Wi-Fi cloud devices.

This repository is a private server-side integration derived from the user's supplied
Lepro APK evidence and is not for public redistribution or release.


Brand assets: user-supplied Lepro wordmark and a launcher icon extracted from the supplied Lepro Home APK.
Lepro trademarks, names, logos, icons, product artwork, and any other Lepro-owned
assets remain the property of their respective owners and are included only in
this private repository.

## Current Support

| Lepro Wi-Fi type | Home Assistant platform | Controls |
| --- | --- | --- |
| `1` light | `light` | On/off, brightness, RGB colour, colour temperature, and app-provided scenes |
| `2` P1 plug | `switch` | On/off, Button Lock, Power Memory, and Indicator Light |

RGBIC, RGBIC-length, and STV1 light families use the product-specific state
datapoints observed in the Lepro Home app. STV1 also exposes Status LED and
Auto-Toggle Lights as configuration entities.

## Verified Protocol Summary

- Regional REST hosts:
  - North America: `api-na-iot.lepro.com`
  - Europe: `api-eu-iot.lepro.com`
  - Asia: `api-fe-iot.lepro.com`
- Login: `POST /user/login` with `platform=2`, `account`, `password`, `mac`, `timestamp`, `language`, and `fcmToken`.
- Profile: `GET /user/profile` supplies MQTT `root`, `cert`, `host`, and `port`.
- Discovery:
  - `GET /family/list/timestamp/{timestamp}`
  - `GET /v3/device/list/fid/{fid}/timestamp/{timestamp}`
- MQTT:
  - Publish get: `le/{deviceId}/prp/get`
  - Publish set: `le/{deviceId}/prp/set`
  - Subscribe: `le/{deviceId}/prp/rpt`, `le/{deviceId}/prp/getr`, `le/{deviceId}/prp/setr`
- Shared on/off datapoint: `d1` (`1` on, `0` off).
- Light datapoints: `d2` work mode, `d3` brightness, `d4` colour temperature,
  and `d5` HSV colour.
- RGBIC datapoints: `d50` scene, `d52` brightness, and `d53` strip length where used.
- P1 plug settings: `d100` Power Memory, `d101` Indicator Light, and `d102` Button Lock.

## MQTT Key Note

The Android app stores the login response `secret` as the Lepro IoT secret and uses a native `getMqttPrivateKey()` method when writing `private_key.key`. This private integration follows that path: the static app client private key is loaded from a private, gitignored runtime asset, while the login response `secret` is passed separately as the TLS private-key password where Paho supports it. The profile continues to provide the MQTT root CA, client certificate, host, and port.

Place the private APK-derived client key at `custom_components/lepro_cloud/_private/mqtt_client_key.pem`, `.lepro_private/mqtt_client_key.pem`, or point `LEPRO_MQTT_CLIENT_KEY_FILE` at the private file on the Home Assistant server. Do not commit or redistribute that key.

## Installation

Copy `custom_components/lepro_cloud` into your Home Assistant `custom_components` directory or install through HACS as a custom repository. Restart Home Assistant, then add **Lepro Cloud** from **Settings > Devices & services**.

## Development Validation

This repository includes focused protocol tests that do not require live Lepro credentials:

```bash
python3 -m pytest
python3 -m compileall custom_components/lepro_cloud/*.py tests
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for maintainer workflow notes and
[SECURITY.md](SECURITY.md) for private credential and asset handling guidance.

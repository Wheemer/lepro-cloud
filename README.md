<p align="center">
  <img src="assets/lepro_logo.png" alt="Lepro Cloud for Home Assistant" width="300">
</p>

# Lepro Cloud for Home Assistant

<p align="center">
  <a href="https://www.hacs.xyz/docs/faq/custom_repositories/"><img src="https://img.shields.io/badge/HACS-CUSTOM-41BDF5?style=for-the-badge&logo=home-assistant&logoColor=white&labelColor=555555" alt="HACS Custom"></a>
  <a href="https://www.home-assistant.io/"><img src="https://img.shields.io/badge/HOME%20ASSISTANT-2024.6%2B-41BDF5?style=for-the-badge&logo=home-assistant&logoColor=white&labelColor=555555" alt="Home Assistant 2024.6 or newer"></a>
  <a href="https://github.com/Wheemer/lepro-cloud/releases"><img src="https://img.shields.io/github/downloads/Wheemer/lepro-cloud/total?style=for-the-badge&label=DOWNLOADS&labelColor=555555&cacheSeconds=300&v=0.1.0" alt="GitHub release downloads"></a>
  <img src="https://img.shields.io/badge/PLATFORMS-LIGHT%20%7C%20PLUG-22C55E?style=for-the-badge&logo=home-assistant&logoColor=white&labelColor=555555" alt="Light and plug platforms">
</p>

Home Assistant custom integration for Lepro Wi-Fi cloud devices.

Lepro names, logos, icons, and product artwork are trademarks of their respective owners.

## Supported Products

The integration discovers supported products already present in your Lepro Home account and adds the appropriate Home Assistant entities.

| Lepro Wi-Fi product family | Home Assistant support |
| --- | --- |
| Standard bulbs and decorative lights | Light entity with on/off, brightness, colour, colour temperature, and app-provided effects where the product reports them. |
| RGBIC light strips, rope lights, and neon-style strips | Light entity with on/off, brightness, colour, saved effects, and product-specific RGBIC scenes. |
| RGBIC length-configurable strips | The same RGBIC controls, including the strip-length state used by the product. |
| TV backlights | RGBIC light entity, saved effects, plus Status LED and Auto-Toggle Lights configuration entities. |
| RGBIC table lamps | RGBIC light entity with the lamp's multi-part effects. |
| P1 smart plugs | Switch entity with on/off, Button Lock, Power Memory, and Indicator Light settings. |

All discovered Lepro Wi-Fi lights are added as light entities; controls are exposed only when their device reports the necessary state.

For the REST, MQTT, and datapoint reference, see [Protocol reference](docs/PROTOCOL.md).

## Installation
[![Add this repository to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Wheemer&repository=lepro-cloud&category=integration)

Copy `custom_components/lepro_cloud` into your Home Assistant `custom_components` directory or install through HACS as a custom repository. Restart Home Assistant, then add **Lepro Cloud** from **Settings > Devices & services**.

## Development Validation

This repository includes focused protocol tests that do not require live Lepro credentials:

```bash
python3 -m pytest
python3 -m compileall custom_components/lepro_cloud/*.py tests
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for maintainer workflow notes.

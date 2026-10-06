# Changelog

All notable changes to Lepro Cloud are documented here.

## v0.1.0

First public release of the Lepro Cloud custom integration for Home Assistant.

### Added

- Account setup using Lepro Home credentials and region selection.
- Cloud discovery and control for supported Lepro Wi-Fi lights and plugs.
- Brightness, colour, colour-temperature, and effect controls where supported by the product.
- App-provided scenes and saved favourite effects in the light Effect selector.
- RGBIC-strip, TV-backlight, and multi-part table-lamp effect handling.

### Reliability

- Effect brightness preserves the supplied colour payload.
- Saved effects load across every page returned by Lepro.
- Strip-light and legacy-scene selection follow the Lepro Home app fallback behavior.

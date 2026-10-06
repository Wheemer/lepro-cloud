# Changelog

All notable changes to Lepro Cloud are documented here.

## v0.1.1

### Changed

- Initial setup now asks Lepro which regional server belongs to the account before logging in.
- The region is no longer shown during initial setup.
- Configure keeps the selected region available as a manual override.

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

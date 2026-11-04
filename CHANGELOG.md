# Changelog

All notable changes to Lepro Cloud are documented here.

## v0.2.0

This release improves device controls, account recovery and connection reliability, and adds authorization through the Lepro app.

### Highlights

- 🔐 Adds setup through the Lepro app for accounts using Apple sign-in, with automatic session renewal and account identity checks. Email and password setup remains available.
- 💡 Preserves active effects when adjusting brightness, including saved multipart patterns, and corrects product-specific brightness ranges and colour controls.
- 🎨 Improves favourite-effect updates, product-family effect selection and capability detection, with a bundled 70-product fallback catalog and complete bulb presets.
- 🔌 Corrects P1 memory, lock and indicator controls.
- 👥 Improves shared-account discovery and keeps devices, favourites and capabilities updated when they change.
- 🔄 Improves expired-session recovery, regional migration and MQTT certificate and secret renewal.
- 📡 Fixes MQTT state handling and connectivity reporting, retries unanswered startup state queries, and prevents stale connections from restoring incorrect availability.
- 🏷️ Preserves friendly names, entity IDs and supported controls during upgrades and reloads.
- 🛠️ Improves setup, unload and reload cleanup, reauthentication, and privacy-safe diagnostics.
- 📦 Strengthens release ZIP validation for translations, branding and required authentication assets, with expanded Home Assistant regression checks.

### Compatibility

Requires Home Assistant 2026.4.0 or newer.

Apple-linked iPhone approval and return still needs confirmation on a physical device. The authorization exchange and password-free renewal have been tested on server.

Existing email and password accounts do not need to be configured again.

## v0.1.3

### Fixed

- Device names now omit Lepro's opaque four-character suffix in Home Assistant.
- Initial setup reuses the successful sign-in session instead of immediately logging in again.

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

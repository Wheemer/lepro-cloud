<div align="center">

<img src="https://raw.githubusercontent.com/Wheemer/lepro-cloud/main/assets/lepro_logo.png" alt="Lepro" width="300">

# Lepro Cloud for Home Assistant

### Bring your Lepro Wi-Fi lighting and smart plugs into Home Assistant

[![HACS Default](https://img.shields.io/badge/HACS-DEFAULT-41BDF5?style=for-the-badge&logo=home-assistant&logoColor=white&labelColor=555555)](https://www.hacs.xyz/)
[![Home Assistant 2026.4+](https://img.shields.io/badge/HOME%20ASSISTANT-2026.4%2B-41BDF5?style=for-the-badge&logo=home-assistant&logoColor=white&labelColor=555555)](https://www.home-assistant.io/)
[![Latest release](https://img.shields.io/github/v/release/Wheemer/lepro-cloud?style=for-the-badge&logo=github&logoColor=white&label=RELEASE&labelColor=555555&color=22C55E)](https://github.com/Wheemer/lepro-cloud/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/Wheemer/lepro-cloud/total?style=for-the-badge&logo=github&logoColor=white&label=DOWNLOADS&labelColor=555555&color=8A2BE2)](https://github.com/Wheemer/lepro-cloud/releases)
[![MIT License](https://img.shields.io/badge/LICENSE-MIT-22C55E?style=for-the-badge&labelColor=555555)](LICENSE)

**Available in the default HACS catalog.**

</div>

Control your Lepro devices alongside the rest of your home: adjust lighting, select saved effects, switch plugs, and use device state in dashboards and automations. Devices are discovered from your Lepro account, with state updates delivered through Lepro's cloud connection.

> **App compatibility:** This integration supports devices used with the newer **Lepro app**, not **Lepro LampUX**. LampUX devices use a separate Tuya-based platform and cannot be added to the newer Lepro app. For those devices, Lepro recommends [Smart Life](https://community.lepro.com/t/passaggio-da-lampux-a-lepro/147305), which can connect through Home Assistant's [Tuya integration](https://www.home-assistant.io/integrations/tuya/).

## Features

- 💡 **Lighting controls** — On/off, brightness, colour and colour temperature, according to the device's capabilities.
- 🎨 **Effects and favourites** — Select compatible app-provided scenes and saved favourite patterns from the light's Effect selector, including multipart table-lamp patterns.
- 🌈 **Effect brightness** — Adjust brightness while retaining the active supported pattern.
- 🔌 **Smart plugs** — Outlet control, with Button Lock, Power Memory and Indicator Light settings for P1 plugs.
- 📺 **TV backlights** — Lighting and saved effects, plus Status LED and Auto-Toggle Lights settings.
- 📡 **Cloud connection status** — A diagnostic connectivity entity for each supported device, based on Lepro's reported online state.
- 🔄 **Account recovery** — Automatic session maintenance and Home Assistant reauthentication when authorization is rejected or revoked.

## Supported Products

Coverage spans the following Lepro Wi-Fi product families. The examples below identify series in the integration's product catalog; available controls depend on the device and the state it reports.

### Bulbs, floor lights and ceiling lights

Standard and decorative bulbs, floor lamps, ceiling fixtures and other cloud-controlled lights. Catalog examples include **B1/B2/B3, BC1, BR1/BR2, R2, BG1, BP1, SE1, F1, F2, O1, T1 and T2**.

Lights expose brightness, colour and white-temperature controls where available, with compatible scenes shown in the Effect selector.

### LED strips, neon and decorative lighting

RGBIC strips, rope/neon-style lights, string lights and outdoor/eaves lighting. Catalog examples include **S1, S1-PRO, S2, S2-PRO, SW1, SD1, N1, N1-PRO, WL1, ZB1, PG1, OE1, OE1-PRO, E1 and EE1**, including their catalogued length variants.

Compatible saved effects retain their complete pattern payload. Controls follow the product's colour and brightness capabilities.

### Table lamps and TV backlights

**TB1, TB1-PRO and TB2** have product-specific scene handling. TB1-family saved multipart patterns are retained when selected from Home Assistant.

**STV1** TV backlights expose lighting controls and compatible saved effects, with additional Status LED and Auto-Toggle Lights switches.

### Smart plugs

Cloud-controlled plugs appear as switch entities. **P1** also exposes Button Lock, Power Memory and Indicator Light configuration switches.

The bundled catalog contains 70 product entries and is supplemented by Lepro's online product metadata. A catalog entry identifies product handling; it does not mean every model and firmware has been physically tested.

## Installation

[![Open Lepro Cloud in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Wheemer&repository=lepro-cloud&category=integration)

### HACS

1. Open **HACS** and search for **Lepro Cloud**.
2. Download the integration.
3. Restart Home Assistant.
4. Follow the account setup below.

Requires **Home Assistant 2026.4.0 or newer**.

### Manual installation

1. Download `lepro_cloud.zip` from the [latest release](https://github.com/Wheemer/lepro-cloud/releases/latest).
2. Extract its contents into `config/custom_components/lepro_cloud/`. The `manifest.json` file should be directly inside that directory.
3. Restart Home Assistant.

## Account Setup

1. Add your devices to your account in the newer **Lepro app**.
2. In Home Assistant, open **Settings → Devices & services → Add integration**.
3. Search for **Lepro Cloud**.
4. Choose a sign-in method and complete setup.

### Email address and password

Use your **Lepro account email address and password**. Leave **Server region** on **Automatic**, or select North America, Europe or Far East if you need to override account-region detection. You can change this later through **Configure**.

### Sign in through the Lepro app

This option is intended for accounts using Apple sign-in. Start setup on the iPhone where Lepro is installed and signed in, choose **Sign in through the Lepro app**, and follow the authorization prompts.

## Using Your Devices

Devices appear under **Settings → Devices & services → Lepro Cloud** and can be added to dashboards or used in automations.

### Scenes and favourite patterns

Open a light's controls and choose from its **Effect** selector. Compatible scenes and favourites saved in Lepro are loaded for that product family; the list can differ between devices.

Create and edit patterns in the Lepro app, then select the saved patterns in Home Assistant. Brightness changes preserve supported running effects, including multipart patterns.

### Automating favourite patterns

Favourites are available through the light entity's **Effect** option in automations and scripts. In the automation editor, add a **Light: Turn on** action, select your light, then choose a favourite under **Effect**.

For example, this action selects a favourite:

```yaml
action: light.turn_on
target:
  entity_id: light.table_lamp
data:
  effect: "Reading"
```

Replace `light.table_lamp` with your light's entity ID and `Reading` with the exact name shown in its Effect selector. Use **Choose** branches to select different favourites based on your automation's conditions.

### Connectivity and device settings

Each supported device has a **Cloud connection** diagnostic entity. It shows the device's reported connection to Lepro; if Home Assistant loses its own cloud connection, the entity becomes unavailable. Before a device has supplied its online state, it can show unknown.

P1 plug settings and STV1 backlight settings appear as additional configuration entities on their devices.

## Updating

Open the Lepro Cloud repository in HACS to install an available update, then restart Home Assistant.

If a published release has not appeared yet, choose **Update information** from the repository's menu in HACS. The update should then appear.

## Troubleshooting

### A device is missing or unavailable

Confirm the device is accessible in the Lepro app using the same account. Check Home Assistant's Lepro Cloud integration for connection or reauthentication messages. When reporting a discovery problem, include the product series and firmware version.

### Home Assistant asks you to sign in again

Complete the reauthentication prompt using the same Lepro account. For an account configured through app authorization, use that authorization flow again.

### Reporting a problem

[Open an issue](https://github.com/Wheemer/lepro-cloud/issues) with your Home Assistant version, integration version, device model and firmware, what you tried, and what happened.

For debug logs, add this to your Home Assistant logger configuration:

```yaml
logger:
  logs:
    custom_components.lepro_cloud: debug
```

Remove account credentials, tokens and other personal information before sharing logs. Integration diagnostics are available from the integration's menu in Home Assistant.

## Documentation

- [Release notes](https://github.com/Wheemer/lepro-cloud/releases)
- [Protocol reference](docs/PROTOCOL.md)
- [App authorization details](docs/app-authorization.md)
- [Development guide](DEVELOPMENT.md)

## License

Released under the [MIT License](LICENSE). Lepro names, logos and product artwork belong to their respective owners.

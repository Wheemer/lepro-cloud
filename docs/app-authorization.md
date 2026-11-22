# Existing Lepro app-linked entries

New setup uses a Lepro email address and password. See [Use a separate account for Home Assistant](../README.md#use-a-separate-account-for-home-assistant) for the device-sharing steps.

Existing app-linked entries can restore and renew their stored credentials. Renewal uses the existing app token and persists its replacement through Home Assistant. A change to the MQTT credentials reconnects the transport.

If a legacy session is rejected, open **Configure** on the existing entry and enter the email and password for a Lepro account with access to the same devices. After successful login, the integration replaces the old session data.

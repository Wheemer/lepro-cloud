# Lepro app authorization

Choose **Sign in through the Lepro app** during setup and continue on the iPhone where Lepro is installed and signed in. Approve the link in Lepro, then return to Home Assistant. Configure and reauthentication use the same flow.

## Session handling

Home Assistant signs and validates the callback state. Lepro's callback code can contain literal plus characters, which normal query parsing converts to spaces; the integration restores those characters only in the authorization code.

The callback is exchanged through Lepro's app web-token endpoints. This path does not require a partner client secret. The resulting account identity is checked against the profile. A successor app token is stored with the API credentials in Home Assistant's config entry.

Renewal uses the app token without asking for a password. It is scheduled one hour before the earlier of the API and app-token expiry times, leaving room for the maintenance interval and retries. New tokens are persisted through Home Assistant's OAuth session helper. Revoked or rejected credentials require authorization again; network errors retain the prior stored credentials.

A renewed MQTT secret causes a transport reconnection even when the broker address and certificates are unchanged.

## Verification

The actual integration code successfully exchanged a real Lepro authorization code, renewed the session without a password, and read the same account's profile using the renewed credentials from an isolated Home Assistant container on server.

Offline tests cover callback encoding, persistent storage and restoration, concurrent renewal, cancellation, account mismatch, rejected credentials, network recovery paths, startup, and MQTT credential rotation.

The final iPhone app approval and return using an Apple-linked account still needs a device-backed test. Server-side success is not proof that this iOS interaction works.

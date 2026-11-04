# Startup regression coverage

The authorized 2026-11-04 installation reached a connected MQTT transport but
left an SE1 (firmware 2.1.26) unavailable, with its cloud sensor unknown. It also
replaced the existing friendly name with its suffixed raw name and removed the
previous colour-temperature control. The previous component was restored.

## Evidence and limits

The before/after entity states, discovery summary and rollback results were
recorded. The original raw MQTT response was **not captured**.
tests/fixtures/se1_upgrade.json separates those observations from constructed
values. Its device ID, d4 value, request ID and c=200 are synthetic. It is an
APK-valid regression fixture, not a packet capture or proof of the exact
device-side cause.

MqttConnectionPool.java:530-544 sends a message containing d to dealDpValue;
only a message without d is dispatched as a c-only result. Discarding every
message with a nonzero c therefore drops valid state envelopes. The tests
reproduce that empty-state failure and enforce the APK dispatch rule.

## Fixes and coverage

- State data and command-result envelopes have separate handling. The real TLS
  broker fixture sends d plus c on GET, and separate c-only results and state
  reports after SET.
- An unanswered initial query is retried twice at 20-second intervals. These
  retries are GET-only, stop after fresh state, and are cancelled on disconnect
  or unload. They do not invent on/off or connectivity state.
- Existing registry metadata preserves a known friendly-name prefix when cloud
  discovery adds an opaque suffix. Arbitrary new user names and explicit vendor
  friendly-name fields retain their normal precedence.
- Existing ordinary-bulb colour-temperature capability is retained during
  upgrade; native d4 reports can establish it on a new installation. A DIY
  picker or RGBIC placeholder does not gain temperature controls from that rule.
- Diagnostic counts distinguish no incoming property messages from messages
  rejected during state validation, without logging identifiers or payloads.
- The real HA upgrade test checks state, cloud connectivity, name, capabilities,
  entity IDs, session refresh, unload/reload, a colour-temperature command and
  explicit offline precedence. The replacement entry runs actual async_start;
  only its remote API and transport are simulated.
- A local HTTPS endpoint rejects certificate requests without the app
  authentication header. It runs inside a container with no external network.
- Server tests also run against the exact HA 2026.11.0b3 image used in the failed
  installation, in addition to the supported minimum and stable test image.

No further live Home Assistant access or release is part of this work.
Server regression success is not a claim that the physical installation has
been retested.

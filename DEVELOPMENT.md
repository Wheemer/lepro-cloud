# Development

This Home Assistant custom integration keeps
`custom_components/lepro_cloud` as the standard integration module and avoids
moving runtime code into a package layout that Home Assistant or HACS would not
install directly.

## Local Validation

Run the same checks used by CI:

```bash
python3 -m pytest
python3 -m compileall custom_components/lepro_cloud/*.py tests
```

The focused tests use stubs and must not require live Lepro credentials, Home
Assistant deployment access, MQTT key material, APK files, or a networked
device.

## Repository Layout

- `custom_components/lepro_cloud/`: Home Assistant integration source.
- `tests/`: protocol, config-flow, MQTT TLS, and platform behavior tests.
- `assets/`: repository artwork used by the README.
- `hacs.json`: HACS integration metadata for integration validation.
- `.github/workflows/`: pinned CI, HACS, CodeQL, Scorecard, and manual release
  verification workflows.

## Private Material

Never commit personal credentials, account certificates, runtime configuration,
or deployment-specific secrets. The app-bundled MQTT client key in
`custom_components/lepro_cloud/_private/mqtt_client_key.pem` is deliberately
included in releases; users do not supply a personal key.

Lepro trademarks and artwork remain the property of their respective owners.

## Isolated Home Assistant regression tests

`tests/real_ha_regressions.py` exercises actual Home Assistant classes separately
from the lightweight unit-test import stubs. Build `tests/Dockerfile.ha` for the
minimum and current tested HA versions, then run the container with
`--network none`, the checkout mounted read-only at `/source`, and a dedicated
permanent test directory mounted at `/audit`. Never mount a live HA config.

```bash
docker build -f tests/Dockerfile.ha --build-arg HA_VERSION=2026.4.0 -t lepro-test:2026.4.0 .
docker run --rm --network none -v "$PWD:/source:ro" -v /path/to/test-data:/audit lepro-test:2026.4.0 /source/tests/real_ha_regressions.py
```

## Release Verification

The manual release verification workflow validates a supplied version tag,
checks it against the manifest version, runs tests, compiles Python sources,
runs HACS validation, and uploads a staged zip artifact for review. It does not
create a GitHub release, publish assets to a release, or push tags.

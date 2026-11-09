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


## Dependency updates

Home Assistant manages the shared Paho dependency. The manifest declares the
minimum version from requirements-runtime.in; CI checks its hash-locked test
version satisfies that minimum. Isolated HA tests use each image's supplied Paho.

CI installs test dependencies with --require-hashes. To refresh the CI lock:

```bash
uv pip compile requirements-test.in --python-version 3.12 --generate-hashes -o requirements-test.txt
python scripts/check_dependency_versions.py --sync
python -m pytest
```

Paho 2.1.0 is a normal upstream release; it is not a test build or prerelease.


## E1 transport regression without Home Assistant

With the test dependencies and OpenSSL installed, run:

python tests/offline_e1_wire.py --work-dir /permanent/server/research

This uses real HTTPS and Paho/mTLS over loopback fixture servers, while stubbing
HA imports. It does not construct a Home Assistant instance or contact Lepro.
Each invocation creates its own run directory. The optional --initial-mode
argument accepts 0, 1 or 2; --reply-suffix accepts getr, rpt, setr or
dsr/app/getr. The test checks initial state before sending colour, so a colour
command cannot conceal an incorrect first brightness command.

### Logging and region diagnostics

The [logging/region audit](docs/LOGGING-AND-REGION-AUDIT.md) records the owned
logging surface, safe fields and account-routing evidence. Add operation
context through log_helpers; never pass exception strings, request bodies,
tokens, IDs, callback URLs or arbitrary metadata directly to a logger.
Run the offline redaction and routing regressions with the hash-locked test
dependencies. Those tests use import stubs and do not instantiate HA.

# Development

This is a private clean-room Home Assistant custom integration. Keep
`custom_components/lepro_cloud` as the standard integration module and avoid
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
- `assets/`: private repository artwork used by the README.
- `hacs.json`: HACS custom repository metadata for integration validation.
- `.github/workflows/`: pinned CI, HACS, CodeQL, Scorecard, and manual release
  verification workflows.

## Private Material

Never commit or package MQTT keys, APKs, credentials, Home Assistant runtime
configuration, or deployment-specific secrets. The ignored private key lookup
locations are documented in the README for private local use only.

Lepro trademarks, names, logos, icons, product artwork, and any other
Lepro-owned assets remain the property of their respective owners and are
included only in this private repository.

## Release Verification

The manual release verification workflow validates a supplied version tag,
checks it against the manifest version, runs tests, compiles Python sources,
runs HACS validation, and uploads a staged zip artifact for review. It does not
create a GitHub release, publish assets to a release, or push tags.

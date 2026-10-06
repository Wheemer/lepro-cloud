# Security Policy

## Supported Use

This repository is private and intended for private Home Assistant use only.
Do not redistribute builds that include Lepro artwork, APK-derived material,
private MQTT keys, credentials, Home Assistant secrets, or deployment data.

## Reporting

Report security concerns privately through the repository owner rather than by
opening a public issue. Include reproduction steps, affected files, and whether
any credential, token, MQTT key, certificate, or Home Assistant deployment
detail may have been exposed.

## Secret Handling

- Do not commit MQTT key material, API credentials, APKs, certificates,
  `.storage`, `secrets.yaml`, or Home Assistant configuration dumps.
- Do not paste private Lepro credentials or MQTT keys into issues, workflow
  logs, screenshots, or test fixtures.
- Keep tests offline and deterministic. Mock protocol behavior instead of using
  live accounts or devices.

## Ownership Notice

The MIT license covers clean-room code and repository documentation only.
Lepro trademarks, names, logos, icons, product artwork, and any other
Lepro-owned assets remain the property of their respective owners and are
included only in this private repository for private interoperability and
documentation purposes.

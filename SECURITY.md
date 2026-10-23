# Security Policy

## Supported Versions

Security fixes are made in the latest released version of Lepro Cloud.

## Report a Vulnerability

Please use [private vulnerability reporting](https://github.com/Wheemer/lepro-cloud/security/advisories/new)
for security concerns. Do not open a public issue for a suspected vulnerability.

Include the affected version, reproduction steps, expected and actual behavior,
and the potential impact. Do not include account passwords, access tokens,
or Home Assistant configuration data in the report.

## Sensitive Information

- Never commit user credentials, access tokens, certificates, `.storage`,
  `secrets.yaml`, or Home Assistant configuration dumps.
- Never include sensitive information in public issues, pull requests,
  workflow logs, screenshots, or test fixtures.
- Keep tests offline and deterministic; use mocks instead of live accounts or
  devices.

## Disclosure

Please allow time for the issue to be investigated and a fix to be released
before discussing the vulnerability publicly.

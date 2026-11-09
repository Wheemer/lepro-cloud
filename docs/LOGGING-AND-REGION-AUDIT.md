# Integration logging and account-region audit

Audit date: 2026-11-09. Scope: all integration Python modules, owned logger
calls, handled external-exception boundaries, downloaded diagnostics, account
routing and session renewal. This work uses server-side offline tests and local
fixture transports only; no live HA, Lepro login or HA instance was used.

## Findings and fixes

| Area | Finding | Correction |
| --- | --- | --- |
| Scene/family loading | Device IDs and arbitrary exception text could enter debug logs; soft failures lacked precise error metadata. | Anonymous per-discovery device/family ordinals, safe error class, vendor code, HTTP status and fixed reason labels. |
| Product/refresh failures | Generic retry messages hid the actual error; metadata could be echoed. | Structured error details and actual retry delay; retain existing fallback/cache behavior. |
| Entity setup | Raw series/picker strings and arbitrary state-key names were printable. | Known product/picker/DP allowlists, effective versus reported classification, and local device ordinal. |
| MQTT callbacks | Broker, subscription and command rejections omitted numeric codes or stringified reason objects. | Numeric reason codes, safe device context, queue versus response versus authoritative-state distinctions. |
| MQTT report validation | Accepted, filtered and rejected reports needed distinct diagnostics. | Fixed topic suffixes, separate wire/inferred field names and nonnegative discard/rejection counters. No raw payloads, patterns or topics are printed; only validated online/mode numbers are summarised. |
| MQTT queue/shutdown | Third-party exceptions could surface private URLs or certificate paths through tracebacks. | Sanitized failure boundaries, visible numeric queue codes and safe cleanup exceptions; cleanup still runs. |
| Certificate/key errors | Decode/network exceptions could chain key bytes, signed URLs or paths into diagnostics. | Fixed messages, certificate role/status context, suppressed unsafe exception chaining and redaction regressions. |
| App authorization | Callback/exchange/renewal failures lacked safe context; -101 conversion lost metadata. | Safe operation boundaries, preserved code/status/region and fixed local reasons, without callback/token/state contents. |
| Setup/unload | Setup exceptions relied on arbitrary exception strings; lifecycle status was implicit. | Safe retry/reauth summaries and debug lifecycle completion. |
| Downloaded diagnostics | Raw firmware/model/control metadata and numeric-looking arbitrary DP keys could be exported. | Strict metadata/field allowlists, active versus configured region, selection mode, anonymous ordinals and report-validation counters. |
| Error labels | Only a few authentication codes had explanations. | Forty fixed RemoteErrorCode labels from the supplied APK, checked against source; no raw vendor message is logged. |

Modules with no owned logger calls were also reviewed: capabilities, catalog,
const, device, protocol and scenes. Their role is data/routing/encoding; logs
are emitted at operation boundaries rather than logging every helper. The
normal warning/debug split remains: connection/command rejection and
reauthentication are visible; routine packets, retries and soft scene failures
remain debug output. No Paho/aiohttp wire logger is enabled.

## Account/server selection

APK evidence: UserApi POST /user/region (account and timestamp), POST
/web/token/region, RegionEntity.apiHost, HttpBaseUrlInterceptor and the release
RegionModeType/NetworkUtils host constants. apiDeviceHost is a provisioning
host, not the account REST host. The server is account-derived; no HA country,
latitude, IP geolocation or closest-server guess is used.

- Automatic mode uses the global bootstrap service. All three production
  region mappings are checked against APK constants.
- Email/password manual mode bypasses lookup and selects only an allowlisted
  North America, Europe or Far East server. Configure and reauthentication
  retain the choice, and Automatic clears the stored override.
- A valid vendor -100 host update remains bounded and allowlisted.
- Automatic transport-level HTTP redirects are now disabled for REST calls.
  Previously they could bypass the vendor-host allowlist and potentially
  forward a POST body or custom token header. HTTP redirects are reported
  with their actual status; their Location is not logged or followed.
- App exchange/renewal previously returned the initial lookup region even if
  a later exchange/profile/token request migrated to another host. It now
  returns the final vendor-validated region. Tests reproduce this at all
  three stages and confirm persisted app-session routing.
- Restoring an unchanged app token preserves an already validated host
  migration. Changing/restoring a token still uses its vendor-derived region.
- Downloaded diagnostics distinguish configured and active regions instead
  of representing a migrated connection as the old configured destination.

These findings do not prove which server issue #38 reached. No user account
was queried. New diagnostics are needed from that actual failing request to
establish its cause.

## Verification

- 335 offline tests pass in a fresh Python 3.12 environment installed from
  hash-locked test dependencies.
- New tests cover exception-text/ID/token redaction, malformed reports, MQTT
  rejection codes, cache failures, setup/cleanup, certificate errors and
  downloaded diagnostics, with an AST guard against raw logger arguments.
- Routing tests cover all production regions, manual/automatic mode,
  Configure/reauthentication, HTTP redirect refusal, bounded vendor redirects,
  app authorization/renewal migrations and preserved errors.
- Actual Paho/mTLS loopback runs pass for product 68 without series metadata
  and product 115 with conflicting D1 metadata, using local HTTPS/MQTT fixtures.
- Ruff, compilation, dependency consistency, APK evidence and archive validation
  pass. The new log_helpers module is required by archive verification.
- Cryptography was added only to hash-locked test dependencies so offline
  app-token routing tests exercise the actual encoder. Runtime requirements
  and existing test dependency pins remain unchanged.
- No HA instance, live installation, device command, remote publication, version
  bump or release was performed for this audit.

Permanent transport/test artifacts:
server:/root/codex-work/lepro-auth-diagnostics-2026-11-09.

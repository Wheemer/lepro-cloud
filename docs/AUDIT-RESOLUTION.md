# Audit resolution

This PR includes the source fixes for the protocol and repository audit. Each
audit ID below has an implementation and a regression check. Regression names
refer to `tests/real_ha_regressions.py` unless another file is named.

## Protocol findings

| ID | Resolution | Regression evidence |
| --- | --- | --- |
| P01 | Actual negative auth codes and HTTP 401 become auth failures; permissions, throttling and bounded host migration remain separate | `test_apk_negative_auth_codes_and_non_auth_failures`, `test_http_401_is_auth_failure_even_with_non_json_body`, `test_region_migration_is_bounded_and_allowlisted` |
| P02 | P1 memory writes 2/0; lock and indicator retain their APK encodings | `test_p1_writer_values_and_no_optimistic_confirmation` |
| P03 | Brightness retains white, colour, scene, music and TV modes | `test_brightness_preserves_all_work_modes_with_cached_color`, `test_low_tv_brightness_and_white_readback_use_the_correct_fields` |
| P04 | d6 rewriting preserves group, timing, mode, hue and temperature; changes the correct colour/white brightness fields | `test_d6_white_and_color_units_preserve_timing_and_other_fields`, `test_d6_dimming_uses_the_scene_even_when_d52_is_cached`; group-string fixture in `test_protocol.py` |
| P05 | Exact product-family selection and only APK-defined fallbacks | `test_family_and_scene_sources_reconcile_by_identity`; multi-family selection checks in `test_platform_devices.py` |
| P06 | Stable scene identities reconcile embedded favorites, REST edits and deletions; optional outage retains last good data | `test_saved_scene_refresh_handles_edits_deletions_and_service_outage` |
| P07 | Context-aware clamps and S1-10 firmware compensation; TV has its separate direct slider mapping | `test_apk_brightness_ranges_and_firmware_compensation`, `test_low_tv_brightness_and_white_readback_use_the_correct_fields` |
| P08 | Validated partial reports infer status with explicit offline precedence; report handling never sends SET | `test_partial_reports_and_explicit_offline_precedence` |
| P09 | Secret-matched account actions, logout reauth and disable discovery refresh; unknown actions do nothing | `test_account_action_requires_matching_secret_and_logout_reauths_once`, `test_account_disable_and_unknown_actions_only_request_discovery`, `test_forced_logout_reauth_survives_an_already_failed_refresh_task` |
| P10 | APK d-bearing state dispatch is separate from correlated c-only responses; rejection/timeout queries state; queue acceptance is not confirmation | `test_command_queue_acceptance_does_not_fabricate_state`, `test_command_timeout_only_queries_and_cleanup_cancels_timers` |
| P11 | Explicit BLE-only and unknown transports are excluded | `test_ble_only_filter_and_packaged_catalog` |
| P12 | Both complete ordinary bulb presets are included; saved multipart patterns pass through unchanged. Rhythm parameter catalogs are not presented as ordinary scenes | `scripts/check_apk_evidence.py`, `test_saved_brightness_metadata_is_used_unless_ha_overrides_it`, TB1 multipart fixture in `test_platform_devices.py` |
| P13 | Packaged 70-product fallback, refreshed remote metadata and last-good configuration on outage | `test_product_metadata_refresh_merges_fields_and_retains_last_good_data`, `test_remote_effect_override_does_not_fall_back_to_old_bulb_presets`, APK comparison script |
| P14 | Scene-container d5 is separate from the outbound dp field; dispatch only supports traced d6/d50 formats | Invalid-HSV-scene and root-container fixtures in `test_platform_devices.py` |

## Lifecycle and entities

| ID | Resolution | Regression evidence |
| --- | --- | --- |
| L01 | Bounded existing-session/profile/certificate recovery; stable installation identity; forced logout requires reauth | Certificate rotation, unchanged-content/changed-URL, no-relogin, and installation-identity cases |
| L02 | Refresh discovery, favorites and product metadata; reload/reconcile when identity, ownership, names or capabilities change | Product refresh, shared discovery, denied-family, scene refresh and real registry cases |
| L03 | Connection state and freshness are applied together on the HA loop; stale-client and SUBACK ordering cannot revive an unavailable transport | `test_connection_and_suback_are_applied_in_order_without_stale_success`, `test_queued_connection_callback_cannot_revive_a_replaced_client`, reconnect case |
| L04 | Authoritative reports notify all sibling entities; commands do not fabricate local state | Real entity listener lifecycle, partial reports, P1 and command response cases |
| L05 | Reauth rejects another account; reconfiguration and cached replacement credentials remain safe across unload | Reauth, real flow update helpers, API-cache and registry reconciliation cases |
| L06 | REST siblings, executor startup, partial platform setup, timers and transport clean up on failure/cancellation | REST cancellation, cancelled-worker-failure, partial-forward failure, failed-maintenance, unload-during-reauth and cleanup cases |
| L07 | Check startup queue results and SUBACK; eleven-device requests are exercised | Eleven-device, initial query failure, subscription rejection and real TLS cases |
| L08 | **Corrected audit claim:** LoginActivity.java:265 trims both credentials. Existing trimming matches the APK and is retained | `test_login_input_matches_app_whitespace_trimming` in `test_config_flow_errors.py` |
| L09 | Picker metadata plus prior native bulb capability and validated reports preserve controls; DIY pickers do not acquire temperature support from placeholder d4; malformed HSV is rejected | `test_all_known_picker_capabilities_are_stable_before_reports`; HSV boundaries in `test_protocol.py` |
| L10 | Diagnostics allowlist excludes account/device identifiers, names, keys, tokens and certificates | `test_diagnostics_excludes_account_identity_and_secrets` |
| L11 | Preserve user text and HA overrides, including an existing friendly-name prefix when discovery adds an opaque suffix | Name/factory-name cases and real registry rename/override assertions |

## Packaging, dependencies and checks

- Minimum HA is 2026.4.0. CI runs real Home Assistant cases on 2026.4.0 and
  2026.10.4, including actual Paho mutual TLS and startup GET-only checks.
- Local `brand/icon.png` is included, decoded and served through the actual HA
  brands view without a CDN fallback. English translations match strings.json.
- Paho declares the stable upstream minimum 2.1.0 as required by Home Assistant
  for a shared dependency. CI dependencies remain hash-locked. Dependency tests
  reject incompatible locks and manifest drift without raising the runtime
  minimum when only the CI lock is updated. Real HA tests use HA-supplied Paho.
- Pagination tests assert both collected results and requested cursors. Larger
  catalogs no longer silently stop at the old hundred-page limit.
- Import stubs are restored after each lightweight test.
- Manual publication downloads the successful verification run's artifact.
  Its receipt binds commit, tag and run ID. The publisher does not rebuild it.
- Ruff, compileall, HACS, Hassfest, CodeQL, Dependency Review and both actual-HA
  jobs remain required checks. Existing main branch requirements are preserved.
- No release, merge or live Home Assistant deployment is part of this PR.

## Scope and external observations

Camera support, microphone synchronization, a DIY editor, commissioning, account
sharing administration, firmware updates and TV calibration were excluded from
the requested feature scope. Preserving active modes and playing saved patterns
are included.

Backend sharing permissions, Apple sign-in policy and physical firmware behavior
cannot be certified by a source audit or offline fixtures. No live account or
production HA was used.

The HACS source examined at a15e87e constructs its update entity picture using
an external brands URL. The integration's local asset and HA serving path are
tested; this PR does not monkey-patch another integration or claim that an
external service's rendering has been verified on a live installation.

The four recorded pip hash-pinning findings are addressed in workflow source.
Scorecard alerts against main may remain until merge and rescan. SAST is exercised by the required CodeQL workflow. Historical
Code Review/Maintained metrics and optional Fuzzing/CII program participation
are not runtime defects; no history was rewritten, irrelevant workflow added,
certification claimed, or alert dismissed to make a score look clean.

## Follow-up after live startup failure

See [startup regression coverage](STARTUP-REGRESSIONS.md) for the observed failures, APK dispatch evidence, reconstructed fixture provenance, upgrade tests and bounded GET recovery. The original MQTT payload was not captured; these server tests do not claim another successful live deployment.

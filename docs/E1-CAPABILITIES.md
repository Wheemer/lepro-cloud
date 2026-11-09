> Historical E1 investigation. The broader [APK command audit](APK-COMMAND-AUDIT.md) adds verified native P4 white support, app length fallback and the other native palette families. Its conclusions supersede earlier RGB-only or missing-length-error assumptions here.

# E1-30 capability regression

## Product evidence

Lepro Home 1.0.9.269's config_response.json maps E1-30 to colorPicker=diyEaves and effect=striplight. The current public config.series.json served by the North American and European API hosts had the same mapping when checked on 2026-11-09.

In the decompiled APK, iotCore/AIOTSeriesType.java identifies E1-30 as RGBIC_LIGHT_E1_30. iotCore/mqtt/MqttConnectionPool.java:1103 requests online, d1, d2, d3, d4, d5, d50, d52 and d53 for this series. The integration requests the same state set. Its ordinary colour command uses d2/d5; saved RGBIC scenes use d2/d50/d52; scene brightness uses d52 without replacing d50.

## Reproduced defect and correction

_load_product_configs previously used an unconditional dictionary update. A successful but partial remote entry containing null colorPicker and effect values erased the bundled or previously valid product metadata. With only an on/off report available, the E1 light then lost its HS capability and saved-scene family selection.

The correction ignores non-string optional capability values and empty effect identifiers. Explicit empty colorPicker strings remain meaningful for dimmable-only products and are retained.

The partial-metadata regression fails against the previous implementation and passes with the correction. It uses a constructed malformed response, not a response captured from the reporter. The public E1-30 records checked during this investigation were valid. This establishes a real capability-loss bug, but does not prove it caused the reporter's exact on/off-only display.

## Server verification

Real Home Assistant tests cover E1-30 platform setup, rendered supported modes, brightness and effect attributes, colour/effect/brightness service calls, startup state queries including d53, and clean unload. The scene is a synthetic opaque payload used to verify byte preservation, not a new hardware-validated effect.

No live Home Assistant instance, Lepro account credentials or physical device was accessed. Physical E1-30 operation remains unverified.

## Valid-metadata follow-up

The published v0.2.0 ZIP was downloaded and verified on server. Its lighting, device classification, protocol, catalog, scene selection and switch modules match the checked-out code. The new valid-metadata lifecycle test passes against that actual extracted release, while the null-metadata regression fails against it.

The lifecycle test uses the real coordinator startup path with an isolated fake API and MQTT transport. It checks E1-30 discovery as type=1/control=2, exact APK state queries, HA registration as a light rather than a switch, capability attributes before any reports, online/on-off-only reports, RGBIC scene reports, colour reports, real HA colour/brightness service calls, metadata/session refresh, entity identity on reload and unload. This is protocol-backed synthetic testing, not captured reporter traffic.

AIOTDeviceType.java confirms LIGHT=1 and PLUG=2. MqttConnectionPool.java confirms E1-30's d53-inclusive query set. SmartCommonLightActivity.java selects PaletteDIYEStringFragment for the diyEaves picker and E1 family; DiyBaseFragment.java constructs saved DIY scenes as d50 EffectEntity payloads. The HA frontend's src/data/light.ts uses supported_color_modes to decide whether brightness and colour controls exist; src/dialogs/more-info/controls/more-info-light.ts renders those controls.

With valid metadata and type=1, this path consistently advertises HS, including when d5 or brightness state is absent. Even the malformed-metadata case falls back to BRIGHTNESS, not ONOFF. Consequently, the metadata defect does not on its own reproduce complete on/off-only controls. A switch classification (type=2), a different installed build or frontend/entity context would be distinct possibilities, not established causes. There is no evidence to justify overriding Lepro's explicit device type or adding speculative MQTT commands.

The reporter's exact symptom remains unresolved. Do not publish this as a confirmed fix for that symptom. The server-only evidence is retained in /root/codex-work/lepro-e1-regressions-2026-11-09.

## Classification and upgrade follow-up

Two additional regressions fail against the earlier implementation:

1. Duplicate family discovery used the last record wholesale. A later record with null type and blank series erased the complete E1 identity and could remove the device from supported discovery. Preserve existing identity fields when the duplicate omits them; explicit type, control and series changes remain authoritative.
2. A device previously registered as a plug switch kept that exact primary switch registration after discovery corrected its type to LIGHT. The correct light was created, but the stale switch remained available as a registry/dashboard reference. Remove only the obsolete primary unique ID owned by this entry, after the replacement domain is registered successfully. Retain it if replacement setup has not registered a new entity. Secondary settings, diagnostics and other integration/account registrations are not selected for deletion.

The real HA upgrade regression starts with a constructed type=2 record (which both the APK and integration treat as a plug), unloads it, corrects discovery to type=1 and verifies that the stale switch is removed and an HS light is present. It then injects stale ONOFF capability metadata into the light registry and verifies reload replaces it with HS while preserving the light's user name and icon.

The APK's HomeDeviceAdapter.java:868-872 routes item type 1 to launchCommonMain and type 2 to launchPlug. No historical integration revision inspected converts a type=1 E1 light into a switch; the primary switch path has consistently required type=2. The original integration's light class declared BRIGHTNESS, not ONOFF.

These are reproduced discovery/upgrade defects and the stale-switch scenario can leave an on/off-only entity in the user's registry. The report does not establish that Andy had a duplicate record, an earlier type=2 record or a stale switch. Do not describe this as his confirmed root cause. No release is authorized by these tests.

## APK-native colour command correction

The E1 diyEaves path is SmartCommonLightActivity → PaletteDIYEStringFragment / PaletteDIYStringFragment → mo13096u1 → IOTNativeUtil.getDiyMessage → native diyValue. DiyBaseFragment.m13080S1 wraps the generated scene as a d50 EffectEntity. State handling in PaletteDIYStringFragment.m14152F2 / mo13085b1 reads neon_effect (d50) and decodes it through IOTNativeUtil.diyEntity. This differs from the integration's previous generic d2=1/d5 command and d5-only colour feedback.

The x86-64 libiot-core.so was extracted directly from the permanently stored 1.0.9.269 split APK. SHA256: ad917cee5a77b1fd65265ad661cb1470030449bb8e1af2e0c21ec5ff1c8bc2e3. The JNI getDiyMessage wrapper calls exported diyValue with output buffer, type, colours/count, lengths/count, speed and light mode. The native encoder was executed in Unicorn on server with libc string/formatting shims; its actual instructions assembled the pattern. It was not replaced with a Python pattern implementation.

tests/fixtures/e1_native_colours.json records four native outputs for solid red, green, blue and white, one group, length 30, type 1, RGB light mode 1. The runtime Python helper is checked byte-for-byte against those APK outputs. The new real-HA regression failed first: the previous implementation sent d2=1/d5 instead of the native scene. It now sends d2=2/d50/d52.

E1-30's initial DiyInfo specifies 30 units, but the APK updates length from d53. Commands therefore use a positive device-reported d53 length, or the length from a fully parsed existing native solid pattern. They never assume 25 segments or send an unverified length when neither source is available. Unknown length produces a clear error without publishing a command.

Only the complete, single-group RGB solid form is decoded for a single HA colour. Multicolour, white-channel, animated and malformed patterns do not become an invented colour or fall back to stale d5 while scene mode is active. Other saved patterns remain opaque and unmodified. Brightness uses d52 without rebuilding the pattern.

The correction applies to the APK's diyEaves picker; other light colour paths remain unchanged. The physical E1-30 is still untested. This establishes a concrete colour command/state defect, not proof of the reporter's missing-control cause. All research, emulation and HA tests ran on server without account login or live HA access. No release.


## Direct comparative path investigation

Comparison pinned to Sanji78/lepro_led commit
444160f738a2cf501f158d1a2668e2b348e3782b. No code copied into this integration.

| Stage | Comparative path | Our path and APK evidence |
| --- | --- | --- |
| Discovery | First family; every record creates a light | All families, type/control filter. APK DeviceEntity serializes type/control/series directly; HomeDeviceAdapter distinguishes light and plug. Keep typed routing. |
| E1 capabilities | Always RGB, independent of metadata/reports | Released code derives capabilities from picker/reports. Server branch fixes null metadata; comparison exposed the additional blank-picker downgrade below. |
| Blank E1 picker | Still RGB | Our branch treated blank as authoritative BRIGHTNESS. APK SmartCommonLightActivity.F5 default constructs RGBcw, not a dimmer/power-only palette. Retain known native colour profile. |
| Startup brightness | Invented 255 until report | Our unknown reading is retained. HA brightness component renders even with unknown reading; do not invent full brightness to solve hidden controls. |
| Power entity | Separate switch for every light | Our primary switch requires cloud type2. This difference does not establish which entity Andy used. |
| E1 commands | Generic native pattern | Released d5 was wrong; earlier server correction uses independent APK-native d50/d52 evidence. |
| Effects | Always advertises built-ins | App scenes and verified presets; missing scenes cannot alone erase colour or brightness controls. |

Nine cases reproduced the blank-picker defect before correction: eight
discovery-to-entity combinations (two type representations, four report states)
and one cached-blank case. They now retain HS/CT and the native E1 writer.
A genuine D1 empty profile remains BRIGHTNESS. This is confirmed capability
loss, not evidence that Andy actually received blank metadata. BRIGHTNESS
still advertises a dimmer, so it does not establish literal ONOFF-only state.

New stub-only tests trace REST discovery, sparse duplicate merging, metadata,
and light/switch entity creation. Debug setup summaries record model, normalized
type, control, resolved picker, modes and received state-field names without
device names, IDs or credentials. They distinguish a switch from a light whose
metadata lost colour support when actual logs become available.

Permanent comparison files:
server:/root/codex-work/lepro-command-audit-2026-11-09/comparison.
APK DEX: SmartCommonLightActivity-F5.dex.txt, default block 0x03b2.
No HA instance, live HA access or release was used for this investigation.

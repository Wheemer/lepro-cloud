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

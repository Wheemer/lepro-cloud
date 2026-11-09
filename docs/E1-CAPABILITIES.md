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

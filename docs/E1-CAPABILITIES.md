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


## Remaining E1 differences: second comparative pass

The actual comparative light class was evaluated on server with its imports
stubbed, alongside our actual light class. This did not instantiate HA, start
MQTT or invoke device commands. Five identical E1 inputs covered no state,
off, on, d52 brightness and a native red d50 pattern. Captured constructor
outputs are in comparison/constructor-results.json.

The pinned HA frontend capability helper bodies were evaluated against those
outputs, retaining their actual decision logic. Both integrations expose
brightness and colour for all five inputs after our metadata corrections.
Results: comparison/frontend-capability-results.json.

| Remaining difference | Trace and result |
| --- | --- |
| RGB versus HS representation | Both are HA colour-capable modes. Native red reads RGB(255,0,0) in the comparative code and HS(0,100) here. Neither representation selects ONOFF. |
| Unknown initial brightness versus 255 | Ours remains unknown until authoritative data; comparative code defaults to 255. The actual HA brightness control renders with an undefined reading. Both still advertise brightness. |
| Multipart pattern readback | Comparative code projects the first colour across a fixed 25-cell view. Ours does not claim a single active colour for an arbitrary multicolour effect. The actual colour picker renders even without a current colour reading. This cannot alone remove its controls. |
| White controls | Comparative E1 exposes RGB only. APK PaletteDIYEStringFragment.initView explicitly enables RGB and white tabs; L2 returns native light mode1 or3. Our HS+CT representation follows that route. |
| Bare power-on | Comparative non-bulb path resends a constructed pattern; our bare power request changes only d1. APK LightBaseActivity switch writer uses DpSwitchLedValue. Resending a pattern is not required to create colour controls and can overwrite an existing effect. |
| Brightness while a scene runs | Comparative code regenerates its pattern. APK scene brightness is d52 without rebuilding d50; ours preserves the pattern. This changes command behavior, not advertised colour support. |
| Fixed 25-cell model | Comparative default segment storage is 25, irrespective of E1-30. APK DIYString uses product/report length. Our native length path follows that evidence; no synthetic segment entities were added. |
| Query versus creation order | Comparative code creates entities before their state request; ours can receive a report before platforms are added. New tests apply the actual coordinator report before and after entity/listener creation. Both preserve red, brightness and supported modes; later reports notify and unload removes listeners. |
| Report filtering and availability | Comparative code accepts incoming data directly and largely exposes an always-available device. Our validated authoritative reports control availability. A valid native E1 frame is accepted in both creation orders. No validation drop reproduced missing controls. |
| Extra entities | Comparative number.py supplies speed/sensitivity; switch.py supplies power. Those are separate from a light's brightness/colour attributes. Their presence does not establish why our reporter sees only on/off. |
| Typed platform routing | APK AIOTDeviceType explicitly defines LIGHT=1/PLUG=2; HomeDeviceAdapter.getItemViewType returns DeviceEntity.type, then selects common light versus plug. Our typed routing matches this. Comparative unconditional light creation is not evidence to override the APK. |

A native P3 warm-format investigation was also recorded in
comparison/e1-p3-native.json. The APK recognizes P3 as a white-editor input,
but the normal E1 white writer uses native mode3/P4. No new P3 encoder or
invented Kelvin readback was added from incomplete evidence. This does not
alter supported controls and is not identified as the reported cause.

The exact report remains unconfirmed. No actual discovery response, entity
attributes or debug log from Andy is available. These results eliminate
specific remaining code-path differences; they do not prove a root cause from
a single description or justify claiming the released E1 issue is solved.


## Full discovery / MQTT transport follow-up

See APK-COMMAND-AUDIT.md for the actual HTTPS plus Paho/mTLS loopback runs;
this extends the earlier constructor-only evidence. Four state-topic variants
each complete discovery, context-specific scene pages, initial GET, colour,
brightness, favourite, off/on and report-driven readback without HA.

A reproduced discovery defect was corrected: the old merge could replace the
reported owner fid with a later sparse family's context, and scene lookup used
that one field for all accounts. The APK instead supplies its selected family.
Queries now follow retained discovery contexts, including a single shared
context whose device reports another owner. Scoped cache and scene identities
avoid cross-family replacement and preserve accessible favourites during an
individual context failure.

This establishes a missing-favourites cause in that discovery path, not the
reporter's missing-colour/on-off-only cause. The complete wire fixture retains
HS/CT controls throughout; no actual reporter payload has become available.


## Source-level native state and brightness correction

Further code tracing found a separate ordinary-bulb fallthrough in light.py.
The E1/PG1 RGB-and-white palette uses native d50 plus d52, but the generic HA
branches could prefer d3/d4/d5 when a report carried ordinary work mode0 or1.
That could display an unrelated near-minimum brightness/white colour and send
the ordinary white dimming command.

The APK source chain is explicit:

- DiyBaseFragment.H1 reads DpStatusData.neon_bright (d52), without selecting d3
  or HSV value based on ordinary mode.
- PaletteDIYEStringFragment.P1 chooses its RGB/white editor tab from the native
  pattern's P1 versus P4/P3 marker.
- LightBaseActivity.setBrightness's j/l callbacks use rgbicBright$default with
  the work-mode default mask. The actual DEX default method supplies mode2.
- AIotUtils.rgbicBright builds DpRGBicBrightValue, carrying d2 and d52.

Corrected light.py uses the native state fields for this RGB/white-pattern
profile and selects mode2/d52 for its brightness request instead of falling
through to ordinary white/HSV commands. Products with a real ordinary CT page
(such as S2 and T1) keep d3/d4 white handling. Active music/TV branches remain
separate. Effect playback matching still requires scene mode2.

The old source was run through the same actual HTTPS/Paho fixture pipeline
without replacing the current checkout. With native red d50, d52=500 and
zero-valued ordinary fields plus d2=0, it reported brightness1 and ordinary
white mode. Dimming sent {d1:1,d2:0,d3:502,d4:0}. The corrected source reads
native red and brightness128; its first dimming command is
{d1:1,d2:2,d52:502}, matching the APK writer.

This is a reproduced conditional runtime defect, not evidence that Andy's
device sent that fixture. It explains a wrong state/dimming path if that
combination occurs; it does not prove literal controls were missing in his UI.
Before/after wire evidence and relevant DEX dumps are stored permanently on
server under lepro-command-audit-2026-11-09.


## Literal on/off-only display: device-page row

Source trace in HA frontend commit 283c335878daa6868fcc4a4fbc606fc9695d4dfc:

1. ha-device-entities-card.ts:147–156 renders a device control via
   entityRowElement(entity_id, name, hass).
2. entity-row-element-directive.ts:24 constructs a normal entity row with
   entity and name only; it supplies no custom control type.
3. create-row-element.ts:83 maps domain light to toggle. This mapping does not
   inspect supported_color_modes, brightness, effect_list or manufacturer.
4. hui-toggle-entity-row.ts:44–67 renders ha-entity-toggle for on/off/unknown/
   unavailable state, inside the generic row.
5. hui-generic-entity-row.ts:55–58 documents the default row action as more-info.
   The name/icon interaction opens the detailed control rather than adding
   colour/brightness controls inline.
6. more-info-light.ts independently renders brightness and colour controls
   from supported_color_modes.

Therefore a correctly configured full-colour E1 light can show exactly one
on/off toggle in the device's Controls list. Both integrations use this
default HA row. The comparative repo's additional power/speed/sensitivity
entities add rows, not inline RGB controls to its light row.

This is a confirmed matching display mechanism, not confirmation of the
reporter's screen. His post does not identify whether he viewed that list
or the light's more-info dialog. The source has not reproduced a correctly
classified E1 light exporting ONOFF-only capability.

The complete switch/device routing history was re-read from git. Since the
initial commit 00f828d, primary switch creation requires plug classification;
no inspected revision turns a type1 E1 into a primary switch. Current HA
2026.11 LightEntity.capability_attributes exports our supported colour modes
independently of readings and EFFECT support. Missing d50/d52 alone cannot
remove those capabilities.

No runtime code was changed for the device-row finding. Adding redundant
control entities to compensate for the normal HA row would change the
integration without identifying the reported fault. Actual debug/state
evidence is needed to distinguish this display path from missing capabilities.
The public thread already contains a request for that log; no duplicate
request or public reply was posted by this investigation.

### Integral numeric representations in discovery and MQTT

Source comparison found another concrete compatibility gap: discovery compared
control using its string spelling, while MQTT validation required the original
value to spell exactly like Python's integer. Thus control 2.0 filtered out a
Wi-Fi light, and online 1.0 discarded an entire otherwise valid state report.
The comparative integration accepts numeric brightness via arithmetic; the APK
Gson JsonReader.nextInt accepts integral decimal/exponent representations and
rejects fractions or values outside signed int bounds.

The correction normalizes valid integral values for device classification,
bounded state datapoints, and command-response IDs/codes. It keeps the existing
boolean state compatibility, but rejects boolean identities and response codes.
A decimal success code no longer spuriously triggers a rejected-command refresh.
Scene cursor/identity policy is unchanged by this correction.

Verification: the actual MQTT callback receives a getr frame containing decimal
online, work mode, native brightness and length, and dispatches the complete
normalized state; fractional classification values are not truncated. All 181
offline tests pass, as do Ruff, compilation and diff whitespace checks. These
tests use import stubs and no Home Assistant instance or vendor account.

This is a reproduced input-handling bug, not evidence that Andy received these
numeric representations. It can explain missing discovery or discarded state;
it does not alone explain colour controls disappearing for a correctly
classified E1-30, whose capability declaration does not depend on MQTT values.
No claim is made that his reported symptom is resolved.

### Discovery transport gate: APK hybrid MQTT values

A further source comparison found has_cloud_control accepted only values 2/3.
APK data/room/entity/ControlType defines MQTT=2, BLE_MQTT=3,
P2P_MQTT=6 and BLE_MQTT_P2P=7. The actual
MqttConnectionPool$completeConnection$1 coroutine subscribes and searches
devices whose control is greater than 1. The comparative integration does not
filter this field at all. Our corrected gate includes the explicitly
MQTT-capable 6/7 alongside 2/3, while retaining the separate light/plug type
check and excluding pure BLE/P2P and cameras.

This reproduces an omitted-device bug with constructed discovery records.
No evidence establishes that E1-30 hardware actually reports control 6/7.
It does not explain partial controls on an already-created light.

The remaining direct path trace confirms: DeviceEntity serializes series,
type and control directly; our entity creation uses only classification;
only product-picker/state inference determines supported_color_modes.
MQTT processing accepts the APK d-object envelope on its four subscribed
response/report topics, merges partial state, and notifies entity listeners.
No MQTT callback modifies device type, series or picker, and native parsing
does not participate in capability declaration. The source still does not
establish the reporter's actual input or exact failure.

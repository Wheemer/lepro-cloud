# APK command audit — 9 November 2026

This supersedes the earlier claim that catalog/query-list agreement established
command compatibility. It did not. That audit missed palette dispatch, native
encoders and the outer saved-scene fallback.

## Evidence and boundaries

Lepro Home 1.0.9.269 base APK SHA256:
a046aaf19c32ab788ed5071f403c78241116381988ea21dc3bbaead5fcc6ee42.
Permanent decompilation on server:
/root/codex-work/lepro-ha-cloud/references/lepro-home-1.0.9.269.
Bytecode dumps, native execution harnesses, hashes and outputs:
/root/codex-work/lepro-command-audit-2026-11-09.

Scope: operations exposed by this integration, authentication, discovery,
state, transport and lifecycle. App-only camera control, BLE, music sync,
effect editing, schedules and firmware updates are not newly implemented.

APK evidence establishes app commands, not physical firmware behavior on every
model. The E1-30 user's exact on/off-only display remains unreproduced; do not
describe these corrections as confirmation of his reported cause.

No live HA, authenticated vendor request or HA instance was used for this
command audit. Tests import stubs. Real-HA results elsewhere are historical
and were not rerun for these changes.

## Account and discovery ledger

APK paths are relative to decompiled sources/com/lepro.

| Operation | APK writer/reader | Integration comparison |
| --- | --- | --- |
| Account region | data/network/api/UserApi.java, region | Form POST /user/region, account/timestamp; host allowlist retained |
| Email login | UserApi.java, login | Form POST /user/login with platform/account/password/mac/timestamp/language/fcmToken; retained |
| Installation identity | LoginActivity login call | Stable HA installation identity retained; no random identity per retry |
| Whitespace | LoginActivity | App trims input; matching behavior retained |
| Profile | UserApi.java, profile | GET /user/profile; MQTT host/port/root/cert plus login secret; retained |
| App token region | UserApi.java, tokenForRegion | JSON POST /web/token/region; retained |
| App exchange and renewal | UserApi.java, toKenLogin | JSON POST /web/token/refresh; uid/token/secret/expiry validation retained |
| Successor token | UserApi.java, getToken | Empty POST /inapp/token; successor userToken/tokenExpire persisted |
| Token wrapping | uikit/utils/AESCipher.java | AES-CBC/PKCS7 plus Base64; retained |
| Apple/app handoff | Existing app-authorization evidence | Signed HA state and app callback code; no session import; no fresh account test in this audit |
| Families and shares | data/network/api/DeviceApi.java, family | GET /family/list/timestamp/{timestamp}; every returned family queried |
| Devices | DeviceApi.java, device | GET /v3/device/list/fid/{fid}/timestamp/{timestamp}; owning fid retained |
| Sparse duplicates | Family merge | Known type/series/control retained when absent in later record; explicit new values authoritative |
| Product metadata | config.series resource and bundled config_response.json | All 70 bundled records checked; null remote fields cannot erase valid capabilities |
| Saved pages | DeviceApi.java, sceneList | Correct fid/did/cid/limit/timestamp route; cursors, identity and outage cache reviewed |
| Revoked credentials | API errors and account logout action | Reauth; no automatic password-login loop |
| App session | Token expiry fields | Expected uid, successor token and persisted OAuth renewal retained; five-minute maintenance is HA policy |

## Transport ledger

| Operation | APK evidence / HA contract | Result |
| --- | --- | --- |
| MQTT login | Connection creation and profile | Mutual TLS, app-style client ID and packaged shared key retained |
| GET / SET | MQTT publish | le/{did}/prp/get and le/{did}/prp/set, id/d envelope, QoS 0 |
| Subscriptions | Connection subscribe | rpt/getr/setr/dsr/app/getr retained |
| Account action | Secret-matched act/app/exe | Logout reauth; disDevice refresh |
| State dispatch | MQTT property dispatch | d-bearing envelope is state regardless of c; c-only response correlated separately |
| Queue acceptance | HA contract | Does not fabricate reported state |
| Rejected/missing reply | HA recovery policy | GET only; never replay a SET |
| Startup | Connection callback | GET only; no on/off command |
| Recovery queries | Pool series list plus MqttDpDataKt DIY query | Fixed: startup and recovery share scene/native extras; native palettes request d50/d52/d53 |
| Partial reports | MQTT DP handling | Online inference and explicit offline precedence retained |
| Availability | HA contract | Broker connectivity plus fresh device report |
| Entity updates | HA contract | Authoritative sibling updates; polling disabled |

## Palette and light ledger

Routing: SmartCommonLightActivity.F5 and PaletteRgbcwFragment.q1/c1.
Where jadx warns of broken branches, matching DEX instructions were dumped and
checked. Normal palette events were followed to outbound writers; editor/save
methods alone were not treated as ordinary commands.

| Operation / family | APK chain | Result |
| --- | --- | --- |
| On/off | LightBaseActivity → DpSwitchLedValue | Numeric d1=1/0 retained |
| Ordinary RGB | RgbFragment → colourFinal → DpColourValue | d2=1/d5 HSV retained |
| Ordinary white | CwFragment → tempFinal → DpTempValue | d2=0/d3 brightness/d4 temperature retained |
| S1/N1 and Pro, SD1 | diy2 → DIY2/Doodle → getDiyMessage | Fixed: native d50/d2=2/d52, not generic d5 |
| S2/S2-Pro/SW1 palette-list members | RGBcw → Doodle2 RGB / Cw white | Fixed: native RGB plus CT; SW1-6 is included in the CCT palette list |
| WL1 | DiyFragment → getDiyMessage | Fixed: native RGB and reported length |
| E1/E1-Plus | DIYEString → DIYString | Native RGB mode1 and white mode3/P4, d50/d52 |
| EE1 | Doodle2 | Native RGB; no invented E1 white axis |
| PG1 | rgbcw special route → DIYEString | Fixed: native RGB/P4 white |
| ZB1 | diyString → RGBcw → DIYZBString / Cw | Fixed: native RGB and ordinary CT |
| TB1/TB1-Pro | DiyStar.u1 | Fixed: 48 weighted cells total 196 units |
| TB2 | MusicFragment inherits normal Doodle palette | Fixed: solid native RGB, length152; no music sync added |
| O1 | O1Diy/OCommonDiy → getDiyMessageForO1 | Fixed: native floor T01 format, length182/layer2; ordinary CT |
| OE1/OE1-Pro | RGBcw → OCommonDiy / OE1WDB | Fixed: native RGB, ordinary CT; save encoder distinct from slider |
| T1 | RGBcw → DiyCeiling / Cw | Fixed: native RGB length32, ordinary CT |
| F2 family | RGBcw → Rgb / FWDB | Ordinary d5 and d3/d4 retained; F2-30 rgb exception has CT |
| STV1 RGB | STV wrapper → STVDIY → Doodle native writer | Fixed: native d50/d52; product IDs 111/112/143/144/158 map to 36/50/48/68/24 units, default36 |
| Other rgbcw/rgb, including T2 | Default RGBcw/RGB | Ordinary d5 and d3/d4; no invented native overrides |
| Length defaults | DiyBaseFragment.initView | All constructor cases compared; SW1-6 proId154=18 |
| Reported lengths | Palette report listeners | d53 used only by palettes that consume it; fixed TB1/TB2/O1 lengths not overwritten |
| E1 absent length | DIYString.F2 | Positive report, valid solid cache, then app fallback15 |
| Native state | Native decoders and complete solid format | Separate RGB/P4 readback; stale d5 not used for active native colour |
| Colour mode | HA supported-mode contract | Valid supported mode; stale P4 cannot override active d2=1 |
| Kelvin units | HA UI semantics | 2700–6500 K maps native warm/cold axis; not APK-verified physical calibration |
| Ordinary brightness | DeviceExtKt.bright / HSV/white writers | d3 or HSV V; clamps and S1-10 2.0.16 compensation retained |
| RGBIC scene brightness | Scene writer | Preserve d2 and d50, adjust d52 |
| d6 dimming | Dp6Scene.withBrightness | White/HSV unit offsets correct; preserve timing/other fields |
| Music dimming | App-specific music parameters | Reject unsupported ordinary-bulb dimming rather than invent d52 |
| TV mode brightness | TVModeFragment seekbar | d2=5/d52 with direct 0–1000 slider mapping |

## Saved scene ledger

SceneEntityKt.effect selects family (striplight → neonlight).
LightBaseActivity.sceneEffect then falls back to root d5 EffectEntity.
Root container d5 does not imply outbound dp=d5.

| Selected dp | AIotUtils.h command | Result |
| --- | --- | --- |
| d50 | res unchanged + d52 brightness, d1=1/d2=2 | Retain multipart/native bytes |
| d6 | res unchanged, d1=1/d2=2 | Fixed: preserve embedded unit brightness when selecting; explicit dimming rewrites |
| d5 | first8 HSV hex + brightness4 hex | Fixed: accept valid HSV scenes and update V |
| d3 | Integer brightness, res ignored | Fixed: accept brightness scene, including empty res |
| d52 | Integer brightness, res ignored | Fixed: accept brightness scene, including empty res |
| Missing family | Outer root fallback after strip/neon | Fixed: root effect not dropped |

App-saved effects pass through without rebuilding editor parameters. This
includes multipart TB1 favorites and supplied breath/gradient/rotation/circular/
flash/wave/laser payloads; names alone do not manufacture an effect.

## Plug and TV settings

P1 Flutter AOT: flutter_module/Module/Plug/PlugMainPage.dart.
Actual writers checked, not just DP labels:

- onLockModeSwitch, 0x4ca294: d102 1/0; AOT tagged Smi2 means integer1.
- onPowerMemorySwitch, 0x4cbb10: d100 2/0; tagged Smi4 means integer2.
- onIndicatorLightSwitch, 0x4cbd94: d101 strings 100000000/000000000.
- Existing values match; no optimistic state updates.
- LightSettingActivity → DpStvSwitchLed: d157 1/0.
- TVModeFragment → DpStvToggleLight: d172 1/0. Existing values match.

## HA lifecycle and packaging

HA contracts were reviewed separately from APK claims: setup cancellation,
partial forwarding failure, unload, listeners, command timers, maintenance
cancellation, MQTT disconnect/loop stop, certificate cleanup, API cache removal,
reauth and reconfigure. Lightweight lifecycle tests do not start HA.

Registry migration removes a stale primary only after the same entry's
replacement exists. User overrides and sibling entities remain.
Shared discovery preserves family ownership and sparse duplicates.
Diagnostics allowlist excludes keys/tokens/certificates/identifiers.

Archive validation now requires capabilities.py plus existing modules,
translations, icon and bundled key. Building the archive does not publish it.

## Native execution

Unicorn executes APK x86-64 libiot-core.so diyValue, diyValueForO1, diyEntity,
and diyEntityForO1. The harness supplies libc/JNI, C-locale primitives and
single-thread mutex/thread stubs, not replacement pattern algorithms.
Scratch stack is cleared before top-level calls.

52 fixtures: RGB primary colours/white at twelve lengths, three P4 inputs, and
O1 solid. All have native decoder results, including O1 layer/direction/length.
Permanent evidence-sha256.json records harness/library/APK/DEX hashes.
Only JSON witnesses are committed; no APK binary is shipped.

Allowed checks: lightweight pytest, Ruff, compileall, APK checker, native
execution and archive verification. No live HA, new HA instance, vendor login,
version bump or release.

Validation result: 119 lightweight tests pass. Existing real-HA regression
expectations were updated for the corrected E1 white capability and app length
fallback, but those HA tests were deliberately not executed under the current
restriction. They remain a required later validation before release.

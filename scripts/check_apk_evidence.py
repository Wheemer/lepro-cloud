"""Cross-check shipped catalog data against the permanently decompiled APK.

This optional maintainer check never downloads an APK or contacts a device.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import zipfile
from pathlib import Path

APK_SHA256 = "a046aaf19c32ab788ed5071f403c78241116381988ea21dc3bbaead5fcc6ee42"
ROOT = Path(__file__).resolve().parents[1]


def verify(apk: Path, decompiled: Path) -> None:
    if hashlib.sha256(apk.read_bytes()).hexdigest() != APK_SHA256:
        raise ValueError("This evidence check targets Lepro Home 1.0.9.269")
    path = ROOT / "custom_components/lepro_cloud/catalog.py"
    spec = importlib.util.spec_from_file_location("catalog_evidence", path)
    catalog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalog)
    source = json.loads(
        (decompiled / "resources/assets/config_response.json").read_text()
    )
    expected = [
        {key: item[key] for key in ("series", "effect", "colorPicker") if key in item}
        for item in source
    ]
    if catalog.PRODUCT_CONFIGS != expected:
        raise ValueError("Packaged product fallback differs from APK data")
    java = (
        decompiled
        / "sources/com/lepro/lamp/p047ui/adapter/BasicEffectBulbLampAdapter.java"
    ).read_text()
    presets = list(
        dict.fromkeys(re.findall(r'new EffectEntity\("([0-9A-Fa-f]+)"', java))
    )
    if list(catalog.BULB_PRESETS.values()) != presets:
        raise ValueError("Ordinary bulb presets differ from the APK constructors")

    path = ROOT / "custom_components/lepro_cloud/capabilities.py"
    spec = importlib.util.spec_from_file_location("capability_evidence", path)
    profiles = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(profiles)
    base = decompiled / "sources/com/lepro/lamp/p047ui"
    defaults = (base / "base/DiyBaseFragment.java").read_text()
    init = defaults[defaults.index("public void initView(") :]
    lengths = {}
    for match in re.finditer(
        r'case "([^"]+)":(.*?)(?=case "|default:)', init, re.DOTALL
    ):
        values = re.search(r"new C8312h\((\d+),", match[2])
        if values:
            lengths[match[1].upper()] = int(values[1])
    star = (base / "fragment/PaletteDiyStarFragment.java").read_text()
    weights = re.search(r"f14218i1 = \{([^}]+)\}", star)
    total = sum(int(value.strip()) for value in weights[1].split(","))
    assert total == 196
    lengths.update({"TB1": total, "TB1-PRO": total})
    if profiles.NATIVE_LENGTHS != lengths:
        raise ValueError("Native palette lengths differ from APK constructors")
    series_java = (
        decompiled / "sources/com/lepro/iotCore/AIOTSeriesType.java"
    ).read_text()
    groups = re.findall(r"mutableListOf\(([^;]+)\);", series_java)
    cct = set()
    for group in groups:
        names = re.findall(r'"([^"]+)"', group)
        if names and all(name.startswith(("S2-", "SW1-")) for name in names):
            cct.update(names)
    if profiles.CCT_STRIP_SERIES != cct:
        raise ValueError("CCT palette membership differs from APK series initializer")
    utilities = (decompiled / "sources/com/lepro/iotCore/AIotUtils.java").read_text()
    stv = utilities.split("public final int getSTVDefaultLength", 1)[1].split(
        "\n    public ", 1
    )[0]
    lengths_by_pid = {
        int(pid): int(length)
        for pid, length in re.findall(r"if \(pid == (\d+)\) \{\s*return (\d+);", stv)
    }
    tail = re.search(r"return pid == (\d+) \? (\d+) : (\d+);", stv)
    lengths_by_pid[int(tail[1])] = int(tail[2])
    if profiles.STV_LENGTHS != lengths_by_pid or int(tail[3]) != 36:
        raise ValueError("TV native lengths differ from APK product-ID dispatch")
    evidence = json.loads(
        (ROOT / "tests/fixtures/apk-native-patterns.json").read_text()
    )
    split = apk.parent / "split_config.x86_64.apk"
    with zipfile.ZipFile(split) as archive:
        library = archive.read("lib/x86_64/libiot-core.so")
    if hashlib.sha256(library).hexdigest() != evidence["library_sha256"]:
        raise ValueError("Native witnesses do not match the supplied APK library")
    if len(evidence["fixtures"]) != 52 or not all(
        "decoded" in item for item in evidence["fixtures"]
    ):
        raise ValueError("Native command witnesses lack decoder results")
    print(
        "APK hash, 70 products, d6 presets, palette lengths and 52 native witnesses verified"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("apk", type=Path)
    parser.add_argument("decompiled", type=Path)
    args = parser.parse_args()
    verify(args.apk, args.decompiled)

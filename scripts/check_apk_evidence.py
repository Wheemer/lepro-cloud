"""Cross-check shipped catalog data against the permanently decompiled APK.

This optional maintainer check never downloads an APK or contacts a device.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
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
    print("APK hash, 70 product records and both complete d6 presets match")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("apk", type=Path)
    parser.add_argument("decompiled", type=Path)
    args = parser.parse_args()
    verify(args.apk, args.decompiled)

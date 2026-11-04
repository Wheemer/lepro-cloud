"""APK scene-family selection and stable catalog reconciliation."""

from __future__ import annotations

import json
from typing import Any

from .catalog import PRODUCT_CONFIGS
from .protocol import scene_brightness

EFFECT_FAMILIES = frozenset(
    {
        "earthlight",
        "ceilinglight",
        "floorlight",
        "striplight",
        "smartbulb",
        "tvlight",
        "neonlight",
        "notelight",
    }
)


def effect_family(device: dict[str, Any], mapping: dict[str, str]) -> str | None:
    series = str(device.get("series") or device.get("pid") or "").upper()
    if series in mapping:
        candidate = mapping[series]
        return candidate if isinstance(candidate, str) else None
    candidate = device.get("effect")
    if not isinstance(candidate, str) or not candidate:
        candidate = next(
            (
                item.get("effect")
                for item in PRODUCT_CONFIGS
                if str(item.get("series", "")).upper() == series
            ),
            None,
        )
    return candidate if isinstance(candidate, str) else None


def selected_effect(
    scene: dict[str, Any], family: str | None
) -> tuple[str, str] | None:
    """Use SceneEntityKt.effect's exact family and only its defined fallbacks."""
    value = scene.get(family if family in EFFECT_FAMILIES else "d5")
    if family == "striplight" and not isinstance(value, dict):
        value = scene.get("neonlight")
    if not isinstance(value, dict):
        return None
    dp, res = value.get("dp"), value.get("res")
    if dp not in {"d6", "d50"} or not isinstance(res, str) or not res:
        return None
    if dp == "d6":
        try:
            scene_brightness(res, 1000)
        except ValueError:
            return None
    return dp, res


def saved_brightness(scene: dict[str, Any], family: str | None) -> int:
    """SavedEffects getBrightness reads EffectEntity.scene key/value metadata."""
    value = scene.get(family if family in EFFECT_FAMILIES else "d5")
    if family == "striplight" and not isinstance(value, dict):
        value = scene.get("neonlight")
    metadata = value.get("scene", "") if isinstance(value, dict) else ""
    if isinstance(metadata, str):
        fields = dict(
            part.split("=") for part in metadata.split("&") if part.count("=") == 1
        )
        try:
            return int(fields.get("brightness", 1000))
        except (ValueError, TypeError):
            pass
    return 1000


def merge_scenes(*sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Later source replaces the same identity; names are not identities."""
    merged: dict[str, dict[str, Any]] = {}
    for source in sources:
        for scene in source:
            if not isinstance(scene, dict):
                continue
            identifier = next(
                (
                    f"{key}:{scene[key]}"
                    for key in ("cid", "sid")
                    if scene.get(key) not in (None, "", 0, "0")
                ),
                None,
            )
            identity = identifier or json.dumps(scene, sort_keys=True)
            merged[identity] = scene
    return list(merged.values())

"""APK scene-family selection and stable catalog reconciliation."""

from __future__ import annotations

import json
from typing import Any

from .catalog import PRODUCT_CONFIGS
from .device import apk_product_series, product_series
from .protocol import parse_lepro_hsv, scene_brightness

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
    series = product_series(device)
    if apk_product_series(device) is not None:
        return next(
            item["effect"] for item in PRODUCT_CONFIGS if item["series"] == series
        )
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
    scene: dict[str, Any], family: str | None, *, root_fallback: bool = True
) -> tuple[str, str] | None:
    """Use SceneEntityKt.effect's exact family and only its defined fallbacks."""
    value = scene.get(family if family in EFFECT_FAMILIES else "d5")
    if family == "striplight" and not isinstance(value, dict):
        value = scene.get("neonlight")
    # LightBaseActivity.sceneEffect falls back to the root d5 EffectEntity
    # when family selection returns null, after striplight -> neonlight.
    if root_fallback and not isinstance(value, dict):
        value = scene.get("d5")
    if not isinstance(value, dict):
        return None
    dp, res = value.get("dp"), value.get("res")
    if not isinstance(dp, str):
        return None
    if dp in {"d3", "d52"}:
        # AIotUtils writes the saved brightness and ignores res for these.
        return dp, ""
    if dp not in {"d5", "d6", "d50"} or not isinstance(res, str) or not res:
        return None
    if dp == "d5":
        # The APK keeps the first eight HSV digits and appends brightness.
        # Normalize here so state matching can still compare a full d5 value.
        hue_saturation = res[:8]
        if len(hue_saturation) != 8 or parse_lepro_hsv(f"{hue_saturation}0000") is None:
            return None
        res = res if parse_lepro_hsv(res) is not None else f"{hue_saturation}0000"
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
    if not isinstance(value, dict):
        value = scene.get("d5")
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
            if scene.get("_family_id") is not None:
                identity = f"family:{scene['_family_id']}:{identity}"
            merged[identity] = scene
    # The same catalog entry can be supplied in multiple family contexts.
    # Keep distinct scoped edits, but do not duplicate byte-identical records.
    unique: dict[str, dict[str, Any]] = {}
    for scene in merged.values():
        content = json.dumps(
            {key: value for key, value in scene.items() if key != "_family_id"},
            sort_keys=True,
        )
        unique.setdefault(content, scene)
    return list(unique.values())

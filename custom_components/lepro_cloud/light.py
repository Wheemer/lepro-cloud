"""Light platform for Lepro Cloud."""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .capabilities import (
    has_native_cct,
    pattern_length,
    resolved_picker,
    uses_native_rgb,
    uses_pattern_cct,
)
from .catalog import BULB_PRESETS, PRODUCT_CONFIGS
from .client import LeproCoordinator
from .const import DOMAIN
from .device import device_info, device_type, is_light
from .protocol import (
    DP_BRIGHTNESS,
    DP_COLOR,
    DP_RGBIC_BRIGHTNESS,
    DP_TEMPERATURE,
    DP_WORK_MODE,
    MAX_HA_KELVIN,
    MIN_HA_KELVIN,
    WORK_MODE_COLOR,
    WORK_MODE_SCENE,
    WORK_MODE_WHITE,
    brightness_payload,
    color_payload,
    device_brightness,
    ha_to_lepro_brightness,
    lepro_hsv_to_hs,
    lepro_temperature_to_kelvin,
    lepro_to_ha_brightness,
    on_payload,
    parse_lepro_hsv,
    parse_rgbic_solid,
    parse_rgbic_white,
    rgbic_colour_payload,
    rgbic_white_payload,
    scene_brightness,
    state_datapoints_for_series,
    state_is_on,
    white_payload,
)
from .scenes import effect_family, saved_brightness, selected_effect

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Lepro Cloud lights."""
    coordinator: LeproCoordinator = entry.runtime_data
    entities = []
    for did, device in coordinator.devices.items():
        if not _is_supported_light(device):
            continue
        entity = LeproCloudLight(coordinator, did, device)
        _LOGGER.debug(
            "Lepro light setup: series=%s type=%s control=%s picker=%r "
            "supported_color_modes=%s state_fields=%s",
            device.get("series"),
            device_type(device),
            device.get("control"),
            resolved_picker(device, PRODUCT_CONFIGS),
            sorted(str(mode) for mode in entity.supported_color_modes),
            sorted(coordinator.states.get(did, {})),
        )
        entities.append(entity)
    async_add_entities(entities)


class LeproCloudLight(LightEntity):
    """A Lepro cloud-controlled light."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False

    def __init__(
        self, coordinator: LeproCoordinator, device_id: str, device: dict[str, Any]
    ) -> None:
        self.coordinator = coordinator
        self.device_id = device_id
        self.device = device
        self._attr_unique_id = f"{DOMAIN}_{device_id}"
        self._attr_device_info = device_info(device, device_id, "Lepro Light")

    async def async_added_to_hass(self) -> None:
        """Register for MQTT state updates."""
        self.async_on_remove(
            self.coordinator.listen(
                lambda did: (
                    self.async_write_ha_state() if did == self.device_id else None
                )
            )
        )

    @property
    def available(self) -> bool:
        """Return if the light is available."""
        return self.coordinator.device_available(self.device_id)

    @property
    def is_on(self) -> bool | None:
        """Return true if the light is on."""
        return state_is_on(self.coordinator.states.get(self.device_id, {}))

    @property
    def brightness(self) -> int | None:
        """Return brightness in Home Assistant scale."""
        state = self.coordinator.states.get(self.device_id, {})
        if self._work_mode == WORK_MODE_WHITE and DP_BRIGHTNESS in state:
            return lepro_to_ha_brightness(state[DP_BRIGHTNESS])
        if (
            self._work_mode == WORK_MODE_SCENE
            and effect_family(self.device, self.coordinator.effect_types) == "smartbulb"
        ):
            value = state.get("d6")
            if isinstance(value, str):
                try:
                    scene_brightness(value, 1000)
                    units = [
                        value[index : index + 22] for index in range(10, len(value), 22)
                    ]
                    return lepro_to_ha_brightness(
                        max(
                            int(
                                unit[14:18]
                                if int(unit[2:14], 16) == 0
                                else unit[10:14],
                                16,
                            )
                            for unit in units
                        )
                    )
                except ValueError:
                    return None
        if self._work_mode == WORK_MODE_COLOR or (
            self._work_mode == WORK_MODE_SCENE
            and self._brightness_datapoint == DP_BRIGHTNESS
            and "d6" not in state
        ):
            hsv = parse_lepro_hsv(state.get(DP_COLOR))
            if hsv is not None:
                return lepro_to_ha_brightness(hsv[2])
        return lepro_to_ha_brightness(state.get(self._brightness_datapoint))

    @property
    def _brightness_datapoint(self) -> str:
        """Select the reported brightness datapoint for this product family."""
        state = self.coordinator.states.get(self.device_id, {})
        series = self.device.get("series") or self.device.get("pid")
        if (
            self._uses_native_pattern
            or DP_RGBIC_BRIGHTNESS in state
            or DP_RGBIC_BRIGHTNESS in state_datapoints_for_series(series)
            or any(
                datapoint == "d50" for datapoint, _value in self._scene_effects.values()
            )
        ):
            return DP_RGBIC_BRIGHTNESS
        return DP_BRIGHTNESS

    @property
    def _work_mode(self) -> int:
        """Return the active device work mode without inventing a mode."""
        try:
            return int(
                self.coordinator.states.get(self.device_id, {}).get(DP_WORK_MODE)
            )
        except (TypeError, ValueError):
            return WORK_MODE_WHITE

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Return color modes supported by currently reported datapoints."""
        state = self.coordinator.states.get(self.device_id, {})
        modes = set()
        picker = resolved_picker(self.device, PRODUCT_CONFIGS)
        series = str(self.device.get("series") or self.device.get("pid") or "").upper()
        if has_native_cct(series, picker):
            return {ColorMode.HS, ColorMode.COLOR_TEMP}
        if uses_native_rgb(series, picker):
            return {ColorMode.HS}
        if picker == "":
            return {ColorMode.BRIGHTNESS}
        if picker == "rgbcw":
            return {ColorMode.HS, ColorMode.COLOR_TEMP}
        if picker == "rgb":
            modes = {ColorMode.HS}
            if effect_family(
                self.device, self.coordinator.effect_types
            ) == "smartbulb" and (
                self.device.get("_native_color_temp")
                or (
                    DP_TEMPERATURE in state
                    and lepro_temperature_to_kelvin(state[DP_TEMPERATURE]) is not None
                )
            ):
                modes.add(ColorMode.COLOR_TEMP)
            return modes
        if picker in {
            "diy",
            "diy2",
            "diyEaves",
            "diyStar",
            "diyString",
            "diyMusic",
        }:
            return {ColorMode.HS}
        if parse_lepro_hsv(state.get(DP_COLOR)) is not None:
            modes.add(ColorMode.HS)
        if lepro_temperature_to_kelvin(state.get(DP_TEMPERATURE)) is not None:
            modes.add(ColorMode.COLOR_TEMP)
        return modes or {ColorMode.BRIGHTNESS}

    @property
    def color_mode(self) -> ColorMode:
        """Return the active HA color mode from Lepro d2 work mode."""
        work_mode = self._work_mode

        supported = self.supported_color_modes
        if work_mode == WORK_MODE_COLOR and ColorMode.HS in supported:
            return ColorMode.HS
        if work_mode == WORK_MODE_WHITE and ColorMode.COLOR_TEMP in supported:
            return ColorMode.COLOR_TEMP
        if (
            work_mode == WORK_MODE_SCENE
            and self._uses_native_pattern
            and parse_rgbic_white(
                self.coordinator.states.get(self.device_id, {}).get("d50")
            )
            is not None
            and ColorMode.COLOR_TEMP in supported
        ):
            return ColorMode.COLOR_TEMP
        if ColorMode.HS in supported:
            return ColorMode.HS
        if ColorMode.COLOR_TEMP in supported:
            return ColorMode.COLOR_TEMP
        return ColorMode.BRIGHTNESS

    @property
    def supported_features(self) -> LightEntityFeature:
        """Return the features backed by app-provided device data."""
        return (
            LightEntityFeature.EFFECT if self._scene_effects else LightEntityFeature(0)
        )

    @property
    def effect_list(self) -> list[str] | None:
        """Return the device-specific scenes supplied by Lepro Cloud."""
        effects = self._scene_effects
        return list(effects) or None

    @property
    def effect(self) -> str | None:
        """Return the selected scene when its exact payload is reported."""
        if self._work_mode != WORK_MODE_SCENE:
            return None
        for name, (datapoint, value) in self._scene_effects.items():
            current = self.coordinator.states.get(self.device_id, {}).get(datapoint)
            if current == value:
                return name
            if datapoint == "d6" and isinstance(current, str):
                try:
                    if scene_brightness(current, 1000) == scene_brightness(value, 1000):
                        return name
                except ValueError:
                    pass
            if (
                datapoint == DP_COLOR
                and isinstance(current, str)
                and re.fullmatch(r"[0-9a-fA-F]{12}", value)
                and re.fullmatch(r"[0-9a-fA-F]{12}", current)
                and current[:8].lower() == value[:8].lower()
            ):
                return name
        return None

    @property
    def _scene_effects(self) -> dict[str, tuple[str, str]]:
        """Map app-provided scene names to their verified MQTT payloads."""
        effect_type = effect_family(self.device, self.coordinator.effect_types)
        effects: dict[str, tuple[str, str]] = {}
        scenes = self.device.get("scenes")
        if not isinstance(scenes, list):
            scenes = []
        for index, scene in enumerate(scenes, start=1):
            if not isinstance(scene, dict):
                continue
            selected = selected_effect(scene, effect_type)
            if selected is None:
                continue
            datapoint, value = selected
            label = scene.get("scene")
            if not isinstance(label, str) or "=" in label:
                label = None
            name = scene.get("name") or scene.get("groupName") or label
            if not isinstance(name, str) or not name.strip():
                name = f"Scene {scene.get('cid', index)}"
            base_name = name.strip()
            name = base_name
            suffix = 2
            while name in effects:
                name = f"{base_name} {suffix}"
                suffix += 1
            effects[name] = (datapoint, value)
        if effect_type == "smartbulb":
            for name, value in BULB_PRESETS.items():
                effects.setdefault(name, ("d6", value))
        return effects

    @property
    def _uses_native_pattern(self) -> bool:
        series = str(self.device.get("series") or self.device.get("pid") or "").upper()
        return uses_native_rgb(series, resolved_picker(self.device, PRODUCT_CONFIGS))

    @property
    def _uses_pattern_white(self) -> bool:
        series = str(self.device.get("series") or self.device.get("pid") or "").upper()
        return uses_pattern_cct(series, resolved_picker(self.device, PRODUCT_CONFIGS))

    def _pattern_length(self) -> int:
        state = self.coordinator.states.get(self.device_id, {})
        series = str(self.device.get("series") or "").upper()
        if series.startswith("E1-") and not state.get("d53"):
            parsed = parse_rgbic_solid(state.get("d50")) or parse_rgbic_white(
                state.get("d50")
            )
            if parsed is not None:
                return parsed[1]
        return pattern_length(self.device, state)

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Read eaves RGB scene colour or the ordinary d5 HSV value."""
        if self._uses_native_pattern and self._work_mode == WORK_MODE_SCENE:
            parsed = parse_rgbic_solid(
                self.coordinator.states.get(self.device_id, {}).get("d50")
            )
            return parsed[0] if parsed is not None else None
        return lepro_hsv_to_hs(
            self.coordinator.states.get(self.device_id, {}).get(DP_COLOR)
        )

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return color temperature from Lepro d4."""
        state = self.coordinator.states.get(self.device_id, {})
        if self._uses_pattern_white and self._work_mode == WORK_MODE_SCENE:
            parsed = parse_rgbic_white(state.get("d50"))
            return parsed[0] if parsed is not None else None
        return lepro_temperature_to_kelvin(state.get(DP_TEMPERATURE))

    @property
    def min_color_temp_kelvin(self) -> int:
        """Return warmest supported white temperature."""
        return MIN_HA_KELVIN

    @property
    def max_color_temp_kelvin(self) -> int:
        """Return coolest supported white temperature."""
        return MAX_HA_KELVIN

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        if ATTR_EFFECT in kwargs and kwargs[ATTR_EFFECT] not in self._scene_effects:
            raise ValueError("Unknown Lepro effect")
        values: dict[str, Any] = on_payload(True)
        brightness = kwargs.get(ATTR_BRIGHTNESS, self.brightness or 255)
        scene_level = None
        if ATTR_EFFECT in kwargs and ATTR_BRIGHTNESS not in kwargs:
            requested = self._scene_effects[kwargs[ATTR_EFFECT]]
            family = effect_family(self.device, self.coordinator.effect_types)
            scene_level = next(
                (
                    saved_brightness(scene, family)
                    for scene in (self.device.get("scenes") or [])
                    if isinstance(scene, dict)
                    and selected_effect(scene, family) == requested
                ),
                1000,
            )

        def level(*, effect: bool = False) -> int:
            if scene_level is not None:
                return device_brightness(
                    scene_level,
                    effect=True,
                    series=str(self.device.get("series") or ""),
                    firmware=str(self.device.get("fwVersion") or ""),
                )
            return ha_to_lepro_brightness(
                brightness,
                effect=effect,
                series=str(self.device.get("series") or ""),
                firmware=str(self.device.get("fwVersion") or ""),
            )

        if ATTR_EFFECT in kwargs and kwargs[ATTR_EFFECT] in self._scene_effects:
            datapoint, value = self._scene_effects[kwargs[ATTR_EFFECT]]
            values.update({DP_WORK_MODE: 2, datapoint: value})
            # The app sends scene brightness separately only for d50 RGBIC
            # payloads. All other scene datapoints already encode their own
            # values and must remain byte-for-byte intact.
            if datapoint == "d50":
                values[DP_RGBIC_BRIGHTNESS] = level(effect=True)
            elif datapoint == "d6" and ATTR_BRIGHTNESS in kwargs:
                values["d6"] = scene_brightness(value, level(effect=True))
            elif datapoint == "d5":
                values["d5"] = f"{value[:8]}{level(effect=True):04X}"
            elif datapoint in {"d3", "d52"}:
                values[datapoint] = level(effect=True)
        elif ATTR_HS_COLOR in kwargs:
            if self._uses_native_pattern:
                values.update(
                    rgbic_colour_payload(
                        kwargs[ATTR_HS_COLOR],
                        level(effect=True),
                        self._pattern_length(),
                        floor=str(self.device.get("series", "")).upper() == "O1",
                    )
                )
            else:
                values.update(color_payload(kwargs[ATTR_HS_COLOR], brightness))
        elif ATTR_COLOR_TEMP_KELVIN in kwargs:
            if self._uses_pattern_white:
                values.update(
                    rgbic_white_payload(
                        kwargs[ATTR_COLOR_TEMP_KELVIN],
                        level(effect=True),
                        self._pattern_length(),
                    )
                )
            else:
                values.update(white_payload(brightness, kwargs[ATTR_COLOR_TEMP_KELVIN]))
        elif ATTR_BRIGHTNESS in kwargs:
            # Keep an active RGBIC scene in d2=2; the official app changes only d52.
            if self._work_mode in (WORK_MODE_SCENE, 3, 5):
                if self._work_mode == 3 and self._brightness_datapoint == DP_BRIGHTNESS:
                    raise ValueError(
                        "Brightness control in app music mode is unavailable for this product"
                    )
                values[DP_WORK_MODE] = self._work_mode
                if self._work_mode == WORK_MODE_SCENE and (
                    effect_family(self.device, self.coordinator.effect_types)
                    == "smartbulb"
                    or self._brightness_datapoint == DP_BRIGHTNESS
                ):
                    state = self.coordinator.states.get(self.device_id, {})
                    active = self._scene_effects.get(self.effect)
                    if active is not None and active[0] in {"d3", "d52"}:
                        values[active[0]] = level(effect=True)
                    elif (active is not None and active[0] == "d5") or (
                        "d6" not in state
                        and parse_lepro_hsv(state.get("d5")) is not None
                    ):
                        values["d5"] = f"{state['d5'][:8]}{level(effect=True):04X}"
                    else:
                        current = state.get("d6")
                        if not isinstance(current, str):
                            raise ValueError(
                                "No valid scene data available for brightness adjustment"
                            )
                        values["d6"] = scene_brightness(current, level(effect=True))
                elif self._work_mode == 5:
                    # TVModeFragment's 0–100 seekbar writes progress * 10 directly.
                    values[DP_RGBIC_BRIGHTNESS] = max(
                        0, min(1000, round(int(brightness) * 1000 / 255))
                    )
                else:
                    values[DP_RGBIC_BRIGHTNESS] = level(effect=True)
            # A brightness-only service call must not change the active colour mode.
            elif self._work_mode == WORK_MODE_COLOR and self.hs_color is not None:
                values.update(color_payload(self.hs_color, kwargs[ATTR_BRIGHTNESS]))
            elif (
                self._work_mode == WORK_MODE_WHITE
                and self.color_temp_kelvin is not None
            ):
                values.update(
                    white_payload(kwargs[ATTR_BRIGHTNESS], self.color_temp_kelvin)
                )
            else:
                values.update(
                    brightness_payload(
                        kwargs[ATTR_BRIGHTNESS],
                        datapoint=self._brightness_datapoint,
                        work_mode=self._work_mode,
                    )
                )
        if DP_WORK_MODE in values and values[DP_WORK_MODE] in (0, 1):
            if DP_BRIGHTNESS in values:
                values[DP_BRIGHTNESS] = level()
            if DP_COLOR in values:
                values[DP_COLOR] = f"{values[DP_COLOR][:8]}{level():04X}"
        await self.hass.async_add_executor_job(
            self.coordinator.command, self.device_id, values
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        values = on_payload(False)
        await self.hass.async_add_executor_job(
            self.coordinator.command, self.device_id, values
        )


def _is_supported_light(device: dict[str, Any]) -> bool:
    """Return true when a discovered device is safe to expose as a basic light."""
    return is_light(device)

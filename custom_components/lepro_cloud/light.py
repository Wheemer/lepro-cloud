"""Light platform for Lepro Cloud."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import LeproCoordinator
from .const import DOMAIN
from .device import device_name, is_light
from .protocol import (
    DP_BRIGHTNESS,
    DP_COLOR,
    DP_ONLINE,
    DP_RGBIC_BRIGHTNESS,
    DP_TEMPERATURE,
    DP_WORK_MODE,
    MAX_HA_KELVIN,
    MIN_HA_KELVIN,
    WORK_MODE_COLOR,
    WORK_MODE_WHITE,
    brightness_payload,
    color_payload,
    ha_to_lepro_brightness,
    lepro_to_ha_brightness,
    lepro_hsv_to_hs,
    lepro_temperature_to_kelvin,
    on_payload,
    parse_lepro_hsv,
    state_datapoints_for_series,
    state_is_on,
    white_payload,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Lepro Cloud lights."""
    coordinator: LeproCoordinator = entry.runtime_data
    async_add_entities(
        LeproCloudLight(coordinator, did, device)
        for did, device in coordinator.devices.items()
        if _is_supported_light(device)
    )


class LeproCloudLight(LightEntity):
    """A Lepro cloud-controlled light."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self, coordinator: LeproCoordinator, device_id: str, device: dict[str, Any]
    ) -> None:
        self.coordinator = coordinator
        self.device_id = device_id
        self.device = device
        self._attr_unique_id = f"{DOMAIN}_{device_id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": device_name(device, "Lepro Light"),
            "manufacturer": "Lepro",
            "model": device.get("series") or device.get("pid") or "Wi-Fi light",
        }

    async def async_added_to_hass(self) -> None:
        """Register for MQTT state updates."""
        self.async_on_remove(
            self.coordinator.listen(
                lambda did: self.async_write_ha_state() if did == self.device_id else None
            )
        )

    @property
    def available(self) -> bool:
        """Return if the light is available."""
        state = self.coordinator.states.get(self.device_id, {})
        if DP_ONLINE in state:
            try:
                return int(state[DP_ONLINE]) > 0
            except (TypeError, ValueError):
                return False
        return self.coordinator.connected

    @property
    def is_on(self) -> bool | None:
        """Return true if the light is on."""
        return state_is_on(self.coordinator.states.get(self.device_id, {}))

    @property
    def brightness(self) -> int | None:
        """Return brightness in Home Assistant scale."""
        state = self.coordinator.states.get(self.device_id, {})
        if self._work_mode == WORK_MODE_COLOR:
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
            DP_RGBIC_BRIGHTNESS in state
            or DP_RGBIC_BRIGHTNESS in state_datapoints_for_series(series)
        ):
            return DP_RGBIC_BRIGHTNESS
        return DP_BRIGHTNESS

    @property
    def _work_mode(self) -> int:
        """Return the active device work mode without inventing a mode."""
        try:
            return int(self.coordinator.states.get(self.device_id, {}).get(DP_WORK_MODE))
        except (TypeError, ValueError):
            return WORK_MODE_WHITE

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Return color modes supported by currently reported datapoints."""
        state = self.coordinator.states.get(self.device_id, {})
        modes = set()
        if DP_COLOR in state:
            modes.add(ColorMode.HS)
        if DP_TEMPERATURE in state:
            modes.add(ColorMode.COLOR_TEMP)
        return modes or {ColorMode.BRIGHTNESS}

    @property
    def color_mode(self) -> ColorMode:
        """Return the active HA color mode from Lepro d2 work mode."""
        state = self.coordinator.states.get(self.device_id, {})
        work_mode = self._work_mode

        supported = self.supported_color_modes
        if work_mode == WORK_MODE_COLOR and ColorMode.HS in supported:
            return ColorMode.HS
        if work_mode == WORK_MODE_WHITE and ColorMode.COLOR_TEMP in supported:
            return ColorMode.COLOR_TEMP
        return ColorMode.BRIGHTNESS

    @property
    def effect_list(self) -> list[str] | None:
        """Return the device-specific scenes supplied by Lepro Cloud."""
        effects = self._scene_effects
        return list(effects) or None

    @property
    def effect(self) -> str | None:
        """Return the selected scene when its exact payload is reported."""
        for name, (datapoint, value) in self._scene_effects.items():
            current = self.coordinator.states.get(self.device_id, {}).get(datapoint)
            if current == value:
                return name
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
        series = str(self.device.get("series") or self.device.get("pid") or "").upper()
        effect_type = self.coordinator.effect_types.get(series) or self.device.get("effect")
        effects: dict[str, tuple[str, str]] = {}
        scenes = self.device.get("scenes")
        if not isinstance(scenes, list):
            return effects
        for index, scene in enumerate(scenes, start=1):
            if not isinstance(scene, dict):
                continue
            effect = scene.get(effect_type) if isinstance(effect_type, str) else None
            if effect_type == "striplight" and not isinstance(effect, dict):
                effect = scene.get("neonlight")
            if not isinstance(effect, dict):
                effect = scene.get(DP_COLOR)
            if not isinstance(effect, dict):
                continue
            datapoint = effect.get("dp") or effect.get("command_type")
            value = effect.get("res")
            if (
                not isinstance(datapoint, str)
                or re.fullmatch(r"d[0-9]+", datapoint) is None
                or not isinstance(value, str)
                or not value
            ):
                continue
            name = (
                scene.get("name")
                or scene.get("groupName")
                or effect.get("scene")
                or scene.get("scene")
            )
            if not isinstance(name, str) or not name.strip():
                name = f"Scene {scene.get('cid', index)}"
            base_name = name.strip()
            name = base_name
            suffix = 2
            while name in effects:
                name = f"{base_name} {suffix}"
                suffix += 1
            effects[name] = (datapoint, value)
        return effects

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return HS color from Lepro d5."""
        return lepro_hsv_to_hs(
            self.coordinator.states.get(self.device_id, {}).get(DP_COLOR)
        )

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return color temperature from Lepro d4."""
        return lepro_temperature_to_kelvin(
            self.coordinator.states.get(self.device_id, {}).get(DP_TEMPERATURE)
        )

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
        values: dict[str, Any] = on_payload(True)
        brightness = kwargs.get(ATTR_BRIGHTNESS, self.brightness or 255)
        if ATTR_EFFECT in kwargs and kwargs[ATTR_EFFECT] in self._scene_effects:
            datapoint, value = self._scene_effects[kwargs[ATTR_EFFECT]]
            values.update({DP_WORK_MODE: 2, datapoint: value})
            # The app sends scene brightness separately only for d50 RGBIC
            # payloads. All other scene datapoints already encode their own
            # values and must remain byte-for-byte intact.
            if datapoint == "d50":
                values[self._brightness_datapoint] = ha_to_lepro_brightness(brightness)
            elif datapoint == DP_COLOR and re.fullmatch(r"[0-9a-fA-F]{12}", value):
                # The app keeps a saved HSV scene's hue and saturation but
                # rewrites its final value component to the requested level.
                values[DP_COLOR] = f"{value[:8]}{ha_to_lepro_brightness(brightness):04X}"
        elif ATTR_HS_COLOR in kwargs:
            values.update(color_payload(kwargs[ATTR_HS_COLOR], brightness))
        elif ATTR_COLOR_TEMP_KELVIN in kwargs:
            values.update(white_payload(brightness, kwargs[ATTR_COLOR_TEMP_KELVIN]))
        elif ATTR_BRIGHTNESS in kwargs:
            # A brightness-only service call must not change the active colour mode.
            if self.color_mode == ColorMode.HS and self.hs_color is not None:
                values.update(color_payload(self.hs_color, kwargs[ATTR_BRIGHTNESS]))
            elif (
                self.color_mode == ColorMode.COLOR_TEMP
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
        await self.hass.async_add_executor_job(
            self.coordinator.command, self.device_id, values
        )
        self.coordinator.states.setdefault(self.device_id, {}).update(values)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        values = on_payload(False)
        await self.hass.async_add_executor_job(
            self.coordinator.command, self.device_id, values
        )
        self.coordinator.states.setdefault(self.device_id, {}).update(values)
        self.async_write_ha_state()


def _is_supported_light(device: dict[str, Any]) -> bool:
    """Return true when a discovered device is safe to expose as a basic light."""
    return is_light(device)

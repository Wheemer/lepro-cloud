"""Tests for Lepro Cloud integration lifecycle setup."""

from __future__ import annotations

import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types
from typing import Any


PACKAGE_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "lepro_cloud"


def _load_integration_module() -> Any:
    homeassistant = types.ModuleType("homeassistant")
    homeassistant.__path__ = []
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    const = types.ModuleType("homeassistant.const")
    const.EVENT_HOMEASSISTANT_STOP = "homeassistant_stop"
    core = types.ModuleType("homeassistant.core")
    core.Event = object
    core.HomeAssistant = object
    exceptions = types.ModuleType("homeassistant.exceptions")

    class ConfigEntryAuthFailed(Exception):
        pass

    class ConfigEntryNotReady(Exception):
        pass

    exceptions.ConfigEntryAuthFailed = ConfigEntryAuthFailed
    exceptions.ConfigEntryNotReady = ConfigEntryNotReady

    package = types.ModuleType("custom_components.lepro_cloud")
    package.__path__ = [str(PACKAGE_PATH)]
    client = types.ModuleType("custom_components.lepro_cloud.client")

    class LeproError(Exception):
        pass

    class LeproApiError(LeproError):
        pass

    class LeproAuthError(LeproError):
        pass

    class LeproMqttError(LeproError):
        pass

    class LeproCoordinator:
        def __init__(self, _hass: Any, _entry: Any) -> None:
            self.started = False
            self.stopped = False

        async def async_start(self) -> None:
            self.started = True

        async def async_stop(self) -> None:
            self.stopped = True

    client.LeproApiError = LeproApiError
    client.LeproAuthError = LeproAuthError
    client.LeproCoordinator = LeproCoordinator
    client.LeproMqttError = LeproMqttError

    integration_const = types.ModuleType("custom_components.lepro_cloud.const")
    integration_const.PLATFORMS = []

    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.const"] = const
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.exceptions"] = exceptions
    sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
    sys.modules["custom_components.lepro_cloud"] = package
    sys.modules["custom_components.lepro_cloud.client"] = client
    sys.modules["custom_components.lepro_cloud.const"] = integration_const

    spec = spec_from_file_location("custom_components.lepro_cloud", PACKAGE_PATH / "__init__.py")
    assert spec and spec.loader
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeBus:
    def __init__(self) -> None:
        self.event_type: str | None = None
        self.listener: Any = None

    def async_listen_once(self, event_type: str, listener: Any) -> Any:
        self.event_type = event_type
        self.listener = listener
        return lambda: None


class FakeConfigEntries:
    async def async_forward_entry_setups(self, _entry: Any, _platforms: list[Any]) -> None:
        return None


class FakeHass:
    def __init__(self) -> None:
        self.bus = FakeBus()
        self.config_entries = FakeConfigEntries()


class FakeEntry:
    def __init__(self) -> None:
        self.data = {"region": "north_america"}
        self.runtime_data: Any = None
        self.unload_callbacks: list[Any] = []

    def async_on_unload(self, callback: Any) -> None:
        self.unload_callbacks.append(callback)


def test_core_stop_cleans_up_the_mqtt_coordinator() -> None:
    module = _load_integration_module()
    hass = FakeHass()
    entry = FakeEntry()

    assert asyncio.run(module.async_setup_entry(hass, entry)) is True
    assert entry.runtime_data.started is True
    assert hass.bus.event_type == "homeassistant_stop"
    assert len(entry.unload_callbacks) == 1

    asyncio.run(hass.bus.listener(None))
    assert entry.runtime_data.stopped is True

"""Fake Home Assistant objects for the unit tests (stub environment only)."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import ServiceCall
from homeassistant.helpers.device_registry import DeviceEntry, DeviceRegistry

from ..vicare_fakes import *  # noqa: F403
from ..vicare_fakes import (
    HEAT_PUMP_IDENTIFIER,
    VICARE_ENTRY_ID,
    FakeCachedService,
    make_runtime_data,
)


class FakeConfigEntries:
    def __init__(self) -> None:
        self.entries: list[ConfigEntry] = []
        self.forwarded: list[tuple[ConfigEntry, list[Any]]] = []
        self.unloaded: list[tuple[ConfigEntry, list[Any]]] = []

    def async_loaded_entries(self, domain: str) -> list[ConfigEntry]:
        return [
            entry
            for entry in self.entries
            if entry.domain == domain and entry.state is ConfigEntryState.LOADED
        ]

    def async_entries(self, domain: str | None = None) -> list[ConfigEntry]:
        return [entry for entry in self.entries if domain in (None, entry.domain)]

    async def async_forward_entry_setups(self, entry: ConfigEntry, platforms: list[Any]) -> None:
        self.forwarded.append((entry, list(platforms)))

    async def async_unload_platforms(self, entry: ConfigEntry, platforms: list[Any]) -> bool:
        self.unloaded.append((entry, list(platforms)))
        return True


class FakeServices:
    def __init__(self, hass: FakeHass) -> None:
        self._hass = hass
        self.registered: dict[tuple[str, str], dict[str, Any]] = {}

    def async_register(self, domain, service, service_func, schema=None, supports_response=None):
        self.registered[(domain, service)] = {
            "func": service_func,
            "schema": schema,
            "supports_response": supports_response,
        }

    async def async_call(self, domain: str, service: str, data: dict[str, Any] | None = None) -> Any:
        """Validate with the registered schema and call the handler."""
        registration = self.registered[(domain, service)]
        validated = registration["schema"](dict(data or {}))
        call = ServiceCall(self._hass, domain, service, validated, return_response=True)
        return await registration["func"](call)


class FakeConfig:
    language = "de"


class FakeHass:
    """The few parts of HomeAssistant this integration touches."""

    def __init__(self) -> None:
        self.config = FakeConfig()
        self.data: dict[str, Any] = {}
        self.config_entries = FakeConfigEntries()
        self.services = FakeServices(self)
        self.device_registry = DeviceRegistry()
        self.executor_jobs: list[Any] = []

    async def async_add_executor_job(self, func, *args):
        self.executor_jobs.append(func)
        return func(*args)


def make_hass(
    payload: dict[str, Any] | None = None,
    oauth_manager: Any = None,
    *,
    empty_cache: bool = False,
    register_device: bool = True,
) -> tuple[FakeHass, FakeCachedService]:
    """Return a hass with one loaded vicare entry."""
    hass = FakeHass()
    entry = ConfigEntry(domain="vicare", entry_id=VICARE_ENTRY_ID)
    entry.runtime_data, service = make_runtime_data(
        payload, oauth_manager, empty_cache=empty_cache
    )
    hass.config_entries.entries.append(entry)
    if register_device:
        hass.device_registry.add(
            DeviceEntry(
                id="ha-device-heat-pump",
                identifiers={("vicare", HEAT_PUMP_IDENTIFIER)},
                config_entry_id=VICARE_ENTRY_ID,
            )
        )
    return hass, service


def vicare_entry(hass: FakeHass) -> ConfigEntry:
    return hass.config_entries.entries[0]


class Platforms:
    """The sensor and binary sensor platforms set up against a fake hass."""

    def __init__(self, hass: FakeHass) -> None:
        from custom_components.vicare_extras.coordinator import ViCareExtrasCoordinator

        self.hass = hass
        self.entry = ConfigEntry(domain="vicare_extras", entry_id="extras")
        self.coordinator = ViCareExtrasCoordinator(hass, self.entry)
        self.sensors: list[Any] = []
        self.binary_sensors: list[Any] = []

    def _adder(self, target: list[Any]):
        def add(entities: list[Any]) -> None:
            for entity in entities:
                target.append(entity)
                # Real Home Assistant subscribes the entity when it is added.
                self.coordinator.async_add_listener(entity._handle_coordinator_update)

        return add

    def setup(self) -> Platforms:
        import asyncio

        asyncio.run(self._async_setup())
        return self

    async def _async_setup(self) -> None:
        from custom_components.vicare_extras import binary_sensor, sensor

        await self.coordinator.async_config_entry_first_refresh()
        self.entry.runtime_data = self.coordinator
        await sensor.async_setup_entry(self.hass, self.entry, self._adder(self.sensors))
        await binary_sensor.async_setup_entry(
            self.hass, self.entry, self._adder(self.binary_sensors)
        )

    def refresh(self) -> None:
        import asyncio

        asyncio.run(self.coordinator.async_refresh())

    @property
    def entities(self) -> list[Any]:
        return [*self.sensors, *self.binary_sensors]

    @staticmethod
    def _index(entities: list[Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for entity in entities:
            index = getattr(entity, "_index", None)
            if index is not None:
                result[f"{entity.translation_key}-{index}"] = entity
            result.setdefault(entity.translation_key, entity)
        return result

    def sensor(self, key: str) -> Any:
        return self._index(self.sensors)[key]

    def binary_sensor(self, key: str) -> Any:
        return self._index(self.binary_sensors)[key]

    def keys(self, entities: list[Any] | None = None) -> set[str]:
        return {entity.translation_key for entity in (self.entities if entities is None else entities)}

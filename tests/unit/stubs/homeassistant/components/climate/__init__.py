"""Stub of homeassistant.components.climate (native temperature API of 2026.11)."""

from enum import IntFlag, StrEnum

from homeassistant.helpers.entity import Entity


class HVACMode(StrEnum):
    OFF = "off"
    HEAT = "heat"
    COOL = "cool"


class HVACAction(StrEnum):
    COOLING = "cooling"
    HEATING = "heating"
    IDLE = "idle"
    OFF = "off"


class ClimateEntityFeature(IntFlag):
    TARGET_TEMPERATURE = 1


class ClimateEntity(Entity):
    _attr_hvac_action = None
    _attr_hvac_mode = None
    _attr_hvac_modes = []
    _attr_native_current_temperature = None
    _attr_native_target_temperature = None
    _attr_native_temperature_unit = None
    _attr_supported_features = ClimateEntityFeature(0)

    @property
    def hvac_mode(self):
        return self._attr_hvac_mode

    @property
    def hvac_modes(self):
        return self._attr_hvac_modes

    @property
    def native_temperature_unit(self):
        return self._attr_native_temperature_unit

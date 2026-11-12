"""Stub of homeassistant.components.sensor."""

from enum import StrEnum

from homeassistant.helpers.entity import Entity


class SensorDeviceClass(StrEnum):
    CO2 = "carbon_dioxide"
    ENERGY = "energy"
    ENUM = "enum"
    HUMIDITY = "humidity"
    POWER = "power"
    TEMPERATURE = "temperature"


class SensorStateClass(StrEnum):
    MEASUREMENT = "measurement"
    TOTAL = "total"
    TOTAL_INCREASING = "total_increasing"


class SensorEntity(Entity):
    _attr_native_unit_of_measurement = None
    _attr_options = None
    _attr_state_class = None
    _attr_suggested_display_precision = None

    @property
    def native_unit_of_measurement(self):
        return self._attr_native_unit_of_measurement

    @property
    def options(self):
        return self._attr_options

    @property
    def state_class(self):
        return self._attr_state_class

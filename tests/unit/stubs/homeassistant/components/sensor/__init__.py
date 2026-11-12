"""Stub of homeassistant.components.sensor."""

from dataclasses import dataclass
from enum import StrEnum


class SensorDeviceClass(StrEnum):
    ENERGY = "energy"


@dataclass(frozen=True, kw_only=True)
class SensorEntityDescription:
    key: str
    translation_key: str | None = None
    device_class: SensorDeviceClass | None = None
    native_unit_of_measurement: str | None = None
    state_class: str | None = None


class SensorEntity:
    entity_description = None
    device_entry = None
    _attr_device_class = None
    _attr_native_unit_of_measurement = None
    _attr_state_class = None
    _attr_unique_id = None
    _attr_device_info = None

    @property
    def device_class(self):
        return self._attr_device_class

    @property
    def native_unit_of_measurement(self):
        return self._attr_native_unit_of_measurement

    @property
    def state_class(self):
        return self._attr_state_class

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def device_info(self):
        return self._attr_device_info

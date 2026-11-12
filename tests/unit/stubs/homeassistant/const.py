"""Stub of homeassistant.const."""

from enum import StrEnum


class Platform(StrEnum):
    BINARY_SENSOR = "binary_sensor"
    CLIMATE = "climate"
    SENSOR = "sensor"


class EntityCategory(StrEnum):
    CONFIG = "config"
    DIAGNOSTIC = "diagnostic"


class UnitOfEnergy(StrEnum):
    WATT_HOUR = "Wh"
    KILO_WATT_HOUR = "kWh"


class UnitOfTemperature(StrEnum):
    CELSIUS = "°C"


ATTR_TEMPERATURE = "temperature"

"""Stub of homeassistant.const."""

from enum import StrEnum


class Platform(StrEnum):
    BINARY_SENSOR = "binary_sensor"
    SENSOR = "sensor"


class EntityCategory(StrEnum):
    CONFIG = "config"
    DIAGNOSTIC = "diagnostic"


class UnitOfEnergy(StrEnum):
    WATT_HOUR = "Wh"
    KILO_WATT_HOUR = "kWh"

"""Stub of homeassistant.const."""

from enum import StrEnum


class Platform(StrEnum):
    SENSOR = "sensor"


class UnitOfEnergy(StrEnum):
    WATT_HOUR = "Wh"
    KILO_WATT_HOUR = "kWh"

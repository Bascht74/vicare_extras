"""Stub of homeassistant.components.binary_sensor."""

from enum import StrEnum

from homeassistant.helpers.entity import Entity


class BinarySensorDeviceClass(StrEnum):
    PROBLEM = "problem"
    RUNNING = "running"
    WINDOW = "window"


class BinarySensorEntity(Entity):
    pass

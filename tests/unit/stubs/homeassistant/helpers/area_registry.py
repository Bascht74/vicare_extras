"""Stub of homeassistant.helpers.area_registry."""

from dataclasses import dataclass


@dataclass
class AreaEntry:
    id: str
    name: str


class AreaRegistry:
    def __init__(self):
        self.areas: dict[str, AreaEntry] = {}

    def add(self, area_id: str, name: str) -> AreaEntry:
        self.areas[area_id] = AreaEntry(area_id, name)
        return self.areas[area_id]

    def async_get_area(self, area_id):
        return self.areas.get(area_id)


def async_get(hass):
    return hass.area_registry

"""Stub of homeassistant.helpers.device_registry."""

from dataclasses import dataclass, field


@dataclass
class DeviceEntry:
    id: str
    identifiers: set = field(default_factory=set)
    config_entry_id: str | None = None


class DeviceRegistry:
    def __init__(self):
        self.devices: dict[str, DeviceEntry] = {}

    def add(self, device: DeviceEntry) -> DeviceEntry:
        self.devices[device.id] = device
        return device

    def async_get(self, device_id):
        return self.devices.get(device_id)

    def async_get_device_by_identifier(self, identifier, config_entry_id):
        for device in self.devices.values():
            if identifier in device.identifiers and device.config_entry_id == config_entry_id:
                return device
        return None


def async_get(hass):
    return hass.device_registry

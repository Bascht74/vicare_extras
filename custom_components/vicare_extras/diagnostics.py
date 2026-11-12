"""Diagnostics for ViCare Extras.

Contains no tokens, serial numbers, installation ids or zigbee addresses:
only device models, types, feature names and the poll intervals.
"""

from __future__ import annotations

import time
from typing import Any

from homeassistant.core import HomeAssistant

from . import bridge
from .coordinator import ViCareExtrasConfigEntry
from .errors import ViCareExtrasError
from .polling import builtin_interval_seconds


def _public_device_id(device_id: str) -> str:
    """Return the device id without the address of a zigbee device."""
    if device_id.startswith("zigbee-"):
        return f"zigbee-...{device_id[-4:]}"
    return device_id


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ViCareExtrasConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the config entry."""
    coordinator = entry.runtime_data
    now = time.monotonic()
    result: dict[str, Any] = {
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "snapshots": [
                {
                    "model": snapshot.device.model,
                    "device_id": _public_device_id(snapshot.device.device_id),
                    "age_seconds": round(now - snapshot.updated, 1),
                    "device_type": snapshot.device.device_type,
                    "feature_count": len(snapshot.features),
                }
                for snapshot in (coordinator.data or {}).values()
            ],
        },
        "vicare_entries_loaded": len(bridge.loaded_vicare_entries(hass)),
        "poll_interval": {
            # Option of this integration; None: the built-in is left alone.
            "option_seconds": coordinator.poll_manager.seconds,
            "vicare_seconds": builtin_interval_seconds(hass),
            "mirror_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
        },
        "devices": [],
    }

    try:
        devices = bridge.collect_all_devices(hass)
    except ViCareExtrasError as err:
        result["error"] = err.translation_key
        return result

    for device in devices:
        info: dict[str, Any] = {
            "model": device.model,
            "device_id": _public_device_id(device.device_id),
            "device_type": device.device_type,
            "set_up_by_vicare": device.identifier is not None,
            "service_class": type(device.service).__name__,
        }
        try:
            payload = bridge.peek_payload(device.service)
        except ViCareExtrasError as err:
            info["cache"] = err.translation_key
        else:
            if payload is None:
                info["cache"] = "empty"
            else:
                names = [
                    feature["feature"]
                    for feature in bridge.device_features(payload, device.device_id)
                ]
                info["cache"] = "present"
                info["cache_age_seconds"] = bridge.cache_age_seconds(device.service)
                info["feature_count"] = len(names)
                info["features"] = sorted(names)
        result["devices"].append(info)
    return result

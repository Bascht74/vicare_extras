"""Coordinator that mirrors data the built-in vicare integration has cached.

The coordinator never talks to the Viessmann API. Once per interval it looks
at the payload PyViCare holds in memory for the built-in integration (see
``bridge.peek_payload``) and keeps the handful of features the sensors need.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import bridge
from .const import (
    DEVICE_TYPE_HEATING,
    DOMAIN,
    MAX_SNAPSHOT_AGE_SECONDS,
    UPDATE_INTERVAL_SECONDS,
    WATCHED_FEATURES,
)
from .errors import ViCareExtrasError

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class DeviceSnapshot:
    """The watched features of one device at the time of the last look."""

    device: bridge.DeviceRef
    features: dict[str, dict[str, Any]]
    updated: float  # time.monotonic()


type ViCareExtrasConfigEntry = ConfigEntry[ViCareExtrasCoordinator]


class ViCareExtrasCoordinator(DataUpdateCoordinator[dict[str, DeviceSnapshot]]):
    """Mirror cached ViCare features, keyed by the vicare device identifier."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )

    async def _async_update_data(self) -> dict[str, DeviceSnapshot]:
        """Look at the cache of the built-in integration. No I/O, no API call."""
        try:
            devices = bridge.collect_all_devices(self.hass)
        except ViCareExtrasError as err:
            raise UpdateFailed(_describe(err)) from err

        previous: dict[str, DeviceSnapshot] = self.data or {}
        now = time.monotonic()
        snapshots: dict[str, DeviceSnapshot] = {}

        for device in devices:
            if device.identifier is None or device.device_type != DEVICE_TYPE_HEATING:
                continue
            try:
                payload = bridge.peek_payload(device.service)
            except ViCareExtrasError as err:
                raise UpdateFailed(_describe(err)) from err

            if payload is None:
                # The built-in integration is refreshing right now (or its
                # last refresh failed). Keep the last snapshot for a while.
                old = previous.get(device.identifier)
                if old is not None and now - old.updated <= MAX_SNAPSHOT_AGE_SECONDS:
                    snapshots[device.identifier] = old
                continue

            snapshots[device.identifier] = DeviceSnapshot(
                device=device,
                features={
                    feature["feature"]: feature
                    for feature in bridge.device_features(payload, device.device_id)
                    if feature["feature"] in WATCHED_FEATURES
                },
                updated=now,
            )
        return snapshots


def _describe(err: ViCareExtrasError) -> str:
    """Return an English log message for an error of the bridge."""
    messages = {
        "vicare_not_loaded": "the Viessmann ViCare integration is not loaded",
        "cache_unsupported": (
            "the PyViCare client of the ViCare integration has no readable "
            "feature cache (incompatible PyViCare version)"
        ),
    }
    if err.translation_key in messages:
        return messages[err.translation_key]
    detail = err.placeholders.get("detail", "")
    return f"unexpected structure of the ViCare integration data: {detail}"

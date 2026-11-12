"""Coordinator that mirrors data the built-in vicare integration has cached.

The coordinator never talks to the Viessmann API. Once per interval it looks
at the payload PyViCare holds in memory for the built-in integration (see
``bridge.peek_payload``) and keeps the feature objects of the devices the
entities are built from (by reference, nothing is copied):

* heating devices the built-in integration has set up,
* room control devices (``roomControl``), which the built-in integration does
  not set up,
* zigbee devices the built-in integration has set up (radiator thermostats).

On every look it also makes sure the optional poll interval of the built-in
integration is applied (``polling.py``) and adapts its own interval to it,
and it lets ``room_links.py`` work out the rooms of the thermostats.
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
    CONF_VICARE_POLL_INTERVAL,
    DEVICE_TYPE_HEATING,
    DEVICE_TYPE_ROOM_CONTROL,
    DEVICE_TYPE_ZIGBEE,
    DOMAIN,
    MAX_MIRROR_INTERVAL_SECONDS,
    MAX_SNAPSHOT_AGE_SECONDS,
    MAX_VICARE_POLL_INTERVAL,
    MIN_VICARE_POLL_INTERVAL,
    MIRROR_LEAD_SECONDS,
    UPDATE_INTERVAL_SECONDS,
)
from .errors import ViCareExtrasError
from .polling import PollIntervalManager, builtin_interval_seconds
from .room_links import RoomLinkManager

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class DeviceSnapshot:
    """The features of one device at the time of the last look."""

    device: bridge.DeviceRef
    features: dict[str, dict[str, Any]]
    updated: float  # time.monotonic()
    # The payload object the features were taken from (identity only).
    source: Any = None


type ViCareExtrasConfigEntry = ConfigEntry[ViCareExtrasCoordinator]


class ViCareExtrasCoordinator(DataUpdateCoordinator[dict[str, DeviceSnapshot]]):
    """Mirror cached ViCare features, keyed by ``DeviceRef.ref_id``."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.poll_manager = PollIntervalManager(_poll_interval_option(config_entry))
        # Values of commands sent from Home Assistant, shown until the
        # built-in integration has polled again: (device, feature, property).
        self._overrides: dict[tuple[str, str, str], Any] = {}
        # Which thermostat belongs to which room (learned, see room_links.py).
        self.room_links = RoomLinkManager(hass, config_entry)

    def set_override(self, ref_id: str, feature: str, prop: str, value: Any) -> None:
        """Remember a value that was just sent to the API."""
        self._overrides[(ref_id, feature, prop)] = value

    def get_override(self, ref_id: str, feature: str, prop: str) -> Any:
        """Return a value sent to the API that the cache does not show yet."""
        return self._overrides.get((ref_id, feature, prop))

    def _follow_builtin_interval(self) -> None:
        """Look slightly more often than the built-in integration polls.

        55 s for the default 60 s, 85 s for 90 s, never more than 120 s:
        looking is free, so there is no reason to let the entities lag far
        behind the built-in integration when it polls rarely.
        """
        builtin = builtin_interval_seconds(self.hass)
        seconds = float(UPDATE_INTERVAL_SECONDS)
        if builtin is not None:
            seconds = max(seconds, builtin - MIRROR_LEAD_SECONDS)
        seconds = min(seconds, float(MAX_MIRROR_INTERVAL_SECONDS))
        if self.update_interval != timedelta(seconds=seconds):
            self.update_interval = timedelta(seconds=seconds)

    async def _async_update_data(self) -> dict[str, DeviceSnapshot]:
        """Look at the cache of the built-in integration. No I/O, no API call."""
        try:
            devices = bridge.collect_all_devices(self.hass)
        except ViCareExtrasError as err:
            raise UpdateFailed(_describe(err)) from err

        # The vicare entry may have been reloaded: its new coordinators start
        # with their own interval again.
        self.poll_manager.apply(self.hass)
        self._follow_builtin_interval()

        previous: dict[str, DeviceSnapshot] = self.data or {}
        now = time.monotonic()
        snapshots: dict[str, DeviceSnapshot] = {}

        for device in devices:
            if not _wanted(device):
                continue
            try:
                payload = bridge.peek_payload(device.service)
            except ViCareExtrasError as err:
                raise UpdateFailed(_describe(err)) from err

            if payload is None:
                # The built-in integration is refreshing right now (or its
                # last refresh failed). Keep the last snapshot for a while.
                old = previous.get(device.ref_id)
                if old is not None and now - old.updated <= MAX_SNAPSHOT_AGE_SECONDS:
                    snapshots[device.ref_id] = old
                continue

            old = previous.get(device.ref_id)
            if old is None or old.source is not payload:
                # The built-in integration has polled since the last look:
                # the cache now shows what a command changed.
                for key in [key for key in self._overrides if key[0] == device.ref_id]:
                    del self._overrides[key]
            snapshots[device.ref_id] = DeviceSnapshot(
                device=device,
                features={
                    feature["feature"]: feature
                    for feature in bridge.device_features(payload, device.device_id)
                },
                updated=now,
                source=payload,
            )
        self.room_links.observe(snapshots, now)
        return snapshots


def _wanted(device: bridge.DeviceRef) -> bool:
    """Return True for the devices entities are created for."""
    if device.device_type in (DEVICE_TYPE_HEATING, DEVICE_TYPE_ZIGBEE):
        # Only devices with a device registry entry of vicare.
        return device.identifier is not None
    return device.device_type == DEVICE_TYPE_ROOM_CONTROL


def _poll_interval_option(config_entry: ConfigEntry) -> int | None:
    """Return the configured poll interval of the built-in integration."""
    value = getattr(config_entry, "options", {}).get(CONF_VICARE_POLL_INTERVAL)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(min(max(value, MIN_VICARE_POLL_INTERVAL), MAX_VICARE_POLL_INTERVAL))


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

"""Sensors of the ViCare Extras integration.

All values come from ``ViCareExtrasCoordinator``, which only mirrors what the
built-in vicare integration has already fetched. No sensor causes an API call.

State class
-----------
The energy sensors show a value that restarts at 0 every day. They deliberately
have **no** ``state_class``:

* ``measurement`` is not allowed for device class ``energy``.
* ``total_increasing`` would make the recorder treat every dip as a meter
  reset. The Viessmann backend corrects and shifts these arrays on its own
  schedule, so dips happen outside midnight too.
* ``total`` needs a ``last_reset`` that matches the real reset moment, which
  the API does not tell (``dayValueReadAt`` is a read time, not a reset time).
  A wrong ``last_reset`` produces negative consumption in the statistics.

Without a state class no long-term statistics are compiled, which is the
honest choice for a "history snapshot" sensor. The built-in integration
already offers statistics-capable sensors for today's consumption.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import features as ft
from .bridge import DeviceRef
from .const import (
    FEATURE_CONSUMPTION_DHW,
    FEATURE_CONSUMPTION_HEATING,
    FEATURE_CONSUMPTION_TOTAL,
    FEATURE_MESSAGES_INFO,
    FEATURE_MESSAGES_SERVICE,
    FEATURE_MESSAGES_STATUS,
    FEATURE_PRODUCTION_DHW,
    FEATURE_PRODUCTION_HEATING,
    VICARE_DOMAIN,
)
from .coordinator import ViCareExtrasConfigEntry, ViCareExtrasCoordinator

_LOGGER = logging.getLogger(__name__)

# Entities only read coordinator data, nothing to throttle.
PARALLEL_UPDATES = 0

KIND_HISTORY = "history"
KIND_SUMMARY = "summary"
KIND_MESSAGES = "messages"

VICARE_UNIT_TO_HA_UNIT = {
    "kilowattHour": UnitOfEnergy.KILO_WATT_HOUR,
    "wattHour": UnitOfEnergy.WATT_HOUR,
}


@dataclass(frozen=True, kw_only=True)
class ViCareExtrasSensorDescription(SensorEntityDescription):
    """Describes a ViCare Extras sensor."""

    kind: str
    # The sensor is created when at least one of these features exists.
    feature_names: tuple[str, ...]


SENSORS: tuple[ViCareExtrasSensorDescription, ...] = (
    ViCareExtrasSensorDescription(
        key="power_consumption_dhw_history",
        translation_key="power_consumption_dhw_history",
        kind=KIND_HISTORY,
        feature_names=(FEATURE_CONSUMPTION_DHW,),
    ),
    ViCareExtrasSensorDescription(
        key="power_consumption_heating_history",
        translation_key="power_consumption_heating_history",
        kind=KIND_HISTORY,
        feature_names=(FEATURE_CONSUMPTION_HEATING,),
    ),
    ViCareExtrasSensorDescription(
        key="power_consumption_total_history",
        translation_key="power_consumption_total_history",
        kind=KIND_HISTORY,
        feature_names=(FEATURE_CONSUMPTION_TOTAL,),
    ),
    ViCareExtrasSensorDescription(
        key="heat_production_dhw_summary",
        translation_key="heat_production_dhw_summary",
        kind=KIND_SUMMARY,
        feature_names=(FEATURE_PRODUCTION_DHW,),
    ),
    ViCareExtrasSensorDescription(
        key="heat_production_heating_summary",
        translation_key="heat_production_heating_summary",
        kind=KIND_SUMMARY,
        feature_names=(FEATURE_PRODUCTION_HEATING,),
    ),
    ViCareExtrasSensorDescription(
        key="messages",
        translation_key="messages",
        kind=KIND_MESSAGES,
        feature_names=(
            FEATURE_MESSAGES_STATUS,
            FEATURE_MESSAGES_INFO,
            FEATURE_MESSAGES_SERVICE,
        ),
    ),
)


def _find_vicare_device(hass: HomeAssistant, device: DeviceRef) -> Any | None:
    """Return the device registry entry of the built-in integration, if any.

    Since Home Assistant 2026 a device belongs to exactly one config entry, so
    the sensors are not linked through ``device_info`` (that would create a
    second device). Instead the existing device entry is attached to the
    entity. If it cannot be found the sensor is created without a device.
    """
    if device.identifier is None or device.entry_id is None:
        return None
    try:
        return dr.async_get(hass).async_get_device_by_identifier(
            (VICARE_DOMAIN, device.identifier), device.entry_id
        )
    except Exception:  # noqa: BLE001 - never fail sensor setup over the link
        _LOGGER.debug("Could not look up the ViCare device", exc_info=True)
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ViCareExtrasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create sensors for every feature that exists, now or later."""
    coordinator = entry.runtime_data
    known: set[tuple[str, str]] = set()

    @callback
    def _async_discover() -> None:
        new_entities: list[ViCareExtrasSensor] = []
        for identifier, snapshot in (coordinator.data or {}).items():
            for description in SENSORS:
                if (identifier, description.key) in known:
                    continue
                if not any(
                    name in snapshot.features for name in description.feature_names
                ):
                    continue
                known.add((identifier, description.key))
                new_entities.append(
                    SENSOR_CLASSES[description.kind](
                        coordinator,
                        description,
                        snapshot.device,
                        _find_vicare_device(hass, snapshot.device),
                    )
                )
        if new_entities:
            async_add_entities(new_entities)

    _async_discover()
    entry.async_on_unload(coordinator.async_add_listener(_async_discover))


class ViCareExtrasSensor(CoordinatorEntity[ViCareExtrasCoordinator], SensorEntity):
    """Base class for the ViCare Extras sensors."""

    entity_description: ViCareExtrasSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ViCareExtrasCoordinator,
        description: ViCareExtrasSensorDescription,
        device: DeviceRef,
        device_entry: Any | None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._identifier = str(device.identifier)
        self._attr_unique_id = f"{self._identifier}-{description.key}"
        # Attach to the device of the built-in integration (no device_info).
        self.device_entry = device_entry

    @property
    def _features(self) -> dict[str, dict[str, Any]]:
        """Return the mirrored features of this sensor's device."""
        snapshot = (self.coordinator.data or {}).get(self._identifier)
        return snapshot.features if snapshot is not None else {}

    @property
    def _feature(self) -> dict[str, Any] | None:
        """Return the (first) feature this sensor is based on."""
        return self._features.get(self.entity_description.feature_names[0])

    @property
    def available(self) -> bool:
        """Return True while the mirrored data contains this sensor's feature."""
        return super().available and any(
            name in self._features for name in self.entity_description.feature_names
        )


class _EnergySensor(ViCareExtrasSensor):
    """Common unit handling of the energy sensors."""

    _attr_suggested_display_precision = 1

    def __init__(
        self,
        coordinator: ViCareExtrasCoordinator,
        description: ViCareExtrasSensorDescription,
        device: DeviceRef,
        device_entry: Any | None,
    ) -> None:
        """Initialize the sensor and take the unit from the feature."""
        super().__init__(coordinator, description, device, device_entry)
        raw = self._raw_unit()
        if raw is None or raw in VICARE_UNIT_TO_HA_UNIT:
            # kWh when the API reports no unit at all.
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_native_unit_of_measurement = VICARE_UNIT_TO_HA_UNIT.get(
                raw or "", UnitOfEnergy.KILO_WATT_HOUR
            )
        else:
            # Unknown unit: show it as reported, without claiming "energy".
            self._attr_native_unit_of_measurement = raw

    def _raw_unit(self) -> str | None:
        raise NotImplementedError


class ViCareExtrasHistorySensor(_EnergySensor):
    """Today's value plus the day/week/month/year arrays as attributes."""

    # The arrays change with every update and would bloat the recorder.
    _unrecorded_attributes = frozenset(
        {
            "day",
            "week",
            "month",
            "year",
            "day_value_read_at",
            "week_value_read_at",
            "month_value_read_at",
            "year_value_read_at",
        }
    )

    def _raw_unit(self) -> str | None:
        return ft.history_unit(self._feature)

    @property
    def native_value(self) -> float | int | None:
        """Return today's value (first element of the day array)."""
        return ft.history_value(self._feature)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the history arrays, newest value first."""
        return ft.history_attributes(self._feature)


class ViCareExtrasSummarySensor(_EnergySensor):
    """Today's value plus the other summary values as attributes."""

    def _raw_unit(self) -> str | None:
        return ft.summary_unit(self._feature)

    @property
    def native_value(self) -> float | int | None:
        """Return the value of the current day."""
        return ft.summary_value(self._feature)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return all summary values."""
        return ft.summary_attributes(self._feature)


class ViCareExtrasMessagesSensor(ViCareExtrasSensor):
    """Code of the newest status message, message lists as attributes."""

    _unrecorded_attributes = frozenset({"status", "info", "service"})

    @property
    def native_value(self) -> str | None:
        """Return the code of the newest status message."""
        return ft.messages_state(self._features)[0]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the status, info and service message lists."""
        return ft.messages_state(self._features)[1]


SENSOR_CLASSES: dict[str, type[ViCareExtrasSensor]] = {
    KIND_HISTORY: ViCareExtrasHistorySensor,
    KIND_SUMMARY: ViCareExtrasSummarySensor,
    KIND_MESSAGES: ViCareExtrasMessagesSensor,
}

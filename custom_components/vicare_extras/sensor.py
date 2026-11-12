"""Sensors of the ViCare Extras integration.

All values come from ``ViCareExtrasCoordinator``, which only mirrors what the
built-in vicare integration has already fetched. No sensor causes an API call.

Which sensor reads which feature is listed in ``specs.py``: ``ValueSpec``
entries become ``ViCareExtrasValueSensor`` (one property of one feature),
``SpecialSpec`` entries become one of the classes below.

State class of the energy sensors
---------------------------------
The history and summary sensors show a value that restarts at 0 every day.
They deliberately have **no** ``state_class``:

* ``measurement`` is not allowed for device class ``energy``.
* ``total_increasing`` would make the recorder treat every dip as a meter
  reset. The Viessmann backend corrects and shifts these values on its own
  schedule, so dips happen outside midnight too.
* ``total`` needs a ``last_reset`` that matches the real reset moment, which
  the API does not tell (``dayValueReadAt`` is a read time, not a reset time).

Without a state class no long-term statistics are compiled, which is the
honest choice for a "history snapshot" sensor. The built-in integration
already offers statistics-capable sensors for today's consumption.

Instantaneous values (temperatures, power, speeds, percentages) have state
class ``measurement``.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import derived, features as ft, messages, specs
from .coordinator import ViCareExtrasConfigEntry, ViCareExtrasCoordinator
from .entity import (
    Target,
    ViCareExtrasEntity,
    ViCareExtrasValueEntity,
    async_setup_discovery,
    create_value_entities,
)

# Entities only read coordinator data, nothing to throttle.
PARALLEL_UPDATES = 0

# Home Assistant stores at most 255 characters as a state.
MAX_STATE_LENGTH = 255

VICARE_UNIT_TO_HA_UNIT = {
    "kilowattHour": UnitOfEnergy.KILO_WATT_HOUR,
    "wattHour": UnitOfEnergy.WATT_HOUR,
}


def _truncate(text: str) -> str:
    return text if len(text) <= MAX_STATE_LENGTH else f"{text[: MAX_STATE_LENGTH - 1]}…"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ViCareExtrasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create sensors for every feature that exists, now or later."""
    coordinator = entry.runtime_data
    create_values = partial(
        create_value_entities,
        specs.PLATFORM_SENSOR,
        ViCareExtrasValueSensor,
        coordinator,
    )

    def create(
        scope: str,
        target: Target,
        features: dict[str, dict[str, Any]],
        known: set[str],
    ) -> list[SensorEntity]:
        entities: list[SensorEntity] = create_values(scope, target, features, known)
        if scope != specs.SCOPE_HEATING:
            return entities
        for spec in specs.SPECIAL_SPECS:
            for index in specs.special_indexes(spec, features):
                suffix = spec.key if index is None else f"{spec.key}-{index}"
                unique_id = f"{target.unique_prefix}-{suffix}"
                if unique_id in known:
                    continue
                known.add(unique_id)
                entities.append(
                    SPECIAL_CLASSES[spec.kind](coordinator, target, spec, index)
                )
        return entities

    entry.async_on_unload(async_setup_discovery(coordinator, create, async_add_entities))


class _DynamicEnumMixin:
    """Enum sensor whose options grow with the values the API sends.

    Home Assistant rejects an enum state that is not one of the options. The
    API can send values this integration has never seen; they are added to
    the options (and shown untranslated) instead of breaking the entity.
    """

    _attr_options: list[str]

    def _init_enum(self, known: tuple[str, ...]) -> None:
        self._attr_device_class = SensorDeviceClass.ENUM
        self._attr_options = list(known)
        self._ensure_current_option()

    def _ensure_current_option(self) -> None:
        value = self.native_value  # type: ignore[attr-defined]
        if isinstance(value, str) and value not in self._attr_options:
            self._attr_options = [*self._attr_options, value]

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if getattr(self, "_attr_device_class", None) is SensorDeviceClass.ENUM:
            self._ensure_current_option()
        super()._handle_coordinator_update()  # type: ignore[misc]


class ViCareExtrasValueSensor(_DynamicEnumMixin, ViCareExtrasValueEntity, SensorEntity):
    """One property of one ViCare feature."""

    def __init__(
        self,
        coordinator: ViCareExtrasCoordinator,
        target: Target,
        spec: specs.ValueSpec,
        index: int | None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, target, spec, index)
        if spec.diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if spec.kind == specs.KIND_ENUM:
            self._init_enum(specs.ENUM_STATES.get(spec.key, ()))
            return
        if spec.device_class is not None:
            self._attr_device_class = SensorDeviceClass(spec.device_class)
        self._attr_native_unit_of_measurement = specs.read_unit(
            spec, self._features, self._index
        )
        if spec.measurement:
            self._attr_state_class = SensorStateClass.MEASUREMENT
        if spec.precision is not None:
            self._attr_suggested_display_precision = spec.precision

    @property
    def native_value(self) -> float | int | str | None:
        """Return the value of the property."""
        return specs.read_value(self._spec, self._features, self._index)


class ViCareExtrasSpecialSensor(ViCareExtrasEntity, SensorEntity):
    """Base class of the sensors with their own logic."""

    def __init__(
        self,
        coordinator: ViCareExtrasCoordinator,
        target: Target,
        spec: specs.SpecialSpec,
        index: int | None,
    ) -> None:
        """Initialize the sensor."""
        self._special = spec
        self._index = index
        self._feature_names = tuple(
            name if index is None else name.replace("{n}", str(index))
            for name in spec.features
        )
        super().__init__(
            coordinator,
            target,
            spec.key,
            spec.key if index is None else f"{spec.key}-{index}",
            specs.special_placeholders(spec, index),
        )
        self._attr_entity_registry_enabled_default = spec.enabled

    @property
    def _language(self) -> str:
        """Return the language for decoded message texts."""
        return getattr(self.coordinator.hass.config, "language", "de") or "de"

    @property
    def _feature(self) -> dict[str, Any] | None:
        """Return the (first) feature this sensor is based on."""
        return self._features.get(self._feature_names[0])

    def _has_data(self) -> bool:
        present = [name in self._features for name in self._feature_names]
        return all(present) if self._special.require == "all" else any(present)


class _EnergySensor(ViCareExtrasSpecialSensor):
    """Common unit handling of the energy sensors."""

    _attr_suggested_display_precision = 1

    def __init__(
        self,
        coordinator: ViCareExtrasCoordinator,
        target: Target,
        spec: specs.SpecialSpec,
        index: int | None,
    ) -> None:
        """Initialize the sensor and take the unit from the feature."""
        super().__init__(coordinator, target, spec, index)
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


class ViCareExtrasMessagesSensor(ViCareExtrasSpecialSensor):
    """Code of the newest status message, decoded lists as attributes."""

    _unrecorded_attributes = frozenset({"status", "info", "service"})

    @property
    def native_value(self) -> str | None:
        """Return the code of the newest status message."""
        return ft.messages_state(self._features, self._language)[0]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the status, info and service message lists with texts."""
        return ft.messages_state(self._features, self._language)[1]


class ViCareExtrasLastStatusSensor(ViCareExtrasSpecialSensor):
    """Decoded text of the newest status message (raw code when unknown)."""

    def _newest(self) -> dict[str, Any] | None:
        entries = derived.active_status_messages(self._features)
        return entries[0] if entries else None

    @property
    def native_value(self) -> str | None:
        """Return the text of the newest status message."""
        if (newest := self._newest()) is None:
            return None
        text = messages.label(newest.get("errorCode"), self._language)
        return _truncate(text) if text else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return code, time and text source of the newest status message."""
        if (newest := self._newest()) is None:
            return {}
        info = messages.describe(newest.get("errorCode"), self._language)
        return {
            "code": info["code"],
            # The device's local clock labelled as UTC ("Z"); not converted.
            "device_time": newest.get("timestamp"),
            "source": info["source"],
            "verified": info["verified"],
        }


class ViCareExtrasActiveStatusSensor(ViCareExtrasSpecialSensor):
    """All status messages that are active right now."""

    _unrecorded_attributes = frozenset({"messages"})

    @property
    def native_value(self) -> str | None:
        """Return the active status codes, sorted, separated by commas."""
        codes = derived.active_status_codes(self._features)
        if codes is None:
            return None
        return _truncate(", ".join(codes))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the active messages with decoded texts."""
        entries = derived.active_status_messages(self._features) or []
        return {
            "count": len(entries),
            "codes": derived.active_status_codes(self._features) or [],
            "messages": messages.decode_entries(entries, self._language),
        }


class ViCareExtrasOperatingStateSensor(ViCareExtrasSpecialSensor):
    """Operating state of the heat pump for a history timeline."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(derived.OPERATING_STATES)

    @property
    def native_value(self) -> str | None:
        """Return the derived operating state (see ``derived.py``)."""
        return derived.operating_state(self._features)[0]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return what the state was derived from."""
        return derived.operating_state(self._features)[1]


class ViCareExtrasHeatingRodStageSensor(ViCareExtrasSpecialSensor):
    """Number of active stages of the instantaneous heating water heater."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | None:
        """Return the number of active stages (0-3)."""
        return derived.heating_rod_stage(self._features)


class ViCareExtrasCopSensor(ViCareExtrasSpecialSensor):
    """Current heat production divided by current power consumption."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    @property
    def native_value(self) -> float | None:
        """Return the COP, unknown while the heat pump is not running."""
        return derived.current_cop(self._features)


class ViCareExtrasScheduleSensor(_DynamicEnumMixin, ViCareExtrasSpecialSensor):
    """Mode a schedule asks for right now, the schedule as attributes."""

    _unrecorded_attributes = frozenset({"entries", "today"})

    def __init__(
        self,
        coordinator: ViCareExtrasCoordinator,
        target: Target,
        spec: specs.SpecialSpec,
        index: int | None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, target, spec, index)
        self._init_enum(specs.SCHEDULE_STATES)

    @property
    def native_value(self) -> str | None:
        """Return the scheduled mode at the current local time."""
        return derived.schedule_mode(self._feature, dt_util.now())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the schedule."""
        entries = ft.prop_value(self._feature, "entries")
        return {
            "active": ft.prop_value(self._feature, "active"),
            "today": derived.schedule_today(self._feature, dt_util.now()),
            "entries": entries if isinstance(entries, dict) else None,
        }


SPECIAL_CLASSES: dict[str, type[ViCareExtrasSpecialSensor]] = {
    specs.SPECIAL_HISTORY: ViCareExtrasHistorySensor,
    specs.SPECIAL_SUMMARY: ViCareExtrasSummarySensor,
    specs.SPECIAL_MESSAGES: ViCareExtrasMessagesSensor,
    specs.SPECIAL_LAST_STATUS: ViCareExtrasLastStatusSensor,
    specs.SPECIAL_ACTIVE_STATUS: ViCareExtrasActiveStatusSensor,
    specs.SPECIAL_OPERATING_STATE: ViCareExtrasOperatingStateSensor,
    specs.SPECIAL_HEATING_ROD_STAGE: ViCareExtrasHeatingRodStageSensor,
    specs.SPECIAL_COP: ViCareExtrasCopSensor,
    specs.SPECIAL_SCHEDULE: ViCareExtrasScheduleSensor,
}


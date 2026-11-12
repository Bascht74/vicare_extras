"""Climate entities: rooms and radiator thermostats of ViCare Smart Climate.

These are the only entities of this integration that can send a command, and
only when the user changes the target temperature. Reading works like for
all other entities: from the data the built-in integration has already
fetched, without any API call.

Room (one entity on the room device this integration creates)
    current temperature  ``rooms.<n>.sensors.temperature``
    target temperature   the first setpoint feature that advertises an
                         executable ``setTemperature`` command
                         (``temperature.levels.normal.perceived``,
                         ``temperature.levels.normal.heating``,
                         ``operating.programs.normalHeating``)
    action               ``rooms.<n>.operating.state`` → ``demand``

Radiator thermostat (attached to the device of the built-in integration)
    current temperature  ``device.sensors.temperature`` (only when connected)
    target temperature   ``trv.temperature`` with ``setTargetTemperature``
    action               heating while ``trv.valve.position`` is above 0

If the API offers no executable command for a setpoint, the entity is created
without the target temperature feature and shows the setpoint as attribute.

Not verified against a real installation: no rooms or thermostats were
available. Built from PyViCare 2.63.0's test responses, ViEventLog and the
Viessmann service manual 6221420.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import commands, specs, thermostats
from .const import DEVICE_TYPE_ROOM_CONTROL, DOMAIN
from .coordinator import ViCareExtrasConfigEntry, ViCareExtrasCoordinator
from .entity import Target, ViCareExtrasEntity, async_setup_discovery
from .errors import ViCareExtrasError
from .features import prop_value

# One command at a time per entity is enough; reads never block.
PARALLEL_UPDATES = 1

UNIQUE_SUFFIX = "climate"
DEFAULT_MIN_TEMP = 5.0
DEFAULT_MAX_TEMP = 30.0
DEFAULT_STEP = 0.5

ACTIONS = {
    thermostats.ACTION_HEATING: HVACAction.HEATING,
    thermostats.ACTION_COOLING: HVACAction.COOLING,
    thermostats.ACTION_IDLE: HVACAction.IDLE,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ViCareExtrasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create climate entities for rooms and radiator thermostats."""
    coordinator = entry.runtime_data

    def create(
        scope: str,
        target: Target,
        features: dict[str, dict[str, Any]],
        known: set[str],
    ) -> list[ClimateEntity]:
        entity: ClimateEntity
        if scope == specs.SCOPE_ROOM and target.room is not None:
            if thermostats.room_setpoint(features, target.room) is None:
                return []
            entity_class: type[ViCareExtrasClimate] = ViCareExtrasRoomClimate
        elif scope == specs.SCOPE_TRV:
            if thermostats.trv_setpoint(features) is None:
                return []
            entity_class = ViCareExtrasThermostatClimate
        else:
            return []
        unique_id = f"{target.unique_prefix}-{UNIQUE_SUFFIX}"
        if unique_id in known:
            return []
        known.add(unique_id)
        entity = entity_class(coordinator, target)
        return [entity]

    entry.async_on_unload(async_setup_discovery(coordinator, create, async_add_entities))


class ViCareExtrasClimate(ViCareExtrasEntity, ClimateEntity):
    """Common behaviour of the room and the thermostat entity."""

    # The entity is the main feature of its device and takes its name.
    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_hvac_mode = HVACMode.HEAT

    def __init__(self, coordinator: ViCareExtrasCoordinator, target: Target) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, target, UNIQUE_SUFFIX)
        self._target = target

    def _setpoint(self) -> thermostats.Setpoint | None:
        raise NotImplementedError

    def _has_data(self) -> bool:
        return self._setpoint() is not None

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Offer the target temperature only when the API offers a command."""
        setpoint = self._setpoint()
        if setpoint is not None and setpoint.command is not None:
            return ClimateEntityFeature.TARGET_TEMPERATURE
        return ClimateEntityFeature(0)

    @property
    def native_target_temperature(self) -> float | None:
        """Return the setpoint: the value just sent, else the cached one."""
        if (setpoint := self._setpoint()) is None:
            return None
        override = self.coordinator.get_override(
            self._ref_id, setpoint.feature, setpoint.prop
        )
        return override if override is not None else setpoint.value

    def _limit(self, name: str, default: float) -> float:
        setpoint = self._setpoint()
        value = getattr(setpoint.command, name) if setpoint and setpoint.command else None
        return default if value is None else value

    @property
    def min_temp(self) -> float:
        """Return the minimum the API accepts."""
        return self._limit("minimum", DEFAULT_MIN_TEMP)

    @property
    def max_temp(self) -> float:
        """Return the maximum the API accepts."""
        return self._limit("maximum", DEFAULT_MAX_TEMP)

    @property
    def target_temperature_step(self) -> float:
        """Return the step the API accepts."""
        return self._limit("step", DEFAULT_STEP)

    def _base_attributes(self) -> dict[str, Any]:
        setpoint = self._setpoint()
        return {
            # Also visible when the setpoint cannot be changed.
            "setpoint": self.native_target_temperature,
            "setpoint_feature": setpoint.feature if setpoint else None,
            "setpoint_writable": bool(setpoint and setpoint.command),
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Heat is the only mode; there is nothing to switch."""
        if hvac_mode is not HVACMode.HEAT:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="command_not_available"
            )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Send the new target temperature (one API call)."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        setpoint = self._setpoint()
        if temperature is None or setpoint is None or setpoint.command is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="command_not_available"
            )
        device = self._target.device
        try:
            # PyViCare uses requests: executor.
            sent = await self.hass.async_add_executor_job(
                commands.execute,
                device.service,
                device.accessor,
                setpoint.command,
                temperature,
            )
        except ViCareExtrasError as err:
            error_class = ServiceValidationError if err.validation else HomeAssistantError
            raise error_class(
                translation_domain=DOMAIN,
                translation_key=err.translation_key,
                translation_placeholders=err.placeholders,
            ) from err
        # Show the new value until the built-in integration has polled again.
        self.coordinator.set_override(self._ref_id, setpoint.feature, setpoint.prop, sent)
        self.async_write_ha_state()


class ViCareExtrasRoomClimate(ViCareExtrasClimate):
    """A room of the ViCare room control."""

    def __init__(self, coordinator: ViCareExtrasCoordinator, target: Target) -> None:
        """Initialize the room entity."""
        super().__init__(coordinator, target)
        self._room = int(target.room or 0)

    def _setpoint(self) -> thermostats.Setpoint | None:
        return thermostats.room_setpoint(self._features, self._room)

    @property
    def native_current_temperature(self) -> float | None:
        """Return the room temperature."""
        return thermostats.sensor_value(
            self._features.get(f"rooms.{self._room}.sensors.temperature")
        )

    @property
    def current_humidity(self) -> float | None:
        """Return the room humidity."""
        return thermostats.sensor_value(
            self._features.get(f"rooms.{self._room}.sensors.humidity")
        )

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return what the room demands."""
        return ACTIONS.get(thermostats.room_action(self._features, self._room) or "")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the setpoint source and the devices assigned to the room."""
        state = self._features.get(f"rooms.{self._room}.operating.state")
        return {
            **self._base_attributes(),
            "level": prop_value(state, "level"),
            "demand": prop_value(state, "demand"),
            "actors": thermostats.room_actors(self._features, self._room),
        }


class ViCareExtrasThermostatClimate(ViCareExtrasClimate):
    """A radiator thermostat (TRV)."""

    def _setpoint(self) -> thermostats.Setpoint | None:
        return thermostats.trv_setpoint(self._features)

    @property
    def native_current_temperature(self) -> float | None:
        """Return the temperature the thermostat measures, if it reports one."""
        return thermostats.sensor_value(
            self._features.get(thermostats.TRV_TEMPERATURE_FEATURE)
        )

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return heating while the valve is open."""
        return ACTIONS.get(thermostats.trv_action(self._features) or "")

    def _find_room(self) -> tuple[int, str | None] | None:
        device = self._target.device
        for snapshot in (self.coordinator.data or {}).values():
            other = snapshot.device
            if (
                other.device_type == DEVICE_TYPE_ROOM_CONTROL
                and other.gateway_serial == device.gateway_serial
                and (found := thermostats.room_of_device(snapshot.features, device.device_id))
            ):
                return found
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the valve opening and the room the thermostat belongs to."""
        room = self._find_room()
        return {
            **self._base_attributes(),
            "valve_position": thermostats.trv_valve_position(self._features),
            "room": (room[1] or f"Room {room[0]}") if room else None,
        }

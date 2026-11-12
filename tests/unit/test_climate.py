"""Tests for the climate entities (rooms and radiator thermostats).

Everything here runs against synthetic features modelled on PyViCare 2.63.0's
test responses and ViEventLog. No real room or thermostat was available.
"""

from __future__ import annotations

import asyncio

import pytest

from homeassistant.components.climate import ClimateEntityFeature, HVACAction, HVACMode
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from . import fakes
from .fakes import Platforms

ROOM_PREFIX = f"{fakes.GATEWAY_SERIAL}_RoomControl-1_room_"
PERCEIVED = "temperature.levels.normal.perceived"


def setup(rooms=None, trv=None, *, answer=None, heat_pump=None):
    payload = fakes.gateway_payload([] if heat_pump is None else heat_pump, rooms or [], trv)
    service = fakes.FakeCommandService(payload, answer)
    hass, _ = fakes.make_hass(with_trv=trv is not None, service=service)
    return Platforms(hass).setup(), service


def room(platforms: Platforms, index: int = 0):
    return next(e for e in platforms.climates if e.unique_id == f"{ROOM_PREFIX}{index}-climate")


def thermostat(platforms: Platforms):
    return next(e for e in platforms.climates if e.unique_id == f"{fakes.TRV_IDENTIFIER}-climate")


def set_temperature(entity, value) -> None:
    asyncio.run(entity.async_set_temperature(temperature=value))


# ------------------------------------------------------------------------ rooms


def test_room_climate_entity() -> None:
    platforms, service = setup(fakes.room_features(0, writable=PERCEIVED, actors=(fakes.TRV_DEVICE_ID,)))
    entity = room(platforms)

    assert entity.native_current_temperature == 21.4
    assert entity.current_humidity == 48
    assert entity.native_target_temperature == 21
    assert entity.native_temperature_unit == "°C"
    assert entity.hvac_modes == [HVACMode.HEAT]
    assert entity.hvac_mode is HVACMode.HEAT
    assert entity.hvac_action is HVACAction.HEATING
    assert entity.supported_features == ClimateEntityFeature.TARGET_TEMPERATURE
    # Limits come from the command the API advertises.
    assert (entity.min_temp, entity.max_temp, entity.target_temperature_step) == (8, 30, 0.5)
    assert entity.extra_state_attributes == {
        "setpoint": 21,
        "setpoint_feature": "rooms.0.temperature.levels.normal.perceived",
        "setpoint_writable": True,
        "level": "normal",
        "demand": "heating",
        "actors": [fakes.TRV_DEVICE_ID],
    }
    # Main entity of the room device this integration creates.
    assert entity._attr_name is None
    assert entity.device_entry is None
    assert entity.device_info.identifiers == {("vicare_extras", f"{ROOM_PREFIX}0")}
    assert entity.device_info.name == "Wohnzimmer"
    assert entity.available
    assert service.commands == []
    assert service.api_calls == 0


def test_setting_the_room_temperature_sends_one_command() -> None:
    platforms, service = setup(fakes.room_features(0, writable=PERCEIVED))
    entity = room(platforms)

    set_temperature(entity, 22.5)

    assert service.commands == [
        ("RoomControl-1", "rooms.0.temperature.levels.normal.perceived", "setTemperature", {"targetTemperature": 22.5})
    ]
    assert len(platforms.hass.executor_jobs) == 1  # the blocking call ran in the executor
    assert entity.state_writes == 1
    # One API call: the cache of the built-in integration was not emptied,
    # so the built-in integration does not fetch again because of us.
    assert service.cache_clears == 0
    # Optimistic: the new value shows although the cache still says 21.
    assert entity.native_target_temperature == 22.5
    assert entity.extra_state_attributes["setpoint"] == 22.5
    # The sensor of the same setpoint is not touched; it follows the next poll.
    assert service.api_calls == 0


def test_optimistic_value_lasts_until_the_builtin_integration_polls_again() -> None:
    platforms, service = setup(fakes.room_features(0, writable=PERCEIVED))
    entity = room(platforms)
    set_temperature(entity, 23)

    platforms.refresh()  # the built-in integration has not polled yet
    assert entity.available
    assert entity.native_target_temperature == 23

    # The built-in integration polls: the API still reports 21 here, so the
    # entity shows what the API says rather than keeping its own value.
    service._cache = fakes.gateway_payload([], fakes.room_features(0, writable=PERCEIVED))
    platforms.refresh()
    assert entity.native_target_temperature == 21


def test_optimistic_value_survives_an_emptied_cache() -> None:
    """Fallback path: PyViCare empties its cache after the command."""
    payload = fakes.gateway_payload([], fakes.room_features(0, writable=PERCEIVED))
    service = fakes.FakeOtherCommandService(payload)
    hass, _ = fakes.make_hass(service=service)
    platforms = Platforms(hass).setup()
    entity = room(platforms)

    set_temperature(entity, 23)
    assert service._cache is None
    platforms.refresh()  # nothing cached: the last snapshot is kept
    assert entity.available
    assert entity.native_target_temperature == 23
    assert entity.native_current_temperature == 21.4

    service._cache = fakes.gateway_payload([], fakes.room_features(0, writable=PERCEIVED))
    platforms.refresh()
    assert entity.native_target_temperature == 21
    assert service.api_calls == 0


def test_room_without_executable_command_is_read_only() -> None:
    for rooms in (
        fakes.room_features(0),
        fakes.room_features(0, writable=PERCEIVED, executable=False),
    ):
        platforms, service = setup(rooms)
        entity = room(platforms)
        assert entity.supported_features == ClimateEntityFeature(0)
        assert entity.native_target_temperature == 21
        assert entity.extra_state_attributes["setpoint"] == 21
        assert entity.extra_state_attributes["setpoint_writable"] is False
        with pytest.raises(ServiceValidationError) as err:
            set_temperature(entity, 22)
        assert err.value.translation_key == "command_not_available"
        assert service.commands == []


def test_room_without_readable_setpoint_gets_no_climate_entity() -> None:
    features = [f for f in fakes.room_features(0) if ".temperature.levels." not in f["feature"]]
    platforms, _ = setup(features)
    assert platforms.climates == []
    assert platforms.sensors  # the room sensors still exist

    platforms, _ = setup(fakes.room_control_only_flags())  # the user's installation
    assert platforms.entities == []


def test_value_outside_the_limits_is_rejected_before_sending() -> None:
    platforms, service = setup(fakes.room_features(0, writable=PERCEIVED))
    entity = room(platforms)
    with pytest.raises(ServiceValidationError) as err:
        set_temperature(entity, 35)
    assert err.value.translation_key == "value_out_of_range"
    assert err.value.translation_placeholders == {"value": "35", "min": "8", "max": "30"}
    assert service.commands == []
    assert entity.native_target_temperature == 21


@pytest.mark.parametrize(
    ("answer", "key"),
    [
        (fakes.PyViCareCommandError(), "command_failed"),
        (fakes.PyViCareRateLimitError(), "rate_limited"),
        (fakes.PyViCareInternalServerError("x"), "server_error"),
    ],
)
def test_failed_command_raises_and_keeps_the_old_value(answer, key) -> None:
    platforms, service = setup(fakes.room_features(0, writable=PERCEIVED), answer=answer)
    entity = room(platforms)
    with pytest.raises(HomeAssistantError) as err:
        set_temperature(entity, 22)
    assert not isinstance(err.value, ServiceValidationError)
    assert err.value.translation_key == key
    assert len(service.commands) == 1
    assert entity.native_target_temperature == 21
    assert entity.state_writes == 0


def test_hvac_mode_cannot_be_changed() -> None:
    platforms, service = setup(fakes.room_features(0, writable=PERCEIVED))
    entity = room(platforms)
    asyncio.run(entity.async_set_hvac_mode(HVACMode.HEAT))  # nothing to do
    with pytest.raises(ServiceValidationError):
        asyncio.run(entity.async_set_hvac_mode(HVACMode.OFF))
    assert service.commands == []


def test_room_action_and_missing_sensors() -> None:
    features = [
        f
        for f in fakes.room_features(1, None)
        if not f["feature"].endswith((".sensors.temperature", ".sensors.humidity", ".operating.state"))
    ]
    platforms, _ = setup(features)
    entity = room(platforms, 1)
    assert entity.native_current_temperature is None
    assert entity.current_humidity is None
    assert entity.hvac_action is None
    assert entity.device_info.name == "Raum 1"  # Home Assistant runs in German here


def test_no_command_is_sent_without_a_user_action() -> None:
    platforms, service = setup(fakes.room_features(0, writable=PERCEIVED), fakes.trv_features())
    for _ in range(5):
        platforms.refresh()
    for entity in platforms.entities:
        entity.available  # noqa: B018 - reading every entity must not send anything
        getattr(entity, "native_value", None)
        getattr(entity, "extra_state_attributes", None)
    assert service.commands == []
    assert service.api_calls == 0


# ------------------------------------------------------------------ thermostats


def test_thermostat_climate_entity() -> None:
    rooms = fakes.room_features(2, "Küche", actors=(fakes.TRV_DEVICE_ID,))
    platforms, service = setup(rooms, fakes.trv_features())
    entity = thermostat(platforms)

    assert entity.native_current_temperature == 20.8
    assert entity.native_target_temperature == 20
    assert entity.hvac_action is HVACAction.HEATING
    assert entity.supported_features == ClimateEntityFeature.TARGET_TEMPERATURE
    assert (entity.min_temp, entity.max_temp, entity.target_temperature_step) == (8, 30, 0.5)
    assert entity.extra_state_attributes == {
        "setpoint": 20,
        "setpoint_feature": "trv.temperature",
        "setpoint_writable": True,
        "valve_position": 17,
        "room": "Küche",
    }
    # Attached to the device the built-in integration created for the thermostat.
    assert entity.device_entry is platforms.hass.device_registry.async_get("ha-device-trv")
    assert entity.device_info is None
    assert entity._attr_name is None
    # No sensors are duplicated for the thermostat (the built-in has them).
    assert all(e.unique_id.startswith(ROOM_PREFIX) for e in [*platforms.sensors, *platforms.binary_sensors])
    assert service.commands == []


def test_setting_the_thermostat_temperature() -> None:
    platforms, service = setup(trv=fakes.trv_features())
    entity = thermostat(platforms)

    set_temperature(entity, 19)

    assert service.commands == [
        (fakes.TRV_DEVICE_ID, "trv.temperature", "setTargetTemperature", {"temperature": 19})
    ]
    assert entity.native_target_temperature == 19


@pytest.mark.parametrize("status", ["notConnected", None])
def test_thermostat_without_actual_temperature(status) -> None:
    """Seen in the field: the thermostat reports no temperature of its own."""
    platforms, _ = setup(trv=fakes.trv_features(temperature_status=status, valve=0))
    entity = thermostat(platforms)
    assert entity.available
    assert entity.native_current_temperature is None
    assert entity.native_target_temperature == 20
    assert entity.hvac_action is HVACAction.IDLE
    assert entity.extra_state_attributes["room"] is None


def test_thermostat_read_only_without_executable_command() -> None:
    platforms, service = setup(trv=fakes.trv_features(executable=False))
    entity = thermostat(platforms)
    assert entity.supported_features == ClimateEntityFeature(0)
    with pytest.raises(ServiceValidationError):
        set_temperature(entity, 19)
    assert service.commands == []


def test_other_zigbee_devices_get_no_climate_entity() -> None:
    """A climate sensor is a zigbee device too, but has no trv.temperature."""
    sensor_only = [f for f in fakes.trv_features() if not f["feature"].startswith("trv.")]
    platforms, _ = setup(trv=sensor_only)
    assert platforms.climates == []


def test_heat_pump_gets_no_climate_entity() -> None:
    platforms, _ = setup(heat_pump=fakes.vitocal_features())
    assert platforms.climates == []
    assert len(platforms.sensors) == 46

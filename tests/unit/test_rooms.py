"""Tests for the room entities (ViCare Smart Climate room control).

The room features are synthetic: modelled on PyViCare 2.63.0's RoomControl
accessors and fixtures. No real installation with rooms was available.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory

from . import fakes
from .fakes import Platforms

ROOM_CONTROL = f"{fakes.GATEWAY_SERIAL}_RoomControl-1"


def setup(rooms: list[dict], heat_pump: list[dict] | None = None):
    hass, service = fakes.make_hass(fakes.gateway_payload([] if heat_pump is None else heat_pump, rooms))
    return Platforms(hass).setup(), service


def room_entities(platforms: Platforms, room: int) -> dict:
    prefix = f"{ROOM_CONTROL}_room_{room}-"
    return {
        entity.unique_id.removeprefix(prefix): entity
        for entity in platforms.entities
        if entity.unique_id.startswith(prefix)
    }


def test_room_entities() -> None:
    platforms, service = setup(fakes.room_features(0))
    entities = room_entities(platforms, 0)

    assert set(entities) == {
        "room_temperature",
        "room_humidity",
        "room_co2",
        "room_setpoint_normal_heating",
        "room_setpoint_reduced_heating",
        "room_setpoint_comfort_heating",
        "room_setpoint_normal_perceived",
        "room_operating_level",
        "room_window_open",
        "room_condensation_risk",
        "room_child_lock",
    }
    assert len(platforms.entities) == 11

    temperature = entities["room_temperature"]
    assert temperature.native_value == 21.4
    assert temperature.native_unit_of_measurement == "°C"
    assert temperature.device_class is SensorDeviceClass.TEMPERATURE
    assert temperature.state_class is SensorStateClass.MEASUREMENT
    assert entities["room_humidity"].native_value == 48
    assert entities["room_humidity"].device_class is SensorDeviceClass.HUMIDITY
    assert entities["room_co2"].native_value == 650
    assert entities["room_co2"].native_unit_of_measurement == "ppm"
    assert entities["room_co2"].device_class is SensorDeviceClass.CO2
    assert entities["room_setpoint_normal_heating"].native_value == 21
    assert entities["room_setpoint_reduced_heating"].native_value == 18
    assert entities["room_setpoint_comfort_heating"].native_value == 23
    assert entities["room_setpoint_normal_heating"].state_class is None
    assert not entities["room_setpoint_normal_perceived"].entity_registry_enabled_default

    level = entities["room_operating_level"]
    assert level.native_value == "normal"
    assert level.device_class is SensorDeviceClass.ENUM
    assert level.extra_state_attributes == {"demand": "heating", "reason": "schedule", "modifier": "none"}

    assert entities["room_window_open"].is_on is True
    assert entities["room_window_open"].device_class is BinarySensorDeviceClass.WINDOW
    assert entities["room_condensation_risk"].is_on is False
    assert entities["room_condensation_risk"].device_class is BinarySensorDeviceClass.PROBLEM
    assert entities["room_child_lock"].is_on is False
    assert entities["room_child_lock"].entity_category is EntityCategory.DIAGNOSTIC
    assert service.api_calls == 0


def test_each_room_gets_its_own_device() -> None:
    """vicare has no device for rooms, so this integration creates one per room."""
    platforms, _ = setup([*fakes.room_features(0), *fakes.room_features(2, None)])

    first = room_entities(platforms, 0)["room_temperature"]
    second = room_entities(platforms, 2)["room_temperature"]

    assert first.device_entry is None  # not linked to a vicare device
    assert first.device_info.identifiers == {("vicare_extras", f"{ROOM_CONTROL}_room_0")}
    assert first.device_info.name == "Wohnzimmer"
    assert first.device_info.manufacturer == "Viessmann"
    assert second.device_info.identifiers == {("vicare_extras", f"{ROOM_CONTROL}_room_2")}
    assert second.device_info.name == "Room 2"  # the API gave no name
    assert first.translation_placeholders == {}
    assert len(room_entities(platforms, 0)) == len(room_entities(platforms, 2)) == 11


def test_room_control_without_rooms_creates_nothing() -> None:
    """Seen on a real installation: only rooms.features.* flags, no rooms."""
    platforms, _ = setup(fakes.room_control_only_flags())
    assert platforms.entities == []
    assert f"{ROOM_CONTROL}" in platforms.coordinator.data  # the device is mirrored


def test_room_sensor_without_value_is_not_created() -> None:
    features = [
        fakes.feature("rooms.1", {"name": {"type": "string", "value": "Bad"}}, "RoomControl-1"),
        fakes.feature(
            "rooms.1.sensors.temperature", {"status": {"type": "string", "value": "notConnected"}}, "RoomControl-1"
        ),
        fakes.feature(
            "rooms.1.sensors.humidity",
            {"status": {"type": "string", "value": "connected"}, "value": {"type": "number", "unit": "percent", "value": 55}},
            "RoomControl-1",
        ),
        fakes.feature("rooms.1.sensors.window.openState", {"value": {"type": "boolean", "value": False}}, "RoomControl-1"),
        fakes.feature(
            "rooms.1.operating.programs.normalHeating",
            {"active": {"type": "boolean", "value": True}, "temperature": {"type": "number", "unit": "celsius", "value": 20}},
            "RoomControl-1",
        ),
    ]
    platforms, service = setup(features)
    entities = room_entities(platforms, 1)

    # Alternative feature names are used; the unconnected sensor is skipped.
    assert set(entities) == {"room_humidity", "room_window_open", "room_setpoint_normal_heating"}
    assert entities["room_setpoint_normal_heating"].native_value == 20
    assert entities["room_window_open"].is_on is False

    # The temperature sensor is connected later: the entity appears.
    connected = [
        fakes.feature(
            "rooms.1.sensors.temperature",
            {"status": {"type": "string", "value": "connected"}, "value": {"type": "number", "unit": "celsius", "value": 19.5}},
            "RoomControl-1",
        )
        if f["feature"] == "rooms.1.sensors.temperature"
        else f
        for f in features
    ]
    service._cache = fakes.gateway_payload([], connected)
    platforms.refresh()
    assert room_entities(platforms, 1)["room_temperature"].native_value == 19.5


def test_rooms_and_heat_pump_together() -> None:
    platforms, service = setup(fakes.room_features(0), fakes.vitocal_features())
    assert len(room_entities(platforms, 0)) == 11
    assert len(platforms.entities) == 64 + 11
    heat_pump = platforms.sensor("heat_production_current")
    assert heat_pump.device_info is None
    assert heat_pump.device_entry is not None
    assert service.api_calls == 0


def test_room_entities_become_unavailable_when_room_disappears() -> None:
    platforms, service = setup(fakes.room_features(0))
    entity = room_entities(platforms, 0)["room_temperature"]
    assert entity.available

    service._cache = fakes.gateway_payload([], fakes.room_control_only_flags())
    platforms.refresh()
    assert not entity.available
    assert entity.native_value is None

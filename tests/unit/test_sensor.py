"""Tests for the coordinator and the sensors, with mocked PyViCare objects."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.vicare_extras import coordinator as coordinator_module, sensor
from custom_components.vicare_extras.coordinator import ViCareExtrasCoordinator
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.exceptions import ConfigEntryNotReady

from . import fakes

ALL_KEYS = {
    "power_consumption_dhw_history",
    "power_consumption_heating_history",
    "power_consumption_total_history",
    "heat_production_dhw_summary",
    "heat_production_heating_summary",
    "messages",
}


class Platform:
    """A sensor platform set up against a fake hass."""

    def __init__(self, hass: fakes.FakeHass) -> None:
        self.hass = hass
        self.entry = ConfigEntry(domain="vicare_extras", entry_id="extras")
        self.coordinator = ViCareExtrasCoordinator(hass, self.entry)
        self.entities: list[sensor.ViCareExtrasSensor] = []

    def setup(self) -> Platform:
        asyncio.run(self._async_setup())
        return self

    async def _async_setup(self) -> None:
        await self.coordinator.async_config_entry_first_refresh()
        self.entry.runtime_data = self.coordinator
        await sensor.async_setup_entry(self.hass, self.entry, self.entities.extend)

    def refresh(self) -> None:
        asyncio.run(self.coordinator.async_refresh())

    def by_key(self) -> dict[str, sensor.ViCareExtrasSensor]:
        return {entity.entity_description.key: entity for entity in self.entities}


def test_all_sensors_are_created_and_attached_to_the_vicare_device() -> None:
    hass, service = fakes.make_hass()
    platform = Platform(hass).setup()

    entities = platform.by_key()
    assert set(entities) == ALL_KEYS
    vicare_device = hass.device_registry.async_get("ha-device-heat-pump")
    for key, entity in entities.items():
        assert entity.unique_id == f"{fakes.HEAT_PUMP_IDENTIFIER}-{key}"
        assert entity.entity_description.translation_key == key
        assert entity._attr_has_entity_name is True
        assert entity.available
        # Attached to the existing device, no device of its own.
        assert entity.device_entry is vicare_device
        assert entity.device_info is None
    assert service.api_calls == 0


def test_history_sensor() -> None:
    hass, _ = fakes.make_hass()
    entity = Platform(hass).setup().by_key()["power_consumption_dhw_history"]

    assert entity.native_value == 2.6  # today = first element of the day array
    assert entity.native_unit_of_measurement == "kWh"
    assert entity.device_class is SensorDeviceClass.ENERGY
    assert entity.state_class is None  # see module docstring of sensor.py
    attributes = entity.extra_state_attributes
    assert attributes["day"] == [2.6, 5.8, 3.5, 2.3, 1.8, 5.1, 3.4, 5.4]
    assert len(attributes["week"]) == 6
    assert len(attributes["month"]) == 13
    assert len(attributes["year"]) == 2
    assert attributes["day_value_read_at"] == "2026-11-12T07:59:00.000Z"
    assert {"day", "week", "month", "year"} <= entity._unrecorded_attributes


def test_other_history_sensors_use_their_own_feature() -> None:
    hass, _ = fakes.make_hass()
    entities = Platform(hass).setup().by_key()
    assert entities["power_consumption_heating_history"].native_value == 7.1
    assert entities["power_consumption_total_history"].native_value == 9.7


def test_summary_sensor() -> None:
    hass, _ = fakes.make_hass()
    entities = Platform(hass).setup().by_key()
    entity = entities["heat_production_dhw_summary"]

    assert entity.native_value == 9.6
    assert entity.native_unit_of_measurement == "kWh"
    assert entity.device_class is SensorDeviceClass.ENERGY
    assert entity.state_class is None
    assert entity.extra_state_attributes == {
        "current_day": 9.6,
        "current_month": 61.8,
        "current_year": 3382.9,
        "last_month": 389.9,
        "last_seven_days": 96.7,
    }
    assert entities["heat_production_heating_summary"].native_value == 31.2


def test_messages_sensor() -> None:
    hass, _ = fakes.make_hass()
    entity = Platform(hass).setup().by_key()["messages"]

    assert entity.native_value == "S.134"
    assert entity.device_class is None
    assert entity.native_unit_of_measurement is None
    attributes = entity.extra_state_attributes
    assert [m["errorCode"] for m in attributes["status"]] == ["S.134", "S.123", "S.165"]
    assert [m["errorCode"] for m in attributes["info"]] == ["I.114"]
    assert attributes["service"] == []
    assert {"status", "info", "service"} <= entity._unrecorded_attributes


def test_sensors_only_for_existing_features() -> None:
    features = [
        f
        for f in fakes.heat_pump_features()
        if f["feature"] in ("heating.power.consumption.total", "device.messages.info.raw")
    ]
    hass, _ = fakes.make_hass(fakes.gateway_payload(features))
    entities = Platform(hass).setup().by_key()

    assert set(entities) == {"power_consumption_total_history", "messages"}
    # Messages sensor without a status feature: no state, info list present.
    assert entities["messages"].native_value is None
    assert entities["messages"].extra_state_attributes["info_count"] == 1


def test_no_sensors_for_devices_vicare_does_not_set_up() -> None:
    """TCU and room control have features but no HA device: no sensors."""
    payload = fakes.gateway_payload([])
    payload["data"].append(
        fakes.feature("device.messages.status.raw", fakes.messages(), "TCU")
    )
    hass, _ = fakes.make_hass(payload)
    assert Platform(hass).setup().entities == []


def test_sensor_appears_when_feature_shows_up_later() -> None:
    hass, service = fakes.make_hass(fakes.gateway_payload([]))
    platform = Platform(hass).setup()
    assert platform.entities == []

    service._cache = fakes.gateway_payload()  # the built-in integration refreshed
    platform.refresh()
    assert set(platform.by_key()) == ALL_KEYS

    platform.refresh()  # no duplicates
    assert len(platform.entities) == 6


def test_values_follow_the_cache_of_the_builtin_integration() -> None:
    hass, service = fakes.make_hass()
    platform = Platform(hass).setup()
    entity = platform.by_key()["power_consumption_dhw_history"]
    assert entity.native_value == 2.6

    features = fakes.heat_pump_features()
    features[0] = fakes.feature(
        "heating.power.consumption.dhw", fakes.consumption([3.1, 5.8, 3.5, 2.3, 1.8, 5.1, 3.4, 5.4])
    )
    service._cache = fakes.gateway_payload(features)  # new payload object, as PyViCare does
    platform.refresh()

    assert entity.native_value == 3.1
    assert service.api_calls == 0


def test_empty_cache_keeps_last_values_for_a_while(monkeypatch) -> None:
    hass, service = fakes.make_hass()
    platform = Platform(hass).setup()
    entity = platform.by_key()["power_consumption_dhw_history"]

    service._cache = None  # the built-in integration is refreshing right now
    platform.refresh()
    assert entity.available
    assert entity.native_value == 2.6

    # ... but not forever (e.g. the Viessmann API is down).
    monkeypatch.setattr(coordinator_module, "MAX_SNAPSHOT_AGE_SECONDS", -1)
    platform.refresh()
    assert not entity.available
    assert entity.native_value is None
    assert entity.extra_state_attributes == {}

    service._cache = fakes.gateway_payload()
    platform.refresh()
    assert entity.available
    assert entity.native_value == 2.6
    assert service.api_calls == 0


def test_setup_at_the_moment_of_an_empty_cache() -> None:
    hass, service = fakes.make_hass(empty_cache=True)
    platform = Platform(hass).setup()  # must not fail
    assert platform.entities == []

    service._cache = fakes.gateway_payload()
    platform.refresh()
    assert len(platform.entities) == 6


def test_vicare_unloaded_makes_sensors_unavailable_and_recovers() -> None:
    hass, _ = fakes.make_hass()
    platform = Platform(hass).setup()
    entity = platform.by_key()["messages"]

    fakes.vicare_entry(hass).state = ConfigEntryState.NOT_LOADED
    platform.refresh()
    assert not platform.coordinator.last_update_success
    assert not entity.available

    # vicare is reloaded: new runtime objects, new service, same device.
    vicare = fakes.vicare_entry(hass)
    features = fakes.heat_pump_features()
    features[5] = fakes.feature(
        "device.messages.status.raw",
        fakes.messages(("S.999", "2026-11-12T09:00:00.000Z", "status")),
    )
    vicare.runtime_data, new_service = fakes.make_runtime_data(fakes.gateway_payload(features))
    vicare.state = ConfigEntryState.LOADED
    platform.refresh()

    assert entity.available
    assert entity.native_value == "S.999"
    assert len(platform.entities) == 6
    assert new_service.api_calls == 0


def test_setup_is_retried_while_vicare_is_not_loaded() -> None:
    hass, _ = fakes.make_hass()
    fakes.vicare_entry(hass).state = ConfigEntryState.SETUP_RETRY
    with pytest.raises(ConfigEntryNotReady):
        Platform(hass).setup()


@pytest.mark.parametrize("broken", ["no_cache_attribute", "no_devices_attribute"])
def test_incompatible_internals_fail_setup_without_side_effects(broken) -> None:
    hass, service = fakes.make_hass()
    runtime_data = fakes.vicare_entry(hass).runtime_data
    if broken == "no_cache_attribute":
        del service._cache
    else:
        del runtime_data.devices
    with pytest.raises(ConfigEntryNotReady):
        Platform(hass).setup()
    assert service.api_calls == 0


def test_sensor_without_device_when_vicare_device_is_unknown() -> None:
    hass, _ = fakes.make_hass(register_device=False)
    entities = Platform(hass).setup().entities
    assert len(entities) == 6
    assert all(entity.device_entry is None for entity in entities)
    assert all(entity.device_info is None for entity in entities)


def test_device_lookup_failure_does_not_break_setup(monkeypatch) -> None:
    hass, _ = fakes.make_hass()
    monkeypatch.setattr(
        hass.device_registry,
        "async_get_device_by_identifier",
        lambda *args: (_ for _ in ()).throw(RuntimeError("changed API")),
    )
    entities = Platform(hass).setup().entities
    assert len(entities) == 6
    assert all(entity.device_entry is None for entity in entities)


@pytest.mark.parametrize(
    ("unit", "expected_unit", "expected_class"),
    [
        ("kilowattHour", "kWh", SensorDeviceClass.ENERGY),
        ("wattHour", "Wh", SensorDeviceClass.ENERGY),
        (None, "kWh", SensorDeviceClass.ENERGY),
        ("gigajoule", "gigajoule", None),
    ],
)
def test_energy_unit_handling(unit, expected_unit, expected_class) -> None:
    properties = fakes.consumption([1.0])
    if unit is None:
        del properties["day"]["unit"]
    else:
        properties["day"]["unit"] = unit
    payload = fakes.gateway_payload([fakes.feature("heating.power.consumption.dhw", properties)])
    hass, _ = fakes.make_hass(payload)
    entity = Platform(hass).setup().by_key()["power_consumption_dhw_history"]
    assert entity.native_unit_of_measurement == expected_unit
    assert entity.device_class is expected_class


def test_update_listener_is_removed_on_unload() -> None:
    hass, _ = fakes.make_hass()
    platform = Platform(hass).setup()
    assert len(platform.coordinator._listeners) == 1
    for unsubscribe in platform.entry._on_unload:
        unsubscribe()
    assert platform.coordinator._listeners == []

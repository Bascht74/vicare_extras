"""Tests for the coordinator and the entities, with mocked PyViCare objects."""

from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.vicare_extras import coordinator as coordinator_module, specs
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.util import dt as dt_util

from . import fakes
from .fakes import Platforms

# The six sensors of version 0.1.0; their unique ids must never change.
LEGACY_KEYS = {
    "power_consumption_dhw_history",
    "power_consumption_heating_history",
    "power_consumption_total_history",
    "heat_production_dhw_summary",
    "heat_production_heating_summary",
    "messages",
}
# What the small synthetic payload of the fakes additionally yields.
SMALL_PAYLOAD_KEYS = LEGACY_KEYS | {"last_status_message", "active_status_messages", "operating_state"}


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    """Thursday 2026-01-15 10:30 local time."""
    monkeypatch.setattr(dt_util, "NOW", datetime(2026, 1, 15, 10, 30))


def vitocal() -> tuple[Platforms, fakes.FakeCachedService]:
    hass, service = fakes.make_hass(fakes.gateway_payload(fakes.vitocal_features()))
    return Platforms(hass).setup(), service


# ------------------------------------------------------------ version 0.1.0


def test_legacy_sensors_keep_unique_ids_and_device_link() -> None:
    hass, service = fakes.make_hass()
    platforms = Platforms(hass).setup()

    assert platforms.keys(platforms.sensors) == SMALL_PAYLOAD_KEYS
    assert platforms.binary_sensors == []
    vicare_device = hass.device_registry.async_get("ha-device-heat-pump")
    for key in LEGACY_KEYS:
        entity = platforms.sensor(key)
        assert entity.unique_id == f"{fakes.HEAT_PUMP_IDENTIFIER}-{key}"
        assert entity._attr_has_entity_name is True
        assert entity.available
        # Attached to the existing device, no device of its own.
        assert entity.device_entry is vicare_device
        assert entity.device_info is None
    assert service.api_calls == 0


def test_history_sensor() -> None:
    hass, _ = fakes.make_hass()
    entity = Platforms(hass).setup().sensor("power_consumption_dhw_history")

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


def test_summary_sensor() -> None:
    hass, _ = fakes.make_hass()
    platforms = Platforms(hass).setup()
    entity = platforms.sensor("heat_production_dhw_summary")

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
    assert platforms.sensor("heat_production_heating_summary").native_value == 31.2
    assert platforms.sensor("power_consumption_heating_history").native_value == 7.1
    assert platforms.sensor("power_consumption_total_history").native_value == 9.7


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
    entity = Platforms(hass).setup().sensor("power_consumption_dhw_history")
    assert entity.native_unit_of_measurement == expected_unit
    assert entity.device_class is expected_class


# ----------------------------------------------------------------- messages


def test_messages_sensor_is_decoded() -> None:
    hass, _ = fakes.make_hass()
    entity = Platforms(hass).setup().sensor("messages")

    assert entity.native_value == "S.134"  # the state stays the raw code
    attributes = entity.extra_state_attributes
    assert attributes["newest_status_text"] == "4/3-Wege-Ventil in Leerlaufstellung"
    assert [(m["errorCode"], m["text"]) for m in attributes["status"]] == [
        ("S.134", "4/3-Wege-Ventil in Leerlaufstellung"),
        ("S.123", "Wärmepumpe ist aus"),
        ("S.165", "Systemstatus der Wärmepumpe: Regelung"),
    ]
    assert attributes["info"][0]["text"] == "Smart Grid im Normalbetrieb"
    assert attributes["service"] == []
    assert {"status", "info", "service"} <= entity._unrecorded_attributes


def test_last_status_message_sensor() -> None:
    platforms, _ = vitocal()
    entity = platforms.sensor("last_status_message")
    assert entity.native_value == "Wärmepumpe heizt"
    assert entity.extra_state_attributes == {
        "code": "S.125",
        "device_time": "2026-01-15T10:21:00.000Z",  # passed on unconverted
        "source": "viessmann",
        "verified": True,
    }


def test_last_status_message_shows_raw_code_when_unknown() -> None:
    features = [
        fakes.feature(
            "device.messages.status.raw",
            fakes.messages(("S.999", "2026-01-15T10:00:00.000Z", "status")),
        )
    ]
    hass, _ = fakes.make_hass(fakes.gateway_payload(features))
    entity = Platforms(hass).setup().sensor("last_status_message")
    assert entity.native_value == "S.999"
    assert entity.extra_state_attributes["source"] is None
    assert entity.extra_state_attributes["verified"] is None


def test_last_status_message_marks_unverified_texts() -> None:
    features = [
        fakes.feature(
            "device.messages.status.raw",
            fakes.messages(("S.1", "2026-01-15T10:00:00.000Z", "status")),
        )
    ]
    hass, _ = fakes.make_hass(fakes.gateway_payload(features))
    entity = Platforms(hass).setup().sensor("last_status_message")
    assert entity.native_value == "S.1 (ungeprüft: Netzspannung eingeschaltet)"
    assert entity.extra_state_attributes == {
        "code": "S.1",
        "device_time": "2026-01-15T10:00:00.000Z",
        "source": "fhem",
        "verified": False,
    }


def test_active_status_messages_sensor() -> None:
    platforms, _ = vitocal()
    entity = platforms.sensor("active_status_messages")

    assert entity.native_value == "S.1, S.115, S.120, S.125, S.165, S.217, S.218, S.219"
    attributes = entity.extra_state_attributes
    assert attributes["count"] == 9  # S.165 is active on two bus participants
    assert attributes["codes"] == ["S.1", "S.115", "S.120", "S.125", "S.165", "S.217", "S.218", "S.219"]
    texts = {m["errorCode"]: m["text"] for m in attributes["messages"]}
    assert texts["S.115"] == "4/3-Wege-Ventil steht auf Trinkwassererwärmung"
    assert texts["S.120"] == "Smart Grid im Normalbetrieb"
    assert texts["S.217"] == "Heizwasser-Durchlauferhitzer: Stufe 1 aus"
    assert texts["S.1"] == "Netzspannung eingeschaltet"
    flags = {m["errorCode"]: m.get("verified") for m in attributes["messages"]}
    assert flags["S.1"] is False  # no Viessmann document confirms this text
    assert flags["S.115"] is None
    assert "messages" in entity._unrecorded_attributes


def test_active_status_state_is_capped_at_255_characters() -> None:
    entries = [(f"S.{1000 + i}", f"2026-01-15T10:{i % 60:02d}:00.000Z", "status") for i in range(60)]
    features = [fakes.feature("device.messages.status.raw", fakes.messages(*entries))]
    hass, _ = fakes.make_hass(fakes.gateway_payload(features))
    entity = Platforms(hass).setup().sensor("active_status_messages")
    assert len(entity.native_value) == 255
    assert entity.native_value.endswith("…")
    assert entity.extra_state_attributes["count"] == 60


# ------------------------------------------------- real device feature list


def test_vitocal_entity_list() -> None:
    """Every entity the Vitocal 250-A feature list yields, and nothing else."""
    platforms, service = vitocal()
    by_scope = {
        "sensor": {s.key for s in specs.HEATING_SPECS if s.platform == "sensor"}
        | {s.key for s in specs.SPECIAL_SPECS},
        "binary_sensor": {s.key for s in specs.HEATING_SPECS if s.platform == "binary_sensor"},
    }
    assert platforms.keys(platforms.sensors) == by_scope["sensor"]
    assert platforms.keys(platforms.binary_sensors) == by_scope["binary_sensor"]
    assert len(platforms.sensors) == 46  # 2 fans, 2 expansion valves
    assert len(platforms.binary_sensors) == 18
    unique_ids = [entity.unique_id for entity in platforms.entities]
    assert len(unique_ids) == len(set(unique_ids))
    vicare_device = platforms.hass.device_registry.async_get("ha-device-heat-pump")
    for entity in platforms.entities:
        assert entity.unique_id.startswith(f"{fakes.HEAT_PUMP_IDENTIFIER}-")
        assert entity.device_entry is vicare_device
        assert entity.device_info is None
        assert entity.available
    assert service.api_calls == 0


@pytest.mark.parametrize(
    ("key", "value", "unit", "device_class"),
    [
        ("heat_production_current", 14.531, "kW", SensorDeviceClass.POWER),
        ("power_consumption_current", 5.717, "kW", SensorDeviceClass.POWER),
        ("compressor_speed", 90.5, "rps", None),
        ("compressor_speed_setpoint", 90.5, "rps", None),
        ("compressor_oil_temperature", 94, "°C", SensorDeviceClass.TEMPERATURE),
        ("compressor_motor_chamber_temperature", 34.2, "°C", SensorDeviceClass.TEMPERATURE),
        ("economizer_liquid_temperature", 13.1, "°C", SensorDeviceClass.TEMPERATURE),
        ("four_three_way_valve_current", 100, "%", None),
        ("four_three_way_valve_target", 100, "%", None),
        ("internal_pump_speed", 67, "%", None),
        ("internal_pump_target", 65, "%", None),
        ("primary_fan_speed-0", 60, "%", None),
        ("primary_fan_speed-1", 65, "%", None),
        ("expansion_valve_target-0", 57, "%", None),
        ("expansion_valve_target-1", 98, "%", None),
        ("boiler_temperature", 54, "°C", SensorDeviceClass.TEMPERATURE),
        ("circuit_temperature_level_min", 20, "°C", SensorDeviceClass.TEMPERATURE),
        ("circuit_temperature_level_max", 40, "°C", SensorDeviceClass.TEMPERATURE),
        ("circuit_summer_eco_threshold", 25, "°C", SensorDeviceClass.TEMPERATURE),
        ("heating_rod_max_outside_temperature", -3, "°C", SensorDeviceClass.TEMPERATURE),
        ("secondary_return_minimum_temperature", 5, "°C", SensorDeviceClass.TEMPERATURE),
    ],
)
def test_vitocal_measurements(key, value, unit, device_class) -> None:
    entity = vitocal()[0].sensor(key)
    assert entity.native_value == value
    assert entity.native_unit_of_measurement == unit
    assert entity.device_class is device_class
    assert entity.state_class is SensorStateClass.MEASUREMENT


@pytest.mark.parametrize(
    ("key", "state"),
    [
        ("four_three_way_valve_position", "domestic_hot_water"),
        ("secondary_circuit_state", "heating"),
        ("circuit_active_program", "normal_heating"),
        ("power_limitation", "14a_off"),
        ("power_status_consumption", "unlimited_autonomous"),
        ("power_status_production", "init"),
        ("operating_state", "dhw"),
    ],
)
def test_vitocal_enum_sensors(key, state) -> None:
    entity = vitocal()[0].sensor(key)
    assert entity.native_value == state
    assert entity.device_class is SensorDeviceClass.ENUM
    assert state in entity.options
    assert entity.state_class is None
    assert entity.native_unit_of_measurement is None


def test_vitocal_derived_sensors() -> None:
    platforms, _ = vitocal()
    state = platforms.sensor("operating_state")
    assert state.options == ["off", "preflow", "heating", "dhw", "cooling", "defrost", "afterflow"]
    assert state.extra_state_attributes == {
        "basis": "status_message",
        "status_code": "S.125",
        "valve_position": "domestic_hot_water",
    }
    cop = platforms.sensor("cop_current")
    assert cop.native_value == 2.54
    assert cop.state_class is SensorStateClass.MEASUREMENT
    assert cop.native_unit_of_measurement is None
    stage = platforms.sensor("heating_rod_stage")
    assert stage.native_value == 0
    # "-1 W" = no limit: unknown instead of a negative power.
    limit = platforms.sensor("power_consumption_limit")
    assert limit.native_value is None
    assert limit.available
    assert platforms.sensor("power_status_consumption").extra_state_attributes == {"limit": -1}
    assert platforms.sensor("secondary_circuit_state").extra_state_attributes == {"target_value": "heating"}


def test_vitocal_schedule_sensors() -> None:
    platforms, _ = vitocal()
    dhw = platforms.sensor("dhw_schedule")
    assert dhw.native_value == "on"  # Thursday 10:30, slot 06:00-22:00
    assert dhw.device_class is SensorDeviceClass.ENUM
    attributes = dhw.extra_state_attributes
    assert attributes["active"] is True
    assert attributes["today"] == [{"start": "06:00", "end": "22:00", "mode": "on", "position": 0}]
    assert set(attributes["entries"]) == {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
    assert {"entries", "today"} <= dhw._unrecorded_attributes
    assert platforms.sensor("dhw_circulation_schedule").native_value == "on"
    circuit = platforms.sensor("circuit_heating_schedule")
    assert circuit.native_value == "normal"
    assert circuit.translation_placeholders == {"number": "1"}
    assert circuit.unique_id.endswith("-circuit_heating_schedule-1")


def test_schedule_follows_the_clock(monkeypatch) -> None:
    platforms, _ = vitocal()
    dhw = platforms.sensor("dhw_schedule")
    monkeypatch.setattr(dt_util, "NOW", datetime(2026, 1, 15, 23, 0))
    assert dhw.native_value == "none"


def test_vitocal_names_and_flags() -> None:
    platforms, _ = vitocal()
    assert platforms.sensor("compressor_speed").translation_placeholders == {"suffix": ""}
    assert platforms.sensor("compressor_speed").unique_id.endswith("-compressor_speed-0")
    assert platforms.sensor("primary_fan_speed-1").translation_placeholders == {"number": "2"}
    assert platforms.sensor("circuit_active_program").translation_placeholders == {"number": "1"}
    assert platforms.sensor("heat_production_current").translation_placeholders == {}

    disabled = {e.translation_key for e in platforms.entities if not e.entity_registry_enabled_default}
    assert disabled == {
        "boiler_temperature",
        "circuit_summer_eco_threshold",
        "circuit_temperature_level_max",
        "circuit_temperature_level_min",
        "device_external_lock",
        "heat_production_cooling_summary",
        "heating_rod_dhw_approved",
        "heating_rod_heating_approved",
        "heating_rod_max_outside_temperature",
        "power_consumption_cooling_summary",
        "power_status_production",
        "primary_four_three_way_valve",
        "secondary_return_minimum_temperature",
    }
    diagnostic = {e.translation_key for e in platforms.entities if e.entity_category is EntityCategory.DIAGNOSTIC}
    assert diagnostic == {
        "circuit_summer_eco_threshold",
        "circuit_temperature_level_max",
        "circuit_temperature_level_min",
        "dhw_hygiene",
        "dhw_scald_protection",
        "heating_rod_dhw_approved",
        "heating_rod_heating_approved",
        "heating_rod_max_outside_temperature",
        "secondary_return_minimum_temperature",
    }


@pytest.mark.parametrize(
    ("key", "is_on", "device_class"),
    [
        ("internal_pump", True, BinarySensorDeviceClass.RUNNING),
        ("defrosting", False, BinarySensorDeviceClass.RUNNING),
        ("crankcase_heater", False, BinarySensorDeviceClass.RUNNING),
        ("evaporator_base_heater", False, BinarySensorDeviceClass.RUNNING),
        ("condensate_pan_heater", False, BinarySensorDeviceClass.RUNNING),
        ("fan_ring_heater", False, BinarySensorDeviceClass.RUNNING),
        ("heating_rod", True, None),
        ("heating_rod_dhw_approved", True, None),
        ("heating_rod_heating_approved", True, None),
        ("secondary_heat_generator", False, None),
        ("dhw_hygiene", False, None),
        ("dhw_scald_protection", True, None),
        ("external_lock", False, None),
        ("device_external_lock", False, None),
        ("malfunction_lock", False, BinarySensorDeviceClass.PROBLEM),
        ("holiday_program", False, None),
        ("holiday_at_home_program", False, None),
        ("primary_four_three_way_valve", False, None),
    ],
)
def test_vitocal_binary_sensors(key, is_on, device_class) -> None:
    entity = vitocal()[0].binary_sensor(key)
    assert entity.is_on is is_on
    assert entity.device_class is device_class


def test_binary_sensor_attributes() -> None:
    platforms, _ = vitocal()
    assert platforms.binary_sensor("holiday_program").extra_state_attributes == {
        "start": "2000-01-01",
        "end": "2000-01-01",
    }
    assert platforms.binary_sensor("secondary_heat_generator").extra_state_attributes == {
        "connection_type": "unknown"
    }
    assert platforms.binary_sensor("defrosting").extra_state_attributes is None


def test_enum_sensor_accepts_values_it_has_never_seen() -> None:
    features = fakes.vitocal_features()
    hass, service = fakes.make_hass(fakes.gateway_payload(features))
    platforms = Platforms(hass).setup()
    entity = platforms.sensor("four_three_way_valve_position")
    assert "brand_new_position" not in entity.options

    changed = [
        fakes.feature(f["feature"], {"value": {"type": "string", "value": "brandNewPosition"}})
        if f["feature"] == "heating.valves.fourThreeWay.position"
        else f
        for f in features
    ]
    service._cache = fakes.gateway_payload(changed)
    platforms.refresh()

    assert entity.native_value == "brand_new_position"
    assert "brand_new_position" in entity.options  # otherwise Home Assistant rejects the state


def test_operating_state_follows_status_messages() -> None:
    features = [f for f in fakes.vitocal_features() if f["feature"] != "device.messages.status.raw"]

    def payload(*codes: str) -> dict:
        entries = [(code, f"2026-01-15T10:{59 - i:02d}:00.000Z", "status") for i, code in enumerate(codes)]
        return fakes.gateway_payload(
            [*features, fakes.feature("device.messages.status.raw", fakes.messages(*entries))]
        )

    hass, service = fakes.make_hass(payload("S.123", "S.134"))
    platforms = Platforms(hass).setup()
    entity = platforms.sensor("operating_state")
    seen = [entity.native_value]
    for codes in (("S.124",), ("S.125", "S.115"), ("S.129",), ("S.123",)):
        service._cache = payload(*codes)
        platforms.refresh()
        seen.append(entity.native_value)
    # The valve feature of the fixture points at hot water.
    assert seen == ["off", "preflow", "dhw", "afterflow", "off"]
    assert service.api_calls == 0


# ------------------------------------------------- creation and availability


def test_entities_only_for_existing_features() -> None:
    features = [
        f
        for f in fakes.heat_pump_features()
        if f["feature"] in ("heating.power.consumption.total", "device.messages.info.raw")
    ]
    hass, _ = fakes.make_hass(fakes.gateway_payload(features))
    platforms = Platforms(hass).setup()

    assert platforms.keys() == {"power_consumption_total_history", "messages"}
    # Messages sensor without a status feature: no state, info list present.
    assert platforms.sensor("messages").native_value is None
    assert platforms.sensor("messages").extra_state_attributes["info_count"] == 1


def test_no_entities_for_devices_vicare_does_not_set_up() -> None:
    """The gateway (TCU) has features but no HA device: no entities."""
    payload = fakes.gateway_payload([])
    payload["data"].append(fakes.feature("device.messages.status.raw", fakes.messages(), "TCU"))
    hass, _ = fakes.make_hass(payload)
    assert Platforms(hass).setup().entities == []


def test_entities_appear_when_features_show_up_later() -> None:
    hass, service = fakes.make_hass(fakes.gateway_payload([]))
    platforms = Platforms(hass).setup()
    assert platforms.entities == []

    service._cache = fakes.gateway_payload(fakes.vitocal_features())
    platforms.refresh()
    assert len(platforms.sensors) == 46
    assert len(platforms.binary_sensors) == 18

    platforms.refresh()  # no duplicates
    assert len(platforms.entities) == 64


def test_values_follow_the_cache_of_the_builtin_integration() -> None:
    hass, service = fakes.make_hass()
    platforms = Platforms(hass).setup()
    entity = platforms.sensor("power_consumption_dhw_history")
    assert entity.native_value == 2.6

    features = fakes.heat_pump_features()
    features[0] = fakes.feature(
        "heating.power.consumption.dhw", fakes.consumption([3.1, 5.8, 3.5, 2.3, 1.8, 5.1, 3.4, 5.4])
    )
    service._cache = fakes.gateway_payload(features)  # new payload object, as PyViCare does
    platforms.refresh()

    assert entity.native_value == 3.1
    assert service.api_calls == 0


def test_empty_cache_keeps_last_values_for_a_while(monkeypatch) -> None:
    platforms, service = vitocal()
    history = platforms.sensor("power_consumption_dhw_history")
    power = platforms.sensor("heat_production_current")
    pump = platforms.binary_sensor("internal_pump")

    service._cache = None  # the built-in integration is refreshing right now
    platforms.refresh()
    assert history.available and power.available and pump.available
    assert power.native_value == 14.531

    # ... but not forever (e.g. the Viessmann API is down).
    monkeypatch.setattr(coordinator_module, "MAX_SNAPSHOT_AGE_SECONDS", -1)
    platforms.refresh()
    assert not history.available and not power.available and not pump.available
    assert history.native_value is None
    assert history.extra_state_attributes == {}
    assert power.native_value is None
    assert pump.is_on is None
    assert platforms.sensor("operating_state").native_value is None

    service._cache = fakes.gateway_payload(fakes.vitocal_features())
    platforms.refresh()
    assert history.available and power.available and pump.available
    assert service.api_calls == 0


def test_setup_at_the_moment_of_an_empty_cache() -> None:
    hass, service = fakes.make_hass(empty_cache=True)
    platforms = Platforms(hass).setup()  # must not fail
    assert platforms.entities == []

    service._cache = fakes.gateway_payload()
    platforms.refresh()
    assert platforms.keys() == SMALL_PAYLOAD_KEYS


def test_vicare_unloaded_makes_entities_unavailable_and_recovers() -> None:
    hass, _ = fakes.make_hass()
    platforms = Platforms(hass).setup()
    entity = platforms.sensor("messages")

    fakes.vicare_entry(hass).state = ConfigEntryState.NOT_LOADED
    platforms.refresh()
    assert not platforms.coordinator.last_update_success
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
    platforms.refresh()

    assert entity.available
    assert entity.native_value == "S.999"
    assert len(platforms.entities) == len(SMALL_PAYLOAD_KEYS)
    assert new_service.api_calls == 0


def test_setup_is_retried_while_vicare_is_not_loaded() -> None:
    hass, _ = fakes.make_hass()
    fakes.vicare_entry(hass).state = ConfigEntryState.SETUP_RETRY
    with pytest.raises(ConfigEntryNotReady):
        Platforms(hass).setup()


@pytest.mark.parametrize("broken", ["no_cache_attribute", "no_devices_attribute"])
def test_incompatible_internals_fail_setup_without_side_effects(broken) -> None:
    hass, service = fakes.make_hass()
    runtime_data = fakes.vicare_entry(hass).runtime_data
    if broken == "no_cache_attribute":
        del service._cache
    else:
        del runtime_data.devices
    with pytest.raises(ConfigEntryNotReady):
        Platforms(hass).setup()
    assert service.api_calls == 0


def test_entities_without_device_when_vicare_device_is_unknown() -> None:
    hass, _ = fakes.make_hass(register_device=False)
    entities = Platforms(hass).setup().entities
    assert len(entities) == len(SMALL_PAYLOAD_KEYS)
    assert all(entity.device_entry is None for entity in entities)
    assert all(entity.device_info is None for entity in entities)


def test_device_lookup_failure_does_not_break_setup(monkeypatch) -> None:
    hass, _ = fakes.make_hass()
    monkeypatch.setattr(
        hass.device_registry,
        "async_get_device_by_identifier",
        lambda *args: (_ for _ in ()).throw(RuntimeError("changed API")),
    )
    entities = Platforms(hass).setup().entities
    assert len(entities) == len(SMALL_PAYLOAD_KEYS)
    assert all(entity.device_entry is None for entity in entities)


def test_update_listeners_are_removed_on_unload() -> None:
    platforms, _ = vitocal()
    discovery_listeners = len(platforms.coordinator._listeners) - len(platforms.entities)
    assert discovery_listeners == 3  # one per platform
    assert len(platforms.entry._on_unload) == 3
    for unsubscribe in platforms.entry._on_unload:
        unsubscribe()
    assert len(platforms.coordinator._listeners) == len(platforms.entities)

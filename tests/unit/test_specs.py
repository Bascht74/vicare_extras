"""Tests for the declarative entity list."""

from __future__ import annotations

import pytest

from custom_components.vicare_extras import specs

from . import fakes


def features() -> dict:
    return {f["feature"]: f for f in fakes.vitocal_features()}


def spec(key: str) -> specs.ValueSpec:
    return next(s for s in specs.ALL_SPECS if s.key == key)


def test_keys_are_unique() -> None:
    keys = [s.key for s in specs.ALL_SPECS] + [s.key for s in specs.SPECIAL_SPECS]
    assert len(keys) == len(set(keys))


def test_every_heating_spec_feature_exists_on_the_real_device() -> None:
    """Each spec points at a feature and property of the Vitocal 250-A dump."""
    data = features()
    for item in specs.HEATING_SPECS:
        assert specs.find_indexes(item, data), item.key


@pytest.mark.parametrize(
    ("value", "key"),
    [
        ("domesticHotWater", "domestic_hot_water"),
        ("climatCircuitTwoDefrost", "climat_circuit_two_defrost"),
        ("14aOff", "14a_off"),
        ("unlimitedAutonomous", "unlimited_autonomous"),
        ("5/25-cycles", "5_25_cycles"),
        ("normalHeating", "normal_heating"),
        ("heating", "heating"),
        ("", None),
        (None, None),
        (5, None),
    ],
)
def test_state_key(value, key) -> None:
    assert specs.state_key(value) == key


def test_indexed_specs() -> None:
    data = features()
    fans = spec("primary_fan_speed")
    assert specs.find_indexes(fans, data) == [0, 1]
    assert specs.read_value(fans, data, 0) == 60
    assert specs.read_value(fans, data, 1) == 65
    assert specs.name_placeholders(fans, 0) == {"number": "1"}
    assert specs.name_placeholders(fans, 1) == {"number": "2"}
    assert specs.unique_suffix(fans, 1) == "primary_fan_speed-1"

    compressor = spec("compressor_speed")
    assert specs.find_indexes(compressor, data) == [0]
    assert specs.name_placeholders(compressor, 0) == {"suffix": ""}
    assert specs.name_placeholders(compressor, 1) == {"suffix": " 2"}

    circuit = spec("circuit_active_program")
    assert specs.find_indexes(circuit, data) == [1]
    assert specs.name_placeholders(circuit, 1) == {"number": "1"}
    assert specs.read_value(circuit, data, 1) == "normal_heating"


def test_values_units_and_attributes() -> None:
    data = features()
    assert specs.read_value(spec("heat_production_current"), data, None) == 14.531
    assert specs.read_unit(spec("heat_production_current"), data, None) == "kW"
    assert specs.read_unit(spec("compressor_speed"), data, 0) == "rps"
    assert specs.read_value(spec("four_three_way_valve_position"), data, None) == "domestic_hot_water"
    state = spec("secondary_circuit_state")
    assert specs.read_value(state, data, None) == "heating"
    assert specs.read_attributes(state, data, None) == {"target_value": "heating"}
    limit = spec("power_status_consumption")
    assert specs.read_attributes(limit, data, None) == {"limit": -1}
    # "-1 W" means "no limit": reported as unknown, not as a negative power.
    assert specs.read_value(spec("power_consumption_limit"), data, None) is None
    assert specs.read_value(spec("internal_pump"), data, None) is True  # status "on"
    assert specs.read_value(spec("defrosting"), data, None) is False
    holiday = spec("holiday_program")
    assert specs.read_attributes(holiday, data, None) == {"start": "2000-01-01", "end": "2000-01-01"}


def test_missing_or_odd_data() -> None:
    item = spec("heat_production_current")
    assert specs.find_indexes(item, {}) == []
    assert specs.read_value(item, {}, None) is None
    name = item.sources[0][0]
    assert specs.find_indexes(item, {name: {"properties": {}}}) == []
    assert specs.read_value(item, {name: {"properties": {"value": {"value": "x"}}}}, None) is None
    assert specs.read_value(item, {name: {"properties": {"value": {"value": True}}}}, None) is None
    pump = spec("internal_pump")
    assert specs.read_value(pump, {"heating.boiler.pumps.internal": {"properties": {"status": {"value": 1}}}}, None) is None


def test_alternative_sources() -> None:
    co2 = spec("room_co2")
    by_name = {f["feature"]: f for f in fakes.room_features(2)}
    assert specs.find_indexes(co2, by_name) == [2]
    assert specs.read_value(co2, by_name, 2) == 650
    # Other firmware delivers the value below rooms.N.sensors.co2.
    other = {"rooms.2.sensors.co2": {"properties": {"value": {"unit": "partsPerMillion", "value": 700}}}}
    assert specs.read_value(co2, other, 2) == 700
    # A sensor that is not connected has no value: no entity.
    missing = {"rooms.2.sensors.co2": {"properties": {"status": {"value": "notConnected"}}}}
    assert specs.find_indexes(co2, missing) == []


def test_rooms() -> None:
    by_name = {f["feature"]: f for f in [*fakes.room_features(0), *fakes.room_features(3, None)]}
    assert specs.room_indexes(by_name) == [0, 3]
    assert specs.room_name(by_name, 0) == "Wohnzimmer"
    assert specs.room_name(by_name, 3) is None
    # A room control without rooms (seen on a real installation).
    flags = {f["feature"]: f for f in fakes.room_control_only_flags()}
    assert specs.room_indexes(flags) == []


def test_special_indexes() -> None:
    data = features()
    by_key = {s.key: s for s in specs.SPECIAL_SPECS}
    assert specs.special_indexes(by_key["cop_current"], data) == [None]
    assert specs.special_indexes(by_key["circuit_heating_schedule"], data) == [1]
    assert specs.special_placeholders(by_key["circuit_heating_schedule"], 1) == {"number": "1"}
    del data["heating.power.consumption.current"]
    assert specs.special_indexes(by_key["cop_current"], data) == []  # needs both
    assert specs.special_indexes(by_key["messages"], {"device.messages.info.raw": {}}) == [None]

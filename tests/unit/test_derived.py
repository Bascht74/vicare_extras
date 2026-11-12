"""Tests for values derived from several features."""

from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.vicare_extras import derived

from . import fakes

T = "2026-01-15T10:{:02d}:00.000Z"


def status(*codes: str) -> dict:
    """Status feature; the first code is the newest."""
    entries = [(code, T.format(59 - i), "status") for i, code in enumerate(codes)]
    return fakes.feature("device.messages.status.raw", fakes.messages(*entries))


def value(name: str, prop: str, val) -> dict:
    return fakes.feature(name, {prop: {"type": "x", "value": val}})


def build(*items: dict) -> dict:
    return {item["feature"]: item for item in items}


VALVE = "heating.valves.fourThreeWay.position"


def test_real_device_snapshot() -> None:
    """Dump: S.125 and S.115 active, valve on hot water, compressor running."""
    features = {f["feature"]: f for f in fakes.vitocal_features()}
    state, details = derived.operating_state(features)
    assert state == "dhw"
    assert details == {"basis": "status_message", "status_code": "S.125", "valve_position": "domestic_hot_water"}
    assert derived.active_status_codes(features) == ["S.1", "S.115", "S.120", "S.125", "S.165", "S.217", "S.218", "S.219"]
    assert derived.heating_rod_stage(features) == 0
    assert derived.current_cop(features) == round(14.531 / 5.717, 2)


@pytest.mark.parametrize(
    ("codes", "valve", "expected"),
    [
        (("S.123",), "climatCircuitTwoDefrost", "off"),
        (("S.124",), "climatCircuitTwoDefrost", "preflow"),
        (("S.125",), "climatCircuitTwoDefrost", "heating"),
        (("S.125",), "climateCircuitOne", "heating"),
        (("S.125",), "domesticHotWater", "dhw"),
        (("S.125",), "climateCircuitTwoDefrostDomesticHotWater", "dhw"),
        (("S.125",), None, "heating"),
        (("S.126",), "climateCircuitOne", "cooling"),
        (("S.127",), "climateCircuitOne", "defrost"),
        (("S.128",), "climateCircuitOne", "defrost"),
        (("S.129",), "domesticHotWater", "afterflow"),
        # Other codes around the phase code do not matter.
        (("S.115", "S.125", "S.120", "S.217"), "domesticHotWater", "dhw"),
        # Two phase codes at once: the newest one counts.
        (("S.124", "S.123"), None, "preflow"),
        (("S.123", "S.129"), None, "off"),
    ],
)
def test_operating_state_from_status_messages(codes, valve, expected) -> None:
    items = [status(*codes)]
    if valve is not None:
        items.append(value(VALVE, "value", valve))
    state, details = derived.operating_state(build(*items))
    assert state == expected
    assert details["basis"] == "status_message"
    assert details["status_code"] in derived.PHASE_CODES


def test_defrosting_feature_wins() -> None:
    features = build(status("S.125"), value("heating.outdoor.defrosting", "active", True))
    assert derived.operating_state(features) == (
        "defrost",
        {"basis": "defrosting", "status_code": None, "valve_position": None},
    )


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        ([value("heating.compressors.0", "active", False)], "off"),
        ([value("heating.compressors.0", "active", True)], "heating"),
        ([value("heating.compressors.0", "active", True), value(VALVE, "value", "domesticHotWater")], "dhw"),
        (
            [
                value("heating.compressors.0", "active", True),
                value("heating.secondaryCircuit.operation.state", "currentValue", "cooling"),
            ],
            "cooling",
        ),
        ([value("heating.compressors.0", "active", False), value("heating.compressors.1", "active", True)], "heating"),
        # Status feature present but without a phase code: fall back.
        ([status("S.120", "S.165"), value("heating.compressors.0", "active", False)], "off"),
    ],
)
def test_operating_state_fallback_without_phase_codes(items, expected) -> None:
    state, details = derived.operating_state(build(*items))
    assert state == expected
    assert details["basis"] == "compressor"


def test_operating_state_unknown_without_any_input() -> None:
    assert derived.operating_state({})[0] is None
    assert derived.operating_state(build(status("S.120")))[0] is None
    # compressor speed feature is not the compressor feature itself
    assert derived.operating_state(build(value("heating.compressors.0.speed.current", "value", 50)))[0] is None


def test_all_states_are_declared() -> None:
    assert set(derived.PHASE_CODES.values()) | {"dhw"} == set(derived.OPERATING_STATES)


@pytest.mark.parametrize(
    ("codes", "stage"),
    [
        (("S.217", "S.218", "S.219"), 0),
        (("S.130",), 0),
        (("S.131", "S.218", "S.219"), 1),
        (("S.131", "S.132", "S.219"), 2),
        (("S.131", "S.132", "S.133"), 3),
        (("S.125", "S.120"), None),
        ((), None),
    ],
)
def test_heating_rod_stage(codes, stage) -> None:
    assert derived.heating_rod_stage(build(status(*codes))) == stage
    assert derived.heating_rod_stage({}) is None


def power(name: str, val, unit: str = "kilowatt") -> dict:
    return fakes.feature(name, {"value": {"type": "number", "unit": unit, "value": val}})


@pytest.mark.parametrize(
    ("heat", "electric", "expected"),
    [
        (14.531, 5.717, 2.54),
        (6.0, 1.5, 4.0),
        (0.0, 0.03, None),  # heat pump off: standby consumption only
        (0.1, 1.0, None),
        (5.0, 0.1, None),
        (None, 1.0, None),
        ("x", 1.0, None),
    ],
)
def test_current_cop(heat, electric, expected) -> None:
    features = build(
        power("heating.heat.production.current", heat),
        power("heating.power.consumption.current", electric),
    )
    assert derived.current_cop(features) == expected


def test_current_cop_converts_watt() -> None:
    features = build(
        power("heating.heat.production.current", 6000, "watt"),
        power("heating.power.consumption.current", 1.5),
    )
    assert derived.current_cop(features) == 4.0
    assert derived.current_cop({}) is None


def schedule(entries, active=True) -> dict:
    return fakes.feature(
        "heating.dhw.schedule",
        {"active": {"type": "boolean", "value": active}, "entries": {"type": "Schedule", "value": entries}},
    )


WEEK = {
    "mon": [
        {"start": "17:00", "end": "22:00", "mode": "on", "position": 1},
        {"start": "05:30", "end": "08:00", "mode": "5/25-cycles", "position": 0},
    ],
    "tue": [{"start": "00:00", "end": "24:00", "mode": "normal", "position": 0}],
    "wed": [],
}


@pytest.mark.parametrize(
    ("when", "mode"),
    [
        (datetime(2026, 1, 12, 5, 29), "none"),  # Monday
        (datetime(2026, 1, 12, 5, 30), "5_25_cycles"),
        (datetime(2026, 1, 12, 7, 59), "5_25_cycles"),
        (datetime(2026, 1, 12, 8, 0), "none"),
        (datetime(2026, 1, 12, 21, 59), "on"),
        (datetime(2026, 1, 12, 22, 0), "none"),
        (datetime(2026, 1, 13, 0, 0), "normal"),  # Tuesday
        (datetime(2026, 1, 13, 23, 59), "normal"),
        (datetime(2026, 1, 14, 12, 0), "none"),  # Wednesday: no slots
        (datetime(2026, 1, 15, 12, 0), "none"),  # Thursday: day missing
    ],
)
def test_schedule_mode(when, mode) -> None:
    assert derived.schedule_mode(schedule(WEEK), when) == mode


def test_schedule_edge_cases() -> None:
    monday = datetime(2026, 1, 12, 6, 0)
    assert derived.schedule_mode(schedule(WEEK, active=False), monday) == "inactive"
    assert derived.schedule_mode(None, monday) is None
    assert derived.schedule_mode(fakes.feature("x", {}), monday) is None
    assert [slot["start"] for slot in derived.schedule_today(schedule(WEEK), monday)] == ["05:30", "17:00"]
    assert derived.schedule_today(None, monday) == []
    odd = {"mon": [{"start": "x", "end": "08:00", "mode": "on"}, "junk"]}
    assert derived.schedule_mode(schedule(odd), monday) == "none"

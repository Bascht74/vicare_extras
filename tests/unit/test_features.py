"""Tests for turning raw features into sensor values."""

from __future__ import annotations

from custom_components.vicare_extras import features as ft

from . import fakes


def _by_name() -> dict:
    return {f["feature"]: f for f in fakes.heat_pump_features()}


def test_history() -> None:
    feature = _by_name()["heating.power.consumption.dhw"]
    assert ft.history_value(feature) == 2.6
    assert ft.history_unit(feature) == "kilowattHour"
    attributes = ft.history_attributes(feature)
    assert attributes["day"] == [2.6, 5.8, 3.5, 2.3, 1.8, 5.1, 3.4, 5.4]
    assert len(attributes["week"]) == 6
    assert len(attributes["month"]) == 13
    assert len(attributes["year"]) == 2
    for period in ("day", "week", "month", "year"):
        assert attributes[f"{period}_value_read_at"] == "2026-11-12T07:59:00.000Z"
    # The attribute is a copy, not PyViCare's cached list.
    assert attributes["day"] is not feature["properties"]["day"]["value"]


def test_history_tolerates_missing_or_odd_data() -> None:
    assert ft.history_value(None) is None
    assert ft.history_value({}) is None
    assert ft.history_value({"properties": {"day": {"value": []}}}) is None
    assert ft.history_value({"properties": {"day": {"value": ["x"]}}}) is None
    assert ft.history_value({"properties": {"day": {"value": [True]}}}) is None
    assert ft.history_value({"properties": {"day": "broken"}}) is None
    assert ft.history_attributes({"properties": None}) == {}
    assert ft.history_unit({"properties": {"day": {"value": [1]}}}) is None


def test_summary() -> None:
    feature = _by_name()["heating.heat.production.summary.dhw"]
    assert ft.summary_value(feature) == 9.6
    assert ft.summary_unit(feature) == "kilowattHour"
    assert ft.summary_attributes(feature) == {
        "current_day": 9.6,
        "current_month": 61.8,
        "current_year": 3382.9,
        "last_month": 389.9,
        "last_seven_days": 96.7,
    }
    assert ft.summary_value(None) is None
    assert ft.summary_attributes(None) == {}


def test_messages_newest_status_first() -> None:
    code, attributes = ft.messages_state(_by_name())
    assert code == "S.134"  # newest by timestamp, not first in the list
    assert attributes["newest_status_timestamp"] == "2026-11-12T07:30:00.000Z"
    assert [m["errorCode"] for m in attributes["status"]] == ["S.134", "S.123", "S.165"]
    assert attributes["status"][0] == {
        "errorCode": "S.134",
        "timestamp": "2026-11-12T07:30:00.000Z",
        "priority": "status",
    }
    assert attributes["status_count"] == 3
    assert attributes["info"] == [
        {"errorCode": "I.114", "timestamp": "2026-11-11T19:00:00.000Z", "priority": "info"}
    ]
    assert attributes["service"] == []
    assert attributes["service_count"] == 0


def test_messages_without_status_feature() -> None:
    features = _by_name()
    del features["device.messages.status.raw"]
    code, attributes = ft.messages_state(features)
    assert code is None
    assert "status" not in attributes
    assert attributes["newest_status_timestamp"] is None
    assert attributes["info_count"] == 1


def test_messages_are_capped() -> None:
    entries = [(f"S.{i}", f"2026-11-01T00:{i:02d}:00.000Z", "status") for i in range(40)]
    features = {"device.messages.status.raw": fakes.feature("device.messages.status.raw", fakes.messages(*entries))}
    code, attributes = ft.messages_state(features)
    assert code == "S.39"
    assert len(attributes["status"]) == 25
    assert attributes["status_count"] == 40


def test_slim_feature() -> None:
    feature = _by_name()["heating.sensors.temperature.outside"]
    assert set(ft.slim_feature(feature)) == {"feature", "timestamp", "isEnabled", "isReady", "properties"}
    assert set(ft.slim_feature(feature, full=True)) == set(feature)


def test_snake_case() -> None:
    assert ft.snake_case("lastSevenDays") == "last_seven_days"
    assert ft.snake_case("currentDay") == "current_day"

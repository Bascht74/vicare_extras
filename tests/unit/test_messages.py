"""Tests for the message code table and decoding."""

from __future__ import annotations

from collections import Counter
import json

import pytest

from custom_components.vicare_extras import messages


def test_table_contents() -> None:
    table = messages.load_table()
    by_class = Counter(code[0] for code in table)
    by_source = Counter(entry["source"] for entry in table.values())

    assert by_source["viessmann"] == 470
    assert by_source["vieventlog"] == 72
    # Viessmann service manual 6200041: S 113, I 90, A 44, P 4, F 219.
    viessmann = Counter(code[0] for code, entry in table.items() if entry["source"] == "viessmann")
    assert viessmann == {"S": 113, "I": 90, "A": 44, "P": 4, "F": 219}
    assert set(by_class) == {"S", "I", "A", "P", "F"}
    assert all(entry["de"] for entry in table.values())


@pytest.mark.parametrize(
    ("code", "text"),
    [
        # Texts ViEventLog showed live for a Vitocal 250-A; Viessmann's wording.
        ("S.115", "4/3-Wege-Ventil in Position „Trinkwassererwärmung“"),
        ("S.120", "Smart Grid: Normalbetrieb aktiv"),
        ("S.123", "Wärmepumpe aus"),
        ("S.124", "Wärmepumpe Vorlaufphase"),
        ("S.125", "Wärmepumpe im Heizbetrieb"),
        ("S.129", "Wärmepumpe Nachlaufphase"),
        ("S.134", "4/3-Wege-Ventil Leerlauf"),
        ("S.165", "Wärmepumpe: Systemstatus Regelung"),
        ("S.217", "Heizwasser-Durchlauferhitzer: Stufe 1 inaktiv"),
        ("S.218", "Heizwasser-Durchlauferhitzer: Stufe 2 inaktiv"),
        ("S.219", "Heizwasser-Durchlauferhitzer: Stufe 3 inaktiv"),
        ("I.114", "Smart Grid: Normalbetrieb aktiv"),
        ("A.11", "Anlagendruck zu niedrig"),
        ("P.4", "Heizwasser nachfüllen."),
        ("F.160", "Kommunikationsstörung CAN-BUS"),
    ],
)
def test_viessmann_texts(code, text) -> None:
    info = messages.describe(code)
    assert info["text"] == text
    assert info["source"] == "viessmann"


def test_s118_uses_viessmann_wording_not_vieventlog() -> None:
    """The manual says "Integrierter Pufferspeicher"; ViEventLog differs."""
    assert messages.describe("S.118")["text"] == "4/3-Wege-Ventil in Position „Integrierter Pufferspeicher“"


def test_vieventlog_fills_gaps_and_is_marked() -> None:
    info = messages.describe("S.427")
    assert info["text"] == "Leistungsbegrenzung durch den Netzbetreiber nach § 14a EnWG"
    assert info["source"] == "vieventlog"


@pytest.mark.parametrize(
    ("code", "category"),
    [("S.1", "status"), ("I.1", "info"), ("A.1", "warning"), ("P.1", "maintenance"), ("F.1", "fault")],
)
def test_categories(code, category) -> None:
    assert messages.category(code) == category
    assert messages.describe(code)["category"] == category


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [("S.123", "S.123"), (" s.0123 ", "S.123"), ("F.01", "F.1"), ("S123", None), ("", None), (None, None), (5, None)],
)
def test_normalize_code(raw, normalized) -> None:
    assert messages.normalize_code(raw) == normalized


def test_unknown_codes_degrade_to_the_raw_code() -> None:
    assert messages.describe("S.1") == {"code": "S.1", "text": None, "source": None, "category": "status"}
    assert messages.label("S.1") == "S.1"
    assert messages.label("X.999") == "X.999"
    assert messages.label("garbage") == "garbage"
    assert messages.describe(None) == {"code": None, "text": None, "source": None, "category": None}
    assert messages.label(None) is None


def test_language_falls_back_to_german() -> None:
    assert messages.describe("S.123", "en")["text"] == "Wärmepumpe aus"
    assert messages.label("S.123", "en-GB") == "Wärmepumpe aus"


def test_missing_table_degrades_gracefully(monkeypatch, tmp_path) -> None:
    messages.load_table.cache_clear()
    monkeypatch.setattr(messages, "TABLE_PATH", tmp_path / "missing.json")
    try:
        assert messages.load_table() == {}
        assert messages.label("S.123") == "S.123"
    finally:
        messages.load_table.cache_clear()


def test_decode_status_event_keeps_raw_event() -> None:
    event = {
        "eventType": "device-message-status",
        "gatewaySerial": "7571381500000001",
        "body": {
            "errorCode": "S.123",
            "deviceId": "0",
            "modelId": "E3_Vitocal_16",
            "active": True,
            "equipmentType": "Boiler",
            "errorDescription": "S.123",
        },
        "createdAt": "2026-11-12T10:23:57.890Z",
        "eventTimestamp": "2026-11-12T10:23:27.000Z",
        "editedBy": "system",
        "origin": "system",
        "audiences": ["IS-SUPPLIER"],
    }
    original = json.loads(json.dumps(event))

    decoded = messages.decode_event(event)

    assert event == original  # input untouched
    assert {key: decoded[key] for key in original} == original  # raw fields intact
    assert decoded["decoded"] == {
        "code": "S.123",
        "text": "Wärmepumpe aus",
        "source": "viessmann",
        "category": "status",
        "active": True,
    }
    assert decoded["summary"] == "S.123: Wärmepumpe aus"


def test_decode_feature_changed_event() -> None:
    event = {
        "eventType": "feature-changed",
        "body": {
            "featureName": "heating.circuits.1.operating.modes.active",
            "commandName": "setMode",
            "commandBody": {"mode": "standby"},
        },
        "editedBy": "00000000-0000-0000-0000-000000000000",
        "origin": "API",
        "audiences": None,
    }
    decoded = messages.decode_event(event)
    assert decoded["summary"] == "heating.circuits.1.operating.modes.active: setMode(mode=standby)"
    assert "decoded" not in decoded


@pytest.mark.parametrize(
    ("event", "summary"),
    [
        ({"eventType": "device-message-info", "body": {"errorCode": "I.114"}}, "I.114: Smart Grid: Normalbetrieb aktiv"),
        ({"eventType": "device-error", "body": {"errorCode": "F.74"}}, "F.74: Hydraulischer Anlagendruck zu niedrig"),
        ({"eventType": "device-message-status", "body": {"errorCode": "S.1"}}, "S.1"),
        ({"eventType": "feature-changed", "body": {"featureName": "heating.dhw.temperature.main"}}, "heating.dhw.temperature.main"),
        (
            {"eventType": "feature-changed", "body": {"featureName": "a.b", "commandName": "setSchedule", "commandBody": {"newSchedule": {"mon": []}}}},
            'a.b: setSchedule(newSchedule={"mon":[]})',
        ),
        ({"eventType": "feature-changed", "body": {"featureName": "a.b", "commandName": "activate", "commandBody": None}}, "a.b: activate()"),
        ({"eventType": "gateway-online", "body": {"online": True}}, None),
        ({"eventType": "gateway-online"}, None),
        ({"eventType": "feature-changed", "body": "odd"}, None),
    ],
)
def test_decode_event_variants(event, summary) -> None:
    assert messages.decode_event(event).get("summary") == summary

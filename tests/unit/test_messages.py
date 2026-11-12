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

    assert len(table) == 500
    assert by_source == {
        "viessmann": 470,
        "viessmann_6221420": 18,
        "viessmann_6179923": 5,
        "vieventlog": 6,
        "fhem": 1,
    }
    # Viessmann service manual 6200041: S 113, I 90, A 44, P 4, F 219.
    viessmann = Counter(code[0] for code, entry in table.items() if entry["source"] == "viessmann")
    assert viessmann == {"S": 113, "I": 90, "A": 44, "P": 4, "F": 219}
    assert set(by_class) == {"S", "I", "A", "P", "F"}
    assert all(entry["de"] for entry in table.values())
    # Only texts no Viessmann document confirms carry the flag.
    unverified = {code for code, entry in table.items() if entry.get("verified") is False}
    assert unverified == {"S.1", "S.119", "S.427", "A.130", "I.94", "I.95", "P.35"}
    assert all(
        table[code]["source"] in ("vieventlog", "fhem") for code in unverified
    )
    assert all("verified" not in entry or entry["verified"] is False for entry in table.values())


def test_table_has_no_manual_style_quotation_marks() -> None:
    """The texts are our own wording: no typographic quotes of the manual."""
    for code, entry in messages.load_table().items():
        if entry["source"].startswith("viessmann"):
            assert not set(entry["de"]) & set("„“”\""), code
            assert entry["de"] == entry["de"].strip()
            assert not entry["de"].endswith("."), code


@pytest.mark.parametrize(
    "code",
    # Placeholder-looking ViEventLog blocks and entries contradicting the
    # official sensor fault scheme are not in the table.
    ["S.10", "S.25", "S.61", "S.105", "S.110", "S.160", "S.192", "F.5", "F.10", "F.22"],
)
def test_dropped_codes_show_the_raw_code(code) -> None:
    assert messages.describe(code)["text"] is None
    assert messages.label(code) == code


@pytest.mark.parametrize(
    ("code", "source", "text"),
    [
        ("A.27", "viessmann_6221420", "Batterieladung gering"),
        ("F.23", "viessmann_6179923", "Puffertemperatursensor Mitte unterbrochen"),
    ],
)
def test_other_viessmann_manuals(code, source, text) -> None:
    info = messages.describe(code)
    assert (info["text"], info["source"], info["verified"]) == (text, source, True)


@pytest.mark.parametrize(
    ("code", "text"),
    [
        # Codes seen live on a Vitocal 250-A. Meaning as in the Viessmann
        # service manual, wording ours.
        ("S.115", "4/3-Wege-Ventil steht auf Trinkwassererwärmung"),
        ("S.120", "Smart Grid im Normalbetrieb"),
        ("S.123", "Wärmepumpe ist aus"),
        ("S.124", "Wärmepumpe in der Vorlaufphase"),
        ("S.125", "Wärmepumpe heizt"),
        ("S.129", "Wärmepumpe in der Nachlaufphase"),
        ("S.134", "4/3-Wege-Ventil in Leerlaufstellung"),
        ("S.165", "Systemstatus der Wärmepumpe: Regelung"),
        ("S.217", "Heizwasser-Durchlauferhitzer: Stufe 1 aus"),
        ("S.218", "Heizwasser-Durchlauferhitzer: Stufe 2 aus"),
        ("S.219", "Heizwasser-Durchlauferhitzer: Stufe 3 aus"),
        ("I.114", "Smart Grid im Normalbetrieb"),
        ("A.11", "Anlagendruck zu gering"),
        ("P.4", "Heizwasser muss nachgefüllt werden"),
        ("F.160", "CAN-BUS: Kommunikation gestört"),
    ],
)
def test_viessmann_texts(code, text) -> None:
    info = messages.describe(code)
    assert info["text"] == text
    assert info["source"] == "viessmann"
    assert info["verified"] is True
    assert messages.label(code) == text


def test_s118_follows_the_manual_not_vieventlog() -> None:
    """The manual means the integrated buffer; ViEventLog says otherwise."""
    assert messages.describe("S.118")["text"] == "4/3-Wege-Ventil steht auf integriertem Pufferspeicher"


def test_unverified_texts_are_marked_and_shown_as_unverified() -> None:
    info = messages.describe("S.427")
    assert info == {
        "code": "S.427",
        "text": "Leistungsbegrenzung durch den Netzbetreiber nach § 14a EnWG",
        "source": "vieventlog",
        "verified": False,
        "category": "status",
    }
    assert messages.label("S.427") == (
        "S.427 (ungeprüft: Leistungsbegrenzung durch den Netzbetreiber nach § 14a EnWG)"
    )
    assert messages.label("S.427", "en") == (
        "S.427 (unverified: Leistungsbegrenzung durch den Netzbetreiber nach § 14a EnWG)"
    )
    assert messages.describe("S.1")["source"] == "fhem"
    assert messages.label("s.01") == "S.1 (ungeprüft: Netzspannung eingeschaltet)"


def test_decode_entries_flags_unverified_texts() -> None:
    decoded = messages.decode_entries(
        [{"errorCode": "S.1"}, {"errorCode": "S.123"}, {"errorCode": "S.999"}]
    )
    assert decoded == [
        {"errorCode": "S.1", "text": "Netzspannung eingeschaltet", "source": "fhem", "verified": False},
        {"errorCode": "S.123", "text": "Wärmepumpe ist aus", "source": "viessmann"},
        {"errorCode": "S.999", "text": None},
    ]


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
    assert messages.describe("S.999") == {
        "code": "S.999",
        "text": None,
        "source": None,
        "verified": None,
        "category": "status",
    }
    assert messages.label("S.999") == "S.999"
    assert messages.label("X.999") == "X.999"
    assert messages.label("garbage") == "garbage"
    assert messages.describe(None) == {
        "code": None,
        "text": None,
        "source": None,
        "verified": None,
        "category": None,
    }
    assert messages.label(None) is None


def test_language_falls_back_to_german() -> None:
    assert messages.describe("S.123", "en")["text"] == "Wärmepumpe ist aus"
    assert messages.label("S.123", "en-GB") == "Wärmepumpe ist aus"


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
        "text": "Wärmepumpe ist aus",
        "source": "viessmann",
        "verified": True,
        "category": "status",
        "active": True,
    }
    assert decoded["summary"] == "S.123: Wärmepumpe ist aus"


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
        ({"eventType": "device-message-info", "body": {"errorCode": "I.114"}}, "I.114: Smart Grid im Normalbetrieb"),
        ({"eventType": "device-error", "body": {"errorCode": "F.74"}}, "F.74: Anlagendruck im Hydraulikkreis zu gering"),
        ({"eventType": "device-message-status", "body": {"errorCode": "S.999"}}, "S.999"),
        (
            {"eventType": "device-message-status", "body": {"errorCode": "S.1"}},
            "S.1 (ungeprüft: Netzspannung eingeschaltet)",
        ),
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

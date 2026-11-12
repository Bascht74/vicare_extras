"""Tests for the two actions, with mocked PyViCare objects."""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlsplit

import pytest
import voluptuous as vol

from custom_components.vicare_extras import services
from custom_components.vicare_extras.const import DOMAIN, EVENT_HISTORY_PATHS
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from . import fakes
from .test_event_history import FALLBACK, NOT_FOUND, PRIMARY, event, page


def setup(manager=None, **kwargs):
    hass, service = fakes.make_hass(oauth_manager=manager, **kwargs)
    services.async_setup_services(hass)
    return hass, service


def call(hass, name, data=None):
    return asyncio.run(hass.services.async_call(DOMAIN, name, data))


def test_actions_are_response_only() -> None:
    hass, _ = setup()
    assert set(hass.services.registered) == {
        (DOMAIN, "get_event_history"),
        (DOMAIN, "get_features"),
    }
    for registration in hass.services.registered.values():
        assert registration["supports_response"] is SupportsResponse.ONLY
        assert registration["schema"] is not None


# ---------------------------------------------------------------- event history


def test_event_history_defaults() -> None:
    manager = fakes.FakeOAuthManager(page([event(n=1)]))
    hass, service = setup(manager)

    result = call(hass, "get_event_history")

    query = parse_qs(urlsplit(manager.urls[0]).query)
    assert urlsplit(manager.urls[0]).path == PRIMARY
    assert query == {"lastNDays": ["30"], "limit": ["1000"]}
    assert result["installation_id"] == "2323232"
    assert result["endpoint"] == PRIMARY
    assert result["count"] == 1
    assert [{k: e[k] for k in event(n=1)} for e in result["events"]] == [event(n=1)]
    assert result["next_cursor"] is None
    assert result["api_calls"] == 1
    assert result["known_gateway_serials"] == [fakes.GATEWAY_SERIAL]
    # The blocking PyViCare call ran through the executor.
    assert len(hass.executor_jobs) == 1
    # The feature cache was not touched.
    assert service.api_calls == 0


def test_event_history_all_fields() -> None:
    manager = fakes.FakeOAuthManager(page([event("device-error")], "c9"))
    hass, _ = setup(manager)

    result = call(
        hass,
        "get_event_history",
        {
            "last_n_days": 7.0,  # the UI number selector sends floats
            "limit": 50,
            "max_pages": 1,
            "installation_id": 2323232,
            "event_type": ["device-error"],
            "gateway_serials": fakes.GATEWAY_SERIAL,
            "edited_by": "someone",
            "cursor": "c8",
        },
    )

    query = parse_qs(urlsplit(manager.urls[0]).query)
    assert query == {
        "lastNDays": ["7"],
        "limit": ["50"],
        "eventType": ["device-error"],
        "gatewaySerials": [fakes.GATEWAY_SERIAL],
        "editedBy": ["someone"],
        "cursor": ["c8"],
    }
    assert result["truncated"] is True
    assert result["next_cursor"] == "c9"


def test_event_history_decodes_messages_and_keeps_raw_events() -> None:
    status = {
        "eventType": "device-message-status",
        "gatewaySerial": fakes.GATEWAY_SERIAL,
        "body": {"errorCode": "S.123", "deviceId": "0", "active": True, "errorDescription": "S.123"},
        "createdAt": "2026-11-12T10:23:57.890Z",
        "eventTimestamp": "2026-11-12T10:23:27.000Z",
        "editedBy": "system",
        "origin": "system",
    }
    changed = {
        "eventType": "feature-changed",
        "body": {
            "featureName": "heating.circuits.1.operating.modes.active",
            "commandName": "setMode",
            "commandBody": {"mode": "standby"},
        },
        "origin": "API",
        "audiences": None,
    }
    other = {"eventType": "gateway-online", "body": {"online": True}}
    hass, _ = setup(fakes.FakeOAuthManager(page([status, changed, other])))

    events = call(hass, "get_event_history")["events"]

    assert events[0]["summary"] == "S.123: Wärmepumpe ist aus"
    assert events[0]["decoded"] == {
        "code": "S.123",
        "text": "Wärmepumpe ist aus",
        "source": "viessmann",
        "verified": True,
        "category": "status",
        "active": True,
    }
    assert events[1]["summary"] == "heating.circuits.1.operating.modes.active: setMode(mode=standby)"
    assert events[2] == other
    for raw, returned in zip((status, changed, other), events, strict=True):
        assert {key: returned[key] for key in raw} == raw


def test_event_history_remembers_working_path() -> None:
    manager = fakes.FakeOAuthManager(NOT_FOUND, page([event()]), page([event()]))
    hass, _ = setup(manager)

    first = call(hass, "get_event_history")
    second = call(hass, "get_event_history")

    assert first["api_calls"] == 2
    assert second["api_calls"] == 1  # no second probe of the missing path
    assert [urlsplit(url).path for url in manager.urls] == [PRIMARY, FALLBACK, FALLBACK]
    assert hass.data[DOMAIN]["event_history_path"] == EVENT_HISTORY_PATHS[1]


@pytest.mark.parametrize(
    "data",
    [
        {"last_n_days": 0},
        {"last_n_days": 366},
        {"limit": 0},
        {"limit": 1001},
        {"max_pages": 0},
        {"max_pages": 21},
        {"event_type": 5},
        {"installation_id": ""},
        {"unknown_field": 1},
    ],
)
def test_event_history_rejects_invalid_input(data) -> None:
    manager = fakes.FakeOAuthManager()
    hass, _ = setup(manager)
    with pytest.raises(vol.Invalid):
        call(hass, "get_event_history", data)
    assert manager.urls == []


def test_event_history_unknown_installation() -> None:
    manager = fakes.FakeOAuthManager()
    hass, _ = setup(manager)
    with pytest.raises(ServiceValidationError) as err:
        call(hass, "get_event_history", {"installation_id": "999"})
    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == "installation_not_found"
    assert err.value.translation_placeholders == {"installation_id": "999", "known": "2323232"}
    assert manager.urls == []


def test_event_history_vicare_not_loaded() -> None:
    manager = fakes.FakeOAuthManager()
    hass, _ = setup(manager)
    fakes.vicare_entry(hass).state = ConfigEntryState.SETUP_RETRY
    with pytest.raises(HomeAssistantError) as err:
        call(hass, "get_event_history")
    assert not isinstance(err.value, ServiceValidationError)
    assert err.value.translation_key == "vicare_not_loaded"
    assert manager.urls == []


def test_event_history_vicare_missing() -> None:
    hass, _ = setup()
    hass.config_entries.entries.clear()
    with pytest.raises(HomeAssistantError) as err:
        call(hass, "get_event_history")
    assert err.value.translation_key == "vicare_not_loaded"


def test_event_history_rate_limit() -> None:
    hass, _ = setup(fakes.FakeOAuthManager(fakes.PyViCareRateLimitError()))
    with pytest.raises(HomeAssistantError) as err:
        call(hass, "get_event_history")
    assert err.value.translation_key == "rate_limited"
    assert err.value.translation_placeholders == {"reset": "2026-11-13 00:00 UTC"}


def test_event_history_incompatible_client() -> None:
    hass, _ = setup()
    fakes.vicare_entry(hass).runtime_data.client.oauth_manager = None
    with pytest.raises(HomeAssistantError) as err:
        call(hass, "get_event_history")
    assert err.value.translation_key == "vicare_incompatible"


def test_event_history_never_posts() -> None:
    """FakeOAuthManager.post raises; a passing call proves it was not used."""
    hass, _ = setup(fakes.FakeOAuthManager(page([])))
    assert call(hass, "get_event_history")["count"] == 0


# --------------------------------------------------------------------- features


def test_features_default_is_the_heating_device() -> None:
    hass, service = setup()
    result = call(hass, "get_features")

    assert result["source"] == "cache"
    assert result["api_calls"] == 0
    assert len(result["devices"]) == 1
    device = result["devices"][0]
    assert device["device_id"] == "0"
    assert device["device_type"] == "heating"
    assert device["model"] == "E3_Vitocal_16"
    assert device["installation_id"] == "2323232"
    assert device["gateway_serial"] == fakes.GATEWAY_SERIAL
    assert device["count"] == result["count"] == 9
    names = [feature["feature"] for feature in device["features"]]
    assert names == sorted(names)
    assert set(device["features"][0]) == {"feature", "timestamp", "isEnabled", "isReady", "properties"}
    assert device["cache_age_seconds"] is not None
    assert service.api_calls == 0


def test_features_prefix() -> None:
    hass, service = setup()
    result = call(hass, "get_features", {"prefix": "heating.power.consumption"})
    assert [f["feature"] for f in result["devices"][0]["features"]] == [
        "heating.power.consumption.dhw",
        "heating.power.consumption.heating",
        "heating.power.consumption.total",
    ]
    day = result["devices"][0]["features"][0]["properties"]["day"]["value"]
    assert day[0] == 2.6
    assert service.api_calls == 0


def test_features_response_is_a_private_copy() -> None:
    hass, service = setup()
    result = call(hass, "get_features", {"prefix": "heating.power.consumption.dhw"})
    result["devices"][0]["features"][0]["properties"]["day"]["value"][0] = -1

    cached = next(
        f for f in service._cache["data"] if f["feature"] == "heating.power.consumption.dhw"
    )
    assert cached["properties"]["day"]["value"][0] == 2.6


def test_features_full_objects() -> None:
    hass, _ = setup()
    result = call(hass, "get_features", {"prefix": "heating.sensors", "full": True})
    feature = result["devices"][0]["features"][0]
    assert {"commands", "uri", "deviceId", "gatewayId"} <= set(feature)


@pytest.mark.parametrize(
    ("data", "device_ids"),
    [
        ({"vicare_device_id": "RoomControl-1"}, ["RoomControl-1"]),
        ({"vicare_device_id": 0}, ["0"]),
        ({"device_type": "TCU"}, ["TCU"]),
        ({"device_type": "roomControl"}, ["RoomControl-1"]),
        ({"device_id": "ha-device-heat-pump"}, ["0"]),
        ({"device_id": ["ha-device-heat-pump"], "device_type": "heating"}, ["0"]),
    ],
)
def test_features_device_selection(data, device_ids) -> None:
    hass, service = setup()
    result = call(hass, "get_features", data)
    assert [device["device_id"] for device in result["devices"]] == device_ids
    assert service.api_calls == 0


@pytest.mark.parametrize(
    "data",
    [
        {"vicare_device_id": "nope"},
        {"device_type": "ventilation"},
        {"device_id": "unknown-ha-device"},
        {"device_id": "ha-device-heat-pump", "device_type": "tcu"},
    ],
)
def test_features_device_not_found(data) -> None:
    hass, _ = setup()
    with pytest.raises(ServiceValidationError) as err:
        call(hass, "get_features", data)
    assert err.value.translation_key == "device_not_found"


def test_features_ha_device_of_other_integration_is_not_matched() -> None:
    from homeassistant.helpers.device_registry import DeviceEntry

    hass, _ = setup()
    hass.device_registry.add(DeviceEntry(id="other", identifiers={("hue", "abc")}))
    with pytest.raises(ServiceValidationError):
        call(hass, "get_features", {"device_id": "other"})


def test_features_empty_cache_fails_without_request(monkeypatch) -> None:
    monkeypatch.setattr(services, "CACHE_WAIT_SECONDS", 0)
    hass, service = setup(empty_cache=True)
    with pytest.raises(HomeAssistantError) as err:
        call(hass, "get_features")
    assert err.value.translation_key == "no_cached_data"
    assert "E3_Vitocal_16" in err.value.translation_placeholders["device"]
    assert service.api_calls == 0


def test_features_waits_while_vicare_refreshes(monkeypatch) -> None:
    """The built-in integration empties the cache during its refresh."""
    monkeypatch.setattr(services, "CACHE_WAIT_SECONDS", 0)
    hass, service = setup(empty_cache=True)
    attempts = 0
    real_peek = services.bridge.peek_payload

    def peek(svc):
        nonlocal attempts
        attempts += 1
        if attempts == 3:
            svc._cache = fakes.gateway_payload()
        return real_peek(svc)

    monkeypatch.setattr(services.bridge, "peek_payload", peek)
    result = call(hass, "get_features")
    assert result["count"] == 9
    assert attempts == 3
    assert service.api_calls == 0


def test_features_vicare_not_loaded() -> None:
    hass, _ = setup()
    fakes.vicare_entry(hass).state = ConfigEntryState.NOT_LOADED
    with pytest.raises(HomeAssistantError) as err:
        call(hass, "get_features")
    assert err.value.translation_key == "vicare_not_loaded"


def test_features_service_without_cache() -> None:
    hass, _ = setup()
    for config in fakes.vicare_entry(hass).runtime_data.client.all_devices:
        config.service = object()
    with pytest.raises(HomeAssistantError) as err:
        call(hass, "get_features")
    assert err.value.translation_key == "cache_unsupported"

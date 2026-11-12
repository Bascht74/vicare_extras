"""Tests for the read-only bridge to the built-in vicare integration."""

from __future__ import annotations

import pytest

from custom_components.vicare_extras import bridge
from custom_components.vicare_extras.errors import ViCareExtrasError
from homeassistant.config_entries import ConfigEntry, ConfigEntryState

from . import fakes


def test_collect_devices_lists_registered_devices_first() -> None:
    hass, service = fakes.make_hass()
    refs = bridge.collect_devices(fakes.vicare_entry(hass))

    assert [ref.device_id for ref in refs] == ["0", "TCU", "RoomControl-1"]
    heat_pump = refs[0]
    assert heat_pump.identifier == fakes.HEAT_PUMP_IDENTIFIER
    assert heat_pump.installation_id == str(fakes.INSTALLATION_ID)
    assert heat_pump.gateway_serial == fakes.GATEWAY_SERIAL
    assert heat_pump.device_type == "heating"
    assert heat_pump.model == "E3_Vitocal_16"
    assert heat_pump.entry_id == fakes.VICARE_ENTRY_ID
    assert heat_pump.service is service
    # Devices the built-in integration does not set up have no HA device.
    assert [ref.identifier for ref in refs[1:]] == [None, None]
    assert service.api_calls == 0


@pytest.mark.parametrize(
    ("serial", "expected"),
    [
        ("7733738100000002", "GW_7733738100000002"),
        ("zigbee-1234567890abcdef", "GW_zigbee_1234567890abcdef"),
        (None, "GW_0"),
    ],
)
def test_identifier_matches_builtin_integration(serial, expected) -> None:
    """Same rule as ViCareEntity.__init__ in core 2026.11.1."""
    service = fakes.FakeCachedService(None)
    config = fakes.FakeDeviceConfig(fakes.FakeAccessor(1, "GW", "0"), service, "M", "heating")
    entry = ConfigEntry(domain="vicare")
    entry.runtime_data = fakes.FakeViCareData(
        fakes.FakeClient(fakes.FakeOAuthManager(), []), [fakes.FakeViCareDevice(config, serial)]
    )
    assert bridge.collect_devices(entry)[0].identifier == expected


def test_peek_payload_reads_cache_without_request() -> None:
    payload = fakes.gateway_payload()
    service = fakes.FakeCachedService(payload)
    assert bridge.peek_payload(service) is payload
    assert service.api_calls == 0


def test_peek_payload_empty_cache_returns_none() -> None:
    service = fakes.FakeCachedService(None)
    assert bridge.peek_payload(service) is None
    assert service.api_calls == 0


@pytest.mark.parametrize("cache", [{"error": "x"}, {"data": "nope"}, [], "text"])
def test_peek_payload_ignores_unexpected_cache_content(cache) -> None:
    assert bridge.peek_payload(fakes.FakeCachedService(cache)) is None


@pytest.mark.parametrize("service", [None, object()])
def test_peek_payload_without_cache_attribute_fails_safely(service) -> None:
    with pytest.raises(ViCareExtrasError) as err:
        bridge.peek_payload(service)
    assert err.value.translation_key == "cache_unsupported"


def test_device_features_filters_by_device() -> None:
    payload = fakes.gateway_payload()
    names = [f["feature"] for f in bridge.device_features(payload, "0")]
    assert "heating.power.consumption.dhw" in names
    assert "tcu.wifi" not in names
    assert "gateway.devices" not in names  # gateway level, belongs to no device
    assert [f["feature"] for f in bridge.device_features(payload, "TCU")] == ["tcu.wifi"]
    assert [f["feature"] for f in bridge.device_features(payload, "RoomControl-1")] == ["rooms"]
    assert bridge.device_features(payload, "does-not-exist") == []


def test_device_features_skips_malformed_items() -> None:
    payload = {"data": [None, "x", {"uri": "/devices/0/"}, {"feature": "a", "deviceId": "0"}]}
    assert [f["feature"] for f in bridge.device_features(payload, "0")] == ["a"]


def test_require_vicare_entries_when_not_loaded() -> None:
    hass, _ = fakes.make_hass()
    fakes.vicare_entry(hass).state = ConfigEntryState.SETUP_RETRY
    with pytest.raises(ViCareExtrasError) as err:
        bridge.require_vicare_entries(hass)
    assert err.value.translation_key == "vicare_not_loaded"
    assert not err.value.validation


def test_loaded_entries_fallback_without_async_loaded_entries() -> None:
    hass, _ = fakes.make_hass()

    class OldManager:
        def async_entries(self, domain):
            return hass.config_entries.entries

    old = type("Hass", (), {"config_entries": OldManager()})()
    assert bridge.loaded_vicare_entries(old) == hass.config_entries.entries


def test_get_oauth_manager() -> None:
    hass, _ = fakes.make_hass()
    runtime_data = bridge.get_runtime_data(fakes.vicare_entry(hass))
    assert bridge.get_oauth_manager(runtime_data) is runtime_data.client.oauth_manager


@pytest.mark.parametrize("runtime_data", [object(), type("R", (), {"client": object()})()])
def test_get_oauth_manager_incompatible(runtime_data) -> None:
    with pytest.raises(ViCareExtrasError) as err:
        bridge.get_oauth_manager(runtime_data)
    assert err.value.translation_key == "vicare_incompatible"


def test_incompatible_runtime_data_is_reported() -> None:
    entry = ConfigEntry(domain="vicare")
    with pytest.raises(ViCareExtrasError) as err:
        bridge.collect_devices(entry)  # runtime_data is None
    assert err.value.translation_key == "vicare_incompatible"

    entry.runtime_data = object()  # no .devices
    with pytest.raises(ViCareExtrasError) as err:
        bridge.collect_devices(entry)
    assert err.value.translation_key == "vicare_incompatible"

    entry.runtime_data = fakes.FakeViCareData(
        fakes.FakeClient(fakes.FakeOAuthManager(), []), [object()]  # device without .config
    )
    with pytest.raises(ViCareExtrasError) as err:
        bridge.collect_devices(entry)
    assert err.value.translation_key == "vicare_incompatible"


def test_cache_age_seconds() -> None:
    service = fakes.FakeCachedService(fakes.gateway_payload())
    age = bridge.cache_age_seconds(service)
    assert age is not None and 0 <= age < 5
    assert bridge.cache_age_seconds(object()) is None

"""Tests for setup, config flow and diagnostics."""

from __future__ import annotations

import asyncio
import json

import pytest

import custom_components.vicare_extras as integration
from custom_components.vicare_extras import config_flow, diagnostics, messages
from custom_components.vicare_extras.const import DOMAIN
from custom_components.vicare_extras.coordinator import ViCareExtrasCoordinator
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryNotReady

from . import fakes


def test_async_setup_registers_actions() -> None:
    hass, _ = fakes.make_hass()
    assert asyncio.run(integration.async_setup(hass, {})) is True
    # The message table (a file) is read through the executor, not in the loop.
    assert hass.executor_jobs == [messages.load_table]
    assert (DOMAIN, "get_event_history") in hass.services.registered
    assert (DOMAIN, "get_features") in hass.services.registered


def test_setup_and_unload_entry() -> None:
    hass, service = fakes.make_hass()
    entry = ConfigEntry(domain=DOMAIN, entry_id="extras")

    assert asyncio.run(integration.async_setup_entry(hass, entry)) is True
    assert isinstance(entry.runtime_data, ViCareExtrasCoordinator)
    assert hass.config_entries.forwarded == [(entry, [Platform.BINARY_SENSOR, Platform.CLIMATE, Platform.SENSOR])]
    assert fakes.HEAT_PUMP_IDENTIFIER in entry.runtime_data.data

    assert asyncio.run(integration.async_unload_entry(hass, entry)) is True
    assert hass.config_entries.unloaded == [(entry, [Platform.BINARY_SENSOR, Platform.CLIMATE, Platform.SENSOR])]
    assert service.api_calls == 0


def test_setup_entry_not_ready_without_loaded_vicare() -> None:
    hass, _ = fakes.make_hass()
    fakes.vicare_entry(hass).state = ConfigEntryState.SETUP_RETRY
    entry = ConfigEntry(domain=DOMAIN, entry_id="extras")
    with pytest.raises(ConfigEntryNotReady):
        asyncio.run(integration.async_setup_entry(hass, entry))
    assert hass.config_entries.forwarded == []


def test_config_flow_creates_single_entry_without_input() -> None:
    flow = config_flow.ViCareExtrasConfigFlow()
    assert config_flow.ViCareExtrasConfigFlow.domain == DOMAIN

    result = asyncio.run(flow.async_step_user())
    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["data_schema"] is None

    result = asyncio.run(flow.async_step_user({}))
    assert result == {"type": "create_entry", "title": "ViCare Extras", "data": {}}


def test_config_flow_aborts_second_instance() -> None:
    flow = config_flow.ViCareExtrasConfigFlow()
    flow._current_entries = [object()]
    result = asyncio.run(flow.async_step_user())
    assert result == {"type": "abort", "reason": "single_instance_allowed"}


def test_diagnostics_contain_no_identifying_numbers() -> None:
    hass, service = fakes.make_hass()
    entry = ConfigEntry(domain=DOMAIN, entry_id="extras")
    asyncio.run(integration.async_setup_entry(hass, entry))

    result = asyncio.run(diagnostics.async_get_config_entry_diagnostics(hass, entry))
    dumped = json.dumps(result)

    assert fakes.GATEWAY_SERIAL not in dumped
    assert fakes.HEAT_PUMP_SERIAL not in dumped
    assert str(fakes.INSTALLATION_ID) not in dumped
    assert result["vicare_entries_loaded"] == 1
    heat_pump = next(d for d in result["devices"] if d["device_id"] == "0")
    assert heat_pump["cache"] == "present"
    assert heat_pump["set_up_by_vicare"] is True
    assert "heating.power.consumption.dhw" in heat_pump["features"]
    assert result["coordinator"]["snapshots"][0]["feature_count"] == 9
    assert service.api_calls == 0


def test_diagnostics_when_vicare_is_not_loaded() -> None:
    hass, _ = fakes.make_hass()
    entry = ConfigEntry(domain=DOMAIN, entry_id="extras")
    asyncio.run(integration.async_setup_entry(hass, entry))
    fakes.vicare_entry(hass).state = ConfigEntryState.NOT_LOADED

    result = asyncio.run(diagnostics.async_get_config_entry_diagnostics(hass, entry))
    assert result["error"] == "vicare_not_loaded"
    assert result["devices"] == []


def test_diagnostics_show_poll_intervals_and_hide_zigbee_addresses() -> None:
    hass, service = fakes.make_hass(with_trv=True)
    entry = ConfigEntry(domain=DOMAIN, entry_id="extras")
    entry.options = {"vicare_poll_interval": 90}
    asyncio.run(integration.async_setup_entry(hass, entry))

    result = asyncio.run(diagnostics.async_get_config_entry_diagnostics(hass, entry))

    assert result["poll_interval"] == {
        "option_seconds": 90,
        "vicare_seconds": 90.0,
        "mirror_seconds": 85.0,
    }
    dumped = json.dumps(result)
    assert fakes.TRV_DEVICE_ID not in dumped
    assert "zigbee-...cdef" in dumped
    assert service.api_calls == 0


def test_diagnostics_without_poll_interval_option() -> None:
    hass, _ = fakes.make_hass()
    entry = ConfigEntry(domain=DOMAIN, entry_id="extras")
    asyncio.run(integration.async_setup_entry(hass, entry))
    result = asyncio.run(diagnostics.async_get_config_entry_diagnostics(hass, entry))
    assert result["poll_interval"] == {
        "option_seconds": None,
        "vicare_seconds": 60.0,
        "mirror_seconds": 55.0,
    }

"""End-to-end tests with a real Home Assistant instance (not executed, see conftest)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .. import vicare_fakes as fakes

DOMAIN = "vicare_extras"


@pytest.fixture
async def vicare(hass: HomeAssistant):
    """A loaded vicare entry whose setup is replaced by fake runtime data."""
    entry = MockConfigEntry(domain="vicare", title="ViCare", data={})
    entry.add_to_hass(hass)
    manager = fakes.FakeOAuthManager()
    runtime_data, service = fakes.make_runtime_data(oauth_manager=manager)

    async def fake_setup_entry(hass: HomeAssistant, config_entry) -> None:
        config_entry.runtime_data = runtime_data

    with (
        patch("homeassistant.components.vicare.async_setup_entry", fake_setup_entry),
        patch("homeassistant.components.vicare.async_unload_entry", return_value=None),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={("vicare", fakes.HEAT_PUMP_IDENTIFIER)},
            manufacturer="Viessmann",
            name="E3 Vitocal 16",
        )
        yield entry, service, manager, device


async def _setup_extras(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="ViCare Extras", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_config_flow(hass: HomeAssistant, vicare) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "ViCare Extras"

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_sensors_attach_to_the_vicare_device(hass: HomeAssistant, vicare) -> None:
    _, service, _, vicare_device = vicare
    entry = await _setup_extras(hass)
    assert entry.state is ConfigEntryState.LOADED

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len(entities) == 6
    assert {entity.device_id for entity in entities} == {vicare_device.id}
    # No device of its own was created.
    assert dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id) == []

    by_key = {entity.unique_id.rsplit("-", 1)[1]: entity for entity in entities}
    state = hass.states.get(by_key["power_consumption_dhw_history"].entity_id)
    assert state.state == "2.6"
    assert state.attributes["unit_of_measurement"] == "kWh"
    assert state.attributes["device_class"] == "energy"
    assert "state_class" not in state.attributes
    assert state.attributes["day"][0] == 2.6
    assert hass.states.get(by_key["messages"].entity_id).state == "S.134"
    assert service.api_calls == 0


async def test_setup_retries_without_vicare(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="ViCare Extras", data={})
    entry.add_to_hass(hass)
    with patch("homeassistant.components.vicare.async_setup", return_value=True):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_get_features_action(hass: HomeAssistant, vicare) -> None:
    _, service, _, vicare_device = vicare
    await _setup_extras(hass)

    response = await hass.services.async_call(
        DOMAIN,
        "get_features",
        {"device_id": vicare_device.id, "prefix": "heating.power.consumption"},
        blocking=True,
        return_response=True,
    )
    assert response["api_calls"] == 0
    assert response["count"] == 3
    assert service.api_calls == 0


async def test_get_event_history_action(hass: HomeAssistant, vicare) -> None:
    _, _, manager, _ = vicare
    await _setup_extras(hass)
    manager.answers.append({"cursor": {}, "data": [{"eventType": "gateway-online"}]})

    response = await hass.services.async_call(
        DOMAIN, "get_event_history", {"last_n_days": 7}, blocking=True, return_response=True
    )
    assert response["count"] == 1
    assert response["endpoint"] == "/eventhistory/installations/2323232/events"
    assert "lastNDays=7" in manager.urls[0]

    manager.answers.append(fakes.PyViCareRateLimitError())
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN, "get_event_history", {}, blocking=True, return_response=True
        )
    assert err.value.translation_key == "rate_limited"

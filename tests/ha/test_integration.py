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
    # 6 sensors of version 0.1.0 plus last/active status messages and operating state.
    assert len(entities) == 9
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
    assert hass.states.get(by_key["last_status_message"].entity_id).state == "4/3-Wege-Ventil in Leerlaufstellung"
    assert hass.states.get(by_key["operating_state"].entity_id).state == "off"
    assert service.api_calls == 0


async def test_vitocal_entities_and_rooms(hass: HomeAssistant, vicare) -> None:
    """Full feature list of a Vitocal 250-A plus one synthetic room."""
    _, service, _, vicare_device = vicare
    service._cache = fakes.gateway_payload(fakes.vitocal_features(), fakes.room_features(0))
    entry = await _setup_extras(hass)

    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    # 46 sensors, 18 binary sensors, 11 room entities and the room's climate entity.
    assert len(entities) == 46 + 18 + 11 + 1
    on_heat_pump = [entity for entity in entities if entity.device_id == vicare_device.id]
    assert len(on_heat_pump) == 46 + 18
    room_devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert [device.name for device in room_devices] == ["Wohnzimmer"]
    # The room is shown as a connected device of the heat pump.
    assert room_devices[0].via_device_id == vicare_device.id

    by_unique_id = {entity.unique_id: entity for entity in entities}
    prefix = fakes.HEAT_PUMP_IDENTIFIER
    assert hass.states.get(by_unique_id[f"{prefix}-operating_state"].entity_id).state == "dhw"
    assert hass.states.get(by_unique_id[f"{prefix}-cop_current"].entity_id).state == "2.54"
    valve = hass.states.get(by_unique_id[f"{prefix}-four_three_way_valve_position"].entity_id)
    assert valve.state == "domestic_hot_water"
    assert hass.states.get(by_unique_id[f"{prefix}-internal_pump"].entity_id).state == "on"
    disabled = [entity for entity in entities if entity.disabled_by is not None]
    assert len(disabled) == 13 + 1  # 13 on the heat pump, 1 perceived setpoint of the room
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
    assert response["endpoint"] == "/events-history/installations/2323232/events"
    assert "lastNDays=7" in manager.urls[0]

    manager.answers.append(fakes.PyViCareRateLimitError())
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN, "get_event_history", {}, blocking=True, return_response=True
        )
    assert err.value.translation_key == "rate_limited"


async def test_options_flow_sets_and_clears_the_poll_interval(hass: HomeAssistant, vicare) -> None:
    """Setting and clearing the option takes effect without a restart."""
    from datetime import timedelta  # noqa: PLC0415

    vicare_entry, service, _, _ = vicare
    builtin = vicare_entry.runtime_data.devices[0].coordinator
    entry = await _setup_extras(hass)
    assert builtin.update_interval == timedelta(seconds=60)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"vicare_poll_interval": 90}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {"vicare_poll_interval": 90}
    assert entry.state is ConfigEntryState.LOADED  # reloaded
    assert builtin.update_interval == timedelta(seconds=90)
    assert service._cacheDuration == 150

    # Clearing the field removes the option and restores the original values.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {}
    assert builtin.update_interval == timedelta(seconds=60)
    assert service._cacheDuration == 60
    assert service.api_calls == 0


async def test_climate_entities_and_set_temperature(hass: HomeAssistant) -> None:
    """A room and a radiator thermostat; setting a temperature is one command."""
    vicare_entry = MockConfigEntry(domain="vicare", title="ViCare", data={})
    vicare_entry.add_to_hass(hass)
    payload = fakes.gateway_payload(
        [],
        fakes.room_features(
            0, writable="temperature.levels.normal.perceived", actors=(fakes.TRV_DEVICE_ID,)
        ),
        fakes.trv_features(),
    )
    service = fakes.FakeCommandService(payload)
    runtime_data, _ = fakes.make_runtime_data(with_trv=True, service=service)

    async def fake_setup_entry(hass: HomeAssistant, config_entry) -> None:
        config_entry.runtime_data = runtime_data

    with (
        patch("homeassistant.components.vicare.async_setup_entry", fake_setup_entry),
        patch("homeassistant.components.vicare.async_unload_entry", return_value=None),
    ):
        assert await hass.config_entries.async_setup(vicare_entry.entry_id)
        await hass.async_block_till_done()
        registry = dr.async_get(hass)
        trv_device = registry.async_get_or_create(
            config_entry_id=vicare_entry.entry_id,
            identifiers={("vicare", fakes.TRV_IDENTIFIER)},
            manufacturer="Viessmann",
            name="Thermostat Wohnzimmer",
        )
        entry = await _setup_extras(hass)

        entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        climates = {e.unique_id: e for e in entities if e.domain == "climate"}
        room = climates[f"{fakes.GATEWAY_SERIAL}_RoomControl-1_room_0-climate"]
        trv = climates[f"{fakes.TRV_IDENTIFIER}-climate"]
        assert trv.device_id == trv_device.id  # attached to the built-in device
        assert room.device_id != trv_device.id

        state = hass.states.get(room.entity_id)
        assert state.state == "heat"
        assert state.attributes["temperature"] == 21
        assert state.attributes["current_temperature"] == 21.4
        assert state.attributes["min_temp"] == 8
        assert state.attributes["max_temp"] == 30
        assert state.attributes["actors"] == [fakes.TRV_DEVICE_ID]

        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": room.entity_id, "temperature": 22.5},
            blocking=True,
        )
        assert service.commands == [
            (
                "RoomControl-1",
                "rooms.0.temperature.levels.normal.perceived",
                "setTemperature",
                {"targetTemperature": 22.5},
            )
        ]
        assert service.cache_clears == 0
        assert hass.states.get(room.entity_id).attributes["temperature"] == 22.5

        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": trv.entity_id, "temperature": 20},
            blocking=True,
        )
        assert service.commands[-1] == (
            fakes.TRV_DEVICE_ID,
            "trv.temperature",
            "setTargetTemperature",
            {"temperature": 20},
        )
        assert service.api_calls == 0


async def test_send_command_action_is_admin_only(hass: HomeAssistant, hass_read_only_user) -> None:
    """One POST as given; the API's rejection comes back as data."""
    from homeassistant.core import Context  # noqa: PLC0415
    from homeassistant.exceptions import Unauthorized  # noqa: PLC0415

    vicare_entry = MockConfigEntry(domain="vicare", title="ViCare", data={})
    vicare_entry.add_to_hass(hass)
    service = fakes.FakeCommandService(
        fakes.gateway_payload(None, fakes.room_features(0)),
        fakes.PyViCareCommandError("COMMAND_NOT_FOUND"),
    )
    runtime_data, _ = fakes.make_runtime_data(service=service)

    async def fake_setup_entry(hass: HomeAssistant, config_entry) -> None:
        config_entry.runtime_data = runtime_data

    data = {
        "vicare_device_id": "RoomControl-1",
        "feature": "rooms.0.temperature.levels.normal.perceived",
        "command": "setTemperature",
        "params": {"targetTemperature": 21},
    }
    with (
        patch("homeassistant.components.vicare.async_setup_entry", fake_setup_entry),
        patch("homeassistant.components.vicare.async_unload_entry", return_value=None),
    ):
        assert await hass.config_entries.async_setup(vicare_entry.entry_id)
        await hass.async_block_till_done()
        await _setup_extras(hass)

        with pytest.raises(Unauthorized):
            await hass.services.async_call(
                DOMAIN,
                "send_command",
                data,
                blocking=True,
                return_response=True,
                context=Context(user_id=hass_read_only_user.id),
            )
        assert service.commands == []

        response = await hass.services.async_call(
            DOMAIN, "send_command", data, blocking=True, return_response=True
        )
        assert response["sent"] is True
        assert response["advertised"] is False
        assert response["success"] is False
        assert response["api_calls"] == 1
        assert response["response"]["error_type"] == "PyViCareCommandError"
        assert len(service.commands) == 1
        assert service.cache_clears == 0

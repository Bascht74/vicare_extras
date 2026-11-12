"""Tests for the optional poll interval of the built-in vicare integration."""

from __future__ import annotations

from datetime import timedelta
import logging

import pytest

from custom_components.vicare_extras import config_flow, polling
from custom_components.vicare_extras.const import CONF_VICARE_POLL_INTERVAL
from custom_components.vicare_extras.polling import PollIntervalManager
import custom_components.vicare_extras as integration
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.exceptions import ConfigEntryNotReady

import asyncio

from . import fakes
from .fakes import Platforms


def builtin(hass):
    """Return (coordinator, service) of the fake vicare entry."""
    device = fakes.vicare_entry(hass).runtime_data.devices[0]
    return device.coordinator, device.config.service


def test_nothing_is_touched_without_the_option() -> None:
    hass, _ = fakes.make_hass()
    coordinator, service = builtin(hass)
    platforms = Platforms(hass).setup()
    platforms.refresh()

    assert coordinator.update_interval == timedelta(seconds=60)
    assert service._cacheDuration == 60
    # The mirror keeps its own slightly shorter period.
    assert platforms.coordinator.update_interval == timedelta(seconds=55)
    assert service.api_calls == 0


def test_option_slows_the_builtin_integration_down(caplog) -> None:
    hass, _ = fakes.make_hass()
    coordinator, service = builtin(hass)
    with caplog.at_level(logging.INFO):
        platforms = Platforms(hass, {CONF_VICARE_POLL_INTERVAL: 90}).setup()

    assert coordinator.update_interval == timedelta(seconds=90)
    # PyViCare must trust its cache longer than one interval, otherwise a
    # read between two polls would fetch again.
    assert service._cacheDuration == 150
    # The mirror follows: a little faster than the built-in integration.
    assert platforms.coordinator.update_interval == timedelta(seconds=85)
    assert [r.getMessage() for r in caplog.records if "Poll interval" in r.getMessage()] == [
        "Poll interval of the ViCare integration set to 90 s (was 60 s)"
    ]

    caplog.clear()
    with caplog.at_level(logging.INFO):
        platforms.refresh()
        platforms.refresh()
    assert coordinator.update_interval == timedelta(seconds=90)
    assert not [r for r in caplog.records if "Poll interval" in r.getMessage()]  # logged once
    assert service.api_calls == 0


def test_unload_restores_the_original_values(caplog) -> None:
    hass, _ = fakes.make_hass()
    coordinator, service = builtin(hass)
    entry = ConfigEntry(domain="vicare_extras", entry_id="extras")
    entry.options = {CONF_VICARE_POLL_INTERVAL: 120}

    asyncio.run(integration.async_setup_entry(hass, entry))
    assert coordinator.update_interval == timedelta(seconds=120)
    assert service._cacheDuration == 180

    with caplog.at_level(logging.INFO):
        for callback in entry._on_unload:  # what Home Assistant runs on unload
            callback()
    assert coordinator.update_interval == timedelta(seconds=60)
    assert service._cacheDuration == 60
    assert "Poll interval of the ViCare integration restored to 60 s" in caplog.text


def test_clearing_the_option_restores_60_seconds_without_restart() -> None:
    """Options change = entry reload = unload (restore) + setup (apply)."""
    hass, _ = fakes.make_hass()
    coordinator, service = builtin(hass)
    entry = ConfigEntry(domain="vicare_extras", entry_id="extras")

    entry.options = {CONF_VICARE_POLL_INTERVAL: 90}
    asyncio.run(integration.async_setup_entry(hass, entry))
    assert coordinator.update_interval == timedelta(seconds=90)

    # The user clears the option: Home Assistant reloads the entry.
    for callback in entry._on_unload:
        callback()
    entry._on_unload.clear()
    entry.options = {}
    asyncio.run(integration.async_setup_entry(hass, entry))

    assert coordinator.update_interval == timedelta(seconds=60)
    assert service._cacheDuration == 60
    assert entry.runtime_data.update_interval == timedelta(seconds=55)


def test_failed_setup_does_not_leave_the_interval_changed() -> None:
    """The option is applied, then the first look fails: restore must run."""
    hass, _ = fakes.make_hass()
    coordinator, service = builtin(hass)
    del service._cache  # the cache cannot be read: setup is not ready
    entry = ConfigEntry(domain="vicare_extras", entry_id="extras")
    entry.options = {CONF_VICARE_POLL_INTERVAL: 90}

    with pytest.raises(ConfigEntryNotReady):
        asyncio.run(integration.async_setup_entry(hass, entry))
    assert coordinator.update_interval == timedelta(seconds=90)  # was applied

    for callback in entry._on_unload:  # Home Assistant runs them after a failed setup
        callback()
    assert coordinator.update_interval == timedelta(seconds=60)
    assert service._cacheDuration == 60


def test_never_faster_than_the_builtin_integration_computed() -> None:
    """Two gateways: the built-in integration polls every 120 s."""
    hass, _ = fakes.make_hass()
    coordinator, service = builtin(hass)
    coordinator.update_interval = timedelta(seconds=120)
    service._cacheDuration = 120

    platforms = Platforms(hass, {CONF_VICARE_POLL_INTERVAL: 90}).setup()

    assert coordinator.update_interval == timedelta(seconds=120)  # untouched
    assert service._cacheDuration == 120
    assert platforms.coordinator.update_interval == timedelta(seconds=115)
    platforms.coordinator.poll_manager.restore()
    assert coordinator.update_interval == timedelta(seconds=120)


def test_reapplied_after_the_vicare_entry_reloads() -> None:
    hass, _ = fakes.make_hass()
    platforms = Platforms(hass, {CONF_VICARE_POLL_INTERVAL: 90}).setup()
    old_coordinator, _ = builtin(hass)

    # vicare reloads: new coordinator and service with their own values.
    vicare = fakes.vicare_entry(hass)
    vicare.runtime_data, new_service = fakes.make_runtime_data()
    new_coordinator = vicare.runtime_data.devices[0].coordinator
    assert new_coordinator is not old_coordinator
    assert new_coordinator.update_interval == timedelta(seconds=60)

    platforms.refresh()

    assert new_coordinator.update_interval == timedelta(seconds=90)
    assert new_service._cacheDuration == 150
    platforms.coordinator.poll_manager.restore()
    assert new_coordinator.update_interval == timedelta(seconds=60)
    assert new_service._cacheDuration == 60
    assert old_coordinator.update_interval == timedelta(seconds=60)


def test_restore_leaves_values_someone_else_changed() -> None:
    hass, _ = fakes.make_hass()
    coordinator, service = builtin(hass)
    manager = PollIntervalManager(90)
    manager.apply(hass)

    coordinator.update_interval = timedelta(seconds=300)  # e.g. a rate limit back-off
    manager.restore()

    assert coordinator.update_interval == timedelta(seconds=300)
    assert service._cacheDuration == 60


@pytest.mark.parametrize("broken", ["no_coordinator_attribute", "interval_not_timedelta", "no_cache_duration"])
def test_unexpected_structure_changes_nothing_and_warns_once(broken, caplog) -> None:
    hass, _ = fakes.make_hass()
    device = fakes.vicare_entry(hass).runtime_data.devices[0]
    coordinator, service = builtin(hass)
    if broken == "no_coordinator_attribute":
        del device.coordinator
    elif broken == "interval_not_timedelta":
        coordinator.update_interval = 60
    else:
        del service._cacheDuration

    with caplog.at_level(logging.WARNING):
        platforms = Platforms(hass, {CONF_VICARE_POLL_INTERVAL: 90}).setup()  # must not fail
        platforms.refresh()

    warnings = [r for r in caplog.records if "cannot be changed" in r.getMessage()]
    assert len(warnings) == 1
    if broken != "interval_not_timedelta":
        assert coordinator.update_interval == timedelta(seconds=60)
    if broken != "no_cache_duration":
        assert service._cacheDuration == 60
    # The sensors work regardless.
    assert platforms.sensor("messages").available


def test_device_without_coordinator_is_skipped() -> None:
    hass, _ = fakes.make_hass()
    coordinator, _ = builtin(hass)
    fakes.vicare_entry(hass).runtime_data.devices[0].coordinator = None
    Platforms(hass, {CONF_VICARE_POLL_INTERVAL: 90}).setup()
    assert coordinator.update_interval == timedelta(seconds=60)
    assert polling.builtin_interval_seconds(hass) is None


def test_vicare_not_loaded() -> None:
    hass, _ = fakes.make_hass()
    fakes.vicare_entry(hass).state = ConfigEntryState.NOT_LOADED
    PollIntervalManager(90).apply(hass)  # nothing to do, no error
    assert polling.builtin_interval_seconds(hass) is None


@pytest.mark.parametrize(
    ("options", "expected"),
    [({}, 60), ({CONF_VICARE_POLL_INTERVAL: 90.0}, 90), ({CONF_VICARE_POLL_INTERVAL: 5}, 60),
     ({CONF_VICARE_POLL_INTERVAL: 5000}, 900), ({CONF_VICARE_POLL_INTERVAL: "x"}, 60), ({CONF_VICARE_POLL_INTERVAL: True}, 60)],
)
def test_option_values_are_clamped(options, expected) -> None:
    hass, _ = fakes.make_hass()
    coordinator, _ = builtin(hass)
    Platforms(hass, options).setup()
    assert coordinator.update_interval == timedelta(seconds=expected)


@pytest.mark.parametrize(
    ("option", "mirror"),
    [(60, 55), (90, 85), (120, 115), (125, 120), (300, 120), (900, 120)],
)
def test_mirror_follows_the_builtin_interval_up_to_two_minutes(option, mirror) -> None:
    """Looking is free: the entities must not lag far behind a slow poll."""
    hass, _ = fakes.make_hass()
    coordinator, _ = builtin(hass)
    platforms = Platforms(hass, {CONF_VICARE_POLL_INTERVAL: option}).setup()
    assert coordinator.update_interval == timedelta(seconds=option)
    assert platforms.coordinator.update_interval == timedelta(seconds=mirror)
    # Never the same period as the built-in integration (no phase lock).
    assert platforms.coordinator.update_interval < coordinator.update_interval


# ----------------------------------------------------------------- options flow


def options_flow(options: dict) -> config_flow.ViCareExtrasOptionsFlow:
    entry = ConfigEntry(domain="vicare_extras", entry_id="extras")
    entry.options = options
    flow = config_flow.ViCareExtrasConfigFlow.async_get_options_flow(entry)
    flow.config_entry = entry  # provided by Home Assistant
    return flow


def test_options_flow_shows_the_current_value() -> None:
    flow = options_flow({CONF_VICARE_POLL_INTERVAL: 90})
    result = asyncio.run(flow.async_step_init())
    assert result["type"] == "form"
    assert result["step_id"] == "init"
    assert flow.suggested_values == {CONF_VICARE_POLL_INTERVAL: 90}
    schema = result["data_schema"]
    assert schema({}) == {}  # the field is optional
    assert schema({CONF_VICARE_POLL_INTERVAL: 90}) == {CONF_VICARE_POLL_INTERVAL: 90}
    for invalid in (59, 901, "x"):
        with pytest.raises(Exception):  # noqa: B017, PT011 - any validation error
            schema({CONF_VICARE_POLL_INTERVAL: invalid})


@pytest.mark.parametrize(
    ("user_input", "stored"),
    [
        ({CONF_VICARE_POLL_INTERVAL: 90.0}, {CONF_VICARE_POLL_INTERVAL: 90}),  # the UI sends floats
        ({CONF_VICARE_POLL_INTERVAL: 600}, {CONF_VICARE_POLL_INTERVAL: 600}),
        ({}, {}),  # field emptied: the option is removed
        ({CONF_VICARE_POLL_INTERVAL: None}, {}),
    ],
)
def test_options_flow_sets_and_clears(user_input, stored) -> None:
    flow = options_flow({CONF_VICARE_POLL_INTERVAL: 120})
    result = asyncio.run(flow.async_step_init(user_input))
    assert result == {"type": "create_entry", "data": stored}
    assert isinstance(flow, config_flow.OptionsFlowWithReload)  # saving reloads the entry

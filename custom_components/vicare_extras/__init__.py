"""ViCare Extras: more data from an existing Viessmann ViCare setup.

Companion of Home Assistant's built-in ``vicare`` integration. It reuses the
PyViCare client the built-in integration has authenticated (through the
``runtime_data`` of the loaded ``vicare`` config entry) and never performs an
API request on its own schedule.

Sensors, binary sensors and the actions ``get_features`` and
``get_event_history`` are read-only. The climate entities (rooms, radiator
thermostats) send a command only when the user changes a target temperature,
and the admin-only action ``send_command`` posts one command as given. The
optional poll interval changes how often the built-in integration polls.
"""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from . import messages
from .const import DOMAIN
from .coordinator import ViCareExtrasConfigEntry, ViCareExtrasCoordinator
from .room_links import STORAGE_VERSION, storage_key
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.SENSOR,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration: load the message table, register the actions."""
    # Reads a file, so not in the event loop. Cached for all later lookups.
    await hass.async_add_executor_job(messages.load_table)
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ViCareExtrasConfigEntry) -> bool:
    """Set up ViCare Extras from a config entry.

    The first refresh raises ConfigEntryNotReady while the ``vicare`` entry is
    not loaded (or its data is not readable); Home Assistant then retries.
    """
    coordinator = ViCareExtrasCoordinator(hass, entry)
    # Put the poll interval of the built-in integration back on unload, which
    # also happens when the option is changed or cleared (the entry reloads).
    # Registered before the first refresh, which already applies the option:
    # Home Assistant also runs these callbacks when the setup fails.
    entry.async_on_unload(coordinator.poll_manager.restore)
    # The rooms of the thermostats learned before the last restart.
    await coordinator.room_links.async_load()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ViCareExtrasConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ViCareExtrasConfigEntry) -> None:
    """Delete the stored room assignment together with the config entry."""
    await Store(hass, STORAGE_VERSION, storage_key(entry.entry_id)).async_remove()

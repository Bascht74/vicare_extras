"""ViCare Extras: more data from an existing Viessmann ViCare setup.

Companion of Home Assistant's built-in ``vicare`` integration. It reuses the
PyViCare client the built-in integration has authenticated (through the
``runtime_data`` of the loaded ``vicare`` config entry) and is strictly
read-only: it never sends a command to the heating system and never performs
an API request on its own schedule.
"""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from . import messages
from .const import DOMAIN
from .coordinator import ViCareExtrasConfigEntry, ViCareExtrasCoordinator
from .services import async_setup_services

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

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
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ViCareExtrasConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

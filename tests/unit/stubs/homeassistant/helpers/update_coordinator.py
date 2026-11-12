"""Stub of homeassistant.helpers.update_coordinator."""

from typing import Generic, TypeVar

from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError

_T = TypeVar("_T")


class UpdateFailed(HomeAssistantError):
    pass


class DataUpdateCoordinator(Generic[_T]):
    def __init__(self, hass, logger, *, config_entry=None, name, update_interval=None):
        self.hass = hass
        self.logger = logger
        self.config_entry = config_entry
        self.name = name
        self.update_interval = update_interval
        self.data = None
        self.last_update_success = True
        self.last_exception = None
        self._listeners = []

    def async_add_listener(self, update_callback, context=None):
        self._listeners.append(update_callback)
        return lambda: self._listeners.remove(update_callback)

    async def _async_update_data(self):
        raise NotImplementedError

    async def async_refresh(self):
        try:
            self.data = await self._async_update_data()
        except UpdateFailed as err:
            self.last_exception = err
            self.last_update_success = False
        else:
            self.last_exception = None
            self.last_update_success = True
        for listener in list(self._listeners):
            listener()

    async def async_config_entry_first_refresh(self):
        await self.async_refresh()
        if not self.last_update_success:
            raise ConfigEntryNotReady(str(self.last_exception))


class CoordinatorEntity(Generic[_T]):
    def __init__(self, coordinator, context=None):
        self.coordinator = coordinator

    @property
    def available(self):
        return self.coordinator.last_update_success

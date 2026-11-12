"""Stub of homeassistant.helpers.storage (kept in memory on the fake hass)."""


class Store:
    def __init__(self, hass, version, key):
        self.hass = hass
        self.version = version
        self.key = key

    def _files(self):
        return self.hass.data.setdefault("__storage__", {})

    async def async_load(self):
        return self._files().get(self.key)

    def async_delay_save(self, data_func, delay=0):
        # Written at once: the tests do not wait.
        self._files()[self.key] = data_func()

    async def async_remove(self):
        self._files().pop(self.key, None)

"""Stub of homeassistant.helpers.entity (only what the tests read)."""


class Entity:
    hass = None
    state_writes = 0
    entity_description = None
    device_entry = None
    _attr_device_class = None
    _attr_device_info = None
    _attr_entity_category = None
    _attr_entity_registry_enabled_default = True
    _attr_has_entity_name = False
    _attr_translation_key = None
    _attr_translation_placeholders = None
    _attr_unique_id = None

    @property
    def device_class(self):
        return self._attr_device_class

    @property
    def device_info(self):
        return self._attr_device_info

    @property
    def entity_category(self):
        return self._attr_entity_category

    @property
    def entity_registry_enabled_default(self):
        return self._attr_entity_registry_enabled_default

    @property
    def translation_key(self):
        return self._attr_translation_key

    @property
    def translation_placeholders(self):
        return self._attr_translation_placeholders or {}

    @property
    def unique_id(self):
        return self._attr_unique_id

    def async_write_ha_state(self):
        self.state_writes += 1

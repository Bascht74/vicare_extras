"""Stub of homeassistant.config_entries."""

from enum import Enum
from typing import Any, Generic, TypeVar

_T = TypeVar("_T")
ConfigFlowResult = dict[str, Any]


class ConfigEntryState(Enum):
    LOADED = "loaded"
    NOT_LOADED = "not_loaded"
    SETUP_RETRY = "setup_retry"


class ConfigEntry(Generic[_T]):
    def __init__(self, domain="test", entry_id="entry", state=ConfigEntryState.LOADED):
        self.domain = domain
        self.entry_id = entry_id
        self.state = state
        self.runtime_data = None
        self.options = {}
        self._on_unload = []

    def async_on_unload(self, func):
        self._on_unload.append(func)


class ConfigFlow:
    VERSION = 1

    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.domain = domain

    def __init__(self):
        self._current_entries = []

    def _async_current_entries(self):
        return self._current_entries

    def async_abort(self, *, reason, **kwargs):
        return {"type": "abort", "reason": reason}

    def async_show_form(self, *, step_id, data_schema=None, **kwargs):
        return {"type": "form", "step_id": step_id, "data_schema": data_schema}

    def async_create_entry(self, *, title, data, **kwargs):
        return {"type": "create_entry", "title": title, "data": data}


class OptionsFlow:
    def __init__(self):
        self.config_entry = None

    def add_suggested_values_to_schema(self, data_schema, suggested_values):
        self.suggested_values = dict(suggested_values or {})
        return data_schema

    def async_show_form(self, *, step_id, data_schema=None, **kwargs):
        return {"type": "form", "step_id": step_id, "data_schema": data_schema}

    def async_create_entry(self, *, data, **kwargs):
        return {"type": "create_entry", "data": data}


class OptionsFlowWithReload(OptionsFlow):
    automatic_reload = True

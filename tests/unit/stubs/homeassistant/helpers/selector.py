"""Stub of homeassistant.helpers.selector."""

from enum import StrEnum

import voluptuous as vol


class NumberSelectorMode(StrEnum):
    BOX = "box"
    SLIDER = "slider"


class NumberSelectorConfig(dict):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class NumberSelector:
    def __init__(self, config=None):
        self.config = config or {}

    def __call__(self, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise vol.Invalid("expected a number")
        if "min" in self.config and value < self.config["min"]:
            raise vol.Invalid("value too small")
        if "max" in self.config and value > self.config["max"]:
            raise vol.Invalid("value too large")
        return value

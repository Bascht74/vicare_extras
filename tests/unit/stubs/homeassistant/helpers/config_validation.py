"""Stub of homeassistant.helpers.config_validation."""

import voluptuous as vol


def string(value):
    if value is None or isinstance(value, (dict, list)):
        raise vol.Invalid("expected a string")
    return str(value)


def boolean(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false", "on", "off", "1", "0"):
        return value.lower() in ("true", "on", "1")
    raise vol.Invalid("expected a boolean")


def config_entry_only_config_schema(domain):
    return lambda config: config

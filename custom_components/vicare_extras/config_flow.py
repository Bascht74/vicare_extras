"""Config flow for ViCare Extras.

Setup: a single instance without any input.
Options: the optional poll interval of the built-in vicare integration.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_VICARE_POLL_INTERVAL,
    DOMAIN,
    MAX_VICARE_POLL_INTERVAL,
    MIN_VICARE_POLL_INTERVAL,
)

OPTIONS_SCHEMA = vol.Schema(
    {
        # Optional and without default: an empty field removes the option.
        vol.Optional(CONF_VICARE_POLL_INTERVAL): NumberSelector(
            NumberSelectorConfig(
                min=MIN_VICARE_POLL_INTERVAL,
                max=MAX_VICARE_POLL_INTERVAL,
                step=1,
                unit_of_measurement="s",
                mode=NumberSelectorMode.BOX,
            )
        ),
    }
)


class ViCareExtrasConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ViCareExtrasOptionsFlow:
        """Return the options flow."""
        return ViCareExtrasOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm and create the single entry."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is None:
            return self.async_show_form(step_id="user")
        return self.async_create_entry(title="ViCare Extras", data={})


class ViCareExtrasOptionsFlow(OptionsFlowWithReload):
    """Options: poll interval of the built-in vicare integration.

    Saving reloads the config entry (``OptionsFlowWithReload``). Unloading
    restores the original interval, setting up applies the new one, so both
    setting and clearing the option take effect without a restart.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form, or store the options."""
        if user_input is not None:
            options: dict[str, Any] = {}
            value = user_input.get(CONF_VICARE_POLL_INTERVAL)
            if value is not None:
                options[CONF_VICARE_POLL_INTERVAL] = int(value)
            return self.async_create_entry(data=options)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )

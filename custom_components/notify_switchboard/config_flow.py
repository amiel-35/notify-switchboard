"""Config flow for Notify Switchboard.

Setup takes no input: a single instance registers `notify.switchboard` and
its entity. Which `notify.*` services receive proxied messages is configured
afterwards through the options flow, as a comma-separated list of service
names (e.g. `notify.mobile_app_amiel, notify.persistent_notification`).
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .const import CONF_DEFAULT_TARGETS, DEFAULT_TARGETS, DOMAIN

TITLE = "Notify Switchboard"


def _targets_to_string(targets: list[str]) -> str:
    """Render a list of service names as a comma-separated string."""
    return ", ".join(targets)


def _string_to_targets(value: str) -> list[str]:
    """Parse a comma-separated string into a list of service names."""
    return [part.strip() for part in value.split(",") if part.strip()]


class SwitchboardConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Notify Switchboard."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the single setup step: create the one allowed entry.

        There is nothing to configure at this stage (targets are set up
        afterwards through the options flow), so the entry is created
        immediately rather than showing an empty form.
        """
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        return self.async_create_entry(title=TITLE, data={})

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> SwitchboardOptionsFlow:
        """Return the options flow for this handler."""
        return SwitchboardOptionsFlow()


class SwitchboardOptionsFlow(OptionsFlow):
    """Handle options for Notify Switchboard: the default target list."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the default targets option."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_DEFAULT_TARGETS: _string_to_targets(
                        user_input[CONF_DEFAULT_TARGETS]
                    )
                }
            )

        current = self.config_entry.options.get(CONF_DEFAULT_TARGETS, DEFAULT_TARGETS)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DEFAULT_TARGETS,
                    default=_targets_to_string(current),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

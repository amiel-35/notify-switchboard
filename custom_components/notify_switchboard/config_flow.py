"""Config and options flows for Notify Switchboard.

Setup takes no input: a single instance is created, then the whole routing
table is edited through the options flow (doctrine §5: config flow and options
flow only, no custom panel). The full row is validated before anything is
written back to `entry.options`.
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
from homeassistant.helpers import selector

from .const import (
    CONF_ALERT_ENTITY,
    CONF_ALLOW_ACKNOWLEDGE,
    CONF_AUDIENCE,
    CONF_CLASS,
    CONF_DEFAULT_DATA,
    CONF_DEFAULT_PRIORITY,
    CONF_DEFAULT_TARGET,
    CONF_OBSERVER_MODE,
    CONF_OUTPUTS,
    CONF_PERSONS,
    CONF_PRESENCE_RULE,
    CONF_SILENCE_ENTITIES,
    CONF_SLUG,
    CONF_SNOOZE_MINUTES,
    CONF_TARGETS,
    CONF_WAKE_TIME,
    DEFAULT_PRESENCE_RULE,
    DEFAULT_PRIORITY,
    DOMAIN,
    VALID_PRESENCE_RULES,
    VALID_PRIORITIES,
)
from .validation import parse_snooze_minutes, validate_person, validate_target

TITLE = "Notify Switchboard"


def _empty_options() -> dict[str, Any]:
    """Return the options of a freshly created entry."""
    return {CONF_PERSONS: [], CONF_TARGETS: [], CONF_DEFAULT_TARGET: None}


class SwitchboardConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Notify Switchboard."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the single allowed entry; the table is set up in options."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        return self.async_create_entry(title=TITLE, data={}, options=_empty_options())

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SwitchboardOptionsFlow:
        """Return the options flow for this handler."""
        return SwitchboardOptionsFlow()


class SwitchboardOptionsFlow(OptionsFlow):
    """Edit the routing table: persons, targets, default target."""

    def __init__(self) -> None:
        """Start from an empty working copy; it is filled on the first step."""
        self._options: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def _persons(self) -> list[dict[str, Any]]:
        return list(self._options.get(CONF_PERSONS) or [])

    @property
    def _targets(self) -> list[dict[str, Any]]:
        return list(self._options.get(CONF_TARGETS) or [])

    def _load(self) -> None:
        """Take a working copy of the stored options."""
        if not self._options:
            stored = dict(self.config_entry.options or {})
            self._options = {
                CONF_PERSONS: [dict(row) for row in stored.get(CONF_PERSONS) or []],
                CONF_TARGETS: [dict(row) for row in stored.get(CONF_TARGETS) or []],
                CONF_DEFAULT_TARGET: stored.get(CONF_DEFAULT_TARGET),
            }

    def _save(self) -> ConfigFlowResult:
        """Write the whole validated table back at once."""
        targets = self._targets
        slugs = [row[CONF_SLUG] for row in targets]
        default_target = self._options.get(CONF_DEFAULT_TARGET)
        if default_target not in slugs:
            default_target = slugs[0] if slugs else None
        self._options[CONF_DEFAULT_TARGET] = default_target
        return self.async_create_entry(data=self._options)

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options menu."""
        self._load()
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "person",
                "remove_person",
                "target",
                "remove_target",
                "general",
            ],
        )

    # ------------------------------------------------------------------
    # Persons
    # ------------------------------------------------------------------

    async def async_step_person(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add or update one person."""
        self._load()
        errors: dict[str, str] = {}

        if user_input is not None:
            row = {
                "entity_id": user_input["entity_id"],
                CONF_OUTPUTS: [
                    output.strip()
                    for output in user_input.get(CONF_OUTPUTS) or []
                    if output.strip()
                ],
                CONF_SILENCE_ENTITIES: list(
                    user_input.get(CONF_SILENCE_ENTITIES) or []
                ),
                CONF_WAKE_TIME: user_input.get(CONF_WAKE_TIME) or None,
            }
            persons = self._persons
            is_new = not any(
                other["entity_id"] == row["entity_id"] for other in persons
            )
            errors = validate_person(row, persons, is_new=is_new)
            if not errors:
                persons = [
                    other for other in persons if other["entity_id"] != row["entity_id"]
                ]
                persons.append(row)
                self._options[CONF_PERSONS] = persons
                return self._save()

        schema = vol.Schema(
            {
                vol.Required("entity_id"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="person")
                ),
                vol.Required(CONF_OUTPUTS, default=[]): selector.TextSelector(
                    selector.TextSelectorConfig(multiple=True)
                ),
                vol.Optional(
                    CONF_SILENCE_ENTITIES, default=[]
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["schedule", "input_boolean", "binary_sensor"],
                        multiple=True,
                    )
                ),
                vol.Optional(CONF_WAKE_TIME): selector.TimeSelector(
                    selector.TimeSelectorConfig()
                ),
            }
        )
        return self.async_show_form(step_id="person", data_schema=schema, errors=errors)

    async def async_step_remove_person(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove one person from the table."""
        self._load()
        persons = self._persons
        if not persons:
            return self.async_abort(reason="nothing_to_remove")

        if user_input is not None:
            entity_id = user_input["entity_id"]
            self._options[CONF_PERSONS] = [
                row for row in persons if row["entity_id"] != entity_id
            ]
            self._options[CONF_TARGETS] = [
                {
                    **row,
                    CONF_AUDIENCE: [
                        person
                        for person in row.get(CONF_AUDIENCE) or []
                        if person != entity_id
                    ],
                }
                for row in self._targets
            ]
            return self._save()

        schema = vol.Schema(
            {
                vol.Required("entity_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[row["entity_id"] for row in persons]
                    )
                )
            }
        )
        return self.async_show_form(step_id="remove_person", data_schema=schema)

    # ------------------------------------------------------------------
    # Targets
    # ------------------------------------------------------------------

    async def async_step_target(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add or update one routing-table row."""
        self._load()
        errors: dict[str, str] = {}
        persons = self._persons
        known_persons = [row["entity_id"] for row in persons]

        if user_input is not None:
            minutes, _ok = parse_snooze_minutes(user_input.get(CONF_SNOOZE_MINUTES))
            row = {
                CONF_SLUG: user_input[CONF_SLUG],
                "name": user_input.get("name") or user_input[CONF_SLUG],
                CONF_CLASS: user_input.get(CONF_CLASS) or "",
                CONF_DEFAULT_PRIORITY: user_input.get(
                    CONF_DEFAULT_PRIORITY, DEFAULT_PRIORITY
                ),
                CONF_ALERT_ENTITY: user_input.get(CONF_ALERT_ENTITY) or None,
                CONF_AUDIENCE: list(user_input.get(CONF_AUDIENCE) or []),
                CONF_PRESENCE_RULE: user_input.get(
                    CONF_PRESENCE_RULE, DEFAULT_PRESENCE_RULE
                ),
                CONF_ALLOW_ACKNOWLEDGE: bool(user_input.get(CONF_ALLOW_ACKNOWLEDGE)),
                CONF_SNOOZE_MINUTES: minutes,
                CONF_DEFAULT_DATA: dict(user_input.get(CONF_DEFAULT_DATA) or {}),
                CONF_OBSERVER_MODE: bool(user_input.get(CONF_OBSERVER_MODE)),
            }
            # Re-read the raw value so an unparsable duration is reported.
            row_for_validation = dict(row)
            row_for_validation[CONF_SNOOZE_MINUTES] = user_input.get(
                CONF_SNOOZE_MINUTES
            )
            targets = self._targets
            is_new = not any(other[CONF_SLUG] == row[CONF_SLUG] for other in targets)
            errors = validate_target(
                row_for_validation, targets, known_persons, is_new=is_new
            )
            if not errors:
                targets = [
                    other for other in targets if other[CONF_SLUG] != row[CONF_SLUG]
                ]
                targets.append(row)
                self._options[CONF_TARGETS] = targets
                return self._save()

        schema = vol.Schema(
            {
                vol.Required(CONF_SLUG): selector.TextSelector(
                    selector.TextSelectorConfig()
                ),
                vol.Required("name"): selector.TextSelector(
                    selector.TextSelectorConfig()
                ),
                vol.Optional(CONF_CLASS, default=""): selector.TextSelector(
                    selector.TextSelectorConfig()
                ),
                vol.Required(
                    CONF_DEFAULT_PRIORITY, default=DEFAULT_PRIORITY
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=list(VALID_PRIORITIES))
                ),
                vol.Optional(CONF_ALERT_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="alert")
                ),
                vol.Required(CONF_AUDIENCE, default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=known_persons, multiple=True)
                ),
                vol.Required(
                    CONF_PRESENCE_RULE, default=DEFAULT_PRESENCE_RULE
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=list(VALID_PRESENCE_RULES))
                ),
                vol.Optional(
                    CONF_ALLOW_ACKNOWLEDGE, default=False
                ): selector.BooleanSelector(),
                vol.Optional(CONF_SNOOZE_MINUTES, default=""): selector.TextSelector(
                    selector.TextSelectorConfig()
                ),
                vol.Optional(CONF_DEFAULT_DATA, default={}): selector.ObjectSelector(),
                vol.Optional(
                    CONF_OBSERVER_MODE, default=False
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="target", data_schema=schema, errors=errors)

    async def async_step_remove_target(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove one routing-table row."""
        self._load()
        targets = self._targets
        if not targets:
            return self.async_abort(reason="nothing_to_remove")

        if user_input is not None:
            slug = user_input[CONF_SLUG]
            self._options[CONF_TARGETS] = [
                row for row in targets if row[CONF_SLUG] != slug
            ]
            return self._save()

        schema = vol.Schema(
            {
                vol.Required(CONF_SLUG): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[row[CONF_SLUG] for row in targets]
                    )
                )
            }
        )
        return self.async_show_form(step_id="remove_target", data_schema=schema)

    # ------------------------------------------------------------------
    # General
    # ------------------------------------------------------------------

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the target used by `notify.switchboard` without a target."""
        self._load()
        targets = self._targets
        if not targets:
            return self.async_abort(reason="nothing_to_configure")

        if user_input is not None:
            self._options[CONF_DEFAULT_TARGET] = user_input[CONF_DEFAULT_TARGET]
            return self._save()

        current = self._options.get(CONF_DEFAULT_TARGET) or targets[0][CONF_SLUG]
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DEFAULT_TARGET, default=current
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[row[CONF_SLUG] for row in targets]
                    )
                )
            }
        )
        return self.async_show_form(step_id="general", data_schema=schema)

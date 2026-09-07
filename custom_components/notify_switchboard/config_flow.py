"""Config and options flows for Notify Switchboard.

Setup takes no input: a single instance is created, then the whole routing
table is edited through the options flow (doctrine §5: config flow and options
flow only, no custom panel). The full row is validated before anything is
written back to `entry.options`.

From 0.4.0 (ADR-0018) the flow also *discovers*, *bootstraps* and *tests*:

- the person editor is two steps, `person` then `person_outputs`, because a
  form cannot react to a field it is showing and the outputs offered depend on
  which person was chosen;
- `person_outputs` lists the instance's own `notify.*` services, puts the ones
  belonging to this person's Companion registrations first and pre-selects them
  together with their iOS Focus sensors;
- the first person added to an empty routing table creates the managed
  `default` row and points `default_target` at it, so `notify.switchboard`
  works without anybody writing a row by hand;
- the row editor ends on `target_saved`, which shows the `alert:` block to
  paste;
- `test_person` / `test_target` send one real message and show the `explain`
  answer for it.

Home Assistant APIs used here (paths in home-assistant/core 2026.9.1):
- homeassistant/helpers/selector.py: SelectSelector / SelectSelectorConfig
  (line 1883, `custom_value` and `sort`), SelectOptionDict (line 1869),
  EntitySelector / EntitySelectorConfig (line 1063), TimeSelector, TextSelector
- homeassistant/core.py: `ServiceRegistry.async_services_for_domain` (line 2647)
- homeassistant/components/mobile_app/const.py: `CONF_USER_ID` (line 17),
  `ATTR_DEVICE_NAME` (line 34) -- the two keys a Companion registration stores
  in its config entry (`mobile_app/config_flow.py`)
- homeassistant/components/person/const.py: the `user_id` state attribute a
  `person.*` publishes (`person/__init__.py`, `PersonEntityStateAttribute`)
- homeassistant/helpers/entity_registry.py: `async_entries_for_config_entry`
- homeassistant/helpers/translation.py: `async_get_translations`
- homeassistant/data_entry_flow.py: `add_suggested_values_to_schema` (line 668),
  `async_show_form(..., description_placeholders=...)`
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components.notify.const import (
    SERVICE_NOTIFY,
    SERVICE_PERSISTENT_NOTIFICATION,
    SERVICE_SEND_MESSAGE,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, selector
from homeassistant.helpers.translation import async_get_translations

from .const import (
    ATTR_USER_ID,
    CONF_ALERT_ENTITY,
    CONF_ALLOW_ACKNOWLEDGE,
    CONF_AUDIENCE,
    CONF_CLASS,
    CONF_DEFAULT_DATA,
    CONF_DEFAULT_PRIORITY,
    CONF_DEFAULT_TARGET,
    CONF_DEFAULT_TITLE,
    CONF_DONE_MESSAGE,
    CONF_MANAGED,
    CONF_MESSAGE,
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
    DEFAULT_TARGET_CLASS,
    DEFAULT_TARGET_SLUG,
    DOMAIN,
    LEGACY_SERVICE_NAME,
    VALID_PRESENCE_RULES,
    VALID_PRIORITIES,
)
from .dispatcher import companion_service_name
from .router import is_recursive_output
from .validation import parse_snooze_minutes, validate_person, validate_target

if TYPE_CHECKING:
    from .dispatcher import Switchboard

TITLE = "Notify Switchboard"

NOTIFY_DOMAIN = "notify"
MOBILE_APP_DOMAIN = "mobile_app"
BINARY_SENSOR_DOMAIN = "binary_sensor"

# The `mobile_app` config-entry data keys the discovery follows. Spelled out
# rather than imported so the integration keeps no dependency on `mobile_app`,
# exactly as `ATTR_USER_ID` already is for `person` (see `const.py`); the paths
# in the module docstring are what makes them auditable.
MOBILE_APP_USER_ID = "user_id"
MOBILE_APP_DEVICE_NAME = "device_name"

# iOS registers its Focus sensor per device; ADR-0018 §3 matches it on the
# entity id **or** on the entity-registry translation key, because the
# Companion app supplies one or the other depending on its version.
FOCUS_MARKER = "focus"

# The three services the `notify` component itself owns
# (`homeassistant/components/notify/const.py`): the aggregate legacy service,
# the `NotifyEntity` action, and the built-in "write it on the dashboard" one.
# None of them is a person's device, and offering `send_message` as an output
# would be a plain bug -- it is an entity action and takes no bare `message`.
# They stay typable thanks to `custom_value`.
NOTIFY_COMPONENT_SERVICES = frozenset(
    {SERVICE_NOTIFY, SERVICE_SEND_MESSAGE, SERVICE_PERSISTENT_NOTIFICATION}
)

KEY_THIS_PERSONS_DEVICE = f"component.{DOMAIN}.common.this_persons_device"
KEY_DEFAULT_TARGET_NAME = f"component.{DOMAIN}.common.default_target_name"
FALLBACK_THIS_PERSONS_DEVICE = "this person's device"
FALLBACK_DEFAULT_TARGET_NAME = "Everybody"

# The `alert:` block `target_saved` offers (ADR-0018 §7). `notifiers:` wants the
# legacy service name without its `notify.` prefix, which is exactly what
# `TargetConfig.service_name` composes; `entity_id` is the one thing the router
# cannot know, so it is left as an obvious placeholder.
ALERT_SNIPPET_ENTITY_PLACEHOLDER = "binary_sensor.CHANGE_ME"


def _empty_options() -> dict[str, Any]:
    """Return the options of a freshly created entry."""
    return {CONF_PERSONS: [], CONF_TARGETS: [], CONF_DEFAULT_TARGET: None}


@callback
def _person_user_id(hass: HomeAssistant, person_entity_id: str) -> str | None:
    """Return the Home Assistant user a `person.*` is linked to, if any."""
    state = hass.states.get(person_entity_id)
    if state is None:
        return None
    user_id = state.attributes.get(ATTR_USER_ID)
    return str(user_id) if user_id else None


@callback
def _companion_entries(hass: HomeAssistant, person_entity_id: str) -> list[ConfigEntry]:
    """Return the `mobile_app` registrations belonging to that person.

    The link is an equality between two stored ids, not a name heuristic:
    guessing `mobile_app_<person object id>` is what ADR-0018 §2 rejects, and
    what a household with two phones per person breaks immediately.
    """
    user_id = _person_user_id(hass, person_entity_id)
    if not user_id:
        return []
    return [
        entry
        for entry in hass.config_entries.async_entries(MOBILE_APP_DOMAIN)
        if entry.data.get(MOBILE_APP_USER_ID) == user_id
    ]


@callback
def _discovered_outputs(hass: HomeAssistant, person_entity_id: str) -> list[str]:
    """Return the legacy push services of that person's phones.

    A registration without push produces no service, so a name that is not
    actually registered is left out rather than offered and silently dropped.
    """
    services = hass.services.async_services_for_domain(NOTIFY_DOMAIN)
    outputs: list[str] = []
    for entry in _companion_entries(hass, person_entity_id):
        device_name = entry.data.get(MOBILE_APP_DEVICE_NAME)
        if not device_name:
            continue
        service = companion_service_name(str(device_name))
        if service in services and service not in outputs:
            outputs.append(service)
    return outputs


@callback
def _discovered_focus_sensors(hass: HomeAssistant, person_entity_id: str) -> list[str]:
    """Return the Focus `binary_sensor`s of that person's phones (ADR-0018 §3).

    Android's "Do Not Disturb" is deliberately not proposed: it is a `sensor`
    with several string states, and this integration's silence contract is
    "state is `on`". `docs/quickstart.md` shows the one-line template
    `binary_sensor` that bridges it.
    """
    registry = er.async_get(hass)
    found: list[str] = []
    for entry in _companion_entries(hass, person_entity_id):
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
            if entity.domain != BINARY_SENSOR_DOMAIN:
                continue
            haystacks = (entity.entity_id, entity.translation_key or "")
            if any(FOCUS_MARKER in haystack for haystack in haystacks):
                found.append(entity.entity_id)
    return sorted(found)


@callback
def _output_options(
    hass: HomeAssistant, owned: list[str], marker: str
) -> list[selector.SelectOptionDict]:
    """Build the `outputs` option list: this person's phones first, labelled.

    `sort` is left at its default `False` on the selector so the frontend keeps
    this order; it is the whole point of the list.
    """
    available = sorted(
        service
        for service in hass.services.async_services_for_domain(NOTIFY_DOMAIN)
        if not is_recursive_output(service) and service not in NOTIFY_COMPONENT_SERVICES
    )
    first = [service for service in owned if service in available]
    rest = [service for service in available if service not in first]
    return [
        selector.SelectOptionDict(value=service, label=f"{service} ({marker})")
        for service in first
    ] + [selector.SelectOptionDict(value=service, label=service) for service in rest]


def _alert_snippet(row: dict[str, Any]) -> str:
    """Return the ready-to-paste `alert:` block for one routing-table row."""
    alert_entity = row.get(CONF_ALERT_ENTITY)
    object_id = (
        str(alert_entity).partition(".")[2] if alert_entity else str(row[CONF_SLUG])
    )
    acknowledge = "true" if row.get(CONF_ALLOW_ACKNOWLEDGE) else "false"
    return "\n".join(
        (
            "alert:",
            f"  {object_id}:",
            f"    name: {row.get('name') or row[CONF_SLUG]}",
            f"    entity_id: {ALERT_SNIPPET_ENTITY_PLACEHOLDER}",
            '    state: "on"',
            "    repeat: [5, 15, 60]",
            f"    can_acknowledge: {acknowledge}",
            "    notifiers:",
            f"      - {LEGACY_SERVICE_NAME}_{row[CONF_SLUG]}",
        )
    )


def _explain_summary(response: dict[str, Any]) -> str:
    """Render an `explain` response as one line per person."""
    return "\n".join(
        f"{person}: {answer['decision']} - {answer['detail']}"
        for person, answer in sorted(response["persons"].items())
    )


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
        # Set by `person` / `edit_person` / `edit_target` so the form that
        # follows opens on the right row instead of on an empty one.
        self._editing_person: str | None = None
        self._editing_slug: str | None = None
        # A validated routing-table row waiting for `target_saved` to be
        # submitted: nothing is written to `entry.options` until it is
        # (ADR-0018 §7).
        self._pending_target: dict[str, Any] | None = None
        # The `explain` summary of the message the test step has just sent.
        self._test_result: str | None = None

    @property
    def _switchboard(self) -> Switchboard | None:
        """Return the loaded entry's `Switchboard`, or None when unloaded.

        The test steps route a real message and then ask `explain`; both need
        the running router, which a disabled or failed entry does not have.
        """
        entry = self.config_entry
        if entry.state is not ConfigEntryState.LOADED:
            return None
        return entry.runtime_data.switchboard  # type: ignore[no-any-return]

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
        """Write the whole validated table back at once.

        Every write is also where a `managed` row's audience is refreshed
        (ADR-0018 §4): while the flag is true that audience is *every*
        configured person, so adding somebody adds them to the default target
        without anybody having to remember to. Submitting the row editor writes
        the row without the flag, which ends the arrangement for good -- a table
        that silently re-adds a person the user has just removed is worse than
        no automation at all.
        """
        self._async_sync_managed_audiences()
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
                "edit_person",
                "remove_person",
                "target",
                "edit_target",
                "remove_target",
                "general",
                "test_person",
                "test_target",
            ],
        )

    # ------------------------------------------------------------------
    # The managed `default` row (ADR-0018 §4)
    # ------------------------------------------------------------------

    @callback
    def _async_sync_managed_audiences(self) -> None:
        """Rewrite the audience of every `managed` row to every person."""
        everybody = [row["entity_id"] for row in self._persons]
        self._options[CONF_TARGETS] = [
            {**row, CONF_AUDIENCE: list(everybody)} if row.get(CONF_MANAGED) else row
            for row in self._targets
        ]

    async def _async_bootstrap_default_target(self) -> None:
        """Create the `default` row the first time a person meets an empty table.

        Up to 0.3.0 a fresh install had an empty routing table, so
        `notify.switchboard` resolved to no target and did nothing at all until
        the user had invented a slug, a name, a class, a priority, an audience
        and a presence rule. This is the one row that removes all of that -- and
        only that: the row exists to bootstrap an empty table, never to add
        itself to a table somebody has already built.
        """
        if self._targets or not self._persons:
            return
        translations = await async_get_translations(
            self.hass, self.hass.config.language, "common", {DOMAIN}
        )
        name = translations.get(KEY_DEFAULT_TARGET_NAME) or FALLBACK_DEFAULT_TARGET_NAME
        self._options[CONF_TARGETS] = [
            {
                CONF_SLUG: DEFAULT_TARGET_SLUG,
                "name": name,
                CONF_CLASS: DEFAULT_TARGET_CLASS,
                CONF_DEFAULT_PRIORITY: DEFAULT_PRIORITY,
                CONF_ALERT_ENTITY: None,
                CONF_AUDIENCE: [row["entity_id"] for row in self._persons],
                CONF_PRESENCE_RULE: DEFAULT_PRESENCE_RULE,
                CONF_ALLOW_ACKNOWLEDGE: False,
                CONF_SNOOZE_MINUTES: [],
                CONF_DEFAULT_DATA: {},
                CONF_OBSERVER_MODE: False,
                CONF_MESSAGE: None,
                CONF_DONE_MESSAGE: None,
                CONF_DEFAULT_TITLE: None,
                CONF_MANAGED: True,
            }
        ]
        self._options[CONF_DEFAULT_TARGET] = DEFAULT_TARGET_SLUG

    # ------------------------------------------------------------------
    # Pre-filling an existing row
    # ------------------------------------------------------------------

    def _stored_person(self) -> dict[str, Any] | None:
        """Return the stored row of the person being edited, if there is one."""
        if self._editing_person is None:
            return None
        for row in self._persons:
            if row["entity_id"] == self._editing_person:
                return row
        return None

    def _suggested_person_outputs(self) -> dict[str, Any]:
        """Return what `person_outputs` opens on.

        The stored row wins over discovery whenever there is one: discovery
        must never silently re-add an output somebody removed (ADR-0018 §2).
        For a **new** person there is nothing stored, so the phones registered
        to their Home Assistant user and those phones' Focus sensors are
        pre-selected -- which is the whole point of the sprint, one form already
        filled in.
        """
        stored = self._stored_person()
        if stored is not None:
            return {
                key: value
                for key, value in stored.items()
                if key != "entity_id" and value not in (None, [])
            }
        person_id = self._editing_person or ""
        return {
            CONF_OUTPUTS: _discovered_outputs(self.hass, person_id),
            CONF_SILENCE_ENTITIES: _discovered_focus_sensors(self.hass, person_id),
        }

    def _suggested_target(self) -> dict[str, Any] | None:
        """Return the stored values of the target row being edited.

        `snooze_minutes` is stored as a list of integers but edited as the
        comma-separated text `parse_snooze_minutes` reads back, so it is
        rendered here rather than handed over raw — a suggested value is put
        straight into the field the user sees.
        """
        if self._editing_slug is None:
            return None
        for row in self._targets:
            if row[CONF_SLUG] != self._editing_slug:
                continue
            suggested = {
                key: value for key, value in row.items() if value not in (None, [])
            }
            suggested[CONF_AUDIENCE] = list(row.get(CONF_AUDIENCE) or [])
            suggested[CONF_SNOOZE_MINUTES] = ", ".join(
                str(minutes) for minutes in row.get(CONF_SNOOZE_MINUTES) or []
            )
            return suggested
        return None

    # ------------------------------------------------------------------
    # Persons
    # ------------------------------------------------------------------

    async def async_step_person(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the person; the outputs are chosen in the next step.

        Splitting the editor is not cosmetic: a form cannot react to a field it
        is showing, so pre-selecting somebody's phones *requires* the person to
        have been chosen in an earlier step (ADR-0018 §2).
        """
        self._load()
        if user_input is not None:
            self._editing_person = str(user_input["entity_id"])
            return await self.async_step_person_outputs()

        # The selector is the guard: `EntitySelector` refuses an entity outside
        # the `person` domain before the step ever runs
        # (`homeassistant/helpers/selector.py`, `EntitySelector.__call__`), so
        # `validation.validate_person`'s `not_a_person` rule only ever has to
        # protect a hand-edited `.storage` file.
        schema = vol.Schema(
            {
                vol.Required("entity_id"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="person")
                )
            }
        )
        return self.async_show_form(step_id="person", data_schema=schema)

    async def async_step_person_outputs(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit one person's outputs, silence entities and wake time."""
        self._load()
        person_id = self._editing_person
        if person_id is None:  # pragma: no cover - unreachable from the UI
            return await self.async_step_person()

        errors: dict[str, str] = {}
        if user_input is not None:
            row = {
                "entity_id": person_id,
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
            is_new = not any(other["entity_id"] == person_id for other in persons)
            errors = validate_person(row, persons, is_new=is_new)
            # `entity_id` was settled by the previous step and is not a field
            # of this form, so an error on it would have nowhere to show.
            errors.pop("entity_id", None)
            if not errors:
                persons = [
                    other for other in persons if other["entity_id"] != person_id
                ]
                persons.append(row)
                self._options[CONF_PERSONS] = persons
                await self._async_bootstrap_default_target()
                return self._save()

        marker = await self._async_owned_device_marker()
        schema = vol.Schema(
            {
                vol.Required(CONF_OUTPUTS, default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_output_options(
                            self.hass,
                            _discovered_outputs(self.hass, person_id),
                            marker,
                        ),
                        multiple=True,
                        # A phone that has not registered yet, or an output
                        # created later, must still be typable -- that is the
                        # 0.1 behaviour this selector replaces (ADR-0018 §2).
                        custom_value=True,
                    )
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
        return self.async_show_form(
            step_id="person_outputs",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                user_input
                if user_input is not None
                else self._suggested_person_outputs(),
            ),
            errors=errors,
            description_placeholders={"person": person_id},
        )

    async def _async_owned_device_marker(self) -> str:
        """Return the translated "this person's device" option marker."""
        translations = await async_get_translations(
            self.hass, self.hass.config.language, "common", {DOMAIN}
        )
        return translations.get(KEY_THIS_PERSONS_DEVICE, FALLBACK_THIS_PERSONS_DEVICE)

    async def async_step_edit_person(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick which person to edit, then open their outputs form pre-filled."""
        self._load()
        persons = self._persons
        if not persons:
            return self.async_abort(reason="nothing_to_edit")

        if user_input is not None:
            self._editing_person = user_input["entity_id"]
            return await self.async_step_person_outputs()

        schema = vol.Schema(
            {
                vol.Required("entity_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[row["entity_id"] for row in persons]
                    )
                )
            }
        )
        return self.async_show_form(step_id="edit_person", data_schema=schema)

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
                # v0.2 addendum (ADR-0016). Absent stays absent: an empty text
                # field means "no override", not an empty message.
                CONF_MESSAGE: user_input.get(CONF_MESSAGE) or None,
                CONF_DONE_MESSAGE: user_input.get(CONF_DONE_MESSAGE) or None,
                CONF_DEFAULT_TITLE: user_input.get(CONF_DEFAULT_TITLE) or None,
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
                # Nothing is written yet: the confirmation step shows the
                # `alert:` block this row expects, and submitting *that* is what
                # writes `entry.options` (ADR-0018 §7). The row is rebuilt from
                # scratch here, without `managed`, which is exactly how editing
                # the default row takes ownership of it (ADR-0018 §4).
                self._pending_target = row
                return await self.async_step_target_saved()

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
                # `TemplateSelector.__call__` runs `cv.template`
                # (`homeassistant/helpers/selector.py`), so an unparsable
                # template is already refused by the schema and needs no rule
                # of its own in `validation.py`.
                vol.Optional(CONF_MESSAGE): selector.TemplateSelector(),
                vol.Optional(CONF_DONE_MESSAGE): selector.TemplateSelector(),
                vol.Optional(CONF_DEFAULT_TITLE): selector.TextSelector(
                    selector.TextSelectorConfig()
                ),
            }
        )
        # Same reasoning as `person`: the three v0.2 texts (`message`,
        # `done_message`, `default_title`) are exactly the fields somebody
        # comes back to tweak, and every other field of the row would otherwise
        # have to be retyped alongside them or be silently reset to its default.
        return self.async_show_form(
            step_id="target",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                user_input if user_input is not None else self._suggested_target(),
            ),
            errors=errors,
        )

    async def async_step_target_saved(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a validated row, showing the `alert:` block to paste.

        A row has just been described in the UI; the `alert:` that feeds it
        still has to be written by hand against a `notifiers:` name the user
        would otherwise have to derive (`switchboard_<slug>`). Showing it here
        is the cheapest possible answer to "and now what?".
        """
        row = self._pending_target
        if row is None:  # pragma: no cover - unreachable from the UI
            return await self.async_step_init()

        if user_input is not None:
            targets = [
                other for other in self._targets if other[CONF_SLUG] != row[CONF_SLUG]
            ]
            targets.append(row)
            self._options[CONF_TARGETS] = targets
            self._pending_target = None
            return self._save()

        return self.async_show_form(
            step_id="target_saved",
            data_schema=vol.Schema({}),
            description_placeholders={"snippet": _alert_snippet(row)},
        )

    async def async_step_edit_target(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick which routing-table row to edit, then open it pre-filled."""
        self._load()
        targets = self._targets
        if not targets:
            return self.async_abort(reason="nothing_to_edit")

        if user_input is not None:
            self._editing_slug = user_input[CONF_SLUG]
            return await self.async_step_target()

        schema = vol.Schema(
            {
                vol.Required(CONF_SLUG): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[row[CONF_SLUG] for row in targets]
                    )
                )
            }
        )
        return self.async_show_form(step_id="edit_target", data_schema=schema)

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

    # ------------------------------------------------------------------
    # Testing a person or a target (ADR-0018 §6)
    # ------------------------------------------------------------------

    async def async_step_test_target(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Send one real test message through a routing-table row."""
        self._load()
        targets = self._targets
        if not targets:
            return self.async_abort(reason="nothing_to_test")

        if user_input is not None:
            return await self._async_run_test(user_input[CONF_SLUG])

        schema = vol.Schema(
            {
                vol.Required(CONF_SLUG): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[row[CONF_SLUG] for row in targets]
                    )
                )
            }
        )
        return self.async_show_form(step_id="test_target", data_schema=schema)

    async def async_step_test_person(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Send one real test message to one person, through a row that reaches them."""
        self._load()
        persons = self._persons
        if not persons:
            return self.async_abort(reason="nothing_to_test")

        if user_input is not None:
            switchboard = self._switchboard
            slug = (
                switchboard.target_for_person(user_input["entity_id"])
                if switchboard is not None
                else None
            )
            if slug is None:
                # Nobody can be notified through no row at all, and saying so is
                # the point: a silent no-op here would read as a broken output.
                return self.async_abort(reason="nothing_to_test")
            return await self._async_run_test(slug)

        schema = vol.Schema(
            {
                vol.Required("entity_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[row["entity_id"] for row in persons]
                    )
                )
            }
        )
        return self.async_show_form(step_id="test_person", data_schema=schema)

    async def _async_run_test(self, slug: str) -> ConfigFlowResult:
        """Route one tagged test message, then explain what happened to it.

        A real message rather than a dry run is the point: it proves the
        *output* works, which `explain` cannot. `explain` is what gives the
        result step its explanation, so the two features pay for each other.
        Nothing is written to `entry.options` by a test.
        """
        switchboard = self._switchboard
        if switchboard is None:  # pragma: no cover - unreachable from the UI
            return self.async_abort(reason="nothing_to_test")

        await switchboard.async_send_test_message(slug)
        self._test_result = _explain_summary(await switchboard.async_explain(slug))
        return await self.async_step_test_result()

    async def async_step_test_result(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the `explain` answer for the message that was just sent."""
        if user_input is not None:
            return await self.async_step_init()

        return self.async_show_form(
            step_id="test_result",
            data_schema=vol.Schema({}),
            description_placeholders={"result": self._test_result or ""},
        )

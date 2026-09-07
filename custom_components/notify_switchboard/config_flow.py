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
  `default` target and points `default_target` at it, so `notify.switchboard`
  works without anybody writing a target by hand;
- the target editor ends on `target_saved`, which shows the `alert:` block to
  paste;
- `test_person` / `test_target` send one real message and show the `explain`
  answer for it.

From 0.6.0 (ADR-0020) both editors are split in two, because a config flow
renders one voluptuous schema per step and Home Assistant has no "collapsed"
or "expert" marker a selector can carry (`async_show_form`,
`homeassistant/data_entry_flow.py` line 706): a second step *is* the
collapsible section.

- `target` asks the five things that make a target route -- `slug`, `name`,
  `alert_entity`, `audience`, `observer_mode` -- and `target_advanced` holds
  the nine preferences that used to sit on the same form;
- `person_outputs` keeps `outputs` and `silence_entities`, and
  `person_advanced` holds `wake_time` and `summary`;
- each half writes **only its own fields**. Editing the priority of a target
  must never be able to empty its audience, which is the 0.2.0 data-loss bug
  (`docs/known-issues.md`) a careless split re-introduces;
- an advanced step is reached from a menu entry of its own, through the
  pickers `edit_target_advanced` / `edit_person_advanced`. A menu entry *is* a
  step id: `async_show_menu` (`homeassistant/data_entry_flow.py` line 878)
  builds `vol.Schema({"next_step_id": vol.In(menu_options)})` at line 894, so
  a labelled entry cannot be a parameterised call into an existing step.

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

import json
import logging
from collections.abc import Mapping
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
    CONF_CLEAR_DONE,
    CONF_CRITICAL_PAYLOAD,
    CONF_DEFAULT_DATA,
    CONF_DEFAULT_PRIORITY,
    CONF_DEFAULT_TARGET,
    CONF_DEFAULT_TITLE,
    CONF_DONE_MESSAGE,
    CONF_ESCALATE_WHEN_NOBODY_HOME,
    CONF_MANAGED,
    CONF_MESSAGE,
    CONF_OBSERVER_MODE,
    CONF_OUTPUTS,
    CONF_PERSONS,
    CONF_PRESENCE_RULE,
    CONF_SILENCE_ENTITIES,
    CONF_SLUG,
    CONF_SNOOZE_MINUTES,
    CONF_SUMMARY,
    CONF_TARGETS,
    CONF_TTL_MINUTES,
    CONF_WAKE_TIME,
    DEFAULT_PRESENCE_RULE,
    DEFAULT_PRIORITY,
    DEFAULT_TARGET_SLUG,
    DEFAULT_TTL_MINUTES,
    DOMAIN,
    LEGACY_SERVICE_NAME,
    VALID_PRESENCE_RULES,
    VALID_PRIORITIES,
)
from .dispatcher import companion_service_name, friendly_name, named_entity
from .router import is_recursive_output
from .validation import parse_snooze_minutes, validate_person, validate_target

if TYPE_CHECKING:
    from .dispatcher import Switchboard

_LOGGER = logging.getLogger(__name__)

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

# v0.7.1: the words an option label is built from. A chip reading
# `airplay_bedroom` or `mobile_app_dev_bob` is the maintainer's own example of
# the interface speaking like the code, so every option the two selectors offer
# is labelled -- and the words that go in a label are translated, like the
# marker above, rather than being English in a French UI.
LABEL_HOME_ASSISTANT_APP = "home_assistant_app"
LABEL_PERSISTENT_NOTIFICATION = "persistent_notification"
OPTION_LABEL_FALLBACKS: dict[str, str] = {
    "this_persons_device": FALLBACK_THIS_PERSONS_DEVICE,
    LABEL_HOME_ASSISTANT_APP: "Home Assistant app",
    LABEL_PERSISTENT_NOTIFICATION: "Home Assistant notifications",
}

# The `SelectSelector` translation keys of the two coded choices
# (`component.<domain>.selector.<key>.options.<value>`): the stored values stay
# `info` / `home_only`, and only what the chip reads changes.
SELECTOR_PRIORITY = "priority"
SELECTOR_PRESENCE_RULE = "presence_rule"

# The `alert:` block `target_saved` offers (ADR-0018 §7). `notifiers:` wants the
# legacy service name without its `notify.` prefix, which is exactly what
# `TargetConfig.service_name` composes; `entity_id` is the one thing the router
# cannot know, so it is left as an obvious placeholder.
ALERT_SNIPPET_ENTITY_PLACEHOLDER = "binary_sensor.CHANGE_ME"

# The ceiling of the time-to-live number selector: thirty days in minutes. A
# deferral that outlives a month is a message nobody was waiting for, and an
# unbounded field is the same `OverflowError` trap `MAX_SILENCE_MINUTES` closes.
MAX_TTL_MINUTES = 43200

# ADR-0020 §1 and §2: which step owns which field. Spelled out here because
# both halves of an editor have to agree on the split -- one writes exactly
# these keys and the other must not touch them -- and because the errors a
# step can show are exactly the errors on its own fields.
TARGET_BASIC_FIELDS: frozenset[str] = frozenset(
    {CONF_SLUG, "name", CONF_ALERT_ENTITY, CONF_AUDIENCE, CONF_OBSERVER_MODE}
)
TARGET_ADVANCED_FIELDS: frozenset[str] = frozenset(
    {
        CONF_DEFAULT_PRIORITY,
        CONF_PRESENCE_RULE,
        CONF_ALLOW_ACKNOWLEDGE,
        CONF_SNOOZE_MINUTES,
        CONF_DEFAULT_DATA,
        CONF_MESSAGE,
        CONF_DONE_MESSAGE,
        CONF_DEFAULT_TITLE,
        CONF_CLEAR_DONE,
    }
)
PERSON_BASIC_FIELDS: frozenset[str] = frozenset({CONF_OUTPUTS, CONF_SILENCE_ENTITIES})
# v0.7 (ADR-0021 §1): `escalate_when_nobody_home` gets a step of its own rather
# than a tenth field on `target_advanced`, because contract v0.6 §"Four
# options-flow step ids are public" enumerates what `target_advanced` holds and
# the v0.7 addendum does not amend that list. `target_escalation` and its
# picker are internal steps, which the same section explicitly allows to change.
TARGET_ESCALATION_FIELDS: frozenset[str] = frozenset({CONF_ESCALATE_WHEN_NOBODY_HOME})
PERSON_ADVANCED_FIELDS: frozenset[str] = frozenset({CONF_WAKE_TIME, CONF_SUMMARY})

# The checkbox `target_saved` grows (ADR-0020 §1): ticked, the flow carries on
# into `target_advanced` for the target just described instead of writing and
# ending. Not a public name -- `target_saved` itself is internal.
CONF_ADVANCED = "advanced"


def _advanced_target_values(stored: dict[str, Any] | None) -> dict[str, Any]:
    """Return the nine advanced values of a target: stored, or documented.

    This is what makes the split invisible in the store: a target created
    through the basic step alone is the exact row 0.5.1 wrote for the same five
    answers, because the nine fields nobody was asked about take the defaults
    the form used to show.
    """
    stored = stored or {}
    return (
        {
            CONF_DEFAULT_PRIORITY: stored.get(CONF_DEFAULT_PRIORITY)
            or DEFAULT_PRIORITY,
            CONF_PRESENCE_RULE: stored.get(CONF_PRESENCE_RULE) or DEFAULT_PRESENCE_RULE,
            CONF_ALLOW_ACKNOWLEDGE: bool(stored.get(CONF_ALLOW_ACKNOWLEDGE)),
            CONF_SNOOZE_MINUTES: list(stored.get(CONF_SNOOZE_MINUTES) or []),
            CONF_DEFAULT_DATA: dict(stored.get(CONF_DEFAULT_DATA) or {}),
            CONF_MESSAGE: stored.get(CONF_MESSAGE) or None,
            CONF_DONE_MESSAGE: stored.get(CONF_DONE_MESSAGE) or None,
            CONF_DEFAULT_TITLE: stored.get(CONF_DEFAULT_TITLE) or None,
        }
        | ({CONF_CLEAR_DONE: True} if stored.get(CONF_CLEAR_DONE) else {})
        | (
            # v0.7 (ADR-0021 §1): carried over, never invented. The basic step must
            # not be able to clear a flag it does not show.
            {CONF_ESCALATE_WHEN_NOBODY_HOME: True}
            if stored.get(CONF_ESCALATE_WHEN_NOBODY_HOME)
            else {}
        )
    )


def _showable(errors: dict[str, str], fields: frozenset[str]) -> dict[str, str]:
    """Keep only the errors this step has a field to show them on.

    Both halves of an editor validate the **whole** target or person, because a
    rule can span two fields (`audience` against the known persons, a slug
    against the other slugs). An error on a field the current form does not
    show has nowhere to appear, and a form that refuses a submission without
    saying why is a flow the user cannot leave. The values that could carry
    such an error came from the store, where they were validated when they were
    written.

    That reasoning holds for values the store wrote; it stops holding the day
    the store holds something the current validation rejects -- a row written
    by an older version, or hand-edited in `.storage`. The submission then goes
    through and the complaint is dropped on the floor, which is the right
    behaviour and an awful thing to debug in silence. What is dropped is
    logged, at debug: nothing is wrong for the user, so nothing should be said
    to them, but a bug report should be able to say what the flow decided not
    to show.
    """
    shown = {field: error for field, error in errors.items() if field in fields}
    if hidden := {
        field: error for field, error in errors.items() if field not in shown
    }:
        _LOGGER.debug("Not shown on this step, which has no field for them: %s", hidden)
    return shown


def _ttl_value(raw: Any) -> int | None:
    """Read one time-to-live field: a positive number, or None for "never"."""
    if raw in (None, ""):
        return None
    try:
        minutes = int(float(raw))
    except TypeError, ValueError:  # pragma: no cover - the selector refuses it
        return None
    return minutes if minutes > 0 else None


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
def _person_label(hass: HomeAssistant, entity_id: str) -> str:
    """Return the name a picker shows for one person.

    The same source the person's virtual device already uses
    (`entity.person_device_name`), so the options menu, the device page and the
    notification all call somebody by the same name.
    """
    return friendly_name(hass, entity_id)


def _target_label(row: Mapping[str, Any]) -> str:
    """Return the name a picker shows for one target.

    The short identifier is plumbing -- it is what `notify.switchboard_<slug>`
    is built from -- and the name is what the household chose. A target saved
    without a name falls back to it, exactly as `_alert_snippet` does.
    """
    return str(row.get("name") or row[CONF_SLUG])


@callback
def _companion_device_names(hass: HomeAssistant) -> dict[str, str]:
    """Map every Companion push service name to the device it belongs to.

    Built from the `mobile_app` config entries rather than from a name
    heuristic, exactly as `_discovered_outputs` is, and for every registration
    of the instance rather than one person's: the audience selector offers a
    phone as a bare output without knowing whose it is.
    """
    return {
        companion_service_name(str(device_name)): str(device_name)
        for entry in hass.config_entries.async_entries(MOBILE_APP_DOMAIN)
        if (device_name := entry.data.get(MOBILE_APP_DEVICE_NAME))
    }


def _output_label(
    service: str,
    devices: Mapping[str, str],
    texts: Mapping[str, str],
    *,
    identifier: str | None = None,
) -> str:
    """Return the label of one `notify` service option, brackets included.

    Three kinds, in order, and each one decides for itself whether the raw
    identifier is worth showing:

    - a Companion registration **is** its device, spelled the way its owner
      spelled it in the app; the `mobile_app_…` slug core derives from that
      name is noise nobody has to read, so it is dropped;
    - `persistent_notification` is the one core service worth a name of its
      own, and that name says the whole thing;
    - anything else has no friendlier name to hide behind, so it is at least
      turned back into words and keeps its own name in brackets -- somebody
      who has to go and change a configuration needs it.

    `identifier` is what those brackets say, the service name by default. The
    audience selector stores `notify.<service>` rather than the bare service
    and has to show what it stores, which is the only reason this is an
    argument rather than `service` itself.
    """
    device = devices.get(service)
    if device is not None:
        return f"{device} ({texts[LABEL_HOME_ASSISTANT_APP]})"
    if service == SERVICE_PERSISTENT_NOTIFICATION:
        return texts[LABEL_PERSISTENT_NOTIFICATION]
    name = service if identifier is None else identifier
    readable = service.replace("_", " ").capitalize()
    return readable if readable == name else f"{readable} ({name})"


@callback
def _output_options(
    hass: HomeAssistant,
    owned: list[str],
    marker: str,
    devices: Mapping[str, str] | None = None,
    labels: Mapping[str, str] | None = None,
) -> list[selector.SelectOptionDict]:
    """Build the `outputs` option list: this person's phones first, all labelled.

    `sort` is left at its default `False` on the selector so the frontend keeps
    this order; it is the whole point of the list.

    v0.7.1 opens the label of the person's *own* phones on the device name,
    which is the only thing they recognise -- "Bob's iPhone" rather than
    `mobile_app_bob_s_iphone` -- and keeps the translated marker for them
    alone, because "which of these is mine" is the question the ordering and
    the marker exist to answer.

    ADR-0018 §2 (amendment 2026-09-07) extends that to the rest of the list:
    every option carries a readable label too. The first version of the ADR
    said the others carried "the service name itself", which left raw slugs on
    screen next to a labelled one -- the interface speaking like the code in
    the one place a newcomer is asked to recognise their own phone. Only the
    marker stays reserved; the `value` is the raw service name throughout.
    """
    devices = devices if devices is not None else _companion_device_names(hass)
    texts = dict(OPTION_LABEL_FALLBACKS) | dict(labels or {})
    available = sorted(
        service
        for service in hass.services.async_services_for_domain(NOTIFY_DOMAIN)
        if not is_recursive_output(service) and service not in NOTIFY_COMPONENT_SERVICES
    )
    first = [service for service in owned if service in available]
    rest = [service for service in available if service not in first]
    return [
        selector.SelectOptionDict(
            value=service,
            label=f"{devices.get(service, service)} — {marker} ({service})",
        )
        for service in first
    ] + [
        selector.SelectOptionDict(
            value=service, label=_output_label(service, devices, texts)
        )
        for service in rest
    ]


@callback
def _audience_options(
    hass: HomeAssistant,
    known_persons: list[str],
    labels: Mapping[str, str] | None = None,
) -> list[selector.SelectOptionDict]:
    """Build the `audience` option list: the persons, then the bare outputs.

    ADR-0021 §5: "the audience selector of the `target` step simply offers the
    registered `notify.*` services alongside the persons". There is no `places`
    object, no schedule and no new menu -- a bare output is an audience entry
    like any other, told apart by its domain and by nothing else.

    The persons come first because they are what an audience usually is; a
    speaker is spelled with its full `notify.` prefix, which is what makes the
    domain readable in the stored row and in the routing-table entity.

    v0.7.1 labels every option: a person by the name Home Assistant shows, a
    speaker in words with the `notify.<service>` it stores kept in brackets, a
    phone by the device its owner named. `_output_label` composes the whole
    label, brackets included, because which identifier is worth showing
    depends on the kind of output.
    """
    texts = dict(OPTION_LABEL_FALLBACKS) | dict(labels or {})
    devices = _companion_device_names(hass)
    speakers = sorted(
        service
        for service in hass.services.async_services_for_domain(NOTIFY_DOMAIN)
        if not is_recursive_output(service) and service not in NOTIFY_COMPONENT_SERVICES
    )
    return [
        selector.SelectOptionDict(value=person_id, label=_person_label(hass, person_id))
        for person_id in known_persons
    ] + [
        selector.SelectOptionDict(
            value=(value := f"{NOTIFY_DOMAIN}.{service}"),
            label=_output_label(service, devices, texts, identifier=value),
        )
        for service in speakers
    ]


@callback
def _person_picker_options(
    hass: HomeAssistant, persons: list[dict[str, Any]]
) -> list[selector.SelectOptionDict]:
    """Return the options of every "pick a person" step, labelled by name."""
    return [
        selector.SelectOptionDict(
            value=row["entity_id"], label=_person_label(hass, row["entity_id"])
        )
        for row in persons
    ]


def _target_picker_options(
    targets: list[dict[str, Any]],
) -> list[selector.SelectOptionDict]:
    """Return the options of every "pick a target" step, labelled by name."""
    return [
        selector.SelectOptionDict(value=row[CONF_SLUG], label=_target_label(row))
        for row in targets
    ]


def _alert_snippet(row: dict[str, Any]) -> str:
    """Return the ready-to-paste `alert:` block for one routing-table row.

    A row in **observer mode** gets no `notifiers:`. That is not a shortening
    of the block, it is what observer mode *is*: the router watches the alert
    entity itself, and the README says the block "needs no `notifiers:` at
    all". Emitting one anyway wires the row both ways at once -- the alert
    calls the router on every `repeat`, and the router routes the same
    transition on its own -- so the first thing the user would see after
    pasting the block they were handed is a duplicated notification.
    """
    alert_entity = row.get(CONF_ALERT_ENTITY)
    object_id = (
        str(alert_entity).partition(".")[2] if alert_entity else str(row[CONF_SLUG])
    )
    acknowledge = "true" if row.get(CONF_ALLOW_ACKNOWLEDGE) else "false"
    lines = [
        "alert:",
        f"  {object_id}:",
        # A row name is free text: an unquoted `Fuite: eau # urgence`
        # is a nested mapping truncated at the `#`. `json.dumps` emits a
        # double-quoted scalar, which YAML 1.1 reads exactly like JSON.
        f"    name: {json.dumps(row.get('name') or row[CONF_SLUG])}",
        f"    entity_id: {ALERT_SNIPPET_ENTITY_PLACEHOLDER}",
        '    state: "on"',
        "    repeat: [5, 15, 60]",
        f"    can_acknowledge: {acknowledge}",
    ]
    if not row.get(CONF_OBSERVER_MODE):
        lines += [
            "    notifiers:",
            f"      - {LEGACY_SERVICE_NAME}_{row[CONF_SLUG]}",
        ]
    return "\n".join(lines)


def _explain_summary(hass: HomeAssistant, response: dict[str, Any]) -> str:
    """Render an `explain` response as a markdown list, one item per person.

    The step description this lands in is rendered as markdown, where a bare
    newline is collapsed: without the list markers every person's answer runs
    into a single paragraph.

    v0.7.1 opens each item on the person's own name and drops the decision
    word: `routed` and `deferred` are the router's vocabulary, and the sentence
    that follows already says what happened, in the reader's language. The
    entity id stays in brackets for whoever has to go and fix something.
    """
    lines = [
        f"{named_entity(hass, person)} — {answer['detail']}"
        for person, answer in sorted(response["persons"].items())
    ]
    return "\n".join(f"- {line}" for line in lines)


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
        """Take a working copy of the stored options.

        The copy is built key by key rather than by copying the dict, so that a
        half-written or hand-edited file cannot smuggle a shape the rest of this
        flow does not expect. `ttl_minutes` (v0.5, ADR-0019 §1) is optional, so
        it is only carried over when it is there -- and it *has* to be carried
        over, or editing a person would silently reset the household's policy.
        """
        if not self._options:
            stored = dict(self.config_entry.options or {})
            self._options = {
                CONF_PERSONS: [dict(row) for row in stored.get(CONF_PERSONS) or []],
                CONF_TARGETS: [dict(row) for row in stored.get(CONF_TARGETS) or []],
                CONF_DEFAULT_TARGET: stored.get(CONF_DEFAULT_TARGET),
            }
            if CONF_TTL_MINUTES in stored:
                self._options[CONF_TTL_MINUTES] = dict(stored[CONF_TTL_MINUTES])
            # v0.7 (ADR-0021 §7), same reason as `ttl_minutes`: a global option
            # that is only present when it differs from its default, and that
            # editing a person must not silently reset.
            if CONF_CRITICAL_PAYLOAD in stored:
                self._options[CONF_CRITICAL_PAYLOAD] = bool(
                    stored[CONF_CRITICAL_PAYLOAD]
                )

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
                "edit_person_advanced",
                "remove_person",
                "target",
                "edit_target",
                "edit_target_advanced",
                "edit_target_escalation",
                "remove_target",
                "general",
                "ttl",
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
        """Create the `default` target the first time a person meets an empty table.

        Up to 0.3.0 a fresh install had an empty routing table, so
        `notify.switchboard` resolved to no target and did nothing at all until
        the user had invented a slug, a name, a priority, an audience and a
        presence rule. This is the one target that removes all of that -- and
        only that: it exists to bootstrap an empty table, never to add itself to
        a table somebody has already built.
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

    def _stored_target(self, slug: str | None) -> dict[str, Any] | None:
        """Return the stored target with that slug, if there is one."""
        for row in self._targets:
            if row[CONF_SLUG] == slug:
                return row
        return None

    def _suggested_target(self) -> dict[str, Any] | None:
        """Return the stored values of the target row being edited.

        `snooze_minutes` is stored as a list of integers but edited as the
        comma-separated text `parse_snooze_minutes` reads back, so it is
        rendered here rather than handed over raw — a suggested value is put
        straight into the field the user sees.
        """
        row = self._stored_target(self._editing_slug)
        if row is None:
            return None
        suggested = {
            key: value for key, value in row.items() if value not in (None, [])
        }
        suggested[CONF_AUDIENCE] = list(row.get(CONF_AUDIENCE) or [])
        suggested[CONF_SNOOZE_MINUTES] = ", ".join(
            str(minutes) for minutes in row.get(CONF_SNOOZE_MINUTES) or []
        )
        return suggested

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
        """Edit one person's notify services and silence entities.

        The two fields a first install has to fill, and only those: the wake
        time and the night summary are preferences, and they moved to
        `person_advanced` (ADR-0020 §2). Both advanced values are carried over
        from the stored person untouched, so changing a phone can never delete
        somebody's night.
        """
        self._load()
        person_id = self._editing_person
        if person_id is None:  # pragma: no cover - unreachable from the UI
            return await self.async_step_person()

        stored = self._stored_person() or {}
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
                # Written by `person_advanced`, never by this step. A new
                # person gets the documented absence of a wake time, whose
                # meaning ADR-0020 §3 spells out.
                CONF_WAKE_TIME: stored.get(CONF_WAKE_TIME) or None,
            }
            # v0.5 (ADR-0019 §2): the key is only written when it is False, so
            # a person row edited without touching it keeps the exact dict it
            # had and an absent key keeps meaning "summarise".
            if stored.get(CONF_SUMMARY) is False:
                row[CONF_SUMMARY] = False
            persons = self._persons
            is_new = not any(other["entity_id"] == person_id for other in persons)
            # `entity_id` was settled by the previous step and is not a field
            # of this form, so an error on it would have nowhere to show.
            errors = _showable(
                validate_person(row, persons, is_new=is_new), PERSON_BASIC_FIELDS
            )
            if not errors:
                persons = [
                    other for other in persons if other["entity_id"] != person_id
                ]
                persons.append(row)
                self._options[CONF_PERSONS] = persons
                await self._async_bootstrap_default_target()
                return self._save()

        labels = await self._async_option_labels()
        schema = vol.Schema(
            {
                vol.Required(CONF_OUTPUTS, default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_output_options(
                            self.hass,
                            _discovered_outputs(self.hass, person_id),
                            labels["this_persons_device"],
                            labels=labels,
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
            description_placeholders={"person": _person_label(self.hass, person_id)},
        )

    async def async_step_person_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit one person's wake time and night summary (ADR-0020 §2).

        Like `target_advanced`, this step writes its own two fields and touches
        neither of the basic ones. Leaving the wake time empty is a supported
        answer, not an unfinished form: ADR-0020 §3 gives its absence a
        meaning.
        """
        self._load()
        person_id = self._editing_person
        stored = self._stored_person()
        if stored is None:  # pragma: no cover - unreachable from the UI
            return await self.async_step_edit_person_advanced()

        errors: dict[str, str] = {}
        if user_input is not None:
            row = {
                key: value
                for key, value in stored.items()
                if key not in PERSON_ADVANCED_FIELDS
            }
            row[CONF_WAKE_TIME] = user_input.get(CONF_WAKE_TIME) or None
            if not user_input.get(CONF_SUMMARY, True):
                row[CONF_SUMMARY] = False
            errors = _showable(
                validate_person(row, self._persons, is_new=False),
                PERSON_ADVANCED_FIELDS,
            )
            if not errors:
                self._options[CONF_PERSONS] = [
                    row if other["entity_id"] == person_id else other
                    for other in self._persons
                ]
                return self._save()

        schema = vol.Schema(
            {
                vol.Optional(CONF_WAKE_TIME): selector.TimeSelector(
                    selector.TimeSelectorConfig()
                ),
                vol.Optional(CONF_SUMMARY, default=True): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="person_advanced",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                user_input
                if user_input is not None
                else {
                    key: value
                    for key, value in stored.items()
                    if key in PERSON_ADVANCED_FIELDS and value is not None
                },
            ),
            errors=errors,
            description_placeholders={
                "person": _person_label(self.hass, str(person_id))
            },
        )

    async def async_step_edit_person_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick whose advanced settings to open.

        The person editor has no confirmation step to hang a shortcut on and
        `person_outputs` deliberately does not grow a checkbox (ADR-0020 §2),
        so this labelled menu entry is the only way in. Internal, like
        `edit_target_advanced`.
        """
        self._load()
        persons = self._persons
        if not persons:
            return self.async_abort(reason="nothing_to_edit")

        if user_input is not None:
            self._editing_person = user_input["entity_id"]
            return await self.async_step_person_advanced()

        schema = vol.Schema(
            {
                vol.Required("entity_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_person_picker_options(self.hass, persons)
                    )
                )
            }
        )
        return self.async_show_form(step_id="edit_person_advanced", data_schema=schema)

    async def _async_option_labels(self) -> dict[str, str]:
        """Return the translated words the two selectors build labels from.

        One lookup for the three of them: the marker that says a phone is this
        person's, and the two names `_output_label` needs. English fallbacks
        keep a label readable on an instance whose language has no file yet.
        """
        translations = await async_get_translations(
            self.hass, self.hass.config.language, "common", {DOMAIN}
        )
        return {
            name: translations.get(f"component.{DOMAIN}.common.{name}", fallback)
            for name, fallback in OPTION_LABEL_FALLBACKS.items()
        }

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
                        options=_person_picker_options(self.hass, persons)
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
                        options=_person_picker_options(self.hass, persons)
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
        """Add or update one target: the five things that make it route.

        `slug` and `name` are the identity the user chooses, `alert_entity` is
        the alert the target is about, `audience` is who it is for, and
        `observer_mode` says whether the router watches that alert itself or
        waits to be called. Everything else has a default that is right for
        almost everybody and lives in `target_advanced` (ADR-0020 §1).

        The whole target is still built here, the nine advanced values coming
        from the target being edited when there is one and from the documented
        defaults when there is not -- which is what makes a target created
        through this step alone the exact row 0.5.1 wrote for the same answers.
        """
        self._load()
        errors: dict[str, str] = {}
        persons = self._persons
        known_persons = [row["entity_id"] for row in persons]

        if user_input is not None:
            row = {
                CONF_SLUG: user_input[CONF_SLUG],
                "name": user_input.get("name") or user_input[CONF_SLUG],
                CONF_ALERT_ENTITY: user_input.get(CONF_ALERT_ENTITY) or None,
                CONF_AUDIENCE: list(user_input.get(CONF_AUDIENCE) or []),
                CONF_OBSERVER_MODE: bool(user_input.get(CONF_OBSERVER_MODE)),
                **_advanced_target_values(self._stored_target(user_input[CONF_SLUG])),
            }
            targets = self._targets
            is_new = not any(other[CONF_SLUG] == row[CONF_SLUG] for other in targets)
            errors = _showable(
                validate_target(row, targets, known_persons, is_new=is_new),
                TARGET_BASIC_FIELDS,
            )
            if not errors:
                # Nothing is written yet: the confirmation step shows the
                # `alert:` block this target expects, and submitting *that* is
                # what writes `entry.options` (ADR-0018 §7). The target is
                # rebuilt from scratch here, without `managed`, which is
                # exactly how editing the default target takes ownership of it
                # (ADR-0018 §4).
                self._pending_target = row
                return await self.async_step_target_saved()

        labels = await self._async_option_labels()
        schema = vol.Schema(
            {
                vol.Required(CONF_SLUG): selector.TextSelector(
                    selector.TextSelectorConfig()
                ),
                vol.Required("name"): selector.TextSelector(
                    selector.TextSelectorConfig()
                ),
                vol.Optional(CONF_ALERT_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="alert")
                ),
                vol.Required(CONF_AUDIENCE, default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_audience_options(self.hass, known_persons, labels),
                        multiple=True,
                        # A speaker that is not registered yet must still be
                        # typable, exactly as an output is (ADR-0018 §2).
                        custom_value=True,
                    )
                ),
                vol.Optional(
                    CONF_OBSERVER_MODE, default=False
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="target",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                user_input if user_input is not None else self._suggested_target(),
            ),
            errors=errors,
        )

    async def async_step_target_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the nine preferences of one target (ADR-0020 §1).

        This step writes its own nine fields and **touches none of the five**.
        Rebuilding the target from the form instead would let somebody who came
        to change a priority walk away with an empty audience -- the 0.2.0
        data-loss bug (`docs/known-issues.md`), re-introduced by a split.
        """
        self._load()
        slug = self._editing_slug
        stored = self._stored_target(slug) if slug is not None else None
        if stored is None:  # pragma: no cover - unreachable from the UI
            return await self.async_step_edit_target_advanced()

        errors: dict[str, str] = {}
        if user_input is not None:
            minutes, _ok = parse_snooze_minutes(user_input.get(CONF_SNOOZE_MINUTES))
            row = {
                # The five basic fields, exactly as they are stored, and
                # `managed` deliberately dropped: submitting either half of the
                # editor is the user taking ownership of the target
                # (ADR-0018 §4, kept by ADR-0020 §1).
                key: value
                for key, value in stored.items()
                if key in TARGET_BASIC_FIELDS
            }
            row |= {
                CONF_DEFAULT_PRIORITY: user_input.get(
                    CONF_DEFAULT_PRIORITY, DEFAULT_PRIORITY
                ),
                CONF_PRESENCE_RULE: user_input.get(
                    CONF_PRESENCE_RULE, DEFAULT_PRESENCE_RULE
                ),
                CONF_ALLOW_ACKNOWLEDGE: bool(user_input.get(CONF_ALLOW_ACKNOWLEDGE)),
                CONF_SNOOZE_MINUTES: minutes,
                CONF_DEFAULT_DATA: dict(user_input.get(CONF_DEFAULT_DATA) or {}),
                # v0.2 addendum (ADR-0016). Absent stays absent: an empty text
                # field means "no override", not an empty message.
                CONF_MESSAGE: user_input.get(CONF_MESSAGE) or None,
                CONF_DONE_MESSAGE: user_input.get(CONF_DONE_MESSAGE) or None,
                CONF_DEFAULT_TITLE: user_input.get(CONF_DEFAULT_TITLE) or None,
            }
            # v0.5 (ADR-0019 §6): same discipline as `managed`, absent is false.
            if user_input.get(CONF_CLEAR_DONE):
                row[CONF_CLEAR_DONE] = True
            # Re-read the raw value so an unparsable duration is reported.
            row_for_validation = dict(row)
            row_for_validation[CONF_SNOOZE_MINUTES] = user_input.get(
                CONF_SNOOZE_MINUTES
            )
            known_persons = [person["entity_id"] for person in self._persons]
            errors = _showable(
                validate_target(
                    row_for_validation, self._targets, known_persons, is_new=False
                ),
                TARGET_ADVANCED_FIELDS,
            )
            if not errors:
                self._options[CONF_TARGETS] = [
                    row if other[CONF_SLUG] == row[CONF_SLUG] else other
                    for other in self._targets
                ]
                return self._save()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DEFAULT_PRIORITY, default=DEFAULT_PRIORITY
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(VALID_PRIORITIES),
                        translation_key=SELECTOR_PRIORITY,
                    )
                ),
                vol.Required(
                    CONF_PRESENCE_RULE, default=DEFAULT_PRESENCE_RULE
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(VALID_PRESENCE_RULES),
                        translation_key=SELECTOR_PRESENCE_RULE,
                    )
                ),
                vol.Optional(
                    CONF_ALLOW_ACKNOWLEDGE, default=False
                ): selector.BooleanSelector(),
                vol.Optional(CONF_SNOOZE_MINUTES, default=""): selector.TextSelector(
                    selector.TextSelectorConfig()
                ),
                vol.Optional(CONF_DEFAULT_DATA, default={}): selector.ObjectSelector(),
                # `TemplateSelector.__call__` runs `cv.template`
                # (`homeassistant/helpers/selector.py`), so an unparsable
                # template is already refused by the schema and needs no rule
                # of its own in `validation.py`.
                vol.Optional(CONF_MESSAGE): selector.TemplateSelector(),
                vol.Optional(CONF_DONE_MESSAGE): selector.TemplateSelector(),
                vol.Optional(CONF_DEFAULT_TITLE): selector.TextSelector(
                    selector.TextSelectorConfig()
                ),
                vol.Optional(
                    CONF_CLEAR_DONE, default=False
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="target_advanced",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                user_input if user_input is not None else self._suggested_target(),
            ),
            errors=errors,
            description_placeholders={"target": _target_label(stored)},
        )

    async def async_step_edit_target_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick which target's advanced settings to open.

        A menu entry is a step id (`async_show_menu`,
        `homeassistant/data_entry_flow.py` line 878), so the labelled entry
        "Advanced settings of a target" needs a step of its own; this is it.
        Internal, and deliberately not one of the four public step ids.
        """
        self._load()
        targets = self._targets
        if not targets:
            return self.async_abort(reason="nothing_to_edit")

        if user_input is not None:
            self._editing_slug = user_input[CONF_SLUG]
            return await self.async_step_target_advanced()

        schema = vol.Schema(
            {
                vol.Required(CONF_SLUG): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_target_picker_options(targets)
                    )
                )
            }
        )
        return self.async_show_form(step_id="edit_target_advanced", data_schema=schema)

    async def async_step_target_saved(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a validated target, showing the `alert:` block to paste.

        A target has just been described in the UI; the `alert:` that feeds it
        still has to be written by hand, and what goes in it depends on the row
        -- `_alert_snippet` names `switchboard_<slug>` under `notifiers:` for
        an ordinary row and emits no `notifiers:` at all for an observer one,
        which is a distinction the user should not have to know to make.
        Showing the finished block here is the cheapest possible answer to "and
        now what?".

        The one checkbox (ADR-0020 §1) is the second way into the advanced
        settings, and the one that matters for somebody who has just met the
        five-field form: ticked, the flow carries on into `target_advanced`
        instead of writing and ending. Unticked -- and `{}` submitted, as every
        Sprint 4 test does -- nothing changes at all.
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
            if user_input.get(CONF_ADVANCED):
                # Still nothing written to `entry.options`: the working copy
                # now holds the target so the advanced step has something to
                # open on, and submitting *that* is what saves.
                self._editing_slug = row[CONF_SLUG]
                return await self.async_step_target_advanced()
            return self._save()

        return self.async_show_form(
            step_id="target_saved",
            data_schema=vol.Schema(
                {vol.Optional(CONF_ADVANCED, default=False): selector.BooleanSelector()}
            ),
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
                        options=_target_picker_options(targets)
                    )
                )
            }
        )
        return self.async_show_form(step_id="edit_target", data_schema=schema)

    async def async_step_target_escalation(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit one target's `escalate_when_nobody_home` (ADR-0021 §1).

        Its own step, and only its own field. `target_advanced` is a public
        step id whose contents contract v0.6 §"Four options-flow step ids are
        public" enumerates -- nine fields, a list the v0.7 addendum does not
        amend -- so the tenth boolean lands here instead. Like both halves of
        the target editor, this step writes **only its own field** and carries
        every other value of the stored row over untouched.
        """
        self._load()
        slug = self._editing_slug
        stored = self._stored_target(slug) if slug is not None else None
        if stored is None:  # pragma: no cover - unreachable from the UI
            return await self.async_step_edit_target_escalation()

        errors: dict[str, str] = {}
        if user_input is not None:
            row = {
                key: value
                for key, value in stored.items()
                if key not in TARGET_ESCALATION_FIELDS and key != CONF_MANAGED
            }
            # Absent means false: the key is written only when it is on, so a
            # target that never used it keeps the exact dict it had.
            if user_input.get(CONF_ESCALATE_WHEN_NOBODY_HOME):
                row[CONF_ESCALATE_WHEN_NOBODY_HOME] = True
            known_persons = [person["entity_id"] for person in self._persons]
            errors = _showable(
                validate_target(row, self._targets, known_persons, is_new=False),
                TARGET_ESCALATION_FIELDS,
            )
            if not errors:
                self._options[CONF_TARGETS] = [
                    row if other[CONF_SLUG] == row[CONF_SLUG] else other
                    for other in self._targets
                ]
                return self._save()

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ESCALATE_WHEN_NOBODY_HOME, default=False
                ): selector.BooleanSelector()
            }
        )
        return self.async_show_form(
            step_id="target_escalation",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                user_input
                if user_input is not None
                else {
                    CONF_ESCALATE_WHEN_NOBODY_HOME: bool(
                        stored.get(CONF_ESCALATE_WHEN_NOBODY_HOME)
                    )
                },
            ),
            errors=errors,
            description_placeholders={"target": _target_label(stored)},
        )

    async def async_step_edit_target_escalation(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick which target's escalation setting to open.

        A menu entry is a step id (`async_show_menu`,
        `homeassistant/data_entry_flow.py` line 878), so the labelled entry
        needs a step of its own; this is it. Internal, like
        `edit_target_advanced`.
        """
        self._load()
        targets = self._targets
        if not targets:
            return self.async_abort(reason="nothing_to_edit")

        if user_input is not None:
            self._editing_slug = user_input[CONF_SLUG]
            return await self.async_step_target_escalation()

        schema = vol.Schema(
            {
                vol.Required(CONF_SLUG): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_target_picker_options(targets)
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="edit_target_escalation", data_schema=schema
        )

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
                        options=_target_picker_options(targets)
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
            # v0.7 (ADR-0021 §7): the key is written only when it is turned
            # **off**, so a household that never opens this step keeps an
            # options dict with the exact keys it always had, and an absent key
            # keeps meaning "on".
            if user_input.get(CONF_CRITICAL_PAYLOAD, True):
                self._options.pop(CONF_CRITICAL_PAYLOAD, None)
            else:
                self._options[CONF_CRITICAL_PAYLOAD] = False
            return self._save()

        current = self._options.get(CONF_DEFAULT_TARGET) or targets[0][CONF_SLUG]
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DEFAULT_TARGET, default=current
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_target_picker_options(targets)
                    )
                ),
                vol.Optional(
                    CONF_CRITICAL_PAYLOAD, default=True
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="general",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {CONF_CRITICAL_PAYLOAD: self._options.get(CONF_CRITICAL_PAYLOAD, True)},
            ),
        )

    async def async_step_ttl(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit `ttl_minutes`, the household's policy for held-back messages.

        The form always opens on the *effective* policy -- the stored mapping
        where there is one, the documented defaults everywhere else -- so what a
        user reads is what the router applies. An empty field means "never
        expires", which is exactly what a `null` in the mapping means, and
        `critical` has no field because a critical message is never held back in
        the first place (ADR-0019 §1).

        The mapping is written whole, and only when it differs from the
        defaults: a household that never opens this step keeps an options dict
        with the exact three keys it always had.
        """
        self._load()
        if user_input is not None:
            chosen = {
                priority: _ttl_value(user_input.get(priority))
                for priority in DEFAULT_TTL_MINUTES
            }
            if chosen == DEFAULT_TTL_MINUTES:
                self._options.pop(CONF_TTL_MINUTES, None)
            else:
                self._options[CONF_TTL_MINUTES] = chosen
            return self._save()

        stored = self._options.get(CONF_TTL_MINUTES)
        current = dict(DEFAULT_TTL_MINUTES)
        if isinstance(stored, dict):
            current.update(
                {
                    priority: stored[priority]
                    for priority in DEFAULT_TTL_MINUTES
                    if priority in stored
                }
            )
        schema = vol.Schema(
            {
                # `None` is accepted alongside the number: a cleared field is
                # how a user says "never expires", and a frontend may send it
                # as an explicit null rather than by omitting the key.
                vol.Optional(priority): vol.Any(
                    None,
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=MAX_TTL_MINUTES,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                )
                for priority in DEFAULT_TTL_MINUTES
            }
        )
        return self.async_show_form(
            step_id="ttl",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {
                    priority: minutes
                    for priority, minutes in current.items()
                    if minutes is not None
                },
            ),
        )

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
                        options=_target_picker_options(targets)
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
                        options=_person_picker_options(self.hass, persons)
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
        self._test_result = _explain_summary(
            self.hass, await switchboard.async_explain(slug)
        )
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

"""Shared fixtures and options-shape builders for the Notify Switchboard acceptance suite.

The options shape built by `make_person` / `make_target` / `make_entry` below is
NORMATIVE — see ../../README.md. The implementation's config flow / options flow
must read `entry.options` in exactly this shape.

Only three names are imported from the integration itself: `DOMAIN`,
`ATTR_PRIORITY` and `ATTR_SOURCE_ENTITY` (frozen contract names, see
docs/notify-switchboard-contract-v0.md). Every other key used below is a plain
string literal defined by this test suite, not a constant owned by the
implementation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from homeassistant.helpers.entity_component import DATA_INSTANCES
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.notify_switchboard.const import (  # noqa: F401  (import-cleanliness check)
    ATTR_PRIORITY,
    ATTR_SOURCE_ENTITY,
    DOMAIN,
)

DEFAULT_ENTRY_ID = "ns_acceptance_entry"
DEFAULT_TITLE = "Notify Switchboard (acceptance)"


# ---------------------------------------------------------------------------
# Options-shape builders (see README.md "Options shape")
# ---------------------------------------------------------------------------


def make_person(
    entity_id: str,
    outputs: list[str],
    *,
    silence_entities: list[str] | None = None,
    wake_time: str | None = None,
    summary: bool = True,
    min_priority: str = "info",
) -> dict[str, Any]:
    """Build one row of `entry.options["persons"]`.

    `summary` is the v0.5 addendum (ADR-0019 §2): an optional per-person key
    whose default is **on**, so it is only written when it is `False`. Every
    S1-S4 person row therefore keeps the exact dict it always had, and an
    absent key means "summarise".

    `min_priority` is the v0.6 addendum (ADR-0020 §6): the same discipline,
    with `info` — the bottom of the rank, which drops nothing — as the default
    that is never written.
    """
    row: dict[str, Any] = {
        "entity_id": entity_id,
        "outputs": list(outputs),
        "silence_entities": list(silence_entities or []),
        "wake_time": wake_time,
    }
    if not summary:
        row["summary"] = False
    if min_priority != "info":
        row["min_priority"] = min_priority
    return row


def make_target(
    slug: str,
    name: str,
    *,
    klass: str = "test",
    default_priority: str = "normal",
    alert_entity: str | None = None,
    audience: list[str] | None = None,
    presence_rule: str = "always",
    allow_acknowledge: bool = False,
    snooze_minutes: list[int] | None = None,
    default_data: dict[str, Any] | None = None,
    observer_mode: bool = False,
    message: str | None = None,
    done_message: str | None = None,
    default_title: str | None = None,
    managed: bool = False,
    clear_done: bool = False,
    escalate_when_nobody_home: bool = False,
    escalation_after_minutes: int | None = None,
    escalation_audience: list[str] | None = None,
    max_deliveries: int | None = None,
    require_authentication: bool | None = None,
) -> dict[str, Any]:
    """Build one row of `entry.options["targets"]` (the routing table).

    `message`, `done_message` and `default_title` are the v0.2 addendum
    (ADR-0016, `docs/contract.md` "Per-row texts"): optional per-row texts,
    `None` by default so every Sprint 1 target keeps building the exact same
    row it always has. `managed` is the v0.4 addendum (ADR-0018) and is only
    written when true, for the same reason; so is `clear_done`, the v0.5
    addendum (ADR-0019 §6), whose default is off.
    """
    row: dict[str, Any] = {
        "slug": slug,
        "name": name,
        "class": klass,
        "default_priority": default_priority,
        "alert_entity": alert_entity,
        "audience": list(audience or []),
        "presence_rule": presence_rule,
        "allow_acknowledge": allow_acknowledge,
        "snooze_minutes": list(snooze_minutes or []),
        "default_data": dict(default_data or {}),
        "observer_mode": observer_mode,
        "message": message,
        "done_message": done_message,
        "default_title": default_title,
    }
    if managed:
        # v0.4 addendum (ADR-0018): an optional row key, *absent* on every row
        # written before 0.4.0 -- which is why it is only added when asked for.
        # Absent means false, so every S1-S3 row keeps the exact dict it had.
        row["managed"] = True
    if clear_done:
        # v0.5 addendum (ADR-0019 §6): same discipline, same reason.
        row["clear_done"] = True
    # v0.6 addendum (ADR-0020): five optional row keys, each written only when
    # it differs from its default, so every S1-S5 row keeps the exact dict it
    # had. `escalation_after_minutes` and `escalation_audience` are documented
    # as required together, and the builder lets a test write one without the
    # other on purpose -- that half-written row is itself a case to pin.
    if escalate_when_nobody_home:
        row["escalate_when_nobody_home"] = True
    if escalation_after_minutes is not None:
        row["escalation_after_minutes"] = escalation_after_minutes
    if escalation_audience is not None:
        row["escalation_audience"] = list(escalation_audience)
    if max_deliveries is not None:
        row["max_deliveries"] = max_deliveries
    if require_authentication is not None:
        row["require_authentication"] = require_authentication
    return row


def make_options(
    *,
    persons: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    default_target: str,
    ttl_minutes: dict[str, int | None] | None = None,
) -> dict[str, Any]:
    """Build the full `entry.options` dict.

    `ttl_minutes` is the v0.5 addendum (ADR-0019 §1): an optional *global*
    mapping from priority to a number of minutes (or `None` for "never
    expires"). It is only written when a test asks for one, so every S1-S4
    options dict keeps the exact three keys it always had, and an absent
    mapping means the documented defaults (`info` 120, `normal` 720,
    `high` none).
    """
    options: dict[str, Any] = {
        "persons": persons,
        "targets": targets,
        "default_target": default_target,
    }
    if ttl_minutes is not None:
        options["ttl_minutes"] = dict(ttl_minutes)
    return options


def make_entry(
    hass,
    *,
    persons: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    default_target: str,
    entry_id: str = DEFAULT_ENTRY_ID,
    ttl_minutes: dict[str, int | None] | None = None,
) -> MockConfigEntry:
    """Create and register (add_to_hass) a MockConfigEntry with the given options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=entry_id,
        title=DEFAULT_TITLE,
        version=1,
        minor_version=1,
        options=make_options(
            persons=persons,
            targets=targets,
            default_target=default_target,
            ttl_minutes=ttl_minutes,
        ),
    )
    entry.add_to_hass(hass)
    return entry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def install(hass) -> Callable[[MockConfigEntry], Any]:
    """Return an async helper that sets up a MockConfigEntry and drains the loop."""

    async def _install(entry: MockConfigEntry) -> MockConfigEntry:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    return _install


@pytest.fixture
def mock_outputs(hass) -> Callable[..., dict[str, list]]:
    """Register fake `notify.<name>` services and return their captured-calls lists.

    Usage: calls = mock_outputs("mobile_app_alice", "mobile_app_bob")
           calls["mobile_app_alice"] -> list[ServiceCall]
    """

    def _mock(*names: str, raise_exception: Exception | None = None) -> dict[str, list]:
        return {
            name: async_mock_service(
                hass, "notify", name, raise_exception=raise_exception
            )
            for name in names
        }

    return _mock


@pytest.fixture
def set_person(hass) -> Callable[[str, str], None]:
    """Set a `person.*` entity's state (home / not_home / anything else)."""

    def _set(entity_id: str, state: str) -> None:
        hass.states.async_set(entity_id, state)

    return _set


@pytest.fixture
def dropped_sensor(hass):
    """Return the current `sensor.switchboard_dropped_today` state object."""

    def _get():
        return hass.states.get("sensor.switchboard_dropped_today")

    return _get


@pytest.fixture
def routed_sensor(hass):
    """Return the current `sensor.switchboard_routed_today` state object."""

    def _get():
        return hass.states.get("sensor.switchboard_routed_today")

    return _get


# ---------------------------------------------------------------------------
# Sprint 4 fixtures: Companion registrations (ADR-0018 §2 and §3)
# ---------------------------------------------------------------------------
#
# The router discovers a person's phones by matching the `user_id` state
# attribute of their `person.*` against the `user_id` stored in each
# `mobile_app` config entry's data, and derives the legacy push service name
# from that entry's `device_name`. Both keys are core's
# (`homeassistant/components/mobile_app/const.py`: `CONF_USER_ID`,
# `ATTR_DEVICE_NAME`), and the entry is what the Companion app's registration
# creates (`mobile_app/config_flow.py`).
#
# The registrations built here are real config entries in the entry registry,
# with the real registration payload shape core's own tests use
# (`tests/components/mobile_app/test_notify.py`), but the `mobile_app`
# component itself is never set up: the router reads config entries, not
# `hass.data`, and setting up `mobile_app` would drag in http, webhooks and a
# push relay for nothing.

MOBILE_APP_DOMAIN = "mobile_app"


def make_mobile_app_entry(
    hass,
    *,
    device_name: str,
    user_id: str,
    webhook_id: str | None = None,
) -> MockConfigEntry:
    """Register one Companion registration as a `mobile_app` config entry."""
    slug = device_name.lower().replace(" ", "_")
    entry = MockConfigEntry(
        domain=MOBILE_APP_DOMAIN,
        source="registration",
        title=device_name,
        data={
            "app_data": {
                "push_token": "PUSH_TOKEN",
                "push_url": "https://example/push",
            },
            "app_id": "io.example.mobile_app",
            "app_name": "mobile app",
            "app_version": "1.0",
            "device_id": f"device-{slug}",
            "device_name": device_name,
            "manufacturer": "Home Assistant",
            "model": "mobile_app",
            "os_name": "iOS",
            "os_version": "18.0",
            "secret": "123abc",
            "supports_encryption": False,
            "user_id": user_id,
            "webhook_id": webhook_id or f"webhook-{slug}",
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mobile_app_registration(hass, device_registry, entity_registry):
    """Return a helper creating one Companion registration and its entities.

    Usage:
        phone = mobile_app_registration("Phone One", user_id=..., \
            binary_sensors={"phone_one_focus": None, "phone_one_mode": "focus"})

    `binary_sensors` maps the object_id of a `binary_sensor` the Companion app
    registered on that device to its entity-registry `translation_key` (or
    `None`). It is how a real iOS Focus sensor reaches the state machine, and
    both halves matter: ADR-0018 §3 proposes an entity whose **entity id or
    translation key** contains `focus`.
    """

    def _make(
        device_name: str,
        *,
        user_id: str,
        binary_sensors: dict[str, str | None] | None = None,
    ) -> MockConfigEntry:
        entry = make_mobile_app_entry(hass, device_name=device_name, user_id=user_id)
        device = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(MOBILE_APP_DOMAIN, entry.data["device_id"])},
            name=device_name,
            manufacturer="Home Assistant",
            model="mobile_app",
        )
        for object_id, translation_key in (binary_sensors or {}).items():
            kwargs: dict[str, Any] = {}
            if translation_key is not None:
                kwargs["translation_key"] = translation_key
            entity_registry.async_get_or_create(
                "binary_sensor",
                MOBILE_APP_DOMAIN,
                f"{entry.data['device_id']}-{object_id}",
                config_entry=entry,
                device_id=device.id,
                suggested_object_id=object_id,
                **kwargs,
            )
            hass.states.async_set(f"binary_sensor.{object_id}", "off")
        return entry

    return _make


@pytest.fixture
def options_flow(hass):
    """Drive the options flow: open the menu, pick a step, submit inputs.

    `await options_flow(entry, "person", {"entity_id": "person.alice"}, {...})`
    opens the menu, selects `person`, then submits each following dict to
    whatever step the flow is on, and returns the last result. Every S4 flow
    test needs the same three lines, and a multi-step editor (ADR-0018 §2 and
    §7) makes them four or five.
    """

    async def _drive(entry: MockConfigEntry, step: str, *inputs: dict[str, Any] | None):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": step}
        )
        for user_input in inputs:
            result = await hass.config_entries.options.async_configure(
                result["flow_id"], user_input
            )
        await hass.async_block_till_done()
        return result

    return _drive


def schema_field(result, key: str):
    """Return (marker, validator) for one field of a flow result's schema.

    The marker carries what `add_suggested_values_to_schema` put there
    (`marker.description["suggested_value"]`); the validator is the selector,
    whose `.config` is the dict the frontend receives
    (`homeassistant/helpers/selector.py`, `Selector.config`).
    """
    for marker, validator in result["data_schema"].schema.items():
        if str(marker) == key:
            return marker, validator
    raise AssertionError(f"{key} is not a field of step {result.get('step_id')!r}")


def suggested_value(result, key: str):
    """Return the pre-selected value of one field, or None when there is none."""
    marker, _validator = schema_field(result, key)
    return (marker.description or {}).get("suggested_value")


def selector_options(result, key: str) -> list[dict[str, str]]:
    """Return a `SelectSelector`'s options, always as `{value, label}` dicts."""
    _marker, validator = schema_field(result, key)
    options = validator.config["options"]
    return [
        option if isinstance(option, dict) else {"value": option, "label": option}
        for option in options
    ]


# ---------------------------------------------------------------------------
# Sprint 5 fixtures: the night, and closing an episode (ADR-0019)
# ---------------------------------------------------------------------------


@pytest.fixture
def deferred_sensor(hass):
    """Return the current `sensor.switchboard_deferred_today` state object."""

    def _get():
        return hass.states.get("sensor.switchboard_deferred_today")

    return _get


@pytest.fixture
def drop_reasons(hass):
    """Return the `reasons` attribute of `sensor.switchboard_dropped_today`.

    Assumption 2 of the Sprint 1 README applies: the container is only ever
    tested with `in`, never for its type or its counts.
    """

    def _get():
        state = hass.states.get("sensor.switchboard_dropped_today")
        assert state is not None
        return state.attributes["reasons"]

    return _get


@pytest.fixture
def dismissals(hass) -> list:
    """Capture `persistent_notification.dismiss` calls.

    ADR-0019 §6 closes the UI half of an episode through core's own service
    (`homeassistant/components/persistent_notification/__init__.py`: the
    `dismiss` service, `SCHEMA_SERVICE_NOTIFICATION`, `async_dismiss`), so the
    test watches that service rather than the notification store.
    """
    return async_mock_service(hass, "persistent_notification", "dismiss")


@pytest.fixture
async def real_alert(hass):
    """Set up one real `alert.*` watching one `binary_sensor`, and drive it.

    Returns an object with `begin()` / `end()`, which move the watched binary
    sensor and therefore the alert through the real transitions the router
    subscribes to: `idle -> on` opens an episode, `-> idle` closes it
    (`$HA_CORE_SRC/homeassistant/components/alert/entity.py`,
    `begin_alerting` / `end_alerting`).

    `repeat` is deliberately long enough never to fire during a test, and the
    alert carries **no** `notifiers` by default: the episode tests drive the
    router through observer mode or through `data.switchboard_done`, and an
    alert that also called `notify.switchboard_<slug>` itself would route every
    message twice. Ending the alert calls `end_alerting`, which cancels the
    repeat (unlike `alert.turn_off`, which only sets `_ack`), so these tests
    leave no lingering timer behind and need no `expected_lingering_timers`
    override — provided every test that calls `begin()` also calls `end()`.

    `notifiers` is the one v0.6 addition (ADR-0020 §0 and §2): the escalation
    granularity is a property of core's own repeat, so the test that pins it
    has to let the alert do the calling.
    """

    made: list[Any] = []

    async def _make(
        object_id: str,
        *,
        repeat: int = 60,
        can_ack: bool = True,
        notifiers: list[str] | None = None,
    ):
        watched = f"binary_sensor.{object_id}_source"
        hass.states.async_set(watched, "off")
        assert await async_setup_component(
            hass,
            "alert",
            {
                "alert": {
                    object_id: {
                        "name": object_id,
                        "entity_id": watched,
                        "state": "on",
                        "repeat": [repeat],
                        "can_acknowledge": can_ack,
                        "skip_first": True,
                        "notifiers": list(notifiers or []),
                    }
                }
            },
        )
        await hass.async_block_till_done()

        class _Alert:
            entity_id = f"alert.{object_id}"
            watched_entity_id = watched

            async def begin(self) -> None:
                hass.states.async_set(watched, "on")
                await hass.async_block_till_done()

            async def end(self) -> None:
                hass.states.async_set(watched, "off")
                await hass.async_block_till_done()

        made.append(_Alert())
        return made[-1]

    yield _make

    # Safety net: a test whose assertion fails before its own `end()` would
    # otherwise leave core's repeat armed and turn one red into a red plus a
    # teardown error. `end_alerting` cancels it; ending an alert that is
    # already idle is a no-op, so a test that ends its own alert is unaffected.
    for alert in made:
        await alert.end()


# ---------------------------------------------------------------------------
# Sprint 6 fixtures: escalation, floors and the two new global entities
# ---------------------------------------------------------------------------


@pytest.fixture
def acknowledgements_sensor(hass):
    """Return the current `sensor.switchboard_acknowledgements` state object."""

    def _get():
        return hass.states.get("sensor.switchboard_acknowledgements")

    return _get


@pytest.fixture
def routing_table_sensor(hass):
    """Return the current `sensor.switchboard_routing_table` state object."""

    def _get():
        return hass.states.get("sensor.switchboard_routing_table")

    return _get


@pytest.fixture
async def schedule_silence(hass):
    """Set up one real `schedule.*` that is `on` all week, carrying block `data`.

    ADR-0020 §6(b) reads a `min_priority` **state attribute** off a silence
    entity that is `on`, and core's `schedule` is the documented way to
    produce one: `Schedule._update`
    (`$HA_CORE_SRC/homeassistant/components/schedule/__init__.py`) does
    `self._attr_extra_state_attributes.update(current_data)` with the active
    time range's `data:` (`CONF_DATA` in `.../schedule/const.py`, validated by
    `CUSTOM_DATA_SCHEMA = vol.Schema({str: vol.Any(bool, str, int, float)})`).

    Every day of the week is covered from `00:00:00` to `24:00` — which
    `deserialize_to_time` turns into `time.max`, the "any time in the day is
    smaller" case — so the entity is `on` whatever day the suite runs on and
    the test needs no frozen clock.
    """

    made: list[str] = []

    async def _make(object_id: str, data: dict[str, Any] | None = None) -> str:
        block: dict[str, Any] = {"from": "00:00:00", "to": "24:00"}
        if data is not None:
            block["data"] = dict(data)
        assert await async_setup_component(
            hass,
            "schedule",
            {
                "schedule": {
                    object_id: {
                        "name": object_id,
                        "monday": [block],
                        "tuesday": [block],
                        "wednesday": [block],
                        "thursday": [block],
                        "friday": [block],
                        "saturday": [block],
                        "sunday": [block],
                    }
                }
            },
        )
        await hass.async_block_till_done()
        entity_id = f"schedule.{object_id}"
        state = hass.states.get(entity_id)
        assert state is not None and state.state == "on", (
            f"{entity_id} must be `on` for this fixture to mean anything; got {state!r}"
        )
        made.append(entity_id)
        return entity_id

    yield _make

    # A `Schedule` always arms a timer for its next event
    # (`Schedule._update` -> `async_track_point_in_utc_time`), and cancels it
    # only through the `async_on_remove(self._clean_up_listener)` its
    # `async_added_to_hass` registers. Removing the entity is therefore the
    # supported way to leave no lingering timer behind.
    component = hass.data.get(DATA_INSTANCES, {}).get("schedule")
    if component is not None:
        for entity_id in made:
            await component.async_remove_entity(entity_id)
    await hass.async_block_till_done()


async def explain(hass, **data):
    """Call `notify_switchboard.explain` the way a caller has to.

    Shared with `test_s4_explain.py`, which has its own copy; this one lives in
    `conftest.py` because three S6 files need it.
    """
    assert hass.services.has_service(DOMAIN, "explain"), (
        f"{DOMAIN}.explain must exist (contract v0.4, ADR-0018 §1)"
    )
    return await hass.services.async_call(
        DOMAIN, "explain", data, blocking=True, return_response=True
    )

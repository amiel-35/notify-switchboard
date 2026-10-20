"""Contract test (ADR-011, extended by ADR-0016): public names frozen by
docs/contract.md.

This is the one test file that mirrors what will become the guarded
`tests/acceptance/test_contract.py` in the real repository. It only checks
existence and shape of the public surface — never internal behaviour (that is
covered by test_s1_*.py / test_s2_*.py).

Extended for the v0.2 addendum (ADR-0016): the contract change that sprint
explicitly authorized was adding the five `notify_switchboard.*` UI services,
so this file is allowed to grow an assertion that they exist after setup —
the same discipline that guards the v0 names.

Extended again for the v0.3 addendum (ADR-0017): the two changes that sprint
authorized are `sensor.switchboard_deferred_today` entering the frozen names,
and the frozen entity ids being frozen *in every instance language* — `fr`
and `es` are `NATIVE_ENTITY_IDS` languages, so translating the entity names
without care renames the ids on exactly those instances.

Extended once more for the v0.4 addendum (ADR-0018): the change that sprint
authorized is a sixth, read-only service, `notify_switchboard.explain`. Its
name, its `SupportsResponse.ONLY` declaration and the keys of its response are
public surface — a card and a template are written against them — so they are
guarded here alongside the v0 names. What each key *means* is
`test_s4_explain.py`'s business, not this file's.

Extended a fourth time for the v0.5 addendum (ADR-0019): two more drop
reasons (`expired`, `not_notified`), the `data` keys `ttl_minutes` and
`switchboard_done`, and the default `tag` / `notification_id` a message
carries when the caller supplies none. Public strings, all of them: an
automation filters on a reason, a Companion channel filters on a tag. The four
`event.switchboard_delivery` event types are asserted, unchanged, by
`test_services_and_entities_exist_after_setup` above — v0.5 adds reasons, not
types. What each rule *does* is `test_s5_*.py`'s business.

Extended a fifth time for the v0.6 addendum (ADR-0020), which is the first one
that *removes* something. `class` leaves the routing-table row keys, so this
file pins its absence from what the router writes; the `ttl_minutes` defaults
are reclassified as defaults a minor version may change, so what is pinned is
the mechanism that makes them changeable and not the three numbers; and four
options-flow step ids become public names, because documents and cards link to
a step by its id. What each step *holds* is `test_s6_*_editor.py`'s business.

Extended a sixth time for the v0.7 addendum (ADR-0021), which both adds and
removes. It adds one frozen entity name (`sensor.switchboard_routing_table`),
one global option (`critical_payload`), two `explain` top-level keys
(`escalated`, `outputs`), two `acknowledged` payload keys (`user_id`,
`person`), and two new kinds of thing a `notify.*` name may be (an audience
entry, an output entity id). It removes one: `data.priority` no longer reaches
a `mobile_app_*` output, which is the only breaking change of 0.7.0 and is
pinned here rather than only in `test_s7_critical_payload.py`. What each rule
*does* is `test_s7_*.py`'s business.

Extended a seventh time for the v0.8 addendum (ADR-0022), which changes what
one public step asks and nothing a caller can observe at run time. The public
step id `target` holds four fields instead of five — `slug` is derived from
the name and never typed — with `observer_mode` on by default; the two
checkboxes `person_outputs` gains store nothing; a wake time typed without
seconds is still stored as `"HH:MM:SS"`. One v0.6 test was amended for that
and nothing else: `test_class_is_not_a_routing_table_row_key` no longer
submits a `slug` to `target`. What each screen *does* is `test_s8_*.py`'s
business.

Extended an eighth time for the v0.9 addendum (ADR-0023): one optional target
key (`done_priority`, absent meaning `normal`) and its ceiling on a done
message; `target_advanced` holds ten fields; one frozen blueprint path and its
six input names. What the ceiling *does* to each kind of done message is
`test_s9_done_priority.py`'s business; what the blueprint does,
`test_s9_blueprint.py`'s.

Extended a ninth time for the v0.10 addendum (ADR-0024): the integration
serves the dashboard cards at one frozen URL, and the two card types
dashboards name are frozen. What registering the resource does is
`tests/unit/test_cards.py`'s business.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import homeassistant.util.dt as dt_util
import pytest
from homeassistant.core import Context, SupportsResponse
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.notify_switchboard.const import DOMAIN

from .conftest import make_entry, make_person, make_target


async def test_services_and_entities_exist_after_setup(
    hass, enable_custom_integrations, install
):
    """After setup: notify.switchboard, notify.switchboard_<slug> per row, event and global/per-person entities."""
    persons = [
        make_person("person.alice", ["mobile_app_alice"]),
        make_person("person.bob", ["mobile_app_bob"]),
    ]
    targets = [
        make_target("leak", "Fuite d'eau", audience=["person.alice", "person.bob"]),
        make_target("garage", "Garage", audience=["person.alice"]),
    ]
    entry = make_entry(hass, persons=persons, targets=targets, default_target="leak")

    await install(entry)

    # --- legacy notify services (contract §"Names") ---
    assert hass.services.has_service("notify", "switchboard")
    assert hass.services.has_service("notify", "switchboard_leak")
    assert hass.services.has_service("notify", "switchboard_garage")

    # --- event entity with fixed event_types ---
    event_state = hass.states.get("event.switchboard_delivery")
    assert event_state is not None
    assert set(event_state.attributes["event_types"]) == {
        "routed",
        "dropped",
        "acknowledged",
        "snoozed",
    }

    # --- global diagnostic entities ---
    assert hass.states.get("sensor.switchboard_routed_today") is not None
    assert hass.states.get("sensor.switchboard_dropped_today") is not None
    # v0.3 addendum (ADR-0017): the deferral counter is a frozen name too.
    assert hass.states.get("sensor.switchboard_deferred_today") is not None

    # --- per-person entities (contract §3.5) ---
    for person_slug in ("alice", "bob"):
        assert hass.states.get(f"binary_sensor.{person_slug}_silenced") is not None
        assert hass.states.get(f"sensor.{person_slug}_last_notification") is not None
        assert hass.states.get(f"sensor.{person_slug}_active_snoozes") is not None


async def test_notify_entity_degraded_path_exists(
    hass, enable_custom_integrations, install
):
    """The NotifyEntity degraded path (`notify.switchboard` entity) exists alongside the legacy service."""
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("default", "Default", audience=["person.alice"])],
        default_target="default",
    )

    await install(entry)

    notify_entity_state = hass.states.get("notify.switchboard")
    assert notify_entity_state is not None
    assert hass.services.has_service("notify", "send_message")


async def test_domain_is_notify_switchboard() -> None:
    """The integration domain must never change without a major version (ADR-011)."""
    assert DOMAIN == "notify_switchboard"


async def test_ui_services_exist_after_setup(hass, enable_custom_integrations, install):
    """v0.2 addendum (ADR-0016): the five UI services are registered after setup."""
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Fuite d'eau", audience=["person.alice"])],
        default_target="leak",
    )

    await install(entry)

    for service in ("acknowledge", "snooze", "unsnooze", "silence", "unsilence"):
        assert hass.services.has_service(DOMAIN, service), (
            f"{DOMAIN}.{service} must exist after setup (contract v0.2, ADR-0016)"
        )


# v0.3 addendum (ADR-0017): the frozen names are frozen in every language.
FROZEN_ENTITY_IDS = (
    "binary_sensor.alice_silenced",
    "event.switchboard_delivery",
    "sensor.alice_active_snoozes",
    "sensor.alice_last_notification",
    "sensor.switchboard_deferred_today",
    "sensor.switchboard_dropped_today",
    "sensor.switchboard_routed_today",
    # v0.7 addendum (ADR-0021 §3): the routing table, for user interfaces.
    "sensor.switchboard_routing_table",
)


@pytest.mark.parametrize("language", ["fr", "es", "en"])
async def test_frozen_entity_ids_do_not_depend_on_the_instance_language(
    hass, enable_custom_integrations, install, language
):
    """v0.3 addendum (ADR-0017): translated names, English ids, in any language."""
    hass.config.language = language
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )

    await install(entry)

    for entity_id in FROZEN_ENTITY_IDS:
        assert hass.states.get(entity_id) is not None, (
            f"{entity_id} is a frozen public name and must exist verbatim on "
            f"a '{language}' instance (docs/contract.md, ADR-0011/ADR-0017)"
        )


# ---------------------------------------------------------------------------
# v0.4 addendum (ADR-0018): the read-only service and its response keys
# ---------------------------------------------------------------------------

# v0.7 addendum (ADR-0021 §8): `escalated` and `outputs` join the three keys
# v0.4 froze. Each person's value keeps exactly the six keys it always had.
EXPLAIN_RESPONSE_KEYS = {"target", "priority", "persons", "escalated", "outputs"}
EXPLAIN_PERSON_KEYS = {
    "decision",
    "until",
    "reason",
    "detail",
    "outputs",
    "missing_outputs",
}


async def test_explain_service_exists_and_only_answers(
    hass, enable_custom_integrations, install
):
    """v0.4 addendum (ADR-0018): a sixth service, declared `SupportsResponse.ONLY`."""
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )

    await install(entry)

    assert hass.services.has_service(DOMAIN, "explain"), (
        f"{DOMAIN}.explain must exist after setup (contract v0.4, ADR-0018)"
    )
    assert (
        hass.services.supports_response(DOMAIN, "explain") is SupportsResponse.ONLY
    ), (
        "`explain` answers and never acts, so it is registered "
        "`SupportsResponse.ONLY` (contract v0.4)"
    )


async def test_explain_response_carries_exactly_the_frozen_keys(
    hass, enable_custom_integrations, install, mock_outputs
):
    """The response shape is public surface: a card is written against it."""
    mock_outputs("mobile_app_alice")
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    response = await hass.services.async_call(
        DOMAIN, "explain", {"target": "leak"}, blocking=True, return_response=True
    )

    assert set(response) == EXPLAIN_RESPONSE_KEYS
    assert set(response["persons"]) == {"person.alice"}, (
        "`persons` is a mapping keyed by the `person.*` entity id (contract v0.4)"
    )
    assert set(response["persons"]["person.alice"]) == EXPLAIN_PERSON_KEYS


# ---------------------------------------------------------------------------
# v0.5 addendum (ADR-0019): two drop reasons, two `data` keys, one tag scheme
# ---------------------------------------------------------------------------

NIGHT = datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC)  # 23:30 Europe/Paris
MORNING = datetime(2026, 9, 11, 5, 5, tzinfo=dt_util.UTC)  # 07:05 Europe/Paris


async def test_expired_is_a_drop_reason_and_data_ttl_minutes_produces_it(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
    """`data.ttl_minutes` is a public input key; `expired` is a public reason."""
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    entry = make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.alice_night"],
                wake_time="07:00:00",
            )
        ],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )
    freezer.move_to(NIGHT)
    await install(entry)

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "good for a minute", "data": {"ttl_minutes": 1}},
        blocking=True,
    )
    await hass.async_block_till_done()

    freezer.move_to(MORNING)
    hass.states.async_set("input_boolean.alice_night", "off")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 0
    reasons = hass.states.get("sensor.switchboard_dropped_today").attributes["reasons"]
    assert "expired" in reasons, (
        "`expired` joins the frozen drop reasons in v0.5 (ADR-0019 §1)"
    )


async def test_not_notified_is_a_drop_reason_and_switchboard_done_produces_it(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert
):
    """`data.switchboard_done` is a public input key; `not_notified` a public reason."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    entry = make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.alice_night"],
            )
        ],
        targets=[
            make_target(
                "leak", "Leak", alert_entity="alert.leak", audience=["person.alice"]
            )
        ],
        default_target="leak",
    )
    alert = await real_alert("leak")
    await install(entry)

    # An episode Alice sleeps through: she is silenced, so she is told nothing.
    await alert.begin()
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "Leak!"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 0

    await alert.end()
    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "All good", "data": {"switchboard_done": True}},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 0
    reasons = hass.states.get("sensor.switchboard_dropped_today").attributes["reasons"]
    assert "not_notified" in reasons, (
        "`not_notified` joins the frozen drop reasons in v0.5 (ADR-0019 §5)"
    )


async def test_the_default_tag_and_notification_id_are_the_documented_values(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """`switchboard-<slug>` on every message, mirrored as the id in the UI."""
    calls = mock_outputs("mobile_app_alice", "persistent_notification")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice", "persistent_notification"])
        ],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)
    # `notify`'s own setup registers `notify.persistent_notification`
    # (core `components/notify/__init__.py`, `async_setup`) and replaces a mock
    # made earlier (`core.py`, `ServiceRegistry._async_register`), so the bare
    # output is mocked once the entry is up.
    calls["persistent_notification"] = async_mock_service(
        hass, "notify", "persistent_notification"
    )

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    assert calls["mobile_app_alice"][0].data["data"]["tag"] == "switchboard-leak"
    ui = calls["persistent_notification"][0].data["data"]
    assert ui["tag"] == "switchboard-leak"
    assert ui["notification_id"] == "switchboard-leak"


async def test_the_summary_tag_is_a_frozen_value(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
    """`switchboard-summary` is public: a Companion channel may key on it."""
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    entry = make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.alice_night"],
                wake_time="07:00:00",
            )
        ],
        targets=[
            make_target("a", "A", audience=["person.alice"]),
            make_target("b", "B", audience=["person.alice"]),
        ],
        default_target="a",
    )
    freezer.move_to(NIGHT)
    await install(entry)

    for slug in ("a", "b"):
        await hass.services.async_call(
            "notify", f"switchboard_{slug}", {"message": slug}, blocking=True
        )
        await hass.async_block_till_done()
        freezer.tick(timedelta(minutes=1))

    freezer.move_to(MORNING)
    hass.states.async_set("input_boolean.alice_night", "off")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1
    assert calls["mobile_app_alice"][0].data["data"]["tag"] == "switchboard-summary"


# ---------------------------------------------------------------------------
# v0.6 addendum (ADR-0020): one key removed, one classification, four step ids
# ---------------------------------------------------------------------------

# The four step ids `docs/contract.md` §v0.6 freezes. The pickers that lead to
# the advanced ones are internal and deliberately not listed.
PUBLIC_STEP_IDS = ("target", "target_advanced", "person_outputs", "person_advanced")


async def test_class_is_not_a_routing_table_row_key(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, set_person
):
    """v0.6 addendum (ADR-0020): the router never writes `class` again."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    entry = make_entry(hass, persons=[], targets=[], default_target=None)
    await install(entry)

    # The bootstrapped target (ADR-0018 §4) and a hand-made one: the two ways
    # a target can come into being, neither of which may produce the key.
    await options_flow(
        entry,
        "person",
        {"entity_id": "person.alice"},
        {"outputs": ["mobile_app_alice"]},
    )
    await options_flow(
        entry,
        "target",
        # v0.8 (ADR-0022 §1): the slug is derived from the name.
        {"name": "Leak", "audience": ["person.alice"]},
        {},
    )

    for row in entry.options["targets"]:
        assert "class" not in row, (
            "`class` left the routing-table row keys in v0.6 (ADR-0020 §4); "
            f"{row['slug']!r} still carries one"
        )


async def test_the_public_options_step_ids_exist(hass):
    """v0.6 addendum: four step ids documents and cards link to."""
    component = (
        Path(__file__).resolve().parents[2] / "custom_components" / "notify_switchboard"
    )
    steps = json.loads((component / "strings.json").read_text(encoding="utf-8"))[
        "options"
    ]["step"]

    for step_id in PUBLIC_STEP_IDS:
        assert step_id in steps, (
            f"{step_id!r} is a public step id (contract v0.6, ADR-0020 §1 and "
            "§2) and must exist, translated, with a title of its own"
        )
        assert steps[step_id].get("title"), f"{step_id!r} has no title"


async def test_the_ttl_defaults_are_defaults_a_household_can_change(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
    """v0.6 addendum: 120 / 720 / none are documented defaults, not frozen values.

    What is frozen is the mechanism: `entry.options["ttl_minutes"]` overrides
    them, priority by priority. A test that asserted the three numbers would be
    asserting exactly what ADR-0020 §5 says nobody may rely on, so this one
    asserts that stating a different number works.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    entry = make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.alice_night"],
                wake_time="07:00:00",
            )
        ],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
        # A `normal` message is worth 720 minutes by default; this household
        # says five.
        ttl_minutes={"normal": 5},
    )
    freezer.move_to(NIGHT)
    await install(entry)

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "stale by morning"}, blocking=True
    )
    await hass.async_block_till_done()

    freezer.move_to(MORNING)
    hass.states.async_set("input_boolean.alice_night", "off")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 0, (
        "the household's own `ttl_minutes` decides, not the documented "
        "default (contract v0.6, ADR-0020 §5)"
    )
    reasons = hass.states.get("sensor.switchboard_dropped_today").attributes["reasons"]
    assert "expired" in reasons


# ---------------------------------------------------------------------------
# v0.7 addendum (ADR-0021): one entity, one option, two payload keys — and one
# key that stops reaching a Companion output
# ---------------------------------------------------------------------------


async def test_the_routing_table_entity_exists_after_setup(
    hass, enable_custom_integrations, install, mock_outputs
):
    """v0.7 addendum: one more frozen global name, with its two closed lists."""
    mock_outputs("mobile_app_alice")
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )

    await install(entry)

    state = hass.states.get("sensor.switchboard_routing_table")
    assert state is not None, (
        "`sensor.switchboard_routing_table` is a frozen public name "
        "(contract v0.7, ADR-0021 §3)"
    )
    assert set(state.attributes) >= {"targets", "persons"}


async def test_data_priority_no_longer_reaches_a_mobile_app_output(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The one breaking change of 0.7.0, pinned as such.

    `data.priority` is the router's own input key — it selects the effective
    priority — and has never been a Companion key. Android's Companion app
    reads `data.priority` and understands exactly one value, `high`, which is
    the value the router now writes itself on a critical message.
    """
    calls = mock_outputs("mobile_app_alice", "kitchen_speaker")
    set_person("person.alice", "home")
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice", "kitchen_speaker"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "m", "data": {"priority": "high"}},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert "priority" not in calls["mobile_app_alice"][0].data.get("data", {}), (
        "`data.priority` is stripped from a `mobile_app_*` output "
        "(contract v0.7, §Breaking)"
    )
    assert calls["kitchen_speaker"][0].data["data"]["priority"] == "high", (
        "every other output keeps receiving it: it is the caller's key and the "
        "router is a proxy"
    )


async def test_critical_payload_is_a_global_option_defaulting_to_on(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """`entry.options["critical_payload"]`: absent means on, `false` means off."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "leak", "Leak", audience=["person.alice"], default_priority="critical"
            )
        ],
        default_target="leak",
        # Absent on purpose: the default is on.
    )
    await install(entry)

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    data = calls["mobile_app_alice"][0].data.get("data", {})
    assert "push" in data or "channel" in data, (
        "with no `critical_payload` key in the options, a critical message "
        "carries the Companion critical keys (contract v0.7, ADR-0021 §7)"
    )


async def test_the_acknowledged_payload_carries_user_id_and_person(
    hass, enable_custom_integrations, install, mock_outputs, real_alert
):
    """v0.7 addendum: two keys join the frozen `acknowledged` payload."""
    mock_outputs("mobile_app_alice")
    hass.states.async_set("person.alice", "home", {"user_id": "user-alice"})
    await real_alert("leak")
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "leak",
                "Leak",
                alert_entity="alert.leak",
                allow_acknowledge=True,
                audience=["person.alice"],
            )
        ],
        default_target="leak",
    )
    await install(entry)

    await hass.services.async_call(
        DOMAIN,
        "acknowledge",
        {"target": "leak"},
        blocking=True,
        context=Context(user_id="user-alice"),
    )
    await hass.async_block_till_done()

    payload = hass.states.get("event.switchboard_delivery").attributes
    assert payload["event_type"] == "acknowledged"
    assert payload["user_id"] == "user-alice"
    assert payload["person"] == "person.alice"


async def test_a_notify_service_may_be_an_audience_entry(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """v0.7 addendum: an audience entry in the `notify` domain is a bare output."""
    calls = mock_outputs("kitchen_speaker")
    set_person("person.alice", "home")
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target("leak", "Leak", audience=["notify.kitchen_speaker"]),
        ],
        default_target="leak",
    )
    await install(entry)

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(calls["kitchen_speaker"]) == 1, (
        "an `audience` entry that is a `notify.*` service name is a public "
        "input shape from v0.7 (ADR-0021 §5)"
    )


async def test_a_notify_entity_id_may_be_an_output(
    hass, enable_custom_integrations, install, set_person, notify_entity
):
    """v0.7 addendum: an output that is a `notify` entity id is a public input shape."""
    set_person("person.alice", "home")
    living_room = await notify_entity("living_room")
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["notify.living_room"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    assert [message for message, _title, _extra in living_room.messages] == ["m"], (
        "an output that is a `notify` entity id is delivered with "
        "`notify.send_message` (contract v0.7, ADR-0021 §6)"
    )


# ---------------------------------------------------------------------------
# v0.8 addendum (ADR-0022): `target` asks four things, two checkboxes store
# nothing, a wake time without seconds
# ---------------------------------------------------------------------------

# The fields of the public step id `target`, in the order the form shows them.
TARGET_STEP_FIELDS = ["name", "alert_entity", "audience", "observer_mode"]


async def test_the_target_step_holds_the_four_frozen_fields(
    hass, enable_custom_integrations, install, options_flow
):
    """v0.8 addendum: `slug` left `target`; `observer_mode` defaults to on."""
    entry = make_entry(hass, persons=[], targets=[], default_target=None)
    await install(entry)

    result = await options_flow(entry, "target")

    assert result["step_id"] == "target"
    fields = {str(marker): marker for marker in result["data_schema"].schema}
    assert list(fields) == TARGET_STEP_FIELDS, (
        "the public step `target` holds name, alert_entity, audience and "
        "observer_mode (contract v0.8, ADR-0022 §1)"
    )
    assert fields["observer_mode"].default() is True, (
        "`observer_mode` defaults to true on `target` (contract v0.8)"
    )


async def test_a_created_target_gets_its_slug_from_its_name(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, set_person
):
    """v0.8 addendum: `slugify(name)`, and `notify.switchboard_<slug>` follows."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[],
        default_target=None,
    )
    await install(entry)

    await options_flow(
        entry,
        "target",
        {"name": "Water leak", "audience": ["person.alice"], "observer_mode": False},
        {},
    )

    assert [row["slug"] for row in entry.options["targets"]] == ["water_leak"]
    await hass.services.async_call(
        "notify", "switchboard_water_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 1


async def test_the_person_checkboxes_store_nothing_and_wake_time_keeps_its_shape(
    hass, enable_custom_integrations, install, options_flow, mock_outputs
):
    """v0.8 addendum: a stored person has exactly the keys it had in v0.7."""
    mock_outputs("mobile_app_alice")
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    await options_flow(
        entry,
        "edit_person",
        {"entity_id": "person.alice"},
        {
            "outputs": ["mobile_app_alice"],
            "silence_entities": [],
            "night_schedule": False,
            "advanced": True,
        },
        {"wake_time": "7:30"},
    )

    (person,) = entry.options["persons"]
    assert set(person) == {"entity_id", "outputs", "silence_entities", "wake_time"}, (
        "`night_schedule` and `advanced` are actions, never stored (contract v0.8)"
    )
    assert person["wake_time"] == "07:30:00", (
        "a wake time typed without seconds is stored as `HH:MM:SS` (contract v0.8)"
    )


# ---------------------------------------------------------------------------
# v0.9 addendum (ADR-0023): `done_priority`, ten fields on `target_advanced`,
# one frozen blueprint
# ---------------------------------------------------------------------------

# The fields of the public step id `target_advanced`, in the order the form
# shows them (contract v0.9 amends the v0.6 row).
TARGET_ADVANCED_STEP_FIELDS = [
    "default_priority",
    "presence_rule",
    "allow_acknowledge",
    "snooze_minutes",
    "default_data",
    "message",
    "done_message",
    "done_priority",
    "default_title",
    "clear_done",
]


async def test_target_advanced_holds_the_ten_frozen_fields(
    hass, enable_custom_integrations, install, options_flow
):
    """v0.9 addendum: `done_priority` joins `target_advanced`, default `normal`."""
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    result = await options_flow(
        entry,
        "edit_target",
        {"slug": "leak"},
        {"name": "Leak", "audience": ["person.alice"], "advanced": True},
    )

    assert result["step_id"] == "target_advanced"
    fields = {str(marker): marker for marker in result["data_schema"].schema}
    assert list(fields) == TARGET_ADVANCED_STEP_FIELDS, (
        "contract v0.9: `target_advanced` holds ten fields"
    )
    assert fields["done_priority"].default() == "normal"


async def test_done_priority_is_written_only_when_it_is_not_normal(
    hass, enable_custom_integrations, install, options_flow
):
    """v0.9 addendum: absent means `normal`, so a 0.8 row stays a 0.8 row."""
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)
    basic = {"name": "Leak", "audience": ["person.alice"], "advanced": True}

    await options_flow(
        entry, "edit_target", {"slug": "leak"}, basic, {"done_priority": "normal"}
    )
    (row,) = entry.options["targets"]
    assert "done_priority" not in row

    await options_flow(
        entry, "edit_target", {"slug": "leak"}, basic, {"done_priority": "critical"}
    )
    (row,) = entry.options["targets"]
    assert row["done_priority"] == "critical"


async def test_an_absent_done_priority_caps_a_done_message_at_normal(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """v0.9 addendum: the documented default, observed on a `critical` target."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    await install(
        make_entry(
            hass,
            persons=[make_person("person.alice", ["mobile_app_alice"])],
            targets=[
                make_target(
                    "leak",
                    "Leak",
                    default_priority="critical",
                    audience=["person.alice"],
                )
            ],
            default_target="leak",
        )
    )

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "All clear", "data": {"switchboard_done": True}},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get("event.switchboard_delivery")
    assert state.attributes["priority"] == "normal"


def test_the_blueprint_path_and_inputs_are_frozen():
    """v0.9 addendum: automations name the path and the six inputs."""
    from homeassistant.util.yaml import load_yaml_dict  # noqa: PLC0415

    component = (
        Path(__file__).resolve().parents[2] / "custom_components" / "notify_switchboard"
    )
    for language in ("en", "fr", "es"):
        path = component / "blueprints" / language / "alert_from_a_sensor.yaml"
        data = load_yaml_dict(str(path))
        assert data["blueprint"]["domain"] == "automation"
        assert list(data["blueprint"]["input"]) == [
            "trigger_entity",
            "trigger_to",
            "alert_name",
            "message",
            "done_message",
            "priority",
        ], f"{language}: the six frozen inputs, in this order (contract v0.9)"


# ---------------------------------------------------------------------------
# v0.10 addendum (ADR-0024): the cards ship with the integration
# ---------------------------------------------------------------------------


def test_the_cards_url_and_types_are_frozen():
    """v0.10 addendum: one URL for the bundle, two card types dashboards name."""
    from custom_components.notify_switchboard import cards  # noqa: PLC0415

    assert cards.CARDS_URL == "/notify_switchboard/notify-switchboard-cards.js"
    bundle = (cards.CARDS_DIR / cards.CARDS_FILENAME).read_text(encoding="utf-8")
    for card_type in ("switchboard-alerts-card", "switchboard-silence-tile"):
        assert f'customElements.define("{card_type}"' in bundle, (
            f"`custom:{card_type}` is a frozen card type (contract v0.10)"
        )

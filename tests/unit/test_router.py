"""Unit tests for the pure decision engine in `router.py`."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest

from custom_components.notify_switchboard.const import (
    DROP_NO_OUTPUTS,
    DROP_NOT_IN_AUDIENCE,
    DROP_NOT_NOTIFIED,
    DROP_PRESENCE,
    DROP_RECURSION,
    DROP_SILENCED,
    DROP_SNOOZED,
    DROP_UNKNOWN_PERSON,
    DROP_UNKNOWN_TARGET,
    PRIORITY_CRITICAL,
    PRIORITY_HIGH,
    PRIORITY_INFO,
    PRIORITY_NORMAL,
    UNCOUNTED_DROP_REASONS,
)
from custom_components.notify_switchboard.router import (
    NotificationRequest,
    ParsedAction,
    PersonConfig,
    RoutingContext,
    RoutingTable,
    TargetConfig,
    acknowledge_action,
    build_actions,
    build_routing_table,
    caller_tag,
    collapse_by_tag,
    critical_keys_for_os,
    decide,
    default_tag,
    effective_priority,
    effective_tag,
    escalate_one_step,
    is_bare_output,
    is_done_message,
    is_recursive_output,
    merge_data,
    nobody_is_home,
    parse_action,
    parse_min_priority,
    parse_person,
    parse_target,
    parse_wake_time,
    presence_allows,
    resolve_priority,
    resolve_ttl,
    silence_catches,
    silences_catching,
    snooze_action,
    snooze_is_active,
    split_outputs,
    state_is_on,
    summary_data,
)

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def person(entity_id: str, **kwargs) -> PersonConfig:
    """Build a person for a test table."""
    return PersonConfig(entity_id=entity_id, **kwargs)


def target(slug: str, **kwargs) -> TargetConfig:
    """Build a routing-table row for a test table."""
    kwargs.setdefault("name", slug.title())
    return TargetConfig(slug=slug, **kwargs)


def table(persons: list[PersonConfig], targets: list[TargetConfig]) -> RoutingTable:
    """Build a routing table from lists."""
    return RoutingTable(
        persons={item.entity_id: item for item in persons},
        targets={item.slug: item for item in targets},
        default_target=targets[0].slug if targets else None,
    )


def context(**kwargs) -> RoutingContext:
    """Build a routing context anchored on a fixed `now`."""
    kwargs.setdefault("now", NOW)
    return RoutingContext(**kwargs)


def request(slugs: tuple[str, ...] = ("leak",), **kwargs) -> NotificationRequest:
    """Build a notification request."""
    kwargs.setdefault("message", "water")
    return NotificationRequest(targets=slugs, **kwargs)


# ---------------------------------------------------------------------------
# Options parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("07:00:00", time(7, 0)),
        ("07:00", time(7, 0)),
        ("7", None),
        ("nonsense", None),
        ("25:00:00", None),
        (time(6, 30), time(6, 30)),
    ],
)
def test_parse_wake_time(raw, expected) -> None:
    """Wake times are parsed leniently and never raise."""
    assert parse_wake_time(raw) == expected


def test_parse_person_normalises_every_list() -> None:
    """Missing keys become empty tuples rather than None."""
    parsed = parse_person({"entity_id": "person.alice"})
    assert parsed.outputs == ()
    assert parsed.silence_entities == ()
    assert parsed.wake_time is None
    assert parsed.object_id == "alice"


def test_parse_person_strips_the_notify_prefix_from_outputs() -> None:
    """`notify.mobile_app_x` and `mobile_app_x` name the same output."""
    parsed = parse_person(
        {
            "entity_id": "person.alice",
            "outputs": ["notify.mobile_app_alice", "persistent_notification"],
        }
    )
    assert parsed.outputs == ("mobile_app_alice", "persistent_notification")


def test_prefixed_outputs_behave_exactly_like_bare_ones() -> None:
    """Every consumer of `outputs` sees the same value for both spellings."""
    prefixed = build_routing_table(
        {
            "persons": [
                {"entity_id": "person.alice", "outputs": ["notify.mobile_app_alice"]}
            ],
            "targets": [{"slug": "leak", "name": "Leak", "audience": ["person.alice"]}],
            "default_target": "leak",
        }
    )
    bare = build_routing_table(
        {
            "persons": [{"entity_id": "person.alice", "outputs": ["mobile_app_alice"]}],
            "targets": [{"slug": "leak", "name": "Leak", "audience": ["person.alice"]}],
            "default_target": "leak",
        }
    )
    assert prefixed == bare

    # Person resolution (dispatcher `_resolve_persons`) works on the bare name.
    owner = prefixed.person_for_output("mobile_app_alice")
    assert owner is not None and owner.entity_id == "person.alice"
    assert prefixed.person_for_output("notify.mobile_app_alice") == owner

    # Companion-button gating and the recursion check see the bare name too.
    ctx = context(person_states={"person.alice": "home"})
    decision = decide(prefixed, request(), ctx)
    assert decision.routed[0].outputs == ("mobile_app_alice",)


def test_parse_person_strips_the_prefix_before_the_recursion_check() -> None:
    """`notify.switchboard_x` is recursive whichever spelling was configured."""
    parsed = parse_person(
        {"entity_id": "person.eve", "outputs": ["notify.switchboard_loop"]}
    )
    assert parsed.outputs == ("switchboard_loop",)
    assert split_outputs(parsed.outputs) == ((), ("switchboard_loop",))


def test_person_object_id_without_a_domain() -> None:
    """A malformed entity id still yields a usable object_id."""
    assert person("alice").object_id == "alice"


def test_parse_target_slugifies_and_falls_back() -> None:
    """Accents and apostrophes are slugified; bad enums fall back."""
    parsed = parse_target(
        {
            "slug": "Fuite d'eau à l'étage",
            "default_priority": "urgent",
            "presence_rule": "sometimes",
        }
    )
    assert parsed.slug == "fuite_d_eau_a_l_etage"
    assert parsed.name == "fuite_d_eau_a_l_etage"
    assert parsed.default_priority == PRIORITY_NORMAL
    assert parsed.presence_rule == "always"
    assert parsed.service_name == "switchboard_fuite_d_eau_a_l_etage"


def test_build_routing_table_skips_malformed_rows() -> None:
    """A hand-edited storage file must not stop the entry from loading."""
    built = build_routing_table(
        {
            "persons": [{"entity_id": "person.alice"}, {}, "not a dict"],
            "targets": [{"slug": "leak", "name": "Leak"}, {"name": "no slug"}],
            "default_target": "does_not_exist",
        }
    )
    assert list(built.persons) == ["person.alice"]
    assert list(built.targets) == ["leak"]
    # An unusable default falls back to the first known row.
    assert built.default_target == "leak"


def test_build_routing_table_without_targets_has_no_default() -> None:
    """An empty table has no default target."""
    built = build_routing_table({"persons": [], "targets": [], "default_target": None})
    assert built.default_target is None


def test_person_for_output_is_none_when_ambiguous() -> None:
    """Two people sharing an output cannot be told apart."""
    built = table(
        [
            person("person.alice", outputs=("shared",)),
            person("person.bob", outputs=("shared",)),
        ],
        [target("leak", audience=("person.alice",))],
    )
    assert built.person_for_output("shared") is None
    assert built.person_for_output("unknown") is None


def test_person_for_output_resolves_a_single_owner() -> None:
    """A unique owner is returned."""
    built = table(
        [person("person.alice", outputs=("mobile_app_alice",))],
        [target("leak", audience=("person.alice",))],
    )
    owner = built.person_for_output("mobile_app_alice")
    assert owner is not None
    assert owner.entity_id == "person.alice"


# ---------------------------------------------------------------------------
# Decision primitives
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("switchboard", True),
        ("notify.switchboard", True),
        ("switchboard_leak", True),
        ("notify.switchboard_leak", True),
        ("mobile_app_alice", False),
        ("switchboardish", False),
    ],
)
def test_is_recursive_output(output, expected) -> None:
    """Only services of this integration count as recursion."""
    assert is_recursive_output(output) is expected


@pytest.mark.parametrize(
    ("rule", "state", "expected"),
    [
        ("always", "home", True),
        ("always", None, True),
        ("home_only", "home", True),
        ("home_only", "not_home", False),
        ("home_only", None, False),
        ("away_only", "not_home", True),
        ("away_only", "home", False),
        ("unknown_rule", "home", True),
    ],
)
def test_presence_allows(rule, state, expected) -> None:
    """Presence rules read the bare `person.*` state."""
    assert presence_allows(rule, state) is expected


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, PRIORITY_HIGH),
        ({"priority": PRIORITY_CRITICAL}, PRIORITY_CRITICAL),
        ({"priority": "made_up"}, PRIORITY_HIGH),
        ({"priority": 3}, PRIORITY_HIGH),
        ({"priority": PRIORITY_INFO}, PRIORITY_INFO),
    ],
)
def test_resolve_priority(data, expected) -> None:
    """`data.priority` overrides the row only when it is a known value."""
    row = target("leak", default_priority=PRIORITY_HIGH)
    assert resolve_priority(row, data) == expected


def test_merge_data_lets_the_caller_win() -> None:
    """Row defaults sit under the caller's data."""
    row = target("leak", default_data={"channel": "family", "sticky": True})
    assert merge_data(row, {"channel": "override"}) == {
        "channel": "override",
        "sticky": True,
    }


def test_snooze_is_active_only_before_expiry() -> None:
    """A snooze in the past no longer blocks."""
    live = context(snoozes={("person.alice", "leak"): NOW + timedelta(minutes=1)})
    stale = context(snoozes={("person.alice", "leak"): NOW - timedelta(minutes=1)})
    assert snooze_is_active("person.alice", "leak", live) is True
    assert snooze_is_active("person.alice", "leak", stale) is False
    assert snooze_is_active("person.bob", "leak", live) is False


def test_split_outputs() -> None:
    """Recursive outputs are separated from usable ones."""
    usable, recursive = split_outputs(("mobile_app_alice", "switchboard_leak"))
    assert usable == ("mobile_app_alice",)
    assert recursive == ("switchboard_leak",)


@pytest.mark.parametrize(
    ("state", "expected"), [("on", True), ("off", False), (None, False)]
)
def test_state_is_on(state, expected) -> None:
    """Only the literal `on` state means silent."""
    assert state_is_on(state) is expected


def test_request_tag() -> None:
    """`data.tag` is exposed as a string, or None."""
    assert request(data={"tag": "t1"}).tag == "t1"
    assert request(data={"tag": 7}).tag == "7"
    assert request().tag is None


# ---------------------------------------------------------------------------
# decide()
# ---------------------------------------------------------------------------


def test_decide_routes_to_every_audience_member() -> None:
    """The happy path: everyone in the audience is routed."""
    built = table(
        [
            person("person.alice", outputs=("mobile_app_alice",)),
            person("person.bob", outputs=("mobile_app_bob",)),
        ],
        [
            target(
                "leak",
                audience=("person.alice", "person.bob"),
                default_data={"channel": "family"},
            )
        ],
    )
    decision = decide(
        built,
        request(data={"tag": "t1"}),
        context(person_states={"person.alice": "home", "person.bob": "home"}),
    )
    assert [item.person for item in decision.routed] == [
        "person.alice",
        "person.bob",
    ]
    assert decision.routed[0].data == {"channel": "family", "tag": "t1"}
    assert decision.dropped == ()


def test_decide_drops_unknown_target() -> None:
    """An unknown slug is dropped, with nobody considered."""
    built = table(
        [person("person.alice", outputs=("mobile_app_alice",))],
        [target("leak", audience=("person.alice",))],
    )
    decision = decide(built, request(("ghost",)), context())
    assert decision.routed == ()
    assert [item.reason for item in decision.dropped] == [DROP_UNKNOWN_TARGET]
    assert decision.dropped[0].person is None


def test_decide_drops_on_presence() -> None:
    """`home_only` skips the person who is away."""
    built = table(
        [
            person("person.alice", outputs=("mobile_app_alice",)),
            person("person.bob", outputs=("mobile_app_bob",)),
        ],
        [
            target(
                "leak",
                audience=("person.alice", "person.bob"),
                presence_rule="home_only",
            )
        ],
    )
    decision = decide(
        built,
        request(),
        context(person_states={"person.alice": "home", "person.bob": "not_home"}),
    )
    assert [item.person for item in decision.routed] == ["person.alice"]
    assert [(item.person, item.reason) for item in decision.dropped] == [
        ("person.bob", DROP_PRESENCE)
    ]


def test_decide_drops_when_silenced_unless_critical() -> None:
    """Silence blocks everything but `critical`."""
    built = table(
        [
            person(
                "person.alice",
                outputs=("mobile_app_alice",),
                silence_entities=("input_boolean.night",),
            )
        ],
        [target("leak", audience=("person.alice",))],
    )
    # v0.7 (ADR-0021 §2): `silenced` holds the entities that are **on**, each
    # mapped to the floor it publishes -- `None` for a silence that publishes
    # none, which is every silence before 0.7.0.
    ctx = context(
        person_states={"person.alice": "home"},
        silenced={"input_boolean.night": None},
    )
    silenced = decide(built, request(), ctx)
    assert silenced.routed == ()
    assert silenced.dropped[0].reason == DROP_SILENCED

    critical = decide(built, request(data={"priority": PRIORITY_CRITICAL}), ctx)
    assert [item.person for item in critical.routed] == ["person.alice"]


def test_decide_drops_when_snoozed_unless_critical() -> None:
    """An active snooze blocks everything but `critical`."""
    built = table(
        [person("person.alice", outputs=("mobile_app_alice",))],
        [target("leak", audience=("person.alice",))],
    )
    ctx = context(
        person_states={"person.alice": "home"},
        snoozes={("person.alice", "leak"): NOW + timedelta(hours=1)},
    )
    assert decide(built, request(), ctx).dropped[0].reason == DROP_SNOOZED
    assert decide(built, request(data={"priority": PRIORITY_CRITICAL}), ctx).routed


def test_decide_rejects_recursion_without_calling_anything() -> None:
    """An output pointing back at the switchboard is dropped, not followed."""
    built = table(
        [person("person.eve", outputs=("switchboard_loop",))],
        [target("loop", audience=("person.eve",))],
    )
    decision = decide(
        built, request(("loop",)), context(person_states={"person.eve": "home"})
    )
    assert decision.routed == ()
    assert [item.reason for item in decision.dropped] == [DROP_RECURSION]


def test_decide_keeps_the_usable_outputs_and_still_reports_recursion() -> None:
    """A partially recursive output list still delivers, and still warns."""
    built = table(
        [person("person.eve", outputs=("switchboard_loop", "mobile_app_eve"))],
        [target("loop", audience=("person.eve",))],
    )
    decision = decide(
        built, request(("loop",)), context(person_states={"person.eve": "home"})
    )
    assert decision.routed[0].outputs == ("mobile_app_eve",)
    assert [item.reason for item in decision.dropped] == [DROP_RECURSION]


def test_decide_drops_a_person_with_no_outputs() -> None:
    """Somebody with no notify service cannot be reached."""
    built = table(
        [person("person.alice")],
        [target("leak", audience=("person.alice",))],
    )
    decision = decide(built, request(), context(person_states={"person.alice": "home"}))
    assert [item.reason for item in decision.dropped] == [DROP_NO_OUTPUTS]


def test_decide_reports_people_outside_the_audience() -> None:
    """Persons outside the audience are recorded, not routed."""
    built = table(
        [
            person("person.alice", outputs=("mobile_app_alice",)),
            person("person.bob", outputs=("mobile_app_bob",)),
        ],
        [target("leak", audience=("person.alice",))],
    )
    decision = decide(
        built,
        request(),
        context(person_states={"person.alice": "home", "person.bob": "home"}),
    )
    assert [item.person for item in decision.routed] == ["person.alice"]
    assert [(item.person, item.reason) for item in decision.dropped] == [
        ("person.bob", DROP_NOT_IN_AUDIENCE)
    ]


def test_decide_reports_an_audience_member_missing_from_the_table() -> None:
    """A row naming an unknown person is a counted `unknown_person` drop."""
    built = table(
        [person("person.alice", outputs=("mobile_app_alice",))],
        [target("leak", audience=("person.alice", "person.ghost"))],
    )
    decision = decide(built, request(), context(person_states={"person.alice": "home"}))
    assert ("person.ghost", DROP_UNKNOWN_PERSON) in [
        (item.person, item.reason) for item in decision.dropped
    ]
    # It is a real loss, so unlike `not_in_audience` it must be counted.
    assert DROP_UNKNOWN_PERSON not in UNCOUNTED_DROP_REASONS
    assert DROP_NOT_IN_AUDIENCE in UNCOUNTED_DROP_REASONS


def test_decide_handles_several_targets_in_one_call() -> None:
    """`target: [a, b]` is routed row by row."""
    built = table(
        [person("person.alice", outputs=("mobile_app_alice",))],
        [
            target("leak", audience=("person.alice",)),
            target("garage", audience=("person.alice",)),
        ],
    )
    decision = decide(
        built,
        request(("leak", "garage")),
        context(person_states={"person.alice": "home"}),
    )
    assert [item.slug for item in decision.routed] == ["leak", "garage"]


def test_decide_with_no_target_routes_nothing() -> None:
    """An empty target list is a no-op, not a crash."""
    built = table(
        [person("person.alice", outputs=("mobile_app_alice",))],
        [target("leak", audience=("person.alice",))],
    )
    decision = decide(built, request(()), context())
    assert decision == decide(built, request(()), context())
    assert decision.routed == ()
    assert decision.dropped == ()


# ---------------------------------------------------------------------------
# Companion actions
# ---------------------------------------------------------------------------


def test_build_actions_full_row() -> None:
    """A row with an alert and durations gets every button."""
    row = target(
        "leak",
        alert_entity="alert.leak",
        allow_acknowledge=True,
        snooze_minutes=(15, 60),
    )
    actions = build_actions(row, {"acknowledge": "Vu", "snooze_15": "15 min"}, False)
    assert [item["action"] for item in actions] == [
        "switchboard:ack:leak",
        "switchboard:snooze:leak:15",
        "switchboard:snooze:leak:60",
    ]
    assert actions[0]["title"] == "Vu"
    assert actions[1]["title"] == "15 min"
    # No label for 60: the generic fallback is used.
    assert actions[2]["title"] == "Snooze 60"
    assert "authenticationRequired" not in actions[0]


def test_build_actions_requires_an_alert_to_acknowledge() -> None:
    """`allow_acknowledge` without an alert yields no Acknowledge button."""
    row = target("leak", allow_acknowledge=True, snooze_minutes=())
    assert build_actions(row, {}, False) == []


def test_build_actions_marks_authentication() -> None:
    """High and critical rows require unlocking the phone."""
    row = target(
        "leak", alert_entity="alert.leak", allow_acknowledge=True, snooze_minutes=(15,)
    )
    actions = build_actions(row, {}, True)
    assert all(item["authenticationRequired"] is True for item in actions)


def test_action_ids_round_trip() -> None:
    """Every id this module builds is one it can parse back."""
    assert parse_action(acknowledge_action("leak")) == ParsedAction("ack", "leak")
    assert parse_action(snooze_action("leak", 60)) == ParsedAction("snooze", "leak", 60)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        7,
        "",
        "switchboard",
        "switchboard:ack",
        "other:ack:leak",
        "switchboard:explode:leak",
        "switchboard:ack:leak:60",
        "switchboard:snooze:leak",
        "switchboard:snooze:leak:soon",
        "switchboard:snooze:leak:0",
        "switchboard:snooze:leak:-5",
        "switchboard:snooze:leak:60:extra",
    ],
)
def test_parse_action_rejects_anything_else(raw) -> None:
    """Forged or malformed action ids are ignored."""
    assert parse_action(raw) is None


# ---------------------------------------------------------------------------
# v0.5 primitives (contract v0.5, ADR-0019)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("priority", "data", "mapping", "expected"),
    [
        # The documented per-priority defaults, with no mapping at all.
        (PRIORITY_INFO, {}, None, timedelta(minutes=120)),
        (PRIORITY_NORMAL, {}, None, timedelta(minutes=720)),
        (PRIORITY_HIGH, {}, None, None),
        # `critical` has no entry and can be given none: never deferred, so
        # never expired.
        (PRIORITY_CRITICAL, {}, None, None),
        # A mapping overrides the default for the priorities it names...
        (PRIORITY_HIGH, {}, {"high": 5}, timedelta(minutes=5)),
        # ...an explicit null means "never"...
        (PRIORITY_INFO, {}, {"info": None}, None),
        # ...a `0` in the mapping is read as null (it would mean "expired
        # before it was queued")...
        (PRIORITY_INFO, {}, {"info": 0}, None),
        # ...and a priority the mapping does not name keeps its default.
        (PRIORITY_INFO, {}, {"normal": 5}, timedelta(minutes=120)),
        # The per-call key wins over both, in both directions.
        (PRIORITY_HIGH, {"ttl_minutes": 5}, {"high": None}, timedelta(minutes=5)),
        (PRIORITY_INFO, {"ttl_minutes": 0}, None, None),
        # A value that is not a duration is a configuration mistake, not a
        # promise: the mapping and then the default answer instead.
        (PRIORITY_INFO, {"ttl_minutes": "soon"}, None, timedelta(minutes=120)),
        (PRIORITY_INFO, {"ttl_minutes": True}, None, timedelta(minutes=120)),
        (PRIORITY_INFO, {}, {"info": "soon"}, None),
    ],
)
def test_resolve_ttl(priority, data, mapping, expected) -> None:
    """`data.ttl_minutes`, then the option, then the documented default."""
    assert resolve_ttl(priority, data, mapping) == expected


def test_default_and_effective_tags() -> None:
    """Every message gets a name; a caller's own always wins."""
    assert default_tag("leak") == "switchboard-leak"
    assert default_tag("leak", done=True) == "switchboard-leak-done"
    assert effective_tag("leak", {}) == "switchboard-leak"
    assert effective_tag("leak", {"switchboard_done": True}) == "switchboard-leak-done"
    assert effective_tag("leak", {"tag": "mine"}) == "mine"
    # An empty tag is not a name, so the default still fills the gap.
    assert effective_tag("leak", {"tag": ""}) == "switchboard-leak"


def test_caller_tag_tells_a_callers_name_from_the_routers_default() -> None:
    """The two do not travel to the same outputs (ADR-0019 §6, amendment (2))."""
    assert caller_tag({"tag": "mine"}) == "mine"
    assert caller_tag({"tag": 7}) == "7"
    assert caller_tag({}) is None
    # Same reading of "not a name" as `effective_tag`.
    assert caller_tag({"tag": ""}) is None
    assert caller_tag({"tag": None}) is None


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, False),
        ({"switchboard_done": False}, False),
        ({"switchboard_done": True}, True),
    ],
)
def test_is_done_message(data, expected) -> None:
    """`data.switchboard_done` is the public marker, and nothing else is."""
    assert is_done_message(data) is expected
    assert NotificationRequest(message="m", data=dict(data)).is_done is expected


def test_collapse_by_tag_keeps_the_last_of_each_tag_in_place() -> None:
    """A collapsed group is represented by its newest member, at its position."""
    items = [("x", "first"), ("y", "second"), ("x", "third"), ("z", "fourth")]
    assert collapse_by_tag(items) == ["second", "third", "fourth"]


def test_summary_data_is_built_not_merged() -> None:
    """Only the switchboard's own keys survive into a digest."""
    assert summary_data(
        [
            {"tag": "x", "channel": "family", "actions": [{"action": "a"}]},
            {"switchboard_done": True, "priority": "high"},
            {"switchboard_done": False},
        ]
    ) == {"tag": "switchboard-summary", "switchboard_done": False}


def test_a_done_message_reaches_only_the_episodes_recipients() -> None:
    """`not_notified` is decided before the rest of the routing decision."""
    table = RoutingTable(
        persons={
            "person.alice": PersonConfig("person.alice", ("mobile_app_alice",)),
            "person.bob": PersonConfig("person.bob", ("mobile_app_bob",)),
        },
        targets={
            "leak": TargetConfig(
                slug="leak",
                name="Leak",
                alert_entity="alert.leak",
                audience=("person.alice", "person.bob"),
            )
        },
        default_target="leak",
    )
    context = RoutingContext(
        now=datetime(2026, 9, 7, tzinfo=UTC),
        person_states={"person.alice": "home", "person.bob": "home"},
        episode_recipients={"leak": frozenset({"person.alice"})},
    )
    request = NotificationRequest(
        message="All good", targets=("leak",), data={"switchboard_done": True}
    )

    decision = decide(table, request, context)

    assert [item.person for item in decision.routed] == ["person.alice"]
    assert ("person.bob", DROP_NOT_NOTIFIED) in [
        (drop.person, drop.reason) for drop in decision.dropped
    ]


def test_an_ordinary_message_ignores_the_episode() -> None:
    """Only a `done` message is filtered by who the episode reached."""
    table = RoutingTable(
        persons={"person.bob": PersonConfig("person.bob", ("mobile_app_bob",))},
        targets={
            "leak": TargetConfig(
                slug="leak",
                name="Leak",
                alert_entity="alert.leak",
                audience=("person.bob",),
            )
        },
        default_target="leak",
    )
    context = RoutingContext(
        now=datetime(2026, 9, 7, tzinfo=UTC),
        person_states={"person.bob": "home"},
        episode_recipients={"leak": frozenset()},
    )

    decision = decide(
        table, NotificationRequest(message="Leak!", targets=("leak",)), context
    )

    assert [item.person for item in decision.routed] == ["person.bob"]


def test_the_v05_person_and_row_keys_default_to_their_absent_meaning() -> None:
    """`summary` absent means on; `clear_done` absent means off."""
    assert parse_person({"entity_id": "person.alice"}).summary is True
    assert (
        parse_person({"entity_id": "person.alice", "summary": False}).summary is False
    )
    assert parse_target({"slug": "leak"}).clear_done is False
    assert parse_target({"slug": "leak", "clear_done": True}).clear_done is True


# ---------------------------------------------------------------------------
# v0.7 (ADR-0021): escalation, floors, bare outputs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (PRIORITY_INFO, PRIORITY_NORMAL),
        (PRIORITY_NORMAL, PRIORITY_HIGH),
        (PRIORITY_HIGH, PRIORITY_CRITICAL),
        (PRIORITY_CRITICAL, PRIORITY_CRITICAL),
        ("nonsense", "nonsense"),
    ],
)
def test_escalate_one_step_moves_by_exactly_one(start, expected) -> None:
    """One step, and `critical` is the ceiling (ADR-0021 §1)."""
    assert escalate_one_step(start) == expected


def test_effective_priority_needs_the_flag_a_person_and_an_empty_house() -> None:
    """Three conditions, and each one on its own is enough to change nothing."""
    audience = ("person.alice",)
    away = RoutingContext(now=NOW, person_states={"person.alice": "not_home"})

    off = target("leak", audience=audience)
    assert effective_priority(off, {}, away) == (PRIORITY_NORMAL, None)

    on = target("leak", audience=audience, escalate_when_nobody_home=True)
    assert effective_priority(on, {}, away) == (PRIORITY_HIGH, "nobody_home")

    home = RoutingContext(now=NOW, person_states={"person.alice": "home"})
    assert effective_priority(on, {}, home) == (PRIORITY_NORMAL, None)

    # An audience of bare outputs only has nobody to ask about, so it is not an
    # empty house -- it is a target with no presence at all.
    speakers = target(
        "leak", audience=("notify.kitchen",), escalate_when_nobody_home=True
    )
    assert effective_priority(speakers, {}, away) == (PRIORITY_NORMAL, None)


def test_a_rule_that_changes_nothing_reports_no_escalation() -> None:
    """`critical` is unchanged, so `escalated` stays None (ADR-0021 §8)."""
    on = target("leak", audience=("person.alice",), escalate_when_nobody_home=True)
    away = RoutingContext(now=NOW, person_states={"person.alice": "not_home"})
    assert effective_priority(on, {"priority": PRIORITY_CRITICAL}, away) == (
        PRIORITY_CRITICAL,
        None,
    )


@pytest.mark.parametrize("state", ["not_home", "Work", "unknown", "unavailable", None])
def test_only_the_literal_state_home_counts_as_home(state) -> None:
    """Anything else is "not home", including a person nobody has heard of."""
    states = {} if state is None else {"person.alice": state}
    context = RoutingContext(now=NOW, person_states=states)
    assert nobody_is_home(target("leak", audience=("person.alice",)), context)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (PRIORITY_HIGH, PRIORITY_HIGH),
        ("loud", None),
        (3, None),
        (True, None),
        (None, None),
    ],
)
def test_parse_min_priority_fails_towards_quiet(raw, expected) -> None:
    """An unreadable floor is ignored, so the entity silences everything."""
    assert parse_min_priority(raw) == expected


@pytest.mark.parametrize(
    ("floor", "priority", "caught"),
    [
        (None, PRIORITY_CRITICAL, True),
        (PRIORITY_HIGH, PRIORITY_NORMAL, True),
        (PRIORITY_HIGH, PRIORITY_HIGH, False),
        (PRIORITY_HIGH, PRIORITY_CRITICAL, False),
        (PRIORITY_INFO, PRIORITY_INFO, False),
    ],
)
def test_silence_catches_only_what_is_below_the_floor(floor, priority, caught) -> None:
    """A floor changes which calls a silence catches, and nothing else."""
    assert silence_catches(floor, priority) is caught


def test_the_strictest_on_silence_decides() -> None:
    """Silence is an OR across sources; a floor narrows one, not the union."""
    alice = person(
        "person.alice",
        silence_entities=("binary_sensor.evening", "binary_sensor.night"),
    )
    context = RoutingContext(
        now=NOW,
        silenced={
            "binary_sensor.evening": PRIORITY_NORMAL,
            "binary_sensor.night": PRIORITY_HIGH,
        },
    )
    assert silences_catching(alice, context, PRIORITY_NORMAL) == ["binary_sensor.night"]
    assert silences_catching(alice, context, PRIORITY_HIGH) == []


@pytest.mark.parametrize(
    ("entry", "bare"),
    [
        ("notify.kitchen_speaker", True),
        ("person.alice", False),
        ("light.kitchen", False),
    ],
)
def test_is_bare_output_reads_the_domain_and_nothing_else(entry, bare) -> None:
    """An audience entry in the `notify` domain is a bare output (ADR-0021 §5)."""
    assert is_bare_output(entry) is bare


def test_a_bare_output_is_its_own_delivery_with_no_person() -> None:
    """One `RoutedDelivery`, `person=None`, one output, the audience entry kept."""
    built = table(
        [person("person.alice", outputs=("mobile_app_alice",))],
        [target("leak", audience=("person.alice", "notify.kitchen_speaker"))],
    )
    context = RoutingContext(now=NOW, person_states={"person.alice": "home"})

    decision = decide(built, request(), context)

    speaker = next(item for item in decision.routed if item.is_bare)
    assert speaker.person is None
    assert speaker.outputs == ("kitchen_speaker",)
    assert speaker.audience_entry == "notify.kitchen_speaker"


def test_a_recursive_bare_output_is_refused_and_names_itself() -> None:
    """`recursion`, no new reason, and the drop carries the output it is about."""
    built = table(
        [person("person.alice", outputs=("mobile_app_alice",))],
        [target("leak", audience=("person.alice", "notify.switchboard_leak"))],
    )
    context = RoutingContext(now=NOW, person_states={"person.alice": "home"})

    decision = decide(built, request(), context)

    refusal = next(drop for drop in decision.dropped if drop.reason == DROP_RECURSION)
    assert refusal.person is None
    assert refusal.output == "notify.switchboard_leak"


def test_the_target_splits_its_audience_by_domain() -> None:
    """`audience_persons` and `bare_outputs` keep the audience order."""
    row = target(
        "leak",
        audience=("person.alice", "notify.kitchen_speaker", "person.bob"),
    )
    assert row.audience_persons == ("person.alice", "person.bob")
    assert row.bare_outputs == ("notify.kitchen_speaker",)


@pytest.mark.parametrize(
    ("os_name", "has_push", "has_channel"),
    [
        ("iOS", True, False),
        ("ipados", True, False),
        ("WATCHOS", True, False),
        ("Android", False, True),
        ("SailfishOS", True, True),
        (None, True, True),
        ("", True, True),
    ],
)
def test_critical_keys_are_translated_per_os(os_name, has_push, has_channel) -> None:
    """An OS the router cannot identify gets both sets (ADR-0021 §7)."""
    keys = critical_keys_for_os(os_name)
    assert ("push" in keys) is has_push
    assert ("channel" in keys) is has_channel
    if has_channel:
        assert keys["ttl"] == 0
        assert keys["priority"] == PRIORITY_HIGH


def test_the_apple_payload_is_a_fresh_object_every_time() -> None:
    """A shared nested mapping would leak into every message's `data`."""
    first = critical_keys_for_os("ios")
    second = critical_keys_for_os("ios")
    assert first == second
    assert first["push"] is not second["push"]


def test_the_v07_target_key_defaults_to_its_absent_meaning() -> None:
    """`escalate_when_nobody_home` absent means off."""
    assert parse_target({"slug": "leak"}).escalate_when_nobody_home is False
    assert (
        parse_target(
            {"slug": "leak", "escalate_when_nobody_home": True}
        ).escalate_when_nobody_home
        is True
    )

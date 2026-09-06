"""Unit tests for the pure decision engine in `router.py`."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest

from custom_components.notify_switchboard.const import (
    DROP_NO_OUTPUTS,
    DROP_NOT_IN_AUDIENCE,
    DROP_PRESENCE,
    DROP_RECURSION,
    DROP_SILENCED,
    DROP_SNOOZED,
    DROP_UNKNOWN_TARGET,
    PRIORITY_CRITICAL,
    PRIORITY_HIGH,
    PRIORITY_INFO,
    PRIORITY_NORMAL,
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
    decide,
    is_recursive_output,
    merge_data,
    parse_action,
    parse_person,
    parse_target,
    parse_wake_time,
    presence_allows,
    resolve_priority,
    snooze_action,
    snooze_is_active,
    split_outputs,
    state_is_on,
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
    ctx = context(
        person_states={"person.alice": "home"},
        silenced={"input_boolean.night": True},
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
    """A row naming an unknown person is reported, never crashes."""
    built = table(
        [person("person.alice", outputs=("mobile_app_alice",))],
        [target("leak", audience=("person.alice", "person.ghost"))],
    )
    decision = decide(built, request(), context(person_states={"person.alice": "home"}))
    assert ("person.ghost", DROP_NOT_IN_AUDIENCE) in [
        (item.person, item.reason) for item in decision.dropped
    ]


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

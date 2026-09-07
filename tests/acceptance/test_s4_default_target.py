"""The managed `default` row: `notify.switchboard` works after one form.

Written before the Sprint 4 implementation exists, against:

- `docs/contract.md` §"v0.4 addendum (ADR-0018)" → "`managed`"
- `docs/ADR/0018-zero-config-and-explainability.md` §4 and §7
- `docs/sprints/sprint-4-brief.md` items 4 and 7

Up to 0.3.0 a fresh install has an empty routing table, so `notify.switchboard`
resolves to no target and does nothing at all until the user has invented a
slug, a name, a class, a priority, an audience and a presence rule. From 0.4.0
the first person added to an empty table also creates one row — `default`,
flagged `managed` — and points `default_target` at it, so the very next
`notify.switchboard` call reaches a real phone.

`managed` is a promise the user can revoke, and revoking it is the interesting
half: the moment somebody opens that row and presses submit, the router stops
rewriting its audience, for ever. A table that silently re-adds a person
somebody has just removed is worse than no automation at all.

The row editor's confirmation step is on the path of every test below that
edits a row, so the `alert:` snippet of brief item 7 is pinned here too rather
than in a file of its own.
"""

from __future__ import annotations

from typing import Any

from homeassistant.data_entry_flow import FlowResultType

from .conftest import make_entry, make_person, make_target


def _target_input(
    slug: str,
    name: str,
    audience: list[str],
    *,
    alert_entity: str | None = None,
) -> dict[str, Any]:
    """Submit the row editor with the three fields that have no default.

    Everything else in the `target` schema carries a default, so this is the
    smallest submission the form accepts — and therefore the cheapest way to
    show that editing *any* field of the managed row takes ownership of it.
    The row editor writes the whole row from what is submitted (0.2.0 fixed the
    data-loss bug where it did not), so a test that wants to keep the row's
    `alert_entity` has to send it back.
    """
    user_input: dict[str, Any] = {"slug": slug, "name": name, "audience": audience}
    if alert_entity is not None:
        user_input["alert_entity"] = alert_entity
    return user_input


def _row(entry, slug: str) -> dict[str, Any]:
    """Return one routing-table row of the stored options."""
    rows = [row for row in entry.options["targets"] if row["slug"] == slug]
    assert rows, (
        f"no routing-table row {slug!r}; got "
        f"{[row['slug'] for row in entry.options['targets']]}"
    )
    return rows[0]


async def _add_person(options_flow, entry, person: str, outputs: list[str]):
    """Add one person through the two-step person editor (ADR-0018 §2)."""
    return await options_flow(
        entry, "person", {"entity_id": person}, {"outputs": outputs}
    )


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------


async def test_the_first_person_creates_the_default_row_and_the_default_target(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, set_person
):
    """One form, and the router has somewhere to send `notify.switchboard`."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    entry = make_entry(hass, persons=[], targets=[], default_target=None)
    await install(entry)

    result = await _add_person(
        options_flow, entry, "person.alice", ["mobile_app_alice"]
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    row = _row(entry, "default")
    assert row["managed"] is True
    assert row["audience"] == ["person.alice"]
    assert row["name"], "the row is named, in the instance language (ADR-0018 §4)"
    # What the bootstrapped row must *not* carry any more (`class`, ADR-0020 §4)
    # is pinned by `test_s6_class_removed.py`, next to the rest of that removal.
    assert row["default_priority"] == "normal"
    assert row["presence_rule"] == "always"
    assert row["alert_entity"] is None
    assert entry.options["default_target"] == "default"


async def test_notify_switchboard_reaches_that_person_immediately(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, set_person
):
    """The promise of the sprint, stated as a delivery rather than as options."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    entry = make_entry(hass, persons=[], targets=[], default_target=None)
    await install(entry)

    await _add_person(options_flow, entry, "person.alice", ["mobile_app_alice"])

    await hass.services.async_call(
        "notify", "switchboard", {"message": "hello"}, blocking=True
    )
    await hass.async_block_till_done()

    assert [call.data["message"] for call in calls["mobile_app_alice"]] == ["hello"], (
        "`notify.switchboard` with no target uses `default_target`, which the "
        "first person is supposed to have created (ADR-0018 §4)"
    )


async def test_no_default_row_is_invented_when_the_table_is_not_empty(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, set_person
):
    """The row exists to bootstrap an empty table, never to add itself later."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    set_person("person.alice", "home")
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    await _add_person(options_flow, entry, "person.bob", ["mobile_app_bob"])

    assert [row["slug"] for row in entry.options["targets"]] == ["leak"]
    assert entry.options["default_target"] == "leak"


# ---------------------------------------------------------------------------
# Staying in sync, and stopping
# ---------------------------------------------------------------------------


async def test_a_second_person_joins_the_managed_rows_audience(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, set_person
):
    """While `managed` is true, the audience is every configured person."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    set_person("person.alice", "home")
    set_person("person.bob", "home")
    entry = make_entry(hass, persons=[], targets=[], default_target=None)
    await install(entry)

    await _add_person(options_flow, entry, "person.alice", ["mobile_app_alice"])
    await _add_person(options_flow, entry, "person.bob", ["mobile_app_bob"])

    assert set(_row(entry, "default")["audience"]) == {"person.alice", "person.bob"}
    assert _row(entry, "default")["managed"] is True


async def test_editing_the_managed_row_takes_ownership_of_it_for_good(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, set_person
):
    """Submitting the row editor clears `managed`; nothing ever sets it back."""
    mock_outputs("mobile_app_alice", "mobile_app_bob", "mobile_app_carol")
    for person in ("alice", "bob", "carol"):
        set_person(f"person.{person}", "home")
    entry = make_entry(hass, persons=[], targets=[], default_target=None)
    await install(entry)
    await _add_person(options_flow, entry, "person.alice", ["mobile_app_alice"])

    result = await options_flow(
        entry,
        "edit_target",
        {"slug": "default"},
        _target_input("default", "My own row", ["person.alice"]),
        {},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    row = _row(entry, "default")
    assert not row.get("managed"), (
        "editing the row — any field — hands its audience to the user (ADR-0018 §4)"
    )
    assert row["name"] == "My own row"

    await _add_person(options_flow, entry, "person.bob", ["mobile_app_bob"])
    assert _row(entry, "default")["audience"] == ["person.alice"], (
        "an unmanaged row's audience is nobody's business but the user's"
    )
    assert not _row(entry, "default").get("managed"), (
        "`managed` must not come back on the next options write"
    )


# ---------------------------------------------------------------------------
# The `alert:` snippet (brief item 7)
# ---------------------------------------------------------------------------


async def test_saving_a_row_shows_a_ready_to_paste_alert_snippet(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, set_person
):
    """The row editor ends on a confirmation step carrying the YAML to paste."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "leak", "Leak", audience=["person.alice"], alert_entity="alert.water"
            )
        ],
        default_target="leak",
    )
    await install(entry)

    result = await options_flow(
        entry,
        "edit_target",
        {"slug": "leak"},
        _target_input("leak", "Leak", ["person.alice"], alert_entity="alert.water"),
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "target_saved"
    snippet = (result["description_placeholders"] or {}).get("snippet")
    assert snippet, (
        "the confirmation step must carry the snippet through "
        "`description_placeholders` (ADR-0018 §7)"
    )
    assert "alert:" in snippet
    assert "notifiers:" in snippet
    assert "switchboard_leak" in snippet, (
        "the notifier name is the legacy service without its `notify.` prefix, "
        "which is what an `alert:` block wants"
    )
    assert "repeat:" in snippet, "brief item 7 asks for a `repeat` example"

    # Nothing is written until the confirmation step is submitted.
    result = await options_flow(
        entry,
        "edit_target",
        {"slug": "leak"},
        _target_input(
            "leak", "Water leak", ["person.alice"], alert_entity="alert.water"
        ),
        {},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _row(entry, "leak")["name"] == "Water leak"


async def test_the_snippet_is_keyed_on_the_rows_own_alert_when_it_has_one(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, set_person
):
    """A row tied to `alert.water` describes *that* alert, not an invented one."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "leak", "Leak", audience=["person.alice"], alert_entity="alert.water"
            )
        ],
        default_target="leak",
    )
    await install(entry)

    result = await options_flow(
        entry,
        "edit_target",
        {"slug": "leak"},
        _target_input("leak", "Leak", ["person.alice"], alert_entity="alert.water"),
    )
    snippet = result["description_placeholders"]["snippet"]

    assert "water:" in snippet, (
        "the block is keyed on the object id of the row's `alert_entity`; got "
        f"{snippet!r}"
    )

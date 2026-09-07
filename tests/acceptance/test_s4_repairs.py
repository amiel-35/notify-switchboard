"""Two consistency repairs: a person nobody can reach, an alert that is not there.

Written before the Sprint 4 implementation exists, against:

- `docs/contract.md` §"v0.4 addendum (ADR-0018)" → "Two more `repairs` keys"
- `docs/ADR/0018-zero-config-and-explainability.md` §5
- `docs/sprints/sprint-4-brief.md` item 5

Both failures are silent today and permanent:

- a person with an empty `outputs` list who sits in an audience is dropped
  with `no_outputs` on every single message, and nothing but the diagnostics
  ever says so;
- a row whose `alert_entity` names an `alert.*` that does not exist
  acknowledges nothing and observes nothing.

Both are configuration gaps the user can close, so both become repairs, in the
shape ADR-0017 §4 established for `person_without_user_id`: severity
`warning`, `is_fixable=False`, raised once, deleted when the cause is gone.

Two conventions carried over from `test_s3_callbacks.py` (README, assumption
7): the `issue_id` is **not** pinned — the contract fixes translation keys, not
ids — and what is asserted instead is the `translation_key`, the severity,
`is_fixable`, how many issues exist, and that each one names its subject in
its `issue_id` or in its `translation_placeholders`.

The alert grace period is reached with `async_fire_time_changed` rather than
with a patch, so nothing here depends on the name of the constant that holds
it (ADR-0018 §5 fixes it at 60 s, in `dispatcher.ALERT_ENTITY_GRACE_SECONDS`).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.helpers import issue_registry as ir, translation
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.notify_switchboard.const import DOMAIN

from .conftest import make_entry, make_options, make_person, make_target

ISSUE_PERSON_WITHOUT_OUTPUTS = "person_without_outputs"
ISSUE_ALERT_ENTITY_MISSING = "alert_entity_missing"

# ADR-0018 §5 fixes the grace at 60 seconds; anything past it will do.
PAST_THE_GRACE = timedelta(seconds=75)


def issues_for(issue_registry, translation_key: str) -> list:
    """Return this integration's issues carrying one translation key."""
    return [
        issue
        for (domain, _issue_id), issue in issue_registry.issues.items()
        if domain == DOMAIN and issue.translation_key == translation_key
    ]


def assert_shape(issue, subject: str) -> None:
    """Assert one repair's severity, fixability, and that it names its subject."""
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.is_fixable is False, (
        "there is nothing this integration can do about it; the fix is in the "
        "user's configuration (ADR-0018 §5)"
    )
    named = subject in issue.issue_id or subject in str(
        issue.translation_placeholders or {}
    )
    assert named, (
        f"the repair must say which one is broken: {subject!r} appears "
        f"neither in {issue.issue_id!r} nor in {issue.translation_placeholders!r}"
    )


async def advance_past_the_grace(hass) -> None:
    """Let the alert-entity grace period expire."""
    async_fire_time_changed(hass, dt_util.utcnow() + PAST_THE_GRACE)
    await hass.async_block_till_done()


# ---------------------------------------------------------------------------
# person_without_outputs
# ---------------------------------------------------------------------------


async def test_a_person_in_an_audience_with_no_outputs_raises_one_repair(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Otherwise the router drops every message for them, silently, for ever."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    set_person("person.bob", "home")
    await install(
        make_entry(
            hass,
            persons=[
                make_person("person.alice", ["mobile_app_alice"]),
                make_person("person.bob", []),
            ],
            targets=[
                make_target("leak", "Leak", audience=["person.alice", "person.bob"])
            ],
            default_target="leak",
        )
    )

    issues = issues_for(ir.async_get(hass), ISSUE_PERSON_WITHOUT_OUTPUTS)
    assert len(issues) == 1, (
        f"exactly one repair, for the person who has no outputs; got {issues}"
    )
    assert_shape(issues[0], "person.bob")


async def test_a_person_with_no_outputs_and_no_audience_raises_nothing(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Without a row there is nothing to fail, so there is nothing to report."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    set_person("person.bob", "home")
    await install(
        make_entry(
            hass,
            persons=[
                make_person("person.alice", ["mobile_app_alice"]),
                make_person("person.bob", []),
            ],
            targets=[make_target("leak", "Leak", audience=["person.alice"])],
            default_target="leak",
        )
    )

    assert issues_for(ir.async_get(hass), ISSUE_PERSON_WITHOUT_OUTPUTS) == []


async def test_giving_that_person_an_output_clears_the_repair(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """An options change reloads the entry; that is when the gap is re-evaluated."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    set_person("person.alice", "home")
    set_person("person.bob", "home")
    entry = make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", []),
        ],
        targets=[make_target("leak", "Leak", audience=["person.alice", "person.bob"])],
        default_target="leak",
    )
    await install(entry)
    assert issues_for(ir.async_get(hass), ISSUE_PERSON_WITHOUT_OUTPUTS)

    hass.config_entries.async_update_entry(
        entry,
        options=make_options(
            persons=[
                make_person("person.alice", ["mobile_app_alice"]),
                make_person("person.bob", ["mobile_app_bob"]),
            ],
            targets=[
                make_target("leak", "Leak", audience=["person.alice", "person.bob"])
            ],
            default_target="leak",
        ),
    )
    await hass.async_block_till_done()

    assert issues_for(ir.async_get(hass), ISSUE_PERSON_WITHOUT_OUTPUTS) == [], (
        "a repair whose cause is gone must be deleted, not left to be dismissed"
    )


# ---------------------------------------------------------------------------
# alert_entity_missing
# ---------------------------------------------------------------------------


async def test_a_row_pointing_at_a_nonexistent_alert_raises_one_repair_after_the_grace(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Not at setup: `alert` may simply not have been set up yet (ADR-0018 §5)."""
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
                    audience=["person.alice"],
                    alert_entity="alert.never_defined",
                )
            ],
            default_target="leak",
        )
    )

    assert issues_for(ir.async_get(hass), ISSUE_ALERT_ENTITY_MISSING) == [], (
        "shouting during startup would train the user to ignore this repair"
    )

    await advance_past_the_grace(hass)

    issues = issues_for(ir.async_get(hass), ISSUE_ALERT_ENTITY_MISSING)
    assert len(issues) == 1, f"one repair for the one broken row; got {issues}"
    assert_shape(issues[0], "leak")
    assert "alert.never_defined" in str(issues[0].translation_placeholders or {}), (
        "the repair must name the entity that is missing, not only the row"
    )


async def test_a_row_whose_alert_exists_raises_nothing(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The alert has to be absent, not merely idle."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("alert.water", "idle")
    await install(
        make_entry(
            hass,
            persons=[make_person("person.alice", ["mobile_app_alice"])],
            targets=[
                make_target(
                    "leak",
                    "Leak",
                    audience=["person.alice"],
                    alert_entity="alert.water",
                )
            ],
            default_target="leak",
        )
    )

    await advance_past_the_grace(hass)

    assert issues_for(ir.async_get(hass), ISSUE_ALERT_ENTITY_MISSING) == []


async def test_the_alert_repair_clears_once_the_alert_exists(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Defining the missing `alert:` block and reloading closes the repair."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "leak",
                "Leak",
                audience=["person.alice"],
                alert_entity="alert.water",
            )
        ],
        default_target="leak",
    )
    await install(entry)
    await advance_past_the_grace(hass)
    assert issues_for(ir.async_get(hass), ISSUE_ALERT_ENTITY_MISSING)

    hass.states.async_set("alert.water", "idle")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await advance_past_the_grace(hass)

    assert issues_for(ir.async_get(hass), ISSUE_ALERT_ENTITY_MISSING) == []


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("language", ["en", "fr", "es"])
@pytest.mark.parametrize(
    "issue_key", [ISSUE_PERSON_WITHOUT_OUTPUTS, ISSUE_ALERT_ENTITY_MISSING]
)
async def test_both_repairs_are_translated(
    hass, enable_custom_integrations, install, mock_outputs, language, issue_key
):
    """A repair a user cannot read is a repair a user cannot act on."""
    mock_outputs("mobile_app_alice")
    await install(
        make_entry(
            hass,
            persons=[make_person("person.alice", ["mobile_app_alice"])],
            targets=[make_target("leak", "Leak", audience=["person.alice"])],
            default_target="leak",
        )
    )

    strings = await translation.async_get_translations(
        hass, language, "issues", {DOMAIN}
    )
    for suffix in ("title", "description"):
        key = f"component.{DOMAIN}.issues.{issue_key}.{suffix}"
        assert strings.get(key), f"translations/{language}.json must define {key}"

"""`class` leaves the routing table, and a stored one is ignored.

Written before the Sprint 6 implementation exists, against:

- `docs/contract.md` §"v0.6 addendum (ADR-0020)" → "`class` is no longer a
  routing-table row key"
- `docs/ADR/0020-consolidation.md` §4
- `docs/sprints/sprint-6-brief.md` item 3

`class` has been asked for on every target since 0.1.0 and read by nothing:
`parse_target` copies it into `TargetConfig.target_class` and no consumer
exists. It is removed from the schema, the strings, the documents and the
examples.

Removing a key that installations already carry has exactly one requirement,
and it is the first test here: **a stored value must be harmless**. It is
ignored — not migrated, not shown, not deleted — so an entry written by 0.5
loads and routes unchanged, and the key never reappears where somebody could
mistake it for something the router reads. That last part is why diagnostics
is checked: a dump is where a dead key would be found and believed.

This file is the only acceptance test that imports the integration's
diagnostics entry point. It is public API — Home Assistant calls it — and
`docs/contract.md` §v0.6 speaks about what a dump exposes, so the assertion
belongs at this level rather than in a unit test.
"""

from __future__ import annotations

from typing import Any

from homeassistant.data_entry_flow import FlowResultType

from custom_components.notify_switchboard.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import make_entry, make_person, make_target


def _row(entry, slug: str) -> dict[str, Any]:
    rows = [row for row in entry.options["targets"] if row["slug"] == slug]
    assert rows, (
        f"no target {slug!r}; got {[row['slug'] for row in entry.options['targets']]}"
    )
    return rows[0]


def _legacy_entry(hass):
    """An entry as 0.5 wrote it: every target carries a `class`."""
    return make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "leak",
                "Leak",
                klass="building",
                audience=["person.alice"],
                default_data={"channel": "family"},
            )
        ],
        default_target="leak",
    )


async def test_a_target_stored_with_class_still_loads_and_routes(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Ignored means ignored: an entry written by 0.5 keeps working."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    await install(_legacy_entry(hass))

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "water"}, blocking=True
    )
    await hass.async_block_till_done()

    assert [call.data["message"] for call in calls["mobile_app_alice"]] == ["water"], (
        "a dead key in a stored target must not stop the entry loading or the "
        "message routing (ADR-0020 §4); there is no migration to lean on"
    )


async def test_class_is_a_field_of_neither_target_step(
    hass, enable_custom_integrations, install, options_flow
):
    """It is gone from the form, both halves of it."""
    entry = await install(_legacy_entry(hass))

    basic = await options_flow(entry, "target")
    assert basic["step_id"] == "target"
    assert "class" not in [str(marker) for marker in basic["data_schema"].schema], (
        "nobody should have to answer a question nothing reads (ADR-0020 §4)"
    )

    advanced = await options_flow(entry, "edit_target_advanced", {"slug": "leak"})
    assert advanced["step_id"] == "target_advanced"
    assert "class" not in [str(marker) for marker in advanced["data_schema"].schema], (
        "removed, not demoted to the advanced step (ADR-0020 §4)"
    )


async def test_class_is_absent_from_the_routing_table_a_diagnostics_dump_exposes(
    hass, enable_custom_integrations, install
):
    """A dump is where a dead key would be found and believed."""
    entry = await install(_legacy_entry(hass))

    dump = await async_get_config_entry_diagnostics(hass, entry)

    targets = dump["entry"]["options"]["targets"]
    assert targets, "the dump still exposes the routing table it always did"
    for row in targets:
        assert "class" not in row, (
            "a stored `class` is never shown (ADR-0020 §4): a bug report that "
            "carries it invites somebody to explain what it does"
        )
    assert targets[0]["slug"] == "leak"
    assert targets[0]["default_data"] == {"channel": "**REDACTED**"}, (
        "the rest of the dump is untouched, redaction included"
    )


async def test_the_bootstrapped_default_target_has_no_class(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, set_person
):
    """The one target the router writes itself does not write the key either."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    entry = await install(make_entry(hass, persons=[], targets=[], default_target=None))

    result = await options_flow(
        entry,
        "person",
        {"entity_id": "person.alice"},
        {"outputs": ["mobile_app_alice"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    row = _row(entry, "default")
    assert row["managed"] is True, (
        "the managed default target still exists (ADR-0018 §4)"
    )
    assert "class" not in row, (
        "`DEFAULT_TARGET_CLASS` goes with the field it filled (ADR-0020 §4)"
    )

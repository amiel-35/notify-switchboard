"""The code name of a target is derived from its name, never typed.

Written before the Sprint 8 implementation exists, against:

- `docs/contract.md` §"v0.8 addendum (ADR-0022)" → "`target` asks four
  things, and the slug is derived"
- `docs/ADR/0022-a-first-alert-without-code.md` §1
- `docs/history/sprints/sprint-8-brief.md` item 1

Up to 0.7.1 the first field of the `target` step is "Short identifier —
lowercase letters, no spaces", which a newcomer has to invent and which is
refused on the first capital letter. From 0.8.0 the step asks for a name, and
the slug — what `notify.switchboard_<slug>` is built from — is derived from
it once, when the target is created, and then never changes.
"""

from __future__ import annotations

from typing import Any

from homeassistant.data_entry_flow import FlowResultType

from .conftest import make_entry, make_person, make_target, suggested_value

# ADR-0022 §1: the four, in the order the form shows them.
TARGET_FIELDS = ["name", "alert_entity", "audience", "observer_mode"]


def _field_names(result) -> list[str]:
    return [str(marker) for marker in result["data_schema"].schema]


def _slugs(entry) -> list[str]:
    return [row["slug"] for row in entry.options["targets"]]


def _row(entry, slug: str) -> dict[str, Any]:
    rows = [row for row in entry.options["targets"] if row["slug"] == slug]
    assert rows, f"no target {slug!r}; got {_slugs(entry)}"
    return rows[0]


def _household(hass, targets: list[dict[str, Any]] | None = None):
    targets = targets or []
    return make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=targets,
        default_target=targets[0]["slug"] if targets else None,
    )


async def test_the_target_step_has_no_code_name_to_invent(
    hass, enable_custom_integrations, install, options_flow
):
    """Four fields; the first one is a name a person would say out loud."""
    entry = await install(_household(hass))

    result = await options_flow(entry, "target")

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "target", "`target` is a public step id"
    assert _field_names(result) == TARGET_FIELDS, (
        "`slug` left the `target` step (ADR-0022 §1): it is derived from the "
        "name, never typed"
    )


async def test_the_slug_is_derived_from_the_name(
    hass, enable_custom_integrations, install, options_flow, mock_outputs
):
    """"Fuite d'eau à l'étage" becomes `fuite_d_eau_a_l_etage`, and its service exists."""
    calls = mock_outputs("mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    entry = await install(_household(hass))

    result = await options_flow(
        entry,
        "target",
        {
            "name": "Fuite d'eau à l'étage",
            "audience": ["person.alice"],
            "observer_mode": False,
        },
        {},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    assert _slugs(entry) == ["fuite_d_eau_a_l_etage"], (
        "the slug is `homeassistant.util.slugify(name)` (ADR-0022 §1)"
    )
    assert _row(entry, "fuite_d_eau_a_l_etage")["name"] == "Fuite d'eau à l'étage"

    await hass.services.async_call(
        "notify", "switchboard_fuite_d_eau_a_l_etage", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 1, (
        "the derived slug is a slug like any other: `notify.switchboard_<slug>` "
        "exists and routes (contract v0, unchanged)"
    )


async def test_two_targets_with_the_same_name_get_distinct_slugs(
    hass, enable_custom_integrations, install, options_flow
):
    """De-duplicated like a helper id: `_2`, `_3`, …"""
    entry = await install(
        _household(hass, [make_target("leak", "Leak", audience=["person.alice"])])
    )

    await options_flow(
        entry, "target", {"name": "Leak", "audience": ["person.alice"]}, {}
    )
    await options_flow(
        entry, "target", {"name": "LEAK", "audience": ["person.alice"]}, {}
    )

    assert _slugs(entry) == ["leak", "leak_2", "leak_3"], (
        "a second target with the same name must not replace the first one: "
        "its slug is de-duplicated (ADR-0022 §1)"
    )
    assert _row(entry, "leak")["name"] == "Leak", "the existing target is untouched"


async def test_a_name_with_nothing_to_slugify_still_gets_a_slug(
    hass, enable_custom_integrations, install, options_flow
):
    """A name made of punctuation falls back to `alert`, never to an empty slug."""
    entry = await install(_household(hass))

    result = await options_flow(
        entry, "target", {"name": "!!!", "audience": ["person.alice"]}, {}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _slugs(entry) == ["alert"]


async def test_editing_shows_the_slug_read_only_and_never_renames_it(
    hass, enable_custom_integrations, install, options_flow
):
    """Renaming a target changes what people read, not what automations call."""
    entry = await install(
        _household(
            hass,
            [make_target("leak", "Leak", audience=["person.alice"])],
        )
    )

    form = await options_flow(entry, "edit_target", {"slug": "leak"})
    assert form["type"] is FlowResultType.FORM
    assert suggested_value(form, "slug") == "leak", (
        "the edit screen shows the behind-the-scenes name (ADR-0022 §1)"
    )
    marker_validator = dict(
        (str(marker), validator)
        for marker, validator in form["data_schema"].schema.items()
    )["slug"]
    assert marker_validator.config.get("read_only") is True, (
        "the slug is shown read-only: it is never renamed by the editor"
    )

    result = await options_flow(
        entry,
        "edit_target",
        {"slug": "leak"},
        {
            "slug": "something_else",
            "name": "Water leak upstairs",
            "audience": ["person.alice"],
        },
        {},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _slugs(entry) == ["leak"], (
        "a value submitted for the read-only slug is ignored, and a new name "
        "derives nothing: existing targets keep their slug (ADR-0022 §1)"
    )
    assert _row(entry, "leak")["name"] == "Water leak upstairs"


async def test_a_target_stored_before_0_8_keeps_its_slug_and_its_service(
    hass, enable_custom_integrations, install, options_flow, mock_outputs
):
    """A slug that is not `slugify(name)` stays exactly what it was."""
    calls = mock_outputs("mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    entry = await install(
        _household(
            hass,
            [make_target("wl", "Water leak", audience=["person.alice"])],
        )
    )

    await options_flow(
        entry,
        "edit_target",
        {"slug": "wl"},
        {"name": "Water leak", "audience": ["person.alice"]},
        {},
    )

    assert _slugs(entry) == ["wl"]
    await hass.services.async_call(
        "notify", "switchboard_wl", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 1, (
        "`notify.switchboard_<slug>` of an existing target is unchanged"
    )

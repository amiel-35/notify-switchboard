"""Per-row optional texts tests (contract §"Per-row texts (v0.2, ADR-0016)").

`message`, `done_message` and `default_title` resolve the known-issues entry
"a real `alert.*` never exposes `message` or `done_message`"
(`docs/known-issues.md`, 2026-09-06): the row, not the alert, is now the
documented source of observer-mode text. These tests drive the same kind of
synthetic `alert.*`-shaped entity_id as `test_s1_observer.py` (real
`AlertEntity` exposes no state attributes at all, so both branches would
otherwise be untestable against a real alert).

All three fields default to `None` (see `conftest.make_target` and
`tests/acceptance/README.md` "v0.2 addendum"), so no existing Sprint 1 test
is affected by their existence.
"""

from __future__ import annotations

from .conftest import make_entry, make_person, make_target

# ---------------------------------------------------------------------------
# `message` / `done_message` templates, observer mode
# ---------------------------------------------------------------------------


async def test_observer_mode_uses_the_rows_message_template_when_the_alert_has_none(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "observed",
                "Observed target",
                alert_entity="alert.observer_test",
                observer_mode=True,
                audience=["person.alice"],
                message="Custom alert, level {{ alert.attributes.level }}",
            )
        ],
        default_target="observed",
    )
    await install(entry)

    hass.states.async_set("alert.observer_test", "idle")
    await hass.async_block_till_done()

    # No "message" attribute on the alert itself: the row's template is used,
    # rendered with the alert's own current state exposed as `alert`.
    hass.states.async_set("alert.observer_test", "on", {"level": "high"})
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1
    assert calls["mobile_app_alice"][0].data["message"] == "Custom alert, level high"


async def test_observer_mode_prefers_the_alerts_own_message_attribute_over_the_row_template(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Forward-compat ordering (ADR-0016): the alert's own attribute, if present, still wins."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "observed",
                "Observed target",
                alert_entity="alert.observer_test",
                observer_mode=True,
                audience=["person.alice"],
                message="Row template, should not be used here",
            )
        ],
        default_target="observed",
    )
    await install(entry)

    hass.states.async_set("alert.observer_test", "idle")
    await hass.async_block_till_done()

    hass.states.async_set("alert.observer_test", "on", {"message": "From the alert"})
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1
    assert calls["mobile_app_alice"][0].data["message"] == "From the alert"


async def test_observer_mode_uses_the_rows_done_message_template(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "observed",
                "Observed target",
                alert_entity="alert.observer_test",
                observer_mode=True,
                audience=["person.alice"],
                message="On: {{ alert.state }}",
                done_message="Cleared, was: {{ alert.attributes.level }}",
            )
        ],
        default_target="observed",
    )
    await install(entry)

    hass.states.async_set("alert.observer_test", "idle")
    await hass.async_block_till_done()
    hass.states.async_set("alert.observer_test", "on", {"level": "high"})
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 1

    hass.states.async_set("alert.observer_test", "idle", {"level": "high"})
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 2
    assert calls["mobile_app_alice"][1].data["message"] == "Cleared, was: high"


async def test_observer_mode_falls_back_to_row_name_when_no_message_and_no_template(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Unchanged S1 behaviour: absent `message` template, absent alert attribute -> row name."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "observed",
                "Observed target",
                alert_entity="alert.observer_test",
                observer_mode=True,
                audience=["person.alice"],
                # message=None (default): no row template configured.
            )
        ],
        default_target="observed",
    )
    await install(entry)

    hass.states.async_set("alert.observer_test", "idle")
    await hass.async_block_till_done()
    hass.states.async_set("alert.observer_test", "on")
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1
    assert calls["mobile_app_alice"][0].data["message"] == "Observed target"


# ---------------------------------------------------------------------------
# `default_title`
# ---------------------------------------------------------------------------


async def test_caller_without_a_title_gets_the_rows_default_title(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "leak",
                "Fuite d'eau",
                audience=["person.alice"],
                default_title="Switchboard alert",
            )
        ],
        default_target="leak",
    )
    await install(entry)

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "no title given"}, blocking=True
    )
    await hass.async_block_till_done()

    assert calls["mobile_app_alice"][0].data.get("title") == "Switchboard alert"


async def test_caller_supplied_title_still_wins_over_the_rows_default_title(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "leak",
                "Fuite d'eau",
                audience=["person.alice"],
                default_title="Switchboard alert",
            )
        ],
        default_target="leak",
    )
    await install(entry)

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "m", "title": "Caller title"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert calls["mobile_app_alice"][0].data.get("title") == "Caller title"


async def test_observer_mode_generated_message_gets_the_rows_default_title(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Observer mode never has a caller to omit a title from -- default_title always applies."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "observed",
                "Observed target",
                alert_entity="alert.observer_test",
                observer_mode=True,
                audience=["person.alice"],
                default_title="Observed alert",
            )
        ],
        default_target="observed",
    )
    await install(entry)

    hass.states.async_set("alert.observer_test", "idle")
    await hass.async_block_till_done()
    hass.states.async_set("alert.observer_test", "on")
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1
    assert calls["mobile_app_alice"][0].data.get("title") == "Observed alert"

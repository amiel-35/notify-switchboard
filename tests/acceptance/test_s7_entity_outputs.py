"""Entity outputs — an output that is a `notify` entity id, not a service.

Written before the Sprint 7 implementation exists, against:

- `docs/contract.md` §"v0.7 addendum (ADR-0021)" → "Entity outputs"
- `docs/ADR/0021-escalation-and-places-reduced.md` §6
- `docs/sprints/sprint-7-brief.md` item 6

Alexa Devices, Telegram and core's own `NotifyGroup` ship `notify.*`
**entities**, not legacy services. The router only knows how to call a service,
so every one of those integrations is unreachable from it today.

The entity behind these tests is a real `NotifyEntity` added to core's own
`notify` entity component (the `notify_entity` fixture), because what is being
pinned is that the router reaches core's entity platform at all —
`component.async_register_entity_service(SERVICE_SEND_MESSAGE, ...)` in
`$HA_CORE_SRC/homeassistant/components/notify/__init__.py` — and that
`message` and `title` are the only things that survive the trip.

Two rules that have to be stated rather than discovered, because a legacy
notify service and a notify entity share one namespace:

- **a registered legacy service wins**, which is exactly today's behaviour for
  every output that exists today;
- **a missing entity is a missing output**, and the router has to check for
  itself: `notify.send_message` is an entity service, and
  `_resolve_entity_service_call_entities`
  (`$HA_CORE_SRC/homeassistant/helpers/service.py`) *logs* an unresolvable
  `entity_id` and filters out an `unavailable` one rather than raising, so
  calling and hoping would count a delivery that never happened.
"""

from __future__ import annotations

from .conftest import explain, make_entry, make_person, make_target


def _entry(hass, outputs: list[str], *, default_data: dict | None = None):
    return make_entry(
        hass,
        persons=[make_person("person.alice", outputs)],
        targets=[
            make_target(
                "leak",
                "Leak",
                audience=["person.alice"],
                default_data=default_data or {},
                default_title="Leak alert",
            )
        ],
        default_target="leak",
    )


async def _send(hass, **data):
    payload: dict = {"message": "Leak!"}
    if data:
        payload["data"] = data
    await hass.services.async_call("notify", "switchboard_leak", payload, blocking=True)
    await hass.async_block_till_done()


async def test_an_output_that_is_a_notify_entity_is_delivered_with_send_message(
    hass, enable_custom_integrations, install, set_person, notify_entity, routed_sensor
):
    """The whole feature: an entity id in `outputs` reaches the entity."""
    set_person("person.alice", "home")
    living_room = await notify_entity("living_room")
    await install(_entry(hass, ["notify.living_room"]))

    await _send(hass)

    assert living_room.messages, (
        "an output that is a `notify` entity id is delivered with "
        "`notify.send_message` (contract v0.7, ADR-0021 §6)"
    )
    message, title, extra = living_room.messages[0]
    assert message == "Leak!"
    assert title == "Leak alert", (
        "`title` is carried; whether the entity uses it is the entity's "
        "business, decided by `NotifyEntityFeature.TITLE`"
    )
    assert extra == {}, "`message` and `title` are the only things carried"
    assert routed_sensor().state == "1"


async def test_an_entity_output_carries_no_data_and_the_call_still_succeeds(
    hass, enable_custom_integrations, install, set_person, notify_entity, drop_reasons
):
    """`data` cannot travel to an entity, and trying would fail every call.

    `notify.send_message`'s schema is `{message: required, title: optional}`.
    A router that handed it the target's `default_data`, the caller's `data` or
    its own default `tag` would raise `vol.Invalid` on every single delivery —
    which is why the limitation is documented rather than worked around.
    """
    set_person("person.alice", "home")
    living_room = await notify_entity("living_room")
    await install(_entry(hass, ["notify.living_room"], default_data={"volume": 0.6}))

    await _send(hass, priority="critical", campaign="night")

    assert len(living_room.messages) == 1
    assert living_room.messages[0][2] == {}
    assert "delivery_failed" not in drop_reasons()


async def test_an_entity_that_does_not_support_a_title_still_gets_the_message(
    hass, enable_custom_integrations, install, set_person, notify_entity
):
    """Core drops the title for such an entity; the router does not have to."""
    set_person("person.alice", "home")
    chime = await notify_entity("chime", title=False)
    await install(_entry(hass, ["notify.chime"]))

    await _send(hass)

    assert len(chime.messages) == 1
    message, title, _extra = chime.messages[0]
    assert message == "Leak!"
    assert title is None, (
        "`NotifyEntity.async_send_message` only passes a title on when the "
        "entity declares `NotifyEntityFeature.TITLE` "
        "($HA_CORE_SRC/homeassistant/components/notify/__init__.py)"
    )


async def test_a_registered_legacy_service_wins_over_an_entity_of_the_same_name(
    hass, enable_custom_integrations, install, set_person, notify_entity, mock_outputs
):
    """The resolution order, pinned: service first, then entity.

    A legacy notify service and a notify entity share one namespace, so an
    installation where both exist under one name has to have a defined answer.
    The service wins, which is exactly what every output that works today
    already does.
    """
    set_person("person.alice", "home")
    living_room = await notify_entity("living_room")
    await install(_entry(hass, ["notify.living_room"]))
    calls = mock_outputs("living_room")

    await _send(hass)

    assert len(calls["living_room"]) == 1
    assert living_room.messages == [], (
        "a registered legacy service takes precedence over an entity of the "
        "same name (ADR-0021 §6)"
    )


async def test_an_available_entity_is_not_reported_missing_but_an_absent_one_is(
    hass, enable_custom_integrations, install, set_person, notify_entity, drop_reasons
):
    """A missing entity is a missing output, and an existing one is not."""
    set_person("person.alice", "home")
    await notify_entity("living_room")
    await install(_entry(hass, ["notify.living_room", "notify.nowhere"]))

    answer = (await explain(hass, target="leak"))["persons"]["person.alice"]

    assert answer["outputs"] == ["notify.living_room"], (
        "an output that resolves to a real `notify` entity is reachable, and "
        "`explain` says so (ADR-0021 §6)"
    )
    assert answer["missing_outputs"] == ["notify.nowhere"], (
        "an entity id that is in no state machine is a missing output, exactly "
        "as a service that is not registered is"
    )

    await _send(hass)
    assert "delivery_failed" not in drop_reasons(), (
        "one output answered, so the person was notified"
    )


async def test_an_output_naming_the_routers_own_notify_entity_is_refused(
    hass, enable_custom_integrations, install, set_person, mock_outputs, drop_reasons
):
    """`notify.switchboard` is this integration's own entity — and now a real loop.

    Before §6 an output naming it was a service that did not exist and did
    nothing; with §6 it would resolve to a live entity. The recursion guard is
    what stops it, on the entity path as on the service path.
    """
    set_person("person.alice", "home")
    mock_outputs("mobile_app_alice")
    await install(_entry(hass, ["mobile_app_alice", "notify.switchboard"]))

    await _send(hass)

    assert "recursion" in drop_reasons(), (
        "an output resolving to `notify.switchboard*` is refused at runtime, "
        "whether it names a service or an entity (contract §Output)"
    )

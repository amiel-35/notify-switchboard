"""Services registered in `async_setup` (contract v0.3, ADR-0017 §5).

Written before the Sprint 3 implementation exists, against:

- `docs/contract.md` §"v0.3 addendum (ADR-0017)" → "Service availability"
- `docs/ADR/0017-debts-and-robustness.md` §5
- `docs/sprints/sprint-3-brief.md` item 5

The quality-scale rule `action-setup` exists because a service that only
appears once a config entry is loaded makes every automation referencing it
fail its own validation at startup with "action not found" — a message that
says nothing about the actual cause. 0.2.0 registers the five
`notify_switchboard.*` services in `async_setup_entry` and removes them on
unload, so this is exactly what a user with a broken entry gets today.

From 0.3.0 the five exist as soon as the integration is set up. Called while
no entry is loaded, each refuses in the way ADR-0015 already requires of a
refused call: `ServiceValidationError`, translated, never a silent no-op.

Note on `pytest.raises(ServiceValidationError)` alone being insufficient
here: core's `ServiceNotFound` **is a subclass of** `ServiceValidationError`
(`homeassistant/exceptions.py`), so an unregistered service would satisfy a
bare `raises`. Every test below therefore asserts `has_service` first and the
`translation_key` after.
"""

from __future__ import annotations

import pytest
from homeassistant.exceptions import ServiceNotFound, ServiceValidationError
from homeassistant.helpers import translation
from homeassistant.setup import async_setup_component

from custom_components.notify_switchboard.const import DOMAIN

from .conftest import make_entry, make_person, make_target

ERROR_TRANSLATION_KEY = "no_loaded_entry"

# The five UI services of contract v0.2, with a minimally valid payload each.
# Nothing here is expected to reach the validation of these fields: with no
# entry loaded, the refusal happens before any of them is looked at.
SERVICE_CALLS: list[tuple[str, dict]] = [
    ("acknowledge", {"target": "leak"}),
    ("snooze", {"target": "leak", "minutes": 15}),
    ("unsnooze", {"target": "leak"}),
    ("silence", {"person": "person.alice", "minutes": 15}),
    ("unsilence", {"person": "person.alice"}),
]


async def test_the_five_services_exist_without_any_config_entry(
    hass, enable_custom_integrations
):
    """Quality-scale `action-setup`: registration belongs to `async_setup`."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    for service, _data in SERVICE_CALLS:
        assert hass.services.has_service(DOMAIN, service), (
            f"{DOMAIN}.{service} must exist as soon as the integration is set "
            "up, with or without a loaded config entry"
        )


@pytest.mark.parametrize(("service", "data"), SERVICE_CALLS)
async def test_calling_a_service_without_a_loaded_entry_is_refused(
    hass, enable_custom_integrations, service, data
):
    """A translated `ServiceValidationError`, not `ServiceNotFound`, not silence."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, service, data, blocking=True)

    assert not isinstance(err.value, ServiceNotFound), (
        f"{DOMAIN}.{service} is not registered at all; the refusal must come "
        "from the handler, not from the service registry"
    )
    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == ERROR_TRANSLATION_KEY


@pytest.mark.parametrize("language", ["en", "fr", "es"])
async def test_the_refusal_message_is_translated(
    hass, enable_custom_integrations, language
):
    """`strings.json` and all three translation files carry the exception text."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    strings = await translation.async_get_translations(
        hass, language, "exceptions", {DOMAIN}
    )
    key = f"component.{DOMAIN}.exceptions.{ERROR_TRANSLATION_KEY}.message"
    assert strings.get(key), f"translations/{language}.json must define {key}"


async def test_the_services_still_work_once_an_entry_is_loaded(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Moving the registration must not change what a loaded entry does.

    `unsilence` is the one service ADR-0016 makes idempotent, so it is the
    cheapest proof that the handler found the loaded switchboard rather than
    refusing with `no_loaded_entry`.
    """
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    await hass.services.async_call(
        DOMAIN, "silence", {"person": "person.alice", "minutes": 30}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.alice_silenced").state == "on"

    await hass.services.async_call(
        DOMAIN, "unsilence", {"person": "person.alice"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.alice_silenced").state == "off"


async def test_unloading_the_entry_leaves_the_services_registered(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Unloading removes the ability to act, not the services themselves.

    0.2.0 unregistered them so that no closure kept a dead `Switchboard`; from
    0.3.0 the handlers look the entry up at call time instead, which is what
    makes `no_loaded_entry` reachable at all.
    """
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    for service, data in SERVICE_CALLS:
        assert hass.services.has_service(DOMAIN, service)
        with pytest.raises(ServiceValidationError) as err:
            await hass.services.async_call(DOMAIN, service, data, blocking=True)
        assert err.value.translation_key == ERROR_TRANSLATION_KEY

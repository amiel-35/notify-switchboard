"""Persistence across restart tests (contract §"Buttons and callbacks": snooze survives restarts).

Storage is mocked in-process by the `hass_storage` fixture (already wired into the
`hass` fixture by pytest-homeassistant-custom-component); a config entry
unload + setup cycle on the *same* `hass_storage` dict stands in for a real HA
restart without needing to tear down and rebuild the whole test HomeAssistant
instance.
"""

from __future__ import annotations

from homeassistant.core import Context

from .conftest import make_entry, make_person, make_target


async def test_snooze_survives_a_config_entry_unload_and_reload(
    hass, hass_storage, enable_custom_integrations, install, mock_outputs, set_person
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
                snooze_minutes=[60],
            )
        ],
        default_target="leak",
    )
    await install(entry)

    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": "switchboard:snooze:leak:60", "device_id": "unresolvable-device"},
        context=Context(user_id="test-user"),
    )
    await hass.async_block_till_done()

    # Sanity check: the snooze is active before the simulated restart.
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "before restart"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 0

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "after restart"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 0  # still snoozed: Store data survived


async def test_config_entry_declares_version_1(
    hass, enable_custom_integrations, install
):
    """Contract/brief: ConfigEntry.version = 1, minor_version = 1 (migration scaffolding present).

    This does not exercise an actual version-upgrade migration (there is no prior
    version to migrate from yet in Sprint 1) -- see README "Assumptions" for why
    a from-old-version migration test is deferred to whichever sprint first bumps
    the schema.
    """
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Fuite d'eau", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    assert entry.version == 1
    assert entry.minor_version == 1

"""UI services tests (contract §"UI services (v0.2, ADR-0016)", sprint-2-brief.md).

Written before the Sprint 2 implementation exists, against:

- `docs/contract.md` §"UI services (v0.2, ADR-0016)"
- `docs/ADR/0016-ui-services-and-row-texts.md`
- `docs/sprints/sprint-2-brief.md`

Unlike the Companion callback path (`mobile_app_notification_action`, tested
in `test_s1_actions.py`), which logs and returns on a refused action because
there is nobody on that path to answer, every one of these five services is
a real domain service call: a refused or invalid call must raise
`ServiceValidationError`, not silently no-op. That is the behavioural
difference this file exists to pin down; every scenario below is expected to
fail against the Sprint 1 codebase because none of `notify_switchboard.
{acknowledge,snooze,unsnooze,silence,unsilence}` are registered services yet
-- the whole file should fail on assertions/`ServiceNotFound`, never on
import.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import homeassistant.util.dt as dt_util
import pytest
import yaml
from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.notify_switchboard.const import ATTR_PRIORITY, DOMAIN

from .conftest import make_entry, make_person, make_target

INTEGRATION_DIR = Path("custom_components") / "notify_switchboard"

# ---------------------------------------------------------------------------
# notify_switchboard.acknowledge
# ---------------------------------------------------------------------------


async def test_acknowledge_service_turns_off_the_row_alert_when_allowed(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Same allow-list as the Companion button (ADR-0009), but as a service call."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "leak",
                "Fuite d'eau",
                alert_entity="alert.test_leak",
                allow_acknowledge=True,
                audience=["person.alice"],
            )
        ],
        default_target="leak",
    )
    await install(entry)

    assert await async_setup_component(
        hass,
        "alert",
        {
            "alert": {
                "test_leak": {
                    "name": "Fuite d'eau",
                    "entity_id": "binary_sensor.leak_sensor",
                    "state": "on",
                    "repeat": [60],
                    "can_acknowledge": True,
                    "skip_first": False,
                    "notifiers": ["switchboard_leak"],
                }
            }
        },
    )
    await hass.async_block_till_done()

    hass.states.async_set("binary_sensor.leak_sensor", "on")
    await hass.async_block_till_done()
    assert hass.states.get("alert.test_leak").state == "on"

    await hass.services.async_call(
        DOMAIN,
        "acknowledge",
        {"target": "leak"},
        blocking=True,
        context=Context(user_id="test-user"),
    )
    await hass.async_block_till_done()

    assert hass.states.get("alert.test_leak").state == "off"


async def test_acknowledge_service_is_refused_for_an_unknown_target(
    hass, enable_custom_integrations, install
):
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Fuite d'eau", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "acknowledge",
            {"target": "totally_unknown_slug"},
            blocking=True,
        )


async def test_acknowledge_service_is_refused_for_a_row_without_an_alert(
    hass, enable_custom_integrations, install
):
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "other",
                "Other (no alert linked)",
                alert_entity=None,
                allow_acknowledge=True,
                audience=["person.alice"],
            )
        ],
        default_target="other",
    )
    await install(entry)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "acknowledge",
            {"target": "other"},
            blocking=True,
        )


async def test_acknowledge_service_is_refused_when_the_row_disallows_it(
    hass, enable_custom_integrations, install
):
    """A row with an alert but `allow_acknowledge: False` is refused too."""
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "leak",
                "Fuite d'eau",
                alert_entity="alert.test_leak",
                allow_acknowledge=False,
                audience=["person.alice"],
            )
        ],
        default_target="leak",
    )
    await install(entry)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "acknowledge",
            {"target": "leak"},
            blocking=True,
        )


# ---------------------------------------------------------------------------
# notify_switchboard.snooze / unsnooze
# ---------------------------------------------------------------------------


async def test_snooze_service_is_bounded_to_the_rows_snooze_minutes(
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
                snooze_minutes=[15, 60],
            )
        ],
        default_target="leak",
    )
    await install(entry)

    # A value the row does not offer is refused, and nothing is stored.
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "snooze",
            {"target": "leak", "minutes": 45, "person": "person.alice"},
            blocking=True,
        )

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "still checking"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 1  # the refused call snoozed nobody

    # A value the row does offer is accepted and blocks routing.
    await hass.services.async_call(
        DOMAIN,
        "snooze",
        {"target": "leak", "minutes": 60, "person": "person.alice"},
        blocking=True,
    )
    await hass.async_block_till_done()

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "still leaking"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 1  # unchanged: dropped as snoozed


async def test_snooze_service_with_a_person_only_snoozes_that_person(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    calls = mock_outputs("mobile_app_alice", "mobile_app_bob")
    set_person("person.alice", "home")
    set_person("person.bob", "home")

    entry = make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        targets=[
            make_target(
                "leak",
                "Fuite d'eau",
                audience=["person.alice", "person.bob"],
                snooze_minutes=[60],
            )
        ],
        default_target="leak",
    )
    await install(entry)

    await hass.services.async_call(
        DOMAIN,
        "snooze",
        {"target": "leak", "minutes": 60, "person": "person.alice"},
        blocking=True,
    )
    await hass.async_block_till_done()

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "still leaking"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 0  # snoozed
    assert len(calls["mobile_app_bob"]) == 1  # not touched


async def test_snooze_service_without_a_person_snoozes_the_whole_audience(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    calls = mock_outputs("mobile_app_alice", "mobile_app_bob")
    set_person("person.alice", "home")
    set_person("person.bob", "home")

    entry = make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        targets=[
            make_target(
                "leak",
                "Fuite d'eau",
                audience=["person.alice", "person.bob"],
                snooze_minutes=[60],
            )
        ],
        default_target="leak",
    )
    await install(entry)

    await hass.services.async_call(
        DOMAIN,
        "snooze",
        {"target": "leak", "minutes": 60},
        blocking=True,
    )
    await hass.async_block_till_done()

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "still leaking"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 0
    assert len(calls["mobile_app_bob"]) == 0


async def test_snooze_service_persists_across_a_config_entry_unload_and_reload(
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

    await hass.services.async_call(
        DOMAIN,
        "snooze",
        {"target": "leak", "minutes": 60, "person": "person.alice"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "after restart"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 0  # still snoozed: Store data survived


async def test_unsnooze_service_clears_an_active_snooze_immediately(
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
                snooze_minutes=[60],
            )
        ],
        default_target="leak",
    )
    await install(entry)

    await hass.services.async_call(
        DOMAIN,
        "snooze",
        {"target": "leak", "minutes": 60, "person": "person.alice"},
        blocking=True,
    )
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN,
        "unsnooze",
        {"target": "leak", "person": "person.alice"},
        blocking=True,
    )
    await hass.async_block_till_done()

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "unsnoozed already"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1  # no longer snoozed


# ---------------------------------------------------------------------------
# notify_switchboard.silence / unsilence
# ---------------------------------------------------------------------------


async def test_silence_service_turns_on_the_binary_sensor_and_drops_routing(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Fuite d'eau", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    assert hass.states.get("binary_sensor.alice_silenced").state == "off"

    await hass.services.async_call(
        DOMAIN,
        "silence",
        {"person": "person.alice", "minutes": 60},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.alice_silenced").state == "on"

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m1"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 0

    dropped = hass.states.get("sensor.switchboard_dropped_today")
    assert "silenced" in dropped.attributes["reasons"]


async def test_silence_service_does_not_block_a_critical_priority_message(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Fuite d'eau", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    await hass.services.async_call(
        DOMAIN,
        "silence",
        {"person": "person.alice", "minutes": 60},
        blocking=True,
    )
    await hass.async_block_till_done()

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "m1", "data": {ATTR_PRIORITY: "critical"}},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1  # critical bypasses temporary silence


async def test_silence_service_persists_across_a_config_entry_unload_and_reload(
    hass, hass_storage, enable_custom_integrations, install, mock_outputs, set_person
):
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Fuite d'eau", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    await hass.services.async_call(
        DOMAIN,
        "silence",
        {"person": "person.alice", "minutes": 60},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.alice_silenced").state == "on"


async def test_silence_service_expires_after_its_duration(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Fuite d'eau", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    await hass.services.async_call(
        DOMAIN,
        "silence",
        {"person": "person.alice", "minutes": 60},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.alice_silenced").state == "on"

    freezer.tick(timedelta(minutes=61))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.alice_silenced").state == "off"

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m1"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 1


async def test_silence_service_with_zero_minutes_is_a_service_validation_error(
    hass, enable_custom_integrations, install
):
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Fuite d'eau", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "silence",
            {"person": "person.alice", "minutes": 0},
            blocking=True,
        )

    assert hass.states.get("binary_sensor.alice_silenced").state == "off"


async def test_silence_service_with_an_unknown_person_is_a_service_validation_error(
    hass, enable_custom_integrations, install
):
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Fuite d'eau", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "silence",
            {"person": "person.someone_else", "minutes": 60},
            blocking=True,
        )


async def test_unsilence_service_lifts_silence_immediately(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Fuite d'eau", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    await hass.services.async_call(
        DOMAIN,
        "silence",
        {"person": "person.alice", "minutes": 60},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.alice_silenced").state == "on"

    await hass.services.async_call(
        DOMAIN,
        "unsilence",
        {"person": "person.alice"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.alice_silenced").state == "off"

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m1"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 1


async def test_unsilence_service_is_a_noop_when_not_silenced(
    hass, enable_custom_integrations, install
):
    """Contract: unsilence on a person who is not temporarily silenced is not an error."""
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Fuite d'eau", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    await hass.services.async_call(
        DOMAIN,
        "unsilence",
        {"person": "person.alice"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.alice_silenced").state == "off"


# ---------------------------------------------------------------------------
# services.yaml + translations (brief item 6)
# ---------------------------------------------------------------------------

EXPECTED_SERVICES = {
    "acknowledge": {"target"},
    "snooze": {"target", "minutes", "person"},
    "unsnooze": {"target", "person"},
    "silence": {"person", "minutes"},
    "unsilence": {"person"},
}


def test_services_yaml_declares_all_five_services_with_their_fields():
    services_yaml = INTEGRATION_DIR / "services.yaml"
    assert services_yaml.exists(), (
        f"{services_yaml} is missing: every notify_switchboard.* service must "
        "be declared for the Developer Tools > Services UI and for HA to "
        "validate calls against a schema."
    )

    declared = yaml.safe_load(services_yaml.read_text(encoding="utf-8")) or {}
    # v0.2 froze these five; later addenda add services (v0.4: `explain`,
    # ADR-0018) that must also be declared here, so the five are a floor,
    # not an exact set. Nothing frozen may be missing.
    assert set(EXPECTED_SERVICES) <= set(declared)

    for service, expected_fields in EXPECTED_SERVICES.items():
        fields = set((declared[service] or {}).get("fields") or {})
        assert fields == expected_fields, (
            f"notify_switchboard.{service}: expected fields {expected_fields}, "
            f"found {fields}"
        )


@pytest.mark.parametrize("locale", ["en", "fr", "es"])
def test_translations_declare_a_matching_services_section(locale: str):
    """Key-parity extension: every service/field actually in services.yaml has a translation.

    Deliberately reads `services.yaml` itself (rather than the `EXPECTED_SERVICES`
    constant above) so this test also catches a translation drifting out of sync
    with a services.yaml that was edited without it, not only the five services
    this spec anticipates.
    """
    services_yaml = INTEGRATION_DIR / "services.yaml"
    assert services_yaml.exists()
    declared = yaml.safe_load(services_yaml.read_text(encoding="utf-8")) or {}

    if locale == "en":
        strings_path = INTEGRATION_DIR / "strings.json"
    else:
        strings_path = INTEGRATION_DIR / "translations" / f"{locale}.json"
    assert strings_path.exists()

    strings = json.loads(strings_path.read_text(encoding="utf-8"))
    services_section = strings.get("services") or {}

    for service, spec in declared.items():
        expected_fields = set((spec or {}).get("fields") or {})
        assert service in services_section, (
            f"{strings_path} is missing a translation for notify_switchboard.{service}"
        )
        entry = services_section[service]
        assert entry.get("name")
        assert entry.get("description")
        translated_fields = set(entry.get("fields") or {})
        assert translated_fields == expected_fields, (
            f"{strings_path}: notify_switchboard.{service} fields "
            f"{translated_fields} do not match services.yaml's {expected_fields}"
        )
        for field in expected_fields:
            assert entry["fields"][field].get("name")
            assert entry["fields"][field].get("description")

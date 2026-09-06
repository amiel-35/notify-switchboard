# Notify Switchboard — Sprint 1 acceptance tests

This directory is the executable specification for
`custom_components.notify_switchboard`, written **before** the integration
exists, against:

- `docs/contract.md` (frozen public contract, ADR-011)
- `docs/sprints/sprint-1-brief.md` (Sprint 1 scope)
- `docs/fr/doctrine.md` §3 and §5 (architecture and
  technical standards)

The coding agent implementing Sprint 1 **must make these tests pass without
modifying them**. When a test file is copied into the real
`amiel-35/notify-switchboard` repository, it lives at `tests/acceptance/` at
the repo root, next to `custom_components/notify_switchboard/`.

Verified against: Home Assistant 2026.9.1,
`pytest-homeassistant-custom-component` 0.13.364, Python 3.14, using the venv
at `/Users/amiellavon/Projets/_ref/venv-ha-2026.9` and the core clone at
`/Users/amiellavon/Projets/_ref/home-assistant-core`. Every helper used
below was confirmed to exist there (paths given inline).

## Constant names relied upon

Tests import exactly three names from `custom_components.notify_switchboard.const`:

| Name | Required value | Why |
|---|---|---|
| `DOMAIN` | `"notify_switchboard"` | integration domain (ADR-011, frozen) |
| `ATTR_PRIORITY` | `"priority"` | key under `data` in a notify call (contract §"Input") |
| `ATTR_SOURCE_ENTITY` | `"source_entity"` | key under `data` in a notify call (contract §"Input") |

No other constant is imported from the implementation. In particular, the
config-entry **options shape** below is built by the test suite itself as
plain Python dicts with literal string keys (see `conftest.py`:
`make_person`, `make_target`, `make_options`) — the implementation does not
need to expose `CONF_*` constants for nested option fields, it only needs to
read `entry.options` in exactly the shape documented below. This was a
deliberate choice to keep the implementation's required public surface
minimal; see "Assumptions" below.

## Options shape (`entry.options`) — NORMATIVE

```python
entry.options = {
    "persons": [
        {
            "entity_id": "person.alice",  # a person.* entity id
            "outputs": [
                "mobile_app_alice"
            ],  # notify service names, WITHOUT the "notify." prefix
            "silence_entities": [
                "input_boolean.alice_silence"
            ],  # entity ids; state "on" == silent
            "wake_time": "07:00:00",  # "HH:MM:SS" or None; end of night silence
        },
        ...,
    ],
    "targets": [
        {
            "slug": "leak",  # -> notify.switchboard_leak
            "name": "Fuite d'eau",  # display name; also the observer-mode fallback message
            "class": "building",  # free text, grouping only, never a code constant
            "default_priority": "normal",  # info|normal|high|critical
            "alert_entity": "alert.test_leak",  # optional alert.* this row is tied to, or None
            "audience": ["person.alice", "person.bob"],  # list of person.* entity ids
            "presence_rule": "always",  # always|home_only|away_only
            "allow_acknowledge": True,  # bool
            "snooze_minutes": [15, 60],  # list[int]; [] == no snooze button
            "default_data": {
                "channel": "family"
            },  # dict merged under caller's data (caller wins)
            "observer_mode": False,  # bool
        },
        ...,
    ],
    "default_target": "leak",  # slug used by notify.switchboard with no target,
    # and by the NotifyEntity degraded path
}
```

`ConfigEntry.version = 1`, `minor_version = 1` (brief item 12).

## What the tests build state-wise, and why

- **`person.*` states are set directly** with `hass.states.async_set(...)`,
  never through the real `person` integration (which is storage/collection
  backed and irrelevant to what the router reads — only the bare state
  `"home"` / `"not_home"` matters, per contract §"Routing decision").
- **Outputs are mocked** with `async_mock_service(hass, "notify", "<name>")`
  (`pytest_homeassistant_custom_component/common.py:380`), never the real
  `mobile_app` integration. The router only needs `notify.<output>` to exist
  as a service and treats any service whose name starts with `mobile_app_`
  as a Companion target for button-adding purposes (brief item 5) — this is
  a string check, not a dependency on the real `mobile_app` component's
  internal architecture (see "Contract ambiguities" below re: `mobile_app`
  no longer registering legacy per-device notify services in 2026.9).
- **The real `alert` component** (`homeassistant/components/alert/`) is used
  in `test_s1_actions.py` for the acknowledge scenarios (it is what actually
  calls `notify.switchboard_<slug>` through its `notifiers` list, exactly as
  a real deployment would configure it) but **not** in
  `test_s1_observer.py` (see below).

## Assumptions the implementation must satisfy

These are implementation details the contract/brief leave open. Each is the
simplest choice; where a test depends on one, the test's docstring says so.

1. **Per-person entity naming.** `binary_sensor.<p>_silenced`,
   `sensor.<p>_last_notification`, `sensor.<p>_active_snoozes` use `<p>` =
   the **object_id** of the person's `entity_id` (e.g. `person.alice` →
   `binary_sensor.alice_silenced`). The contract only fixes the `unique_id`
   scheme, not the entity_id/slug; `test_contract.py` asserts this literal
   naming.
2. **`sensor.switchboard_dropped_today` reasons attribute** is exposed under
   the key `"reasons"` and supports Python's `in` operator for a reason
   string (i.e. it is a `dict[str, int]` keyed by reason, or a
   `list[str]`/`set[str]` of reasons — tests only ever assert
   `"silenced" in reasons`, `"recursion" in reasons`, etc., never a specific
   container type or count beyond "at least one").
3. **Ambiguous device → person resolution for snooze (brief item 6)**: when
   the `mobile_app_notification_action` event's `device_id` does not resolve
   to a specific person (e.g. no matching device registry entry — the
   situation the acceptance tests exercise, by firing the event with an
   arbitrary `device_id` that was never registered), the brief explicitly
   allows falling back to "snooze for all persons in the audience of the
   row". The acceptance suite **only** exercises this documented fallback
   (`test_s1_actions.py::test_snooze_action_drops_delivery_then_expires_after_its_duration`,
   `test_s1_persistence.py::test_snooze_survives_a_config_entry_unload_and_reload`).
   It does **not** assert anything about the "resolves to exactly one
   person" path, because the exact device-registry → config-entry →
   service-name mapping is an internal heuristic not fixed by the contract
   (see "Contract ambiguities" below). The implementation is free to
   implement single-person resolution too; it is simply untested here.
4. **Night deferral bypasses the live silence check at `wake_time`.** The
   tests turn the person's `silence_entities` off at the moment they advance
   the clock to `wake_time`, so this assumption is not load-bearing for
   passing the tests — but conceptually, `wake_time` is documented as "end
   of night silence" (brief item 2), so a real schedule helper would already
   be `off` by then. The implementation should not need to special-case
   "still silenced at the moment the deferred message would fire".
5. **Recursion detection must be synchronous / non-looping at runtime.**
   `test_s1_routing.py::test_output_pointing_back_to_switchboard_is_rejected_as_recursion`
   configures a person whose only output is itself a `switchboard_*`
   service and carries a `pytest.mark.timeout(10)` safety net: an
   implementation that fails to detect recursion and instead actually calls
   itself would hang rather than fail cleanly, so the timeout exists to turn
   that into a fast, legible test failure instead of a stuck CI job.
6. **No migration-from-old-version test.** Sprint 1 is also where `version =
   1` is introduced, so there is no prior schema to migrate *from* yet.
   `test_s1_persistence.py::test_config_entry_declares_version_1` only
   checks the declared version/minor_version; a real "migrate an old entry"
   test is deferred to whichever future sprint first bumps the schema.

## Contract ambiguities found while writing these tests

Flagging these for the coding agent and/or a follow-up ADR — none of them
block Sprint 1, but they are real gaps between the brief/doctrine text and
either the frozen contract or the actual Home Assistant 2026.9.1 core
behaviour:

1. **Observer mode's "alert's `message` attribute" does not exist on a real
   `alert.*` entity.** Brief item 8 says: "`idle→on` route the alert's
   `message` attribute if present else the row name" and "`→idle` route the
   `done_message` if the alert exposes one". Inspecting
   `homeassistant/components/alert/entity.py` in the pinned core clone shows
   `AlertEntity` has **no `extra_state_attributes` property at all** — its
   `message`/`done_message` templates are rendered internally only to build
   the payload sent to `notifiers`; they are never surfaced as state
   attributes on `alert.*` itself. So a real `alert.*` entity will **always**
   take the "attribute absent" fallback branch in practice today. This is
   either (a) an intentional design of `notify_switchboard` where the
   integration's own config (`alert_entity` + a template it owns) is meant
   to supply the message/done_message rather than reading them off the
   `alert` entity's state — which would make brief item 8's wording
   misleading — or (b) a real gap that needs an upstream `alert` component
   change or a documented limitation. `test_s1_observer.py` sidesteps this
   by driving a synthetic `alert.*`-shaped `entity_id` directly with
   `hass.states.async_set(..., attributes={"message": ...})` so both
   branches are still deterministically testable at the router level,
   independent of what the real `alert` platform can or cannot expose. This
   should be raised as an ADR question before Sprint 2 cards build UI copy
   around it.
2. **`mobile_app` no longer registers legacy per-device `notify.mobile_app_*`
   services in current core.** `homeassistant/components/mobile_app/notify.py`
   in the pinned 2026.9.1 clone shows the Companion push path is now a
   `NotifyEntity` (`MobileAppNotifyEntity`), not a legacy
   `BaseNotificationService` with a `targets` property. The doctrine and
   brief's `notify.mobile_app_<person>` naming is therefore not something a
   real, current mobile_app integration will hand you outright as a legacy
   service — whatever a person's `outputs` list contains has to just happen
   to be a legacy notify service that exists (which is exactly what the
   acceptance tests mock directly with `async_mock_service`, sidestepping
   the question). This doesn't affect Sprint 1 pass/fail, but the
   `notify.mobile_app_*`-prefix check in brief item 5 ("only services whose
   name starts with `notify.mobile_app_`") should be revisited once a real
   Companion device is wired up in S2/inflexion-01, since it may simply
   never match in practice with the modern integration.
3. **`unknown_target` repairs issue exact `issue_id`/`translation_key` is not
   specified.** `test_s1_routing.py::test_unknown_target_is_dropped_and_raises_one_repairs_issue`
   only asserts that at least one `issue_registry` entry with
   `domain == DOMAIN` exists after an unknown-target call; it does not pin
   an exact `issue_id` string, since the contract does not fix one.

## Running (once the implementation exists)

From the repository root (containing `custom_components/notify_switchboard/`
and this `tests/` tree):

```bash
/Users/amiellavon/Projets/_ref/venv-ha-2026.9/bin/python -m pytest tests/acceptance -v
```

The target repository's own `pytest.ini`/`pyproject.toml` must set
`asyncio_mode = auto` (or equivalent) for `pytest-asyncio`, as is standard
for every `pytest-homeassistant-custom-component`-based test suite — this
staging directory does not ship one since it has no importable
`custom_components/` yet and is not meant to be run standalone.

Lint the test files themselves with:

```bash
/Users/amiellavon/Projets/_ref/venv-ha-2026.9/bin/python -m ruff check tests/acceptance
```

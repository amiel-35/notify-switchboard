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

Sprint 2 (`test_s2_services.py`, `test_s2_row_texts.py`) is the executable
specification for the v0.2 addendum against `docs/contract.md` §"UI services
(v0.2, ADR-0016)" / §"Per-row texts (v0.2, ADR-0016)" and
`docs/sprints/sprint-2-brief.md`, written the same way and against the same
discipline: before the Sprint 2 implementation exists. Every Sprint 1 test
file must keep passing unmodified once Sprint 2's rows/fixtures exist —
Sprint 2 only ever *adds* optional, default-`None` fields.

Verified against: Home Assistant 2026.9.1,
`pytest-homeassistant-custom-component` 0.13.364, Python 3.14, using the venv
in a dedicated virtualenv (`$HA_VENV`) and a clone of the core repository
(`$HA_CORE`). Every helper used
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
            "message": None,  # str | None; template, v0.2 addendum (ADR-0016)
            "done_message": None,  # str | None; template, v0.2 addendum (ADR-0016)
            "default_title": None,  # str | None; v0.2 addendum (ADR-0016)
        },
        ...,
    ],
    "default_target": "leak",  # slug used by notify.switchboard with no target,
    # and by the NotifyEntity degraded path
}
```

`ConfigEntry.version = 1`, `minor_version = 1` (brief item 12).

### v0.2 addendum (ADR-0016, Sprint 2): `message`, `done_message`, `default_title`

Three optional per-row keys, added for Sprint 2 and built by `make_target`
with a default of `None` for all three, so every Sprint 1 test that calls
`make_target` without them keeps building the exact same row dict it always
has (this is asserted by re-running the whole S1 suite unmodified — see
"Running" below).

- `message` — a template string, rendered with the row's alert's current
  state exposed as `alert` in the template context (or `None` if the row has
  no `alert_entity`, or that entity does not currently exist). Read by
  observer mode on `idle -> on`, ahead of the row's bare `name` and behind
  the alert's own `message` attribute when present (see `test_s2_row_texts.py`).
- `done_message` — the same idea for the `on|off -> idle` transition, but the
  chain is deliberately **not** the mirror of `message`'s, and this paragraph
  originally described it the wrong way round (corrected in 0.3.0, ADR-0017 §6;
  `docs/contract.md` is authoritative): the row's `done_message` template comes
  **first**, then the alert's own `done_message` attribute, then the translated
  `common.back_to_normal`. Pinned by `test_s3_done_message.py`.
- `default_title` — used as the outgoing `title` when the caller did not
  supply one (a legacy `notify.switchboard[_<slug>]` call without `title`,
  or any observer-mode-generated message, which never had a caller to omit
  one from).

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
   Companion device is wired up on the development instance in S2, since it may
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
"$HA_VENV/bin/python" -m pytest tests/acceptance -v
```

The target repository's own `pytest.ini`/`pyproject.toml` must set
`asyncio_mode = auto` (or equivalent) for `pytest-asyncio`, as is standard
for every `pytest-homeassistant-custom-component`-based test suite — this
staging directory does not ship one since it has no importable
`custom_components/` yet and is not meant to be run standalone.

Lint the test files themselves with:

```bash
"$HA_VENV/bin/python" -m ruff check tests/acceptance
```

---

## Sprint 3 (`test_s3_*.py`, and the v0.3 additions to `test_contract.py`)

Executable specification for the v0.3 addendum, against `docs/contract.md`
§"v0.3 addendum (ADR-0017)", `docs/ADR/0017-debts-and-robustness.md` and
`docs/sprints/sprint-3-brief.md`. Same discipline as S1 and S2: written
before the implementation, and the coding agent must make them pass without
modifying them. Every S1 and S2 file keeps passing unmodified — Sprint 3 adds
no user-facing concept and no options key.

| File | What it pins |
|---|---|
| `test_s3_entities.py` | Friendly names follow `hass.config.language`; entity ids stay the frozen English ones in `fr` as in `en`; every entity has an `entity.<platform>.<key>.name` in en/fr/es; `sensor.switchboard_deferred_today` exists. |
| `test_s3_fanout.py` | All (person, output) deliveries of one decision run concurrently; each is bounded by `dispatcher.OUTPUT_TIMEOUT_SECONDS`; a timeout or an exception is accounted for exactly as a failed delivery already was. |
| `test_s3_callbacks.py` | `context.user_id` ↔ `person.user_id` resolves the acting person even when `device_id` is absent or points at somebody else; one `person_without_user_id` repair per unlinked person in a button-bearing row, deleted on reload once linked. |
| `test_s3_services.py` | The five UI services exist after `async_setup`, with no config entry; calling one then raises `ServiceValidationError` with translation key `no_loaded_entry`. |
| `test_s3_done_message.py` | The `done_message` fallback order, and the deliberate asymmetry with `message`. |
| `test_contract.py` | `sensor.switchboard_deferred_today`, and the entity-id freeze under `fr` / `es` / `en`. |

### Switching the instance language

`hass.config.language = "fr"` **before** the config entry is set up, exactly
as core's own tests do it (`$HA_CORE_SRC/tests/components/holiday/test_calendar.py`
line 164, `$HA_CORE_SRC/tests/components/google_assistant_sdk/test_helpers.py`,
`$HA_CORE_SRC/tests/components/assist_pipeline/test_pipeline.py` line 407).
Plain assignment, not `hass.config.async_update(...)`: the entity platform
reads `hass.config.language` once, in
`EntityPlatform.async_load_translations`, when the platform is set up, so the
language must be in place before `async_setup` of the entry and nothing needs
to be re-fired afterwards.

The **expected strings are never hard-coded**. The tests read them back from
the integration's own translation files through
`homeassistant.helpers.translation.async_get_translations(hass, language,
category, {DOMAIN})` (`$HA_CORE_SRC/homeassistant/helpers/translation.py`,
used the same way in `$HA_CORE_SRC/tests/helpers/test_translation.py`), for
the categories `entity`, `issues`, `exceptions` and `common`. What is
asserted is that the key exists, that it is non-empty, that the entity shows
it, and — for `fr` and `es` — that it is not simply a copy of the English
one. Choosing the actual wording is the coding agent's job, not the
specification's.

Why the language test matters rather than being a formality: `fr` and `es`
are both members of `NATIVE_ENTITY_IDS`
(`$HA_CORE_SRC/homeassistant/generated/languages.py`, line 75), and
`EntityPlatform.async_load_translations`
(`$HA_CORE_SRC/homeassistant/helpers/entity_platform.py`, lines 224-244)
builds object ids from that language's names. Adding `_attr_translation_key`
without also pinning the object id therefore *renames every entity* on a
French or Spanish install. `Entity.suggested_object_id`
(`$HA_CORE_SRC/homeassistant/helpers/entity.py`, line 748) is the documented
override; see ADR-0017 §2.

### Patching the fan-out timeout

`test_s3_fanout.py` patches
`custom_components.notify_switchboard.dispatcher.OUTPUT_TIMEOUT_SECONDS`
(30 s in production) down to a fraction of a second. The constant's **name
and module are part of the specification** — ADR-0017 §3 fixes them precisely
so the timeout is testable without waiting 30 s. The timing assertions are
written to sit between the parallel cost and the sequential cost of the same
scenario (roughly a factor of four apart), so they separate the two
implementations rather than measuring the machine.

### Assumptions added by Sprint 3

7. **The repair's `issue_id` is not pinned**, in the same spirit as
   assumption 3 of Sprint 1 and as `test_s1_routing.py`'s `unknown_target`
   assertion: the contract fixes no id. What `test_s3_callbacks.py` asserts
   is the `translation_key` (`person_without_user_id`), the severity
   (`warning`), `is_fixable is False`, *how many* issues exist for a given
   configuration, and that each one names its person somewhere in its
   `issue_id` or its `translation_placeholders`.
8. **The `person.*` `user_id` link is set as a plain state attribute** by the
   tests (`hass.states.async_set("person.alice", "home", {"user_id": ...})`),
   never through the real `person` integration — the same choice Sprint 1
   made for presence. Core writes exactly that attribute
   (`$HA_CORE_SRC/homeassistant/components/person/__init__.py`, line 650,
   `PersonEntityStateAttribute.USER_ID`).
9. **`ServiceNotFound` is a subclass of `ServiceValidationError`**
   (`$HA_CORE_SRC/homeassistant/exceptions.py`), so a bare
   `pytest.raises(ServiceValidationError)` would be satisfied by a service
   that is not registered at all. `test_s3_services.py` asserts
   `hass.services.has_service(...)` first and the `translation_key` after;
   any future test of a refusal should do the same.

### `test_s3_done_message.py` is green from the start, on purpose

Unlike the other four S3 files it passes against 0.2.0. The 0.2.0 *code*
already implements the contract's order; what disagrees with it is prose —
the "v0.2 addendum" section of this very README and
`docs/sprints/sprint-2-brief.md` item 8, both of which describe the
`done_message` chain the other way round (`docs/known-issues.md`,
2026-09-07). ADR-0017 §6 settles it in favour of `docs/contract.md` and
ADR-0016; the coding agent corrects the two prose documents, and this test
exists so that nobody later "fixes" the code to match them.

---

## Sprint 4 (`test_s4_*.py`, and the v0.4 additions to `test_contract.py`)

Executable specification for the v0.4 addendum, against `docs/contract.md`
§"v0.4 addendum (ADR-0018)", `docs/ADR/0018-zero-config-and-explainability.md`
and `docs/sprints/sprint-4-brief.md`. Same discipline as S1-S3: written before
the implementation, and the coding agent must make them pass without modifying
them. Every S1, S2 and S3 file keeps passing unmodified — Sprint 4 adds one
optional routing-table row key (`managed`) and changes no routing rule.

| File | What it pins |
|---|---|
| `test_s4_explain.py` | Every decision `notify_switchboard.explain` can return (`routed`, `deferred`, `dropped`) with its `reason`, its `until`, its `outputs`/`missing_outputs` and a `detail` that names the deciding object; `not_in_audience` answered rather than refused; unknown target/person refused; `SupportsResponse.ONLY`; the `detail` translated; and — the property the whole feature rests on — that asking changes nothing. |
| `test_s4_discovery.py` | The person editor's second step offers every legacy `notify.*` except `switchboard*`, puts this person's own Companion services first with a translated label, pre-selects them and their Focus `binary_sensor`s for a new person, suggests the *stored* values when editing an existing one, and still accepts a service that does not exist yet. |
| `test_s4_default_target.py` | The first person added to an empty table creates the `managed` `default` row and the default target, `notify.switchboard` reaches them straight away, a second person joins that audience, submitting the row editor clears `managed` for good — and the row editor's confirmation step carries the `alert:` snippet (brief item 7, pinned here because this is the file that drives that editor). |
| `test_s4_repairs.py` | `person_without_outputs` raised for a person in an audience with no outputs and cleared when they get one; `alert_entity_missing` raised only after the grace period and cleared once the alert exists; both translated in en/fr/es. |
| `test_s4_test_message.py` | The two options-menu test steps route one real, counted message carrying `data.tag: switchboard-test`, pick a row that actually reaches the chosen person, abort when none does, show the `explain` answer in the step description, and never rewrite `entry.options`. |
| `test_contract.py` | `notify_switchboard.explain` exists, is declared `SupportsResponse.ONLY`, and its response carries exactly the frozen keys. |

### Fixtures and helpers added in `conftest.py`

- **`make_target(..., managed=True)`** writes the v0.4 row key. It is only
  written when true, so every S1-S3 row keeps the exact dict it had — `managed`
  absent means false (contract v0.4).
- **`make_mobile_app_entry` / the `mobile_app_registration` fixture** build one
  Companion registration as a real `mobile_app` config entry, with the
  registration payload shape core's own tests use
  (`$HA_CORE_SRC/tests/components/mobile_app/test_notify.py`), plus its device
  and whichever `binary_sensor` entities the test wants on it. The `mobile_app`
  component itself is never set up: the router reads config entries, and
  setting the component up would drag in http, webhooks and a push relay for
  nothing.
- **`options_flow`** opens the options menu, picks a step and submits a
  sequence of inputs. S4 turns two one-shot forms into multi-step editors (the
  person editor of ADR-0018 §2, the row editor's confirmation step of §7), so
  every flow test needs four or five lines of the same boilerplate.
- **`schema_field` / `suggested_value` / `selector_options`** read a flow
  result's own `data_schema`: the selector's `.config` (what the frontend
  receives) and the marker's `description["suggested_value"]` (what
  `add_suggested_values_to_schema` pre-selected). Every discovery assertion
  goes through these, so what is pinned is the form a user sees, never how the
  implementation builds it.

### Assumptions added by Sprint 4

10. **Options-flow step ids are part of the specification.** `person` (pick
    the `person.*`), `person_outputs` (outputs / silence entities / wake
    time), `target_saved` (the row editor's confirmation), `test_person`,
    `test_target`, `test_result`. A form cannot react to a field it is
    showing, so pre-selecting a person's phones *requires* the person to be
    chosen in an earlier step; the ids are pinned so the tests can drive it.
    `edit_person` keeps picking an existing row and now opens
    `person_outputs`.
11. **`user_id` values are plain strings.** The link the router follows is an
    equality between the `user_id` state attribute of a `person.*` and the
    `user_id` stored in a `mobile_app` config entry's data. Nothing reads the
    auth provider, so the tests use literal ids — the same choice S1 made for
    presence and S3 for `person.user_id`.
12. **The alert grace period is reached by time travel, not by patching.**
    ADR-0018 §5 fixes it at 60 s in `dispatcher.ALERT_ENTITY_GRACE_SECONDS`,
    but `test_s4_repairs.py` advances the clock past it with
    `async_fire_time_changed` instead of importing the constant, so a red in
    that file is always a behavioural red and never an `ImportError` that
    hides the rest of the module. The constant still has to exist and has to
    be cancellable on unload, or the suite's lingering-timer check fails.
13. **The `issue_id` of the two new repairs is not pinned**, exactly as in
    assumption 7 for `person_without_user_id`. What is asserted is the
    `translation_key`, the severity, `is_fixable`, how many issues exist, and
    that each one names its subject in its `issue_id` or its
    `translation_placeholders`.
14. **The response of `explain` is a mapping, `persons` included.** Core
    answers per-entity questions that way (`weather.get_forecasts`,
    `calendar.get_events`). `outputs` and `missing_outputs` carry **full**
    `notify.*` service names, unlike the bare form stored in `entry.options`:
    `explain` is read by a human or a card, and the useful answer to "where
    would this go" is something you can paste into Developer tools.

### Two S4 tests are green from the start, on purpose

`test_s4_repairs.py::test_a_person_with_no_outputs_and_no_audience_raises_nothing`
and `::test_a_row_whose_alert_exists_raises_nothing` pass against 0.3.0,
because 0.3.0 raises neither repair in any circumstance. They exist for the
same reason `test_s3_done_message.py` did: to pin the *negative* half of a
rule that is easy to over-implement. A repair that fires for a person nobody
routes to, or for an alert that is perfectly fine, is worse than no repair.

### What Sprint 4 deliberately does not pin

- The wording of anything: the row name of the `default` row, the test
  message, the `detail` sentences, the "this person's device" marker. The
  tests read the translation files back or assert only that a string exists,
  differs between languages, and names the object it is about.
- The `recursion` case of `explain`. A person whose outputs include a
  `switchboard*` service produces both a routed delivery and a `recursion`
  drop in `router.decide`; ADR-0018 §1 says the routed answer wins and the
  recursive outputs are excluded from `outputs`, but no acceptance test drives
  it — the options flow refuses such an output at config time, so it can only
  be reached through a hand-edited `.storage` file.
- Which step the `test_result` form returns to when it is submitted.

---

## Sprint 5 (`test_s5_*.py`, and the v0.5 additions to `test_contract.py`)

Executable specification for the v0.5 addendum, against `docs/contract.md`
§"v0.5 addendum (ADR-0019)",
`docs/ADR/0019-night-catch-up-and-closing-the-loop.md` and
`docs/sprints/sprint-5-brief.md`. Same discipline as S1-S4: written before the
implementation, and the coding agent must make them pass without modifying
them. Sprint 5 adds three optional options keys (`ttl_minutes`, `summary`,
`clear_done`), two drop reasons and two `data` keys, and changes no routing
rule for a message that is not deferred.

**The one S1-S4 change Sprint 5 forces.** ADR-0019 §6 makes the router push a
`clear_notification` to the Companion outputs an episode reached when an
observer-mode row's `alert_entity` returns to `idle`. That push is an ordinary
`notify.mobile_app_*` call, so it lands in the same captured-calls list as a
real message — but **a clear is not a message**: it is not counted, it fires no
event, and it must never be read as the `done` message it follows. Every
acceptance test that counts calls or compares a message list on an output
after an observer `→ idle` therefore filters `"clear_notification"` out, in
S1-S3 as in S5. Six older tests were amended for that and for nothing else
(`test_s1_observer.py::test_observer_mode_routes_done_message_on_return_to_idle`,
`test_s2_row_texts.py::test_observer_mode_uses_the_rows_done_message_template`,
and the four `test_s3_done_message.py` tests that read `[-1]` after
`_drive_to_idle`, through that file's new `_messages()` helper). No assertion
was weakened: the same texts, in the same order, are still pinned.

Two consequences of §6 the suite deliberately does **not** pin, both settled by
the ADR's "Amendment 2026-09-07": the closing sequence is observer-mode only
(on a `notifiers:`-driven row core's `end_alerting` sends the done message
*before* the state reaches `idle`, so a clear there would wipe it), and an
episode left open by a real Home Assistant restart lingers until that row's
next `idle → on`, because core's `AlertEntity` never re-reads its watched
entity at startup.

| File | What it pins |
|---|---|
| `test_s5_ttl.py` | The per-priority defaults (`info` 120, `normal` 720, `high` none), the global `ttl_minutes` option, the per-call `data.ttl_minutes` override and its `0` opt-out, the new reason `expired`, and the fact that an expired deferral leaves the queue instead of waiting for the next night. |
| `test_s5_summary.py` | Three deferrals, two sharing a `tag`, become one two-line notification whose title carries the line count and whose `data` is `{"tag": "switchboard-summary"}` and nothing else; `summary: false` delivers three; a single survivor is delivered plainly, with its own tag and its own buttons; `common.summary_title` exists in en/fr/es with a `{count}` placeholder. |
| `test_s5_redecision.py` | A flush re-runs the whole decision: `presence` for somebody who left under a `home_only` row, `snoozed` for a row snoozed overnight, and — the half that must not change — `silenced` still holds the message instead of dropping it. The re-decision uses the message's original priority, not the row's current default. |
| `test_s5_early_flush.py` | The last active silence entity turning `off` at 05:00 flushes before the 07:00 wake time, with **no timer fired**; it does not deliver twice at the wake time; a running temporary silence, or a second silence entity still `on`, holds the queue. |
| `test_s5_episode.py` | A `done` message reaches only the persons the episode reached, through observer mode and through `data.switchboard_done: true`; the others are dropped with `not_notified`; the recipients survive a config-entry reload; an ordinary message is not filtered by the episode; a row with no `alert_entity` has no episodes at all. |
| `test_s5_clear.py` | The default `data.tag` `switchboard-<slug>` and the `data.notification_id` that mirrors it on the `persistent_notification` output (and only there); a caller's own values winning; `clear_notification` sent to the `mobile_app_*` outputs the episode reached and `persistent_notification.dismiss` for the matching id when the episode ends; the done message's own `-done` tag; `clear_done`; and the fact that a clear is not counted as a routed message. |
| `test_contract.py` | `expired` and `not_notified` as public drop reasons, `data.ttl_minutes` and `data.switchboard_done` as public input keys, and the default tag / notification id / summary tag values. |

### Fixtures and helpers added in `conftest.py`

- **`make_person(..., summary=False)`**, **`make_target(..., clear_done=True)`**
  and **`make_options(..., ttl_minutes={...})`** write the three v0.5 options
  keys. Each is only written when it differs from its default — `summary`
  defaults to **on** so it is written only when `False`; `clear_done` defaults
  to off and `ttl_minutes` is absent by default — so every S1-S4 row and every
  S1-S4 options dict keeps the exact dict it had.
- **`real_alert`** sets up one real `alert.*` watching one `binary_sensor` and
  returns an object with `begin()` / `end()`. Those move the watched sensor,
  so the alert goes through its own `idle → on` and `→ idle` transitions,
  which is what an episode *is* (ADR-0019 §5). The alert carries no
  `notifiers:` — the episode tests drive the router through observer mode or
  through `data.switchboard_done`, and an alert that also called
  `notify.switchboard_<slug>` would route everything twice — and `repeat` is
  long enough never to fire inside a test.
- **`drop_reasons`** returns the `reasons` attribute of
  `sensor.switchboard_dropped_today` (assumption 2 of Sprint 1 still applies:
  only `in`, never a container type or a count).
- **`deferred_sensor`** mirrors `routed_sensor` / `dropped_sensor` for
  `sensor.switchboard_deferred_today`.
- **`dismissals`** captures `persistent_notification.dismiss` calls, which is
  how the UI half of an episode is closed
  (`$HA_CORE_SRC/homeassistant/components/persistent_notification/__init__.py`).

### Moving time

Exactly as the S1 deferral tests do it (`test_s1_observer.py`): the instance is
pinned to `Europe/Paris` with `hass.config.async_set_time_zone`, the clock is
moved with `freezer.move_to` to an **absolute UTC instant** whose local
equivalent is written in a comment, and the wake-time timer is released with
`async_fire_time_changed(hass, dt_util.utcnow())`. Nothing patches a constant:
the 120 / 720 minute defaults are reached by waiting, so a red in
`test_s5_ttl.py` is always behavioural.

`test_s5_early_flush.py` deliberately does **not** fire a timer in its first
test. The delivery there must be caused by the silence entity's state change
alone; firing a timer as well would let an implementation that only reacts to
`wake_time` look correct.

### Assumptions added by Sprint 5

15. **The summary's line format is structural, its title is translated.** The
    tests assert how many lines there are, which messages and titles are in
    them and in what order — never the bullet, the dash or the wording. The
    title is asserted to exist and to carry the count; that
    `common.summary_title` exists in en/fr/es with a `{count}` placeholder is
    asserted separately, through
    `homeassistant.helpers.translation.async_get_translations` on the `common`
    category, the same way S3 reads entity names back.
16. **`persistent_notification` is an output like any other**, named by its
    bare legacy service name (`notify.persistent_notification`). It is what
    the `notification_id` rule keys on, and the tests mock it with
    `async_mock_service` exactly as they mock a Companion output — but they
    mock it **after** the config entry is up, not before. Setting the entry up
    sets up core's `notify` integration, whose `async_setup` registers
    `notify.persistent_notification` unconditionally
    (`$HA_CORE_SRC/homeassistant/components/notify/__init__.py`), and
    `ServiceRegistry._async_register` (`$HA_CORE_SRC/homeassistant/core.py`)
    replaces an existing handler silently. A mock made before `install(...)`
    is therefore gone by the time the first message goes out, and captures
    nothing. Three tests re-mock the bare output right after their
    `await install(...)` for exactly this reason:
    `test_s5_clear.py::test_a_message_carries_the_default_tag_and_notification_id`,
    `test_s5_clear.py::test_a_caller_supplied_tag_and_notification_id_win` and
    `test_contract.py::test_the_default_tag_and_notification_id_are_the_documented_values`.
    The other tests that use this output only need the call to *succeed* (so
    that the episode records it), which core's own handler does.
17. **The episode's tags are a set, normally of one.** ADR-0019 §6 gives every
    message a default `data.tag`, so an episode has exactly one tag unless a
    caller varied it; the clear is specified as one call per tag, and the
    tests only ever exercise the one-tag case.
18. **An episode ends when the `alert.*` reaches `idle`**, which for a real
    alert means the watched entity left the alert state (`end_alerting`), not
    an acknowledgement (`alert.turn_off`, which only sets `_ack` and leaves
    the state at `off`). That is why these tests need no
    `expected_lingering_timers` override: `end_alerting` cancels the repeat,
    and the S1/S2 acknowledge tests are still the only three that cannot.
19. **A clear is invisible to the counters.** `test_s5_clear.py` asserts
    `sensor.switchboard_routed_today` counts the two real messages of an
    episode and not the clears; nothing asserts a new event type, because
    ADR-0019 adds none.

### Tests that are green from the start, on purpose

Following `test_s3_done_message.py` and the two S4 repairs tests: the negative
half of a rule is worth pinning even when today's code already satisfies it.

- `test_s5_summary.py::test_summary_off_delivers_every_message_one_by_one` —
  a summary that cannot be turned off is worse than no summary.
- `test_s5_redecision.py::test_a_deferral_still_silenced_at_the_flush_is_kept_not_dropped`
  — a full re-decision must not start dropping messages because the night ran
  late.
- `test_s5_redecision.py::test_the_re_decision_uses_the_priority_the_message_was_queued_with`
  — 0.4.0 has no TTL to fall into, but re-deciding with the row's current
  default instead of the message's own priority is the most natural way to get
  §3 wrong.
- `test_s5_early_flush.py::test_no_early_flush_while_another_silence_entity_is_still_on`
  — the line an over-eager §4 crosses first.
- `test_s5_episode.py::test_a_row_without_an_alert_entity_has_no_episodes` —
  `not_notified` must be unreachable for a household that never wrote an
  `alert:` block.
- `test_s5_clear.py::test_a_caller_supplied_tag_and_notification_id_win` — a
  default that overrode a caller would be worse than no default; 0.4.0 already
  passes both keys through untouched, and §6 must not change that.

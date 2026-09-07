# ADR 0017: Debts and robustness — frozen ids under any language, parallel fan-out, canonical callbacks, services without an entry

Date: 2026-09-07

## Status

Accepted.

## Context

Sprint 3 adds no user-facing concept. It pays the debts that a serious HACS
review would stop on, and it fixes three correctness gaps found by re-reading
the 0.2.0 code base:

- `docs/known-issues.md` (2026-09-07, "entity display names are hard-coded in
  English") records that every entity of this integration passes a literal
  English `_attr_name` to its constructor, so a French or Spanish instance
  sees English entity names while every other string of the integration is
  translated. The fix touches every entity and every translation file at
  once, and it collides head-on with the frozen contract: the naive fix —
  `_attr_translation_key` and nothing else — **renames the entity ids** on
  exactly the instances the fix is for.
- `sensor.switchboard_deferred_today` has existed in code since 0.1.0 and is
  documented in `docs/ARCHITECTURE.md`, but never entered `docs/contract.md`.
  It is a public name that nothing pins.
- `dispatcher._async_deliver` awaits each output of each person in turn, and
  each `hass.services.async_call(..., blocking=True)` has no timeout. One
  Companion push service that hangs — a phone off the network, a cloud relay
  that stalls — blocks every other person's notification for as long as it
  takes, with no upper bound at all.
- The Companion callback path resolves the acting person by `context.user_id`
  first and by `device_id` second, but nothing tells the user when the first,
  exact path cannot work because their `person.*` is not linked to a Home
  Assistant user. They silently get the documented "snooze the whole
  audience" fallback instead.
- The five `notify_switchboard.*` services are registered in
  `async_setup_entry`. The quality-scale rule `action-setup` exists precisely
  because a service that only appears once an entry is loaded makes every
  automation referencing it fail validation at startup with "action not
  found" instead of with something a user can read.
- `docs/contract.md` and ADR-0016 order the `done_message` fallback one way,
  `tests/acceptance/README.md` and `docs/sprints/sprint-2-brief.md` the other
  (`docs/known-issues.md`, 2026-09-07). Nothing pins it.

## Decision

### 1. `sensor.switchboard_deferred_today` is a frozen public name

It joins `sensor.switchboard_routed_today` and
`sensor.switchboard_dropped_today` in the contract's names table and in
`tests/acceptance/test_contract.py`. Nothing about the entity changes; this
records that it may not be renamed without a new ADR, the same as its two
siblings. A deferral is neither routed nor dropped, and a card that wants to
say "three messages are waiting for the morning" has no other source.

### 2. Translated friendly names, English entity ids, in every language

Every entity of this integration gets `_attr_has_entity_name = True` (already
the case, `entity.SwitchboardEntity`) and a `_attr_translation_key`, with the
matching `entity.<platform>.<key>.name` strings in `strings.json` and in
`translations/{en,fr,es}.json`. The keys are the `kind` strings the entity
classes already use, so the translation key, the `unique_id` suffix and the
frozen object id all say the same word:

| Platform | `translation_key` | Frozen entity id |
|---|---|---|
| `sensor` | `routed_today` | `sensor.switchboard_routed_today` |
| `sensor` | `dropped_today` | `sensor.switchboard_dropped_today` |
| `sensor` | `deferred_today` | `sensor.switchboard_deferred_today` |
| `sensor` | `last_notification` | `sensor.<person object_id>_last_notification` |
| `sensor` | `active_snoozes` | `sensor.<person object_id>_active_snoozes` |
| `binary_sensor` | `silenced` | `binary_sensor.<person object_id>_silenced` |
| `event` | `delivery` | `event.switchboard_delivery` |

**The entity ids do not change, in any language.** This is not automatic, and
it is the whole reason this section exists rather than being a one-line commit
message. In core 2026.9.1, `EntityPlatform.async_load_translations`
(`homeassistant/helpers/entity_platform.py`, lines 224-244) picks the language
used to build object ids:

```python
object_id_language = (
    hass.config.language
    if hass.config.language in languages.NATIVE_ENTITY_IDS
    else languages.DEFAULT_LANGUAGE
)
```

and `fr` and `es` are both members of `NATIVE_ENTITY_IDS`
(`homeassistant/generated/languages.py`, line 75). On a French instance, core
would therefore build the object id out of the *French* entity name, and a
fresh install would come up with `sensor.switchboard_<french words>` — every
`alert:`, card and automation written against the documented names broken on
exactly the instances the translation was added for.

The mechanism that prevents it is `Entity.suggested_object_id`
(`homeassistant/helpers/entity.py`, property at line 748). By default it
returns the entity's name rendered through
`self.platform_data.object_id_platform_translations` — the localized name
above. Overridden to return the frozen English object id, it is used verbatim:
`_async_derive_object_ids` (`homeassistant/helpers/entity_platform.py`, line
1295) hands it to `EntityRegistry.async_get_or_create` as
`suggested_object_id`, which "has priority over `object_id_base`" and "will
not be prefixed with the device name"
(`homeassistant/helpers/entity_registry.py`, lines 1357-1361). The name the
user sees still comes from `Entity.name`, which reads
`platform_data.platform_translations` — the instance language.

Setting `self.entity_id` in `__init__`, which 0.2.0 does, reaches the same
result through `internal_integration_suggested_object_id`
(`homeassistant/helpers/entity_platform.py`, lines 887-909) and stays
acceptable; `suggested_object_id` is the documented, non-internal name for the
same intent and is what this ADR asks for. Either way the requirement is
behavioural and is what the acceptance test asserts: **frozen ids, translated
names, under `fr` as under `en`**.

Existing installs are unaffected regardless: a registry entry keeps the
entity id it was created with, whatever the integration suggests later. The
requirement is for *new* installs in any language.

Per-person entities keep reading as "<the person> <translated suffix>": they
carry `has_entity_name`, so Home Assistant composes the friendly name from
their device (one virtual device per person) and the translated entity name.

### 3. Parallel fan-out with a per-output timeout

All (person, output) deliveries of one routing decision run **concurrently**,
each wrapped in a timeout:

- `asyncio.gather(..., return_exceptions=True)` (the shape core itself uses
  for fan-out that must not be aborted by one member —
  `homeassistant/helpers/entity_platform.py` line 681,
  `homeassistant/core.py` line 1158);
- each delivery wrapped in `async with asyncio.timeout(OUTPUT_TIMEOUT_SECONDS)`
  (the shape core uses for a bounded await — `homeassistant/core.py` line
  1230, `homeassistant/helpers/condition.py` line 766);
- `OUTPUT_TIMEOUT_SECONDS` is a module constant of `dispatcher.py`, value
  **30 seconds**. It is a constant, not an option: it is a backstop against a
  hung service, not a tuning knob, and a row that needs a different one has a
  broken output, not a configuration need. Tests patch the constant.

Failure semantics are **exactly today's**, deliberately: a `TimeoutError` and
an exception from an output are both recorded the way a failing output is
recorded in 0.2.0 — the same `failing_outputs` counter feeding the same
`missing_output` repair after `MAX_CONSECUTIVE_OUTPUT_MISSES`, and, when
*every* output of one person failed, the same `delivery_failed` drop reason,
the same `sensor.switchboard_dropped_today` increment and the same `dropped`
`event.switchboard_delivery` payload. No new drop reason, no new event type,
no new counter. A person whose outputs did not all fail is still counted
routed once, as today.

What this changes for a caller: **the order of `event.switchboard_delivery`
events is no longer promised.** Counts are, per-person outcomes are, ordering
between two persons of the same decision is not. Nothing in the contract ever
promised it; this ADR says so out loud because concurrency makes the
difference observable.

Note that a slow output no longer holds the whole routing decision open: the
wall time of one decision is bounded by the slowest *single* output (itself
bounded by `OUTPUT_TIMEOUT_SECONDS`), not by the sum of all of them.

### 4. `person.user_id` is the canonical link for Companion callbacks

The `mobile_app_notification_action` handler resolves the acting person by
`context.user_id` ↔ the `person.*` entity's `user_id` state attribute, first
and authoritatively. This is not a heuristic: `mobile_app` re-fires a
Companion action with the registration's own context
(`homeassistant/components/mobile_app/webhook.py`, `webhook_fire_event` at
line 309, firing the event with
`context=registration_context(config_entry.data)` at line 319, which is
`Context(user_id=registration[CONF_USER_ID])` —
`homeassistant/components/mobile_app/helpers.py` line 128), and a person
entity publishes the user it is linked to as a state attribute
(`homeassistant/components/person/__init__.py` line 650, writing
`PersonEntityStateAttribute.USER_ID`, `person/const.py` line 17).

The `device_id` path stays, as a **fallback only**, and is logged at DEBUG as
such. It remains unverified against a real device
(`docs/known-issues.md`), which is exactly why it must not be reached when the
exact path could have worked. The documented last resort — act on the whole
audience of the row — is unchanged.

A person who cannot be resolved that way is a configuration gap the user can
fix, so it becomes a repair rather than a silent degradation:

- issue `person_without_user_id`, severity `warning`, `is_fixable = False`
  (there is nothing this integration can do; the fix is in Settings →
  People), translated in `strings.json` and `translations/{en,fr,es}.json`;
- raised **once per person** who is in the audience of at least one row that
  adds Companion buttons — `allow_acknowledge` true, or a non-empty
  `snooze_minutes` — and whose `person.*` entity carries no `user_id`;
- a person in no such row raises nothing: without buttons there is no
  callback to resolve;
- deleted when the condition disappears, which is evaluated on reload (an
  options change already reloads the entry, and linking a person to a user is
  a `person` change the user makes deliberately, not a routing event).

### 5. Services registered in `async_setup`, refusing without a loaded entry

The five `notify_switchboard.*` services are registered in `async_setup`,
once, for the integration — not in `async_setup_entry`. This is the
quality-scale rule `action-setup`: an automation that references a service
should fail its own validation only when the service genuinely does not
exist, not because a config entry happened to be unloaded.

`manifest.json` declares `single_config_entry: true`, so a handler does not
need to be told which entry to act on: it acts on the loaded one. When no
entry is loaded, every one of the five raises
`ServiceValidationError` with `translation_domain = notify_switchboard` and
`translation_key = "no_loaded_entry"`, a new entry under `exceptions` in
`strings.json` and in all three translation files. This is ADR-0015's rule
applied one level further out: a refused call raises, it never fails
silently.

Consequence: unloading an entry no longer removes the services. What it
removes is their ability to act — which is the point, since the reason 0.2.0
unregistered them was to avoid a closure holding a dead `Switchboard`. The
handlers now look the switchboard up at call time instead of capturing it.

### 6. The `done_message` fallback order, in one place

The contract's order is authoritative and is repeated here so there is no
third reading of it:

| Transition | Order |
|---|---|
| `idle -> on` | the alert's own `message` attribute → the row's `message` template → the row's `name` |
| `on\|off -> idle` | the row's `done_message` template → the alert's own `done_message` attribute → the translated `common.back_to_normal` |

The asymmetry is intentional and is ADR-0016's: for `message`, the alert's
attribute wins because the row template is the *fallback* introduced when
core turned out to expose nothing; for `done_message`, the row template wins
because it is the only source a user can actually write today. On a real
`AlertEntity`, which exposes no state attributes at all, the two orders are
indistinguishable — the choice only matters for a synthetic `alert.*`-shaped
entity, which is exactly what the acceptance tests drive.

0.2.0's code already implements this order. What is wrong is
`tests/acceptance/README.md` ("v0.2 addendum") and
`docs/sprints/sprint-2-brief.md` item 8, which describe the reverse; both are
corrected, and `tests/acceptance/test_s3_done_message.py` pins the order so
the next reader does not have to work out which document to believe.

## What does not change

- Every v0 and v0.2 name, the four `event.switchboard_delivery` event types,
  the routing decision, the drop reasons, and the `data.*` input keys.
- The five services' signatures, their non-admin status (ADR-0016 addendum)
  and the ADR-0009 allow-list that bounds them.
- The per-row texts of ADR-0016 and the observer-mode transitions.
- The `Store` schema: nothing in this ADR persists anything new.
- Anything about routing itself. No TTL, no summary, no escalation, no
  places, no labels — those are later sprints, and this one deliberately adds
  no concept a user has to learn.

## Consequences

- `docs/contract.md` gains a "v0.3 addendum (ADR-0017)" block: one more frozen
  name, the fan-out guarantees (and the explicit non-guarantee on event
  order), the callback resolution order, and the availability of the services
  without a loaded entry. This is the second amendment ADR-0011's "requires an
  ADR" clause authorizes; released as router 0.3.0, still not a major version,
  because nothing documented is removed or renamed.
- Every entity file and all three translation files change at once, plus a new
  `entity` section in `strings.json` and two new keys (`issues`.
  `person_without_user_id`, `exceptions.no_loaded_entry`).
- `quality_scale.yaml` can honestly claim `action-setup` and
  `entity-translations`, which it could not before.
- A future ADR is needed to make `OUTPUT_TIMEOUT_SECONDS` configurable, to
  promise an ordering between concurrent deliveries, or to make the
  `device_id` callback path anything other than a fallback.

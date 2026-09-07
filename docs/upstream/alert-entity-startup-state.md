# `AlertEntity` never reads its watched entity, so a condition that was already true at startup produces no transition

> Draft for `home-assistant/core`. Checked against **2026.9.1**.
> Suggested labels: `integration: alert`, `bug`.
>
> `AlertEntity`'s own docstring says "DEVELOPMENT OF THE ALERT INTEGRATION IS
> FROZEN", so this may well be filed as documentation rather than as a fix.
> It is worth writing down either way: the behaviour is not documented
> anywhere, and anything watching an `alert.*` is built on the assumption that
> it is not true.

## The problem

An `alert` whose watched entity is *already* in the alerting state when Home
Assistant starts comes up `idle`, and stays `idle` until that entity changes
state again. If the condition never stops being true, the alert never fires at
all.

`AlertEntity.__init__` (`homeassistant/components/alert/entity.py`, class at
line 30, `__init__` at line 38) sets the firing flag to false at line 71 and
subscribes to **future** changes only, at lines 77-79:

```python
class AlertEntity(Entity):
    def __init__(self, hass: HomeAssistant, watched_entity_id: str) -> None:
        ...
        self._firing = False  # line 71
        ...
        async_track_state_change_event(  # lines 77-79
            hass, [watched_entity_id], self.watched_entity_change
        )
```

There is no `async_added_to_hass` on the class, and nothing anywhere reads
`hass.states.get(watched_entity_id)`. The `state` property derives `on` /
`off` / `idle` from `self._firing` and `self._ack` alone, so a restart is
indistinguishable from "the condition has never been true".

## Why this is not just a startup race

A `binary_sensor` that is restored or re-read at startup usually writes its
state, which produces a state-changed event and wakes the alert up. Three
cases where it does not:

- the watched entity is itself restored to the same value it had, and its
  integration writes it without a change (no event, or an event the alert
  ignores because `old_state` equals `new_state`);
- the watched entity is a template or a group whose value is computed once at
  startup and does not change afterwards;
- the condition is long-lived by nature — a leak that has not been mopped up,
  a door left open, a freezer that is still too warm. These are exactly the
  conditions `alert` exists for, and exactly the ones that do not helpfully
  toggle after a reboot.

## Consequence for anything watching an alert

An integration or automation that subscribes to an `alert.*` — to route its
notifications, to display it, to escalate it — sees `idle` after the restart
and has no way to tell that apart from "resolved". No `idle → on` transition is
ever produced for a condition that never stopped being true, so an observer
concludes the leak is over.

In this project (a `notify` router that watches alerts) that shows up as an
"episode" opened before the restart and never closed, because the closing
transition the router waits for cannot happen. It is recorded as an accepted
limitation on our side, but the root cause is here.

## Reproduction

1. `binary_sensor.test_leak` is `on`.
2. Configure an alert on it:

   ```yaml
   alert:
     leak:
       name: Leak
       entity_id: binary_sensor.test_leak
       state: "on"
       repeat: [5]
   ```

3. Restart Home Assistant, with the binary sensor still `on` and its value
   restored rather than re-written.
4. Observe `alert.leak` is `idle`, and no notification is sent.

Expected: the alert comes up `on` (or produces an `idle → on` transition
shortly after startup), because its condition is true.

## Possible fix

**Not written, not tested** — a sketch of the shape, not a patch.

It needs two changes rather than one. `AlertEntity` does not keep the entity
it watches: `__init__` takes `watched_entity_id` (line 43) and hands it
straight to `async_track_state_change_event` (line 78) without storing it, so
there is nothing to read the state of. Keeping it is the first half — one
line in `__init__`, just above the existing `async_track_state_change_event`
call:

```python
self._watched_entity_id = watched_entity_id
```

The second is an `async_added_to_hass` that reads it once the state machine is
up and calls the existing `begin_alerting` when it already matches — the same
thing `watched_entity_change` does, without waiting for an event:

```python
async def async_added_to_hass(self) -> None:
    """Adopt the watched entity's current state."""
    await super().async_added_to_hass()
    state = self.hass.states.get(self._watched_entity_id)
    if state is not None and state.state == self._alert_state:
        await self.begin_alerting()
```

The details worth a maintainer's opinion: whether to do it at
`EVENT_HOMEASSISTANT_STARTED` rather than at add time (so integrations that
write their states late are not missed), and whether an alert that was
acknowledged before the restart should come back acknowledged — `_ack` is not
persisted either, so today it does not.

Happy to open a PR if the integration is open to one despite the freeze.

## Environment

- Home Assistant core 2026.9.1
- `homeassistant/components/alert/entity.py`

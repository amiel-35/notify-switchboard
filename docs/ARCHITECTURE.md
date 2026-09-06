# Architecture

## The proxy model

Notify Switchboard never delivers a notification. It receives a request on
`notify.switchboard` (or the `NotifyEntity`), decides which already-existing
`notify.*` services should receive it, and calls them unchanged. It creates
no channel of its own and no dependency on an external service.

```
             state that persists              one-off fact
                    |                               |
             binary_sensor.*                  event.* / automation
                    |                               |
                 alert.*  ---- notifiers ----> notify.switchboard <---- notify.send_message
          (repeat, ack, done)                       |
                                                     |  per person (future):
                                                     |  concerned by this class?
                                                     |  present, if required?
                                                     |  silenced / DND? does priority override it?
                                                     |  active snooze?
                                                     v
                notify.mobile_app_<person>   notify.<voice_adapter>   notify.persistent_notification
```

Cards (a separate repository, see the umbrella doctrine) read `alert.*` and
this integration's own entities. There is no intermediate "house" sensor.

## Input contract

`notify.switchboard`, and the `NotifyEntity`'s `send_message`, accept:

- `message`, `title`: text.
- `target`: optional, a list of persons or groups (routing decision only;
  not implemented yet, see Roadmap).
- `data.class`: alert class (`building`, `pets`, `infra`, `comfort`, ... —
  defined by the deployment's own configuration, never hardcoded here).
- `data.priority`: `info` | `normal` | `high` | `critical`. Only `critical`
  is defined to override silence.
- `data.alert_entity`: the originating `alert.*`, for future acknowledge /
  snooze actions.
- Anything else in `data` (`tag`, `actions`, `url`, `push`, ...) is passed
  through unchanged to the resolved `notify.*` services.

## Output contract

For every `notify.*` service the `Router` resolves to, Notify Switchboard
calls it with `message`, `title`, and `data`, exactly as received. Nothing
is added, nothing is dropped, in this release. See `router.py`: the
`Router.route()` method already returns a `RoutingDecision` (chosen targets
+ dropped targets with reasons), but the current implementation is a
pass-through — every configured default target is always chosen.

## Why both a legacy service and an entity

Home Assistant's `alert` integration lists `notifiers:` by legacy
`notify.*` service name; there is currently no way to point `alert` at a
`NotifyEntity` instead. So the legacy `notify.switchboard` service (set up
through Home Assistant's discovery helper, the same mechanism `mobile_app`
uses for its own per-device services) exists purely for `alert`
compatibility. The `NotifyEntity` is the forward-looking surface: it is
what new automations, and this project's own future action buttons, should
target, and it survives if/when the legacy notify platform is eventually
deprecated (see ADR 0004 in `docs/ADR/`). Both share one `Router` instance
stored on `entry.runtime_data`, so behavior never diverges between them.

## Entity plan

This release ships one `NotifyEntity` per config entry (there is only ever
one entry: setup is single-instance). Future sprints add, per person:
`switch.<person>_dnd`, `sensor.<person>_last_notification`,
`sensor.<person>_active_snoozes`; and globally:
`sensor.switchboard_routed_today`, `sensor.switchboard_dropped_today`, and
an `event.switchboard_delivery` log. None of that exists yet — see
`router.py` for where the routing logic that would drive these entities
will live.

## Roadmap

Each increment ships something usable on its own; there is no fixed
duration per sprint.

| # | Increment | Testable how |
|---|---|---|
| S0 | Foundations: repo, template, CI, dev instance | CI green on the skeleton; `hassfest` passes |
| S1 | Router v0.1: notify platform, person <-> service mapping, per-person DND, classes, priorities, diagnostics, config flow | A test alert routes to a present phone, not to an absent one; DND blocks unless `critical` |
| S2 | Router v0.2: acknowledge / snooze action buttons, night-time deferral, per-class snooze bounds | Acknowledging from a phone stops the repeat; a 1h snooze holds; a leak cannot be snoozed |
| S3 | `notify-cast` v0.1: a `notify` per Cast speaker that talks | An announcement is heard in the kitchen |
| S4 | `notify-airplay` v0.1: same for AirPlay speakers | An announcement is heard on an AirPlay speaker |
| S5 | `notify-alexa` v0.1: same via Alexa Media Player | An announcement is heard on an Echo |
| S6 | Cards v0.1: alert bubble, DND tiles | The wall shows active alerts and can acknowledge them |
| S7 | Blueprints + docs site | An external user routes an alert in 10 minutes |
| S8 | HACS default submission, quality scale silver | HACS acceptance |

This repository (`notify-switchboard`) covers S0/S1 of the router; the
other rows live in sibling repositories per the umbrella doctrine.

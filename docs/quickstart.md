# Quickstart: a working `notify.switchboard` in ten minutes

Ten minutes is the real path, measured end to end on a fresh instance:
install, add one person, write the `alert:` block, restart Home Assistant,
watch a notification arrive. The restart and the YAML are in the ten — they
are most of it. The shortest part, and the only one that is not optional, has
no YAML at all: add the integration, add one person — their phones and their
Focus sensors are already filled in — and `notify.switchboard` works.

It follows the public contract in [`contract.md`](contract.md); read that file
if you need the exact rules (which priority overrides silence, what happens
with an unknown target, and so on). Every word this page uses for a thing —
target, person, output, audience, silence, wake time, deferral, episode — is
defined once, in the [Glossary](../README.md#glossary).

> Names used below (`notify.switchboard`, `notify.switchboard_<target>`,
> `data.priority`, `data.source_entity`, `notify_switchboard.explain`) are
> frozen (see the header of [`contract.md`](contract.md)) — they will not
> change without a major version, so it is safe to build automations and
> blueprints against them today.

## 1. Add the integration

Install it from HACS (see the buttons in [`../README.md`](../README.md)),
restart, then **Settings → Devices & services → Add integration** → search for
**Notify Switchboard**.

Setup takes no input — a single instance is created and immediately registers
the `notify.switchboard` service (so `alert:` can list it) and a
`notify.switchboard` entity (the degraded path, see the last section).

## 2. Add a person — the only step that is not optional

Open **Configure → Add or update a person** and pick a `person.*`. The next
form is already filled in for you:

- **Notify services** — a multi-select of every `notify.*` service this
  instance has. The push services of the phones registered to *this person's*
  Home Assistant user come first, marked as their device, and are already
  selected. The link is exact: a Companion registration stores the `user_id` it
  was created for, and a `person.*` publishes the user it is linked to. If a
  person is not linked to a user (Settings → People), nothing is pre-selected
  — the integration will not guess from their name.
  You can still type a service that does not exist yet: a phone that has not
  registered is tolerated and retried.

  A speaker works the same way once it is a `notify.*` service. Core already
  ships one that speaks — the legacy `platform: tts` notify platform:

  ```yaml
  notify:
    - platform: tts
      name: kitchen_speaker      # -> notify.kitchen_speaker
      entity_id: tts.home_assistant_cloud
      media_player: media_player.kitchen
  ```

  Aim it at a Music Assistant player to get pause/announce/resume; a raw
  Cast player is interrupted. Type `notify.kitchen_speaker` into **Notify
  services** to give it to a person, exactly as you would a phone.
  Assist Satellite Notifier (a sibling integration) is worth reaching for
  only when the output is an `assist_satellite`, which has no `notify`
  platform of its own.
- **Silence entities** — any entity whose `on` state means "do not disturb".
  The Focus `binary_sensor` of that person's iPhones is proposed
  automatically.
That is the whole form: two fields. A person's **wake time** and their night
**summary** live behind **Advanced settings of a person** in the options menu,
and both are optional — leaving the wake time empty is an answer, not an
unfinished form. Without one, a message held back during a silence waits for
the end that silence publishes (a `schedule.*` publishes one, an
`input_boolean` does not) instead of being dropped.

Submitting that form on an **empty** routing table also creates one target,
`default`, with that person as its audience, and points the default target at
it. So `notify.switchboard` now reaches a real phone:

```yaml
action: notify.switchboard
data:
  message: "Hello from the switchboard"
```

That target is *managed*: while it is, adding a second person adds them to its
audience too. The moment you open either half of its editor and submit, it
becomes yours and the router stops touching it — for good.

### Android's Do Not Disturb

Android exposes Do Not Disturb as a `sensor` with several states
(`off`, `priority_only`, `alarms_only`, `total_silence`), and this
integration's silence contract is "state is `on`". One template
`binary_sensor` bridges it, and can then be picked as a silence entity:

```yaml
template:
  - binary_sensor:
      - name: "Alice phone do not disturb"
        state: >-
          {{ states('sensor.alice_phone_do_not_disturb_sensor')
             not in ['off', 'unknown', 'unavailable'] }}
```

## 3. Tie a target to an alert — two ways, neither of them urgent

A target is what turns one `alert.*` into one `notify.switchboard_<slug>`
service with its own audience, priority and buttons. **Configure → Add or
update a target** asks five things: a slug, a name, the `alert.*` it is about
(that field is what enables the Acknowledge button), the audience, and whether
the router watches that alert itself.

Priority, presence rule, snooze durations, templates, default data and the
acknowledgement flag are not on that form: they all have a default that suits
almost everybody, and live behind **Advanced settings of a target** — offered
by a checkbox on the step that follows, and in the options menu for ever
after.

**Either** point the target at an `alert.*` you already have and switch
**Observer mode** on: the router watches that alert's state itself, so nothing
in your YAML changes — no `notifiers:` line, no restart. This is the path to
start with.

**Or** let the target tell you what to write. Submitting the form ends on a
confirmation step that shows the exact `alert:` block it expects,
`notifiers:` included:

```yaml
alert:
  leak_kitchen:
    name: Water leak
    entity_id: binary_sensor.CHANGE_ME
    state: "on"
    repeat: [5, 15, 60]
    can_acknowledge: true
    notifiers:
      - switchboard_leak
```

Point `entity_id` at your real sensor, paste it into your configuration (or a
package), restart Home Assistant, and the alert routes through the target.
The `notifiers:` entry — the slug, **without** the `notify.` prefix — is the
only place the alert tells Notify Switchboard who it is (ADR-0008), so nothing
about the alert has to travel through `data`.

Three complete examples live in [`examples/`](examples/).

## 4. Test it from the options menu

**Configure → Test a person** or **Test a target** sends one *real* message
through the ordinary routing path — counted, evented, deferred or dropped like
any other, and carrying `data.tag: switchboard-test` so a Companion channel or
an automation can tell it from the real thing. Testing a person picks the
default target when it reaches them, otherwise the first target whose audience
contains them.

The step that follows says what happened to each person, in the same words
`explain` uses. A dry run could not have told you the *output* works; this can.

## 5. Ask why — `notify_switchboard.explain`

"Why didn't I get the leak alert?" now has an answer you can reach.
**Developer tools → Actions**, `notify_switchboard.explain`, in YAML mode:

```yaml
action: notify_switchboard.explain
data:
  target: leak
  # priority: critical      # optional; defaults to the target's own
  # person: person.alice    # optional; defaults to the whole audience
```

It must be called with **Return response**. It answers, per person:

```yaml
target: leak
priority: normal
persons:
  person.alice:
    decision: dropped          # routed | deferred | dropped
    until: null                # ISO instant, deferred only
    reason: silenced           # a drop reason, dropped only
    detail: "person.alice is silenced by input_boolean.quiet_hours. Only a critical message would get through."
    outputs: []                # what would be called
    missing_outputs: []        # configured outputs that are not services
```

`explain` changes nothing at all: no notification is sent, no counter moves,
no event fires, no deferral is queued. A person who is simply not in the
target's audience is answered (`dropped` / `not_in_audience`), not refused; an
unknown target or an unknown person raises, like every other service.

## 6. When something is wrong, the router says so

Three repairs cover the silent failures this integration used to have, in
**Settings → Repairs**:

- **A person has no notify service** — they sit in an audience and every
  message meant for them is dropped with `no_outputs`.
- **A target points at an alert that does not exist** — raised a minute after
  startup, never during it, so it is never noise.
- **A notify service is unusable** — an output that has failed several times
  in succession.

And the diagnostic entities are still there: `sensor.switchboard_routed_today`,
`sensor.switchboard_dropped_today` (with a `reasons` attribute),
`sensor.switchboard_deferred_today`, and per person
`binary_sensor.<person>_silenced`, `sensor.<person>_last_notification`,
`sensor.<person>_active_snoozes`.

## Acknowledge and snooze from the phone

If a target has an `alert.*` and **Allow acknowledgement** (in its advanced
settings), Companion notifications get action buttons:

- **Acknowledge** → the router calls `alert.turn_off` on *that target's* alert
  and on no other (an allow-list; anything else is refused and logged with the
  acting user's id).
- **Snooze `<n>`** — one button per configured duration. Snoozes are stored per
  (person, target), survive a restart, and expire on their own.

Everything those buttons do is also a service — `notify_switchboard.acknowledge`,
`snooze`, `unsnooze`, `silence`, `unsilence` — so a card or a script can do it
too.

## Two other paths worth knowing about

- **Degraded path (`NotifyEntity`)**: automations that call
  `action: notify.send_message` targeted at the `notify.switchboard` entity
  reach the router too, but only `message` and `title` make the trip (a
  Home Assistant limitation — `NotifyEntity` has no `target` or `data`).
  They route through the **default target** at `normal` priority. Use the
  legacy `notify.switchboard_<target>` / `notify.switchboard` services
  whenever you need a specific target, a priority, or `source_entity`.
- **Observer mode**: already used in step 3, and also the plan B if the legacy
  `notify.*` service platform is ever retired upstream — a target with
  `observer_mode: on` keeps working without being listed in any `notifiers:`
  (`idle → on` routes its message, `→ idle` routes the done message,
  `on → off` just stops).

## Migrating an existing installation

Already have a dozen `notify.mobile_app_*` calls scattered through your
automations, and a handful of `alert:` blocks? Read
[`migration-guide.md`](migration-guide.md) instead of starting here: it says
where to begin, what to move first, and how to undo any of it in one line.

## Next

- One-off facts instead of a lasting alert (a door opened, a delivery
  arrived, a machine finished its cycle)? See
  [`docs/blueprints.md`](blueprints.md) for three ready-made automation
  blueprints, including the "a sensor went silent and nobody noticed" case.
- Full field-by-field behaviour: [`contract.md`](contract.md).

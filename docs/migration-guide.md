# Migrating an existing installation

You already have a working setup: notifications go out, you get them, mostly.
Somewhere in your configuration there are **N** automations that call
`notify.mobile_app_something` directly, and **M** `alert:` blocks with a
`notifiers:` list of one or two phones. Nothing is broken. You are here because
one of these is true:

- somebody in the house gets notifications they do not want, at hours they do
  not want them;
- adding a person means editing N automations;
- an alert that fired at 03:00 is still on a phone at lunchtime;
- you cannot answer "why didn't I get it?" without reading the trace.

This page is about doing the move **in pieces you can undo**, not in one
weekend. If you have no existing setup, read
[`quickstart.md`](quickstart.md) instead. Every word here — target, person,
output, audience, silence, wake time, deferral, episode, observer mode — is
defined once, in the [Glossary](../README.md#glossary).

## The one rule that makes this safe

**Rollback is one line.** A target that turns out to be wrong is deleted in
**Configure → Remove a target**, and the alert it was attached to is untouched:
its `notifiers:` list, its `repeat:`, its `can_acknowledge:` are yours, not the
router's. An automation you have not edited yet still calls the phone directly
and always will.

So there is no big-bang step and no point at which half your house is
unreachable. Do one thing, live with it for a few days, do the next.

## Step 0 — install, and add your people

Install the integration and add **one person per human**, not one per phone:
pick their `person.*`, and the notify services of the phones registered to
their Home Assistant user are already listed and selected. Add their night
silence entity here too if they have one — a `schedule`, an `input_boolean`,
an iPhone Focus sensor.

The first person you add on an empty routing table creates a `default` target
whose audience is everybody, so `notify.switchboard` works immediately.

Nothing routes through the router yet. Nothing has changed.

## Step 1 — move the "everybody" notifications first

Find the automations that notify **the whole household**: the washing machine
is done, the bin goes out tomorrow, somebody is at the door. They are the
easiest, because the audience is the one the `default` target already has, and
because getting one wrong costs nothing.

Replace this:

```yaml
- action: notify.mobile_app_alice_phone
  data:
    message: "The washing machine is done"
- action: notify.mobile_app_bob_phone
  data:
    message: "The washing machine is done"
```

with this:

```yaml
- action: notify.switchboard
  data:
    message: "The washing machine is done"
    data:
      priority: info
```

You have just gained: presence, silence, snooze, one counter, and one place to
add the third person. You have lost nothing — those two phones are the
`default` target's outputs.

Do this for as many of the N as are genuinely "everybody". Stop there for the
first week if you like.

## Step 2 — one target per alert, starting with the one that annoys you most

Now the `alert:` blocks. **One alert, one target** — resist the urge to build
a target per room or per device class, because a target's job is to say *who*
is told about *that* alert, and two alerts that share an audience share a
target only by coincidence.

Pick the alert that causes the most arguments. In **Configure → Add or update
a target**, answer five things:

| Field | For an existing alert |
|---|---|
| Slug | Lowercase, no spaces. It becomes `notify.switchboard_<slug>`, so pick something you will not want to rename. |
| Name | What people read. |
| Alert | The `alert.*` you already have. |
| Audience | Who should actually be told. This is the whole point: it is probably not everybody. |
| Observer mode | **On**, for an existing alert. See below. |

Then leave the second form alone. Priority, presence rule, snooze durations,
templates and default data all have a default that suits almost everybody, and
they live in **Advanced settings of a target** whenever you want them.

### Observer mode, or `notifiers:`

For an alert you already have, tick **Observer mode**. The router watches that
alert's state itself: nothing in your YAML changes, no restart is needed, and
you can turn it off again with one click. The old `notifiers:` list keeps
working next to it, so for a day or two both paths fire and you can compare —
then empty the `notifiers:` list when you trust the target.

The other way round — leaving observer mode off and adding
`- switchboard_<slug>` to `notifiers:` — is the one to pick when you want the
alert's own `repeat:` schedule to drive the sending. It needs a restart, which
is why it is not the way to start.

## Step 3 — check it before you trust it

Do not wait for the leak. **Developer tools → Actions**,
`notify_switchboard.explain`, with **Return response** on:

```yaml
action: notify_switchboard.explain
data:
  target: leak
```

It answers, per person, what would happen to a message sent right now —
`routed`, `deferred` or `dropped`, with the reason and the exact notify
services it would call — and it sends nothing, counts nothing and queues
nothing. Run it once with everybody home and once at night; that is the whole
test.

**Configure → Test a target** is the other half: it sends one *real* message
through the ordinary path, tagged `switchboard-test`, and then shows you the
same explanation. `explain` proves the decision; the test message proves the
output.

## Step 4 — the night, once the rest works

Only now give people a night. A person with a silence entity has a queue: a
message that arrives while they are silent is held rather than dropped, and it
goes out when the silence ends. If they want a specific hour instead, set a
**wake time** in **Advanced settings of a person**.

Expect this to change what you receive, and give it a week before you tune it.
The time to live is what stops a 23:31 door notification arriving at 07:00 —
its defaults are two hours for `info` and twelve for `normal`.

## Step 5 — the rest of the N

The automations you have not touched are the ones with a genuinely specific
recipient: "tell Alice her parcel arrived". Give each one a target with an
audience of one and no alert at all — a target does not need an `alert.*`
unless you want the Acknowledge button — and call
`notify.switchboard_<slug>`.

At the end of this you have zero `notify.mobile_app_*` calls outside the
integration's options, and adding a phone is one form.

## What not to do

- **Do not delete your `alert:` blocks.** The router routes alerts; it does not
  replace them. `alert` is what holds a condition open, repeats, and stops.
- **Do not build a target per phone.** A target has an audience of *people*;
  which phones they carry is the person's business, and it changes.
- **Do not migrate everything in one evening.** Every step above is
  independently useful and independently reversible, and the point of doing
  them in order is that a mistake in step 2 cannot cost you the notification
  that mattered in step 1.
- **Do not use a target's slug for anything you might rename.** It is a public
  service name: renaming it breaks every `alert:` and automation that uses it.

## If you want to go back

Remove a target: the alert keeps its own `notifiers:`, and the automations you
have not edited still call the phones directly. Remove the integration
entirely: `notify.switchboard` and its entities disappear, and every
`notify.*` service it forwarded to is exactly as it was. The only thing you
lose is the routing table, which is the thing you were testing.

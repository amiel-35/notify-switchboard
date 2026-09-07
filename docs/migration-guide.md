# Migrating an existing installation

You already have a working setup: **N** automations calling
`notify.mobile_app_something` directly, and **M** `alert:` blocks with a
`notifiers:` list of one or two phones. Nothing is broken — you are here
because adding a person means editing N automations, an alert that fired at
03:00 is still on a phone at lunchtime, or you cannot answer "why didn't I
get it?" without reading the trace.

This page moves things **in pieces you can undo**, not in one weekend. No
existing setup? Read [`quickstart.md`](quickstart.md) instead. Every word
here is defined once, in the [Glossary](../README.md#glossary).

## The one rule that makes this safe

**Rollback is one menu action.** Deleting a target (**Configure → Remove a
target**) leaves the alert it was attached to untouched — its `notifiers:`,
its `repeat:`, its `can_acknowledge:` are yours, not the router's. An
automation you have not edited yet still calls the phone directly. There is
no big-bang step: do one thing, live with it, do the next.

## Step 0 — install, and add your people

Add **one person per human**, not one per phone: their notify services and
Focus sensors are already listed and selected (see
[`quickstart.md`](quickstart.md)). The first person you add creates a
`default` target whose audience is everybody, so `notify.switchboard` works
immediately. Nothing routes through the router yet.

## Step 1 — move the "everybody" notifications first

Find the automations that notify the whole household (the washing machine is
done, the bin goes out tomorrow). They are the easiest: the audience is the
one the `default` target already has, and getting one wrong costs nothing.

Replace direct `notify.mobile_app_*` calls with:

```yaml
- action: notify.switchboard
  data:
    message: "The washing machine is done"
    data:
      priority: info
```

(The nesting is not a typo: the outer `data:` is the action's own, the inner
one is the notify payload the router reads `priority`/`tag` from.)

> **Upgrading from 0.6.x?** `data.priority` no longer reaches a `mobile_app_*`
> output — see [`contract.md`](contract.md), "Breaking". If an automation
> relied on `data: {priority: high}` for an urgent Android push, route at
> `critical` instead; the router writes the Companion payload itself.

## Step 2 — one target per alert, starting with the one that annoys you most

**One alert, one target** — a target's job is to say *who* is told about
*that* alert, not to group by room or device class. In **Configure → Add or
update a target**, fill the slug, name, `alert.*`, and audience (probably not
everybody), and turn **Observer mode** on for an existing alert. Leave the
rest — priority, presence rule, snooze durations, templates — at their
defaults, in **Advanced settings of a target**.

Full wiring detail: [`../README.md`](../README.md#wiring-a-target-to-an-alert).
With observer mode on, the old `notifiers:` list keeps working alongside it,
so you can compare for a day before emptying `notifiers:` (a YAML edit, which
needs a restart — unlike turning observer mode on).

## Step 3 — check it before you trust it

Do not wait for the leak: run `notify_switchboard.explain` (with **Return
response**) once with everybody home and once at night —
[`quickstart.md`](quickstart.md#5-ask-why--notify_switchboardexplain) has the
full example. **Configure → Test a target** is the other half: it sends one
*real* message, tagged `switchboard-test`, then shows the same explanation.

## Step 4 — the night, once the rest works

Only now give people a night. A person with a silence entity has a queue:
give them a **wake time** in **Advanced settings of a person** if they want a
specific hour, and expect this to change what you receive — give it a week
before tuning. If a night that holds *everything* is too much, give the
silence a **floor** rather than adding a second silence entity (see
[The night](../README.md#the-night)).

## Step 4b — the house nobody is in

The alert fires, everybody is out, and the message goes out at the priority
you chose for a household that was home to hear it. Turn on **Escalation of a
target** for that one target — see
[When the house is empty](../README.md#when-the-house-is-empty) — target by
target, not everywhere: a shopping list that escalates is noise.

## Step 5 — the rest of the N

The remaining automations have a genuinely specific recipient ("tell Alice
her parcel arrived"). Give each one a target with an audience of one and no
alert at all — a target does not need an `alert.*` unless you want the
Acknowledge button. At the end of this you have zero `notify.mobile_app_*`
calls outside the integration's options.

## What not to do

- **Do not delete your `alert:` blocks.** The router routes alerts; it does
  not replace them.
- **Do not build a target per phone.** A target's audience is *people*; which
  phones they carry is the person's business.
- **Do not migrate everything in one evening.** Every step above is
  independently useful and reversible.
- **Do not use a target's slug for anything you might rename.** It is a
  public service name.

## If you want to go back

Remove a target: the alert keeps its own `notifiers:`, and unedited
automations still call the phones directly. Remove the integration entirely:
`notify.switchboard` and its entities disappear, every `notify.*` service it
forwarded to is exactly as it was. The only thing you lose is the routing
table — the thing you were testing.

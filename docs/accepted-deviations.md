# Accepted deviations

Five places where this integration knowingly bends one of its own stated
principles, and what each one bought. They are design choices, not findings —
[`known-issues.md`](known-issues.md) is for findings accepted instead of being
fixed. Vocabulary is the [Glossary](../README.md#glossary)'s.

## 1. A temporary silence is state the router owns

**Deviation.** `notify_switchboard.silence` sets a per-person silence in this
integration's own storage, with an expiry the router schedules and purges
itself — unlike presence, a night schedule or a Focus sensor, which are all
somebody else's entity.

**Bends.** Native first ([ADR-0001](ADR/0001-native-first.md)) and pure proxy
([ADR-0002](ADR/0002-pure-proxy.md)): an `input_boolean` the household owns
would satisfy both.

**Why.** An `input_boolean` cannot expire. "Quiet for the next hour" has no
native equivalent without a helper and an automation per person. The router
already owns snoozes, the same shape (an instant, per person, persisted,
expiring); the silence is held to the same standard: persisted, visible in
`binary_sensor.<person>_silenced` with an `until` attribute, and it never
touches entities the household owns.

**Costs.** One more piece of state to migrate, and an answer to "why am I
silent?" that lives inside this integration rather than a dashboard entity —
`explain` names it explicitly for that reason.

## 2. An episode is a small persisted record of who was told

**Deviation.** For every target tied to an `alert.*`, the router remembers one
**episode** between `idle → on` and the return to `idle`: who was notified,
which outputs answered, under which tags. Persisted, survives a restart.

**Bends.** Pure proxy ([ADR-0002](ADR/0002-pure-proxy.md)): a proxy that
remembers is not only a proxy.

**Why.** Without it, a back-to-normal message reaches people who slept
through the alarm, and notifications cannot be cleared because nothing knows
which phones received them. `alert` itself keeps none of this. The episode is
the smallest record that answers both questions, and holds no message bodies.

**Costs.** A store migration, an open episode that can linger across a real
restart (see [`known-issues.md`](known-issues.md)), and a persisted object
whose lifetime this integration does not fully control.

## 3. `not_in_audience` is not counted

**Deviation.** `sensor.switchboard_dropped_today` does not count a person
dropped with the reason `not_in_audience`. The decision still records it, and
`explain` still reports it.

**Bends.** "Nothing is silently lost" ([`contract.md`](contract.md), Routing
decision): every dropped call is normally counted with its reason.

**Why.** A person outside a target's audience was never a recipient, so
counting them would make "dropped today" a function of household size rather
than of anything going wrong — a household of six with a target for two would
add four to the counter on every single message.

**Costs.** One case where the daily figures do not add up: a deferral whose
person left the target's audience overnight re-decides at flush time to
`not_in_audience`, and so leaves the queue without reappearing in
`routed_today` or `dropped_today`. Accepted rather than a defect, because it
is exactly what the live path already does with the same decision.

## 4. `escalate_when_nobody_home` is not on `target_advanced`

**Deviation.** [ADR-0021](ADR/0021-escalation-and-places-reduced.md) says the
options flow gains one boolean on `target_advanced`. It ships on a step of
its own, `target_escalation`, instead.

**Bends.** An ADR is normative; an implementation that does not do what its
ADR says is what [ADR-0011](ADR/0011-frozen-contract-and-contract-test.md)
exists to prevent.

**Why.** [`contract.md`](contract.md)'s frozen list of what
`target_advanced` holds does not include this field, and the acceptance suite
pins that list exactly, frozen. The same contract section says undocumented
steps "are internal and may change" — so a new internal step is where the
field could go without amending the frozen list. What the ADR asks for (a
boolean in the options flow) is delivered; where it sits is what moved.

**Costs.** Nothing user-visible; the field works, and the two normative
documents (ADR and contract) technically disagree until one is amended.

## 5. A title is gated on the entity's `supported_features`

**Deviation.** ADR-0021 §6 says the router passes `title` to
`notify.send_message` regardless, and lets core drop it when unsupported. The
router instead reads the entity's `supported_features` first and sends the
title only when the entity declares it (or publishes no features at all).

**Bends.** Pure proxy again: a router that inspects the far end before
deciding what to send is doing more than proxying.

**Why.** Core's own gate for dropping an unsupported title does not always
run — a platform can override `async_send_message` and never reach it. For
such an entity, "pass it regardless" hands a title to a platform that
declared it cannot take one. The frozen acceptance suite pins the opposite
outcome, so reading the attribute is the only way to match both the ADR's
intent and the frozen tests.

**Costs.** One state read per entity delivery; an entity that starts
declaring the feature late loses titles sent before that point, and one that
misreports its features is believed.

## What would change any of these

None is closed: an expiring native helper would retire (1); `alert` recording
its own delivery outcome would shrink (2) to a pointer; a per-reason
breakdown on the dropped counter would let (3) be counted without drowning the
headline number; a contract amendment would move (4) onto `target_advanced`;
and core running its title gate somewhere a platform cannot bypass would
retire (5). Any change needs an ADR, exactly as accepting the deviation did.

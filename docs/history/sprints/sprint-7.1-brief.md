# Sprint 7.1 brief — Notify Switchboard v0.7.1 (plain-language interface)

> Opened on 2026-09-07, after the maintainer opened the person step of a real
> instance and said: *« cet écran est incompréhensible pour un humain »*.
> No behaviour changes. No new option, no new step, no store migration.

## The problem

The interface speaks like the code. On the screens a household actually
touches, a user who does not read Python meets `person.dev_bob` in a
description, "services notify", "entités de silence", "toléré et réessayé",
option chips carrying raw service names, and a field called "Slug". Everything
on those screens is true and almost none of it is usable.

## Goal

Every user-facing string — config flow, options flow menu and steps, field
labels, `data_description`, errors, aborts, exceptions, repairs, entity names,
service descriptions and fields — is written for somebody who does not code:
**say what will happen, not how the router works**.

## Rules

1. **Translation keys do not change.** Only values change. Step ids, field
   names and menu ids are frozen (contract v0.6 §"Four options-flow step ids
   are public", `tests/test_translations.py`, `tests/acceptance/`).
2. **No raw entity id and no code word in a title, a label or a description**,
   in any of the three languages: no `person.`, `alert.`, `notify.`, and none
   of *slug*, *entity/entité*, *service notify*, *legacy*, *payload*,
   *retry/réessayé*, *store*, *flow*, *row*, *target_map*.
   Two exceptions, and only two:
   - the identifier field may show its own example (`fuite_eau` and the
     `notify.switchboard_…` service it becomes) — that example *is* the
     explanation;
   - a `data_description` may name a YAML key a power user needs, in **one**
     sentence, placed **after** the plain sentence.
3. **People are named by their friendly name.** A description that interpolates
   a person or a target shows the name Home Assistant shows, never the id.
4. **Every option in a selector carries a readable label**, wherever an
   acceptance test does not already pin the label.
5. The 0.6.0 vocabulary discipline stays (`test_s6_vocabulary.py`): one word
   per concept, *cible* / *target*, *règle* only in *règle de présence*.

## Reference rewrite (the person step, French)

| | Before | After |
|---|---|---|
| Title | Services notify et silence | Prévenir {person} |
| Description | Quels services notify joignent person.dev_bob… | Sur quels appareils Bob reçoit les notifications, et quand faut-il ne pas le déranger ? |
| `outputs` | Services notify | Où prévenir |
| `silence_entities` | Entités de silence | Quand ne pas déranger |

The same spirit everywhere: the identifier field becomes "Identifiant court",
the audience becomes "Qui prévenir", the observer mode becomes "Surveiller
l'alerte directement".

## Code changes (small, and tested)

1. `description_placeholders["person"]` and `["target"]` carry the friendly
   name (falling back to the id when there is no state).
2. Readable option labels: the person pickers list people by name; the audience
   selector labels a person by name and a bare output by a readable service
   name; `_output_options` puts the phone's own device name in front of the
   service it selects.
3. Anything that shows an id in a sentence a user reads — `explain` details,
   the test result, the repairs — prefers the friendly name, with the id in
   parentheses where the id is what the user has to go and fix.

## Order of work

French first (the maintainer reads French), then English, then Spanish
(machine-translated, as the README already says), then the code, then the
unit tests. A `test:` commit is red before the `fix:` that follows it.

## Acceptance

- `tests/unit/test_plain_language.py`: no raw id and no code word in any title,
  label or description of `strings.json` and the three translations; the label
  builders and the friendly-name placeholders behave.
- Translation parity green, the full suite green, hassfest, ruff, mypy green.
- README Glossary gains a short "Words used in the interface" mapping, so the
  contract term and the word on screen stay linked.
- CHANGELOG 0.7.1 "Changed: interface wording"; `manifest.json` and
  `pyproject.toml` at 0.7.1.

## Definition of done

A non-technical reader opens the French person step and the French target step
and can say, without help, what each field does.

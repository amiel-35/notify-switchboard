# Review checklist — Notify Switchboard suite (given to the reviewer agent with every PR)

The reviewer receives: this checklist, the doctrine, `contract.md`, all ADRs,
the diff, the CI output, `known-issues.md`. Verdict is **go / no-go** only;
everything else is a finding (blocking or accepted).

## A. Contract and doctrine
- [ ] No public name changed (domain, `notify.switchboard*`, entity ids, `data.*` keys, event types) without an ADR in the same PR.
- [ ] The contract test still passes and was not edited to pass.
- [ ] No behaviour specific to one household; classes/targets are configuration.
- [ ] Router still sends nothing itself: outputs are `notify.*` service calls only; no HTTP, no external dependency added.
- [ ] Voice adapters not wired to any alert by default in examples or blueprints.

## B. Home Assistant API correctness (hallucination guard)
- [ ] Every core API used is cited with a path in `$HA_CORE_SRC` (2026.9.1) in the PR description; spot-check at least three.
- [ ] Legacy notify platform: `async_get_service` signature, `BaseNotificationService.async_send_message(message, **kwargs)`, `targets` property returning a mapping.
- [ ] `NotifyEntity` used only with `message`/`title`; no invented kwargs.
- [ ] `ConfigEntry.runtime_data` typed; `async_forward_entry_setups` / `async_unload_platforms` paired.
- [ ] No blocking I/O in the event loop (file, network, sleep); `Store` used for persistence.
- [ ] Entities: `unique_id` from `entry_id` + stable ids, `_attr_has_entity_name`, device grouping, translation keys exist.
- [ ] `manifest.json`: `iot_class: calculated`, `integration_type: helper`, no HACS integration in `dependencies`.

## C. Security and privacy
- [ ] Acknowledge callback only acts on `alert.*` present in the routing table; refusal logged with `context.user_id`.
- [ ] `authenticationRequired: true` set for `high`/`critical` targets by default.
- [ ] Recursion to `notify.switchboard*` rejected at config time and runtime.
- [ ] Diagnostics use `async_redact_data`; no message bodies stored beyond the documented option.
- [ ] No secrets, tokens, or real household data in code, tests, fixtures, or docs.

## D. Robustness
- [ ] A failing output does not stop other persons/outputs (test present).
- [ ] Missing output at startup tolerated; disappeared output raises a single `repairs` issue.
- [ ] Snoozes persisted and restored (restart test present).
- [ ] Time logic tested across midnight and a DST change; uses HA timezone helpers (`dt_util`).
- [ ] Config entry migration path exists (`version`/`minor_version`, `async_migrate_entry`).

## E. Quality
- [ ] Acceptance tests from the brief pass unmodified; new tests cover new branches; coverage threshold kept.
- [ ] `ruff`, `mypy` (core config), `hassfest`, HACS action green.
- [ ] `strings.json` is the source; `translations/en|fr|es.json` have identical key sets; `fr` reads naturally; `es` labelled machine-translated.
- [ ] `CHANGELOG.md` updated under Unreleased; docs updated where behaviour changed.
- [ ] No edits to `.github/workflows` unless the sprint is dedicated to CI.

## F. Verdict
- **go** if every A–C item holds and D/E gaps are recorded in `known-issues.md` with the orchestrator's acceptance.
- **no-go** otherwise, with the blocking findings listed first.

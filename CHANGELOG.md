# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Repository scaffold: `custom_components/notify_switchboard`, CI
  (hassfest, HACS validation, lint, tests, release), HACS metadata.
- Config flow (single instance) and options flow (`default_targets`).
- Legacy `notify.switchboard` service and a modern `NotifyEntity`, both
  proxying, unchanged, to the notify services configured as default
  targets (pass-through only; no per-person routing yet).
- `Router` interface (`NotificationRequest` / `RoutingDecision`) that will
  carry future routing logic without changing the contract.
- Diagnostics, translations (`en`, `fr`, `es`), and tests for the config
  flow, the notify platform, and translation key parity.

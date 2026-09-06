# Contributing

Thanks for considering a contribution to Notify Switchboard.

## Ground rules

- **English only** in code, comments, commit messages, and documentation.
  Translation files (`translations/*.json`) are the exception.
- **Pull requests only.** `main` is protected; nothing is pushed directly.
  One PR = one reviewed increment.
- **Conventional commits.** Prefix commit subjects with `feat:`, `fix:`,
  `docs:`, `test:`, `chore:`, `refactor:`, or `ci:`, e.g.
  `feat: add snooze duration to options flow`.
- **Tests are required** for any behavioral change: config flow changes,
  new notify data handled, new entities or services. CI must be green
  (hassfest, HACS validation, lint, tests) before a PR is merged.
- **No product decisions specific to one household.** Classes, persons, and
  rules are configuration, not code (see `docs/ARCHITECTURE.md`).

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_dev.txt
```

```bash
ruff format --check .
ruff check .
mypy custom_components/notify_switchboard
pytest --cov=custom_components.notify_switchboard
```

## Adding or changing user-facing strings

Update `custom_components/notify_switchboard/strings.json` (the source of
truth, English) and `translations/en.json` together, then update
`translations/fr.json` and `translations/es.json` with real, natural
translations — not machine-literal ones. `tests/test_translations.py`
checks that all three files expose the same set of keys.

## Reporting issues

Open an issue with your Home Assistant version, the integration version,
relevant logs (`custom_components.notify_switchboard: debug` in
`logger:`), and steps to reproduce.

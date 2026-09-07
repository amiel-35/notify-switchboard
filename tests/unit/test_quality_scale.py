"""`quality_scale.yaml` has to parse, and to assess every rule there is.

Hassfest reads this file for core integrations only, so nothing in CI ever
opened it: a syntax error or a rule quietly missing from the assessment could
sit there indefinitely while the README claimed the scale was fully assessed.

The expected rule set is `script.hassfest.quality_scale.ALL_RULES` from Home
Assistant 2026.9.1. That module is not shipped in the `homeassistant` wheel
(only in the core repository, under `script/`), so it cannot be imported from
the test environment; the names are transcribed below with their tier, from
`script/hassfest/quality_scale.py` lines 36-92 of the 2026.9.1 tag. Refresh
them when the pinned core version moves.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

QUALITY_SCALE = (
    Path(__file__).parents[2]
    / "custom_components"
    / "notify_switchboard"
    / "quality_scale.yaml"
)

# script/hassfest/quality_scale.py, ALL_RULES, Home Assistant 2026.9.1.
BRONZE_RULES = (
    "action-setup",
    "appropriate-polling",
    "brands",
    "common-modules",
    "config-flow",
    "config-flow-test-coverage",
    "dependency-transparency",
    "docs-actions",
    "docs-conditions",
    "docs-high-level-description",
    "docs-installation-instructions",
    "docs-removal-instructions",
    "docs-triggers",
    "entity-event-setup",
    "entity-unique-id",
    "has-entity-name",
    "runtime-data",
    "test-before-configure",
    "test-before-setup",
    "unique-config-entry",
)
SILVER_RULES = (
    "action-exceptions",
    "config-entry-unloading",
    "docs-configuration-parameters",
    "docs-installation-parameters",
    "entity-unavailable",
    "integration-owner",
    "log-when-unavailable",
    "parallel-updates",
    "reauthentication-flow",
    "test-coverage",
)
GOLD_RULES = (
    "devices",
    "diagnostics",
    "discovery",
    "discovery-update-info",
    "docs-data-update",
    "docs-examples",
    "docs-known-limitations",
    "docs-supported-devices",
    "docs-supported-functions",
    "docs-troubleshooting",
    "docs-use-cases",
    "dynamic-devices",
    "entity-category",
    "entity-device-class",
    "entity-disabled-by-default",
    "entity-translations",
    "exception-translations",
    "icon-translations",
    "reconfiguration-flow",
    "repair-issues",
    "stale-devices",
)
PLATINUM_RULES = (
    "async-dependency",
    "inject-websession",
    "strict-typing",
)
ALL_RULES = BRONZE_RULES + SILVER_RULES + GOLD_RULES + PLATINUM_RULES


def _load() -> dict[str, Any]:
    """Parse the assessment file the way hassfest would."""
    loaded = yaml.safe_load(QUALITY_SCALE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_quality_scale_is_valid_yaml() -> None:
    """Regression: an unquoted `comment` containing ": " broke the parse.

    `comment: There is no dependency: requirements is empty` is a mapping
    value inside a mapping value, which PyYAML rejects outright -- the whole
    file was unreadable, not just that entry.
    """
    rules = _load()["rules"]
    assert isinstance(rules, dict)


def test_every_hassfest_rule_is_assessed() -> None:
    """No rule of any tier is left out, and none is invented."""
    assert set(_load()["rules"]) == set(ALL_RULES)


def test_every_assessment_has_a_status_and_a_reason() -> None:
    """`todo` and `exempt` always say why; `done` may be a bare string."""
    for name, entry in _load()["rules"].items():
        if isinstance(entry, str):
            assert entry == "done", name
            continue
        assert entry["status"] in {"done", "todo", "exempt"}, name
        assert entry.get("comment"), name

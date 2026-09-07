"""One word per concept, enforced on the strings a user actually reads.

Written before the Sprint 6 implementation exists, against:

- `docs/contract.md` §"v0.6 addendum (ADR-0020)" → "One word per concept"
- `docs/ADR/0020-consolidation.md` §6
- `docs/sprints/sprint-6-brief.md` item 5

The same object is called a *row*, a *rule*, a *routing-table row* and a
*target*, sometimes twice in one sentence. `strings.json` alone calls a target
a row eleven times, in a menu that calls it a target. From 0.6.0 there is one
word: **target**, in every user-facing string, in `en`, `fr` and `es`.

Three rules, and they are deliberately narrow — this file guards the
vocabulary, not the prose:

1. no user-facing English string calls a target a *row*;
2. *rule* survives only as **presence rule**, the name of a field, or as the
   `{rule}` placeholder that carries its value;
3. every `issues.*` / `exceptions.*` message that names a target says
   "target", so somebody reading a repair or an error learns the word the menu
   uses.

`fr` and `es` get the same treatment through their own words: *ligne* /
*règle*, *fila* / *regla*, with *règle de présence* and *regla de presencia*
exempt for the same reason "presence rule" is.

The one allowance the brief asks for: a `data_description` may use these words
while it explains the legacy notify `target` list, which is the one place two
meanings of "target" genuinely meet.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

COMPONENT = (
    Path(__file__).resolve().parents[2] / "custom_components" / "notify_switchboard"
)
ENGLISH_FILES = [COMPONENT / "strings.json", COMPONENT / "translations" / "en.json"]

PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def _walk(node: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[str, str]]:
    """Yield every ("a/b/c", "text") leaf of a translation file."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, (*path, str(key)))
    elif isinstance(node, str):
        yield "/".join(path), node


def _strings(file: Path) -> list[tuple[str, str]]:
    return list(_walk(json.loads(file.read_text(encoding="utf-8"))))


def _explains_the_notify_target_list(key: str, text: str) -> bool:
    """Is this the one string allowed to talk about the legacy `target:` list?

    ADR-0020 §6 spells that list "the notify `target` list" and mentions it
    where it has to be distinguished from a routing-table target. A
    `data_description` doing that may use whatever words it needs.
    """
    return "data_description" in key and "target list" in text.lower()


def _without_placeholders(text: str) -> str:
    """Drop `{...}` so a placeholder name is never read as prose."""
    return PLACEHOLDER.sub(" ", text)


def _names_a_target(text: str) -> bool:
    """Does this message speak about a routing-table target at all?"""
    flat = text.replace("-", " ").lower()
    return "{target}" in text or "{slug}" in text or "routing table" in flat


@pytest.mark.parametrize("file", ENGLISH_FILES, ids=lambda file: file.name)
def test_no_user_facing_string_calls_a_target_a_row(file: Path):
    """A target is a target, in the menu and everywhere the menu leads."""
    offenders = [
        (key, text)
        for key, text in _strings(file)
        if re.search(r"\brows?\b", text, re.IGNORECASE)
        and not _explains_the_notify_target_list(key, text)
    ]

    assert not offenders, (
        f"{file.name} calls a target a row in {len(offenders)} string(s); the "
        "word is `target` everywhere a user can read it (ADR-0020 §6):\n"
        + "\n".join(f"  {key}: {text}" for key, text in offenders)
    )


@pytest.mark.parametrize("file", ENGLISH_FILES, ids=lambda file: file.name)
def test_rule_is_only_ever_the_presence_rule(file: Path):
    """`presence_rule` is a field; a target is not a rule."""
    offenders = []
    for key, text in _strings(file):
        if _explains_the_notify_target_list(key, text):
            continue
        stripped = re.sub(
            r"presence\s+rules?", " ", _without_placeholders(text), flags=re.IGNORECASE
        )
        if re.search(r"\brules?\b", stripped, re.IGNORECASE):
            offenders.append((key, text))

    assert not offenders, (
        f"{file.name} uses 'rule' for something other than the presence rule "
        f"in {len(offenders)} string(s) (ADR-0020 §6):\n"
        + "\n".join(f"  {key}: {text}" for key, text in offenders)
    )


@pytest.mark.parametrize("file", ENGLISH_FILES, ids=lambda file: file.name)
def test_every_issue_or_exception_naming_a_target_says_target(file: Path):
    """A repair and a refusal teach the word the options menu uses."""
    offenders = [
        (key, text)
        for key, text in _strings(file)
        if key.split("/")[0] in {"issues", "exceptions"}
        and _names_a_target(text)
        and "target" not in text.lower()
    ]

    assert not offenders, (
        f"{file.name} has {len(offenders)} repair/exception message(s) that "
        "speak about a target without using the word (ADR-0020 §6):\n"
        + "\n".join(f"  {key}: {text}" for key, text in offenders)
    )


# ---------------------------------------------------------------------------
# The same discipline in the two translated languages (ADR-0020 §6)
# ---------------------------------------------------------------------------

TRANSLATED = {
    # language: (forbidden word for "target", forbidden word for "rule",
    #            the one allowed use of the second)
    "fr": (r"\blignes?\b", r"\br[eè]gles?\b", r"r[eè]gles?\s+de\s+pr[ée]sence"),
    "es": (r"\bfilas?\b", r"\breglas?\b", r"reglas?\s+de\s+presencia"),
}


@pytest.mark.parametrize("language", sorted(TRANSLATED))
def test_the_translations_use_one_word_for_a_target_too(language: str):
    """`cible` / `destino`, never `ligne` / `fila` (ADR-0020 §6)."""
    row_word, rule_word, allowed_rule = TRANSLATED[language]
    file = COMPONENT / "translations" / f"{language}.json"
    offenders = []
    for key, text in _strings(file):
        if _explains_the_notify_target_list(key, text):
            continue
        if re.search(row_word, text, re.IGNORECASE):
            offenders.append((key, text))
            continue
        stripped = re.sub(
            allowed_rule, " ", _without_placeholders(text), flags=re.IGNORECASE
        )
        if re.search(rule_word, stripped, re.IGNORECASE):
            offenders.append((key, text))

    assert not offenders, (
        f"{file.name} calls a target a row or a rule in {len(offenders)} "
        "string(s); the translated vocabulary follows the English one "
        "(ADR-0020 §6):\n" + "\n".join(f"  {key}: {text}" for key, text in offenders)
    )

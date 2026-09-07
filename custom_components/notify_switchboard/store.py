"""Persisted state for Notify Switchboard.

Doctrine §5: nothing lives in RAM only. Snoozes, night deferrals, the temporary
per-person silences of `notify_switchboard.silence` (v0.2, ADR-0016) and the
episodes of a row's `alert_entity` (v0.5, ADR-0019 §5) go through
`homeassistant.helpers.storage.Store` so they survive a reload or a restart,
and the recorder database is never touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import STORAGE_KEY, STORAGE_MINOR_VERSION, STORAGE_VERSION

# Minor version that introduced `queued_at` on a deferral.
STORAGE_MINOR_VERSION_QUEUED_AT = 2
# Minor version that introduced the temporary per-person silences (ADR-0016).
STORAGE_MINOR_VERSION_SILENCES = 3
# Minor version that introduced the episodes of a row's alert (ADR-0019 §5).
STORAGE_MINOR_VERSION_EPISODES = 4


class StoredData(TypedDict, total=False):
    """Shape of the JSON document written by `Store`."""

    snoozes: list[dict[str, Any]]
    deferrals: list[dict[str, Any]]
    silences: list[dict[str, Any]]
    episodes: list[dict[str, Any]]


@dataclass(slots=True)
class DeferredMessage:
    """A message queued during a person's night silence (brief item 7)."""

    person: str
    slug: str
    tag: str
    message: str
    title: str | None = None
    priority: str = "normal"
    data: dict[str, Any] = field(default_factory=dict)
    # When the message was queued. Kept so that a restart spanning the wake
    # time can tell "this is still tonight's message" from "this one is
    # already late" -- see `Switchboard._async_catch_up_deferrals`.
    queued_at: datetime = field(default_factory=dt_util.utcnow)

    @property
    def key(self) -> tuple[str, str, str]:
        """Return the de-duplication key: (person, target, tag)."""
        return (self.person, self.slug, self.tag)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "person": self.person,
            "slug": self.slug,
            "tag": self.tag,
            "message": self.message,
            "title": self.title,
            "priority": self.priority,
            "data": self.data,
            "queued_at": self.queued_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DeferredMessage | None:
        """Rebuild a deferral from storage, or None when the row is unusable."""
        try:
            queued_at = dt_util.parse_datetime(str(raw.get("queued_at", "")))
            return cls(
                person=str(raw["person"]),
                slug=str(raw["slug"]),
                tag=str(raw.get("tag", "")),
                message=str(raw["message"]),
                title=raw.get("title"),
                priority=str(raw.get("priority", "normal")),
                data=dict(raw.get("data") or {}),
                queued_at=queued_at or dt_util.utcnow(),
            )
        except KeyError, TypeError, ValueError:
            return None


@dataclass(slots=True)
class Episode:
    """One run of a routing-table row's `alert_entity` (ADR-0019 §5).

    An episode opens on that entity's `idle -> on` transition and closes on its
    `-> idle` one. While it is open the router records who was actually told
    (`persons`), which `notify.*` outputs were successfully called (`outputs`)
    and under which effective `data.tag` the messages went out (`tags`).

    The record is **closed, not deleted**, when the alert returns to idle: a
    `done` message is by definition sent after that, so the recipients have to
    outlive the episode's end. It is reset when the row's *next* episode opens.
    """

    slug: str
    persons: set[str] = field(default_factory=set)
    outputs: set[str] = field(default_factory=set)
    tags: set[str] = field(default_factory=set)
    is_open: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation, sorted for stability."""
        return {
            "slug": self.slug,
            "persons": sorted(self.persons),
            "outputs": sorted(self.outputs),
            "tags": sorted(self.tags),
            "open": self.is_open,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Episode | None:
        """Rebuild an episode from storage, or None when the row is unusable."""
        slug = raw.get("slug")
        if not slug:
            return None
        return cls(
            slug=str(slug),
            persons={str(person) for person in raw.get("persons") or ()},
            outputs={str(output) for output in raw.get("outputs") or ()},
            tags={str(tag) for tag in raw.get("tags") or ()},
            is_open=bool(raw.get("open")),
        )


class SwitchboardStorage(Store[StoredData]):
    """`Store` subclass owning the schema migration of the stored document."""

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Migrate a stored document to the current version.

        `homeassistant/helpers/storage.py`, `Store.async_load`, calls this
        whenever the file on disk does not carry the current
        `version`/`minor_version` pair, then re-saves the result.
        """
        if old_major_version > STORAGE_VERSION:
            raise ValueError(f"Cannot downgrade {STORAGE_KEY} from {old_major_version}")

        if old_minor_version < STORAGE_MINOR_VERSION_QUEUED_AT:
            # `queued_at` did not exist. Stamping "now" is the conservative
            # choice: the deferral keeps waiting for its next wake time rather
            # than firing immediately on the upgrade.
            stamp = dt_util.utcnow().isoformat()
            for raw in old_data.get("deferrals", []):
                raw.setdefault("queued_at", stamp)

        if old_minor_version < STORAGE_MINOR_VERSION_SILENCES:
            # Temporary silences did not exist. An upgrade must not invent one,
            # so the list simply starts empty.
            old_data.setdefault("silences", [])

        if old_minor_version < STORAGE_MINOR_VERSION_EPISODES:
            # Episodes did not exist either, and an upgrade must not invent one:
            # a restart in the middle of a leak must not turn "back to normal"
            # into a message for people who slept through it (ADR-0019 §5).
            old_data.setdefault("episodes", [])

        return old_data


class SwitchboardStore:
    """Thin, typed wrapper around the integration's `Store`."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialise the store for this Home Assistant instance."""
        self._store: Store[StoredData] = SwitchboardStorage(
            hass,
            STORAGE_VERSION,
            STORAGE_KEY,
            minor_version=STORAGE_MINOR_VERSION,
        )
        self.snoozes: dict[tuple[str, str], datetime] = {}
        self.deferrals: dict[tuple[str, str, str], DeferredMessage] = {}
        # Temporary, router-owned per-person silences (ADR-0016): person -> the
        # UTC instant the silence lifts. Configured `silence_entities` are read,
        # never owned, and never appear here.
        self.silences: dict[str, datetime] = {}
        # One episode per routing-table row that has an `alert_entity`, keyed on
        # the **row** and never on the alert: two rows may watch one alert with
        # different audiences, and the contract says the row is the identity
        # (ADR-008, ADR-0019 §5).
        self.episodes: dict[str, Episode] = {}

    async def async_load(self) -> None:
        """Load snoozes, deferrals and silences, dropping anything unparsable."""
        data = await self._store.async_load()
        if not data:
            return

        for raw in data.get("silences", []):
            person = raw.get("person")
            until = dt_util.parse_datetime(str(raw.get("until", "")))
            if not person or until is None:
                continue
            self.silences[str(person)] = until

        for raw in data.get("snoozes", []):
            person = raw.get("person")
            slug = raw.get("slug")
            expiry = dt_util.parse_datetime(str(raw.get("expires_at", "")))
            if not person or not slug or expiry is None:
                continue
            self.snoozes[(str(person), str(slug))] = expiry

        for raw in data.get("deferrals", []):
            deferral = DeferredMessage.from_dict(raw)
            if deferral is None:
                continue
            self.deferrals[deferral.key] = deferral

        for raw in data.get("episodes", []):
            episode = Episode.from_dict(raw)
            if episode is None:
                continue
            self.episodes[episode.slug] = episode

    async def async_save(self) -> None:
        """Persist the current snoozes and deferrals."""
        await self._store.async_save(
            {
                "snoozes": [
                    {
                        "person": person,
                        "slug": slug,
                        "expires_at": expiry.isoformat(),
                    }
                    for (person, slug), expiry in self.snoozes.items()
                ],
                "deferrals": [
                    deferral.as_dict() for deferral in self.deferrals.values()
                ],
                "silences": [
                    {"person": person, "until": until.isoformat()}
                    for person, until in self.silences.items()
                ],
                "episodes": [episode.as_dict() for episode in self.episodes.values()],
            }
        )

    async def async_remove(self) -> None:
        """Delete the stored document (used when the entry is removed)."""
        self.snoozes.clear()
        self.deferrals.clear()
        self.silences.clear()
        self.episodes.clear()
        await self._store.async_remove()

    def purge_expired_snoozes(self, now: datetime) -> bool:
        """Drop snoozes that have expired; return True when something changed."""
        expired = [key for key, expiry in self.snoozes.items() if expiry <= now]
        for key in expired:
            del self.snoozes[key]
        return bool(expired)

    def purge_expired_silences(self, now: datetime) -> bool:
        """Drop temporary silences that have lifted; True when something changed.

        ADR-0016: a temporary silence expires lazily, exactly the way a snooze
        already does, so a missed timer can never leave somebody silent forever.
        """
        expired = [person for person, until in self.silences.items() if until <= now]
        for person in expired:
            del self.silences[person]
        return bool(expired)

    def is_temporarily_silenced(self, person: str, now: datetime) -> bool:
        """Return True when a temporary silence for `person` has not expired."""
        until = self.silences.get(person)
        return until is not None and until > now

    def active_snoozes(self, person: str, now: datetime) -> int:
        """Return how many snoozes are still running for a person."""
        return sum(
            1
            for (owner, _slug), expiry in self.snoozes.items()
            if owner == person and expiry > now
        )

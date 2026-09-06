"""Persisted state for Notify Switchboard.

Doctrine §5: nothing lives in RAM only. Snoozes and night deferrals go through
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

from .const import STORAGE_KEY, STORAGE_VERSION


class StoredData(TypedDict, total=False):
    """Shape of the JSON document written by `Store`."""

    snoozes: list[dict[str, Any]]
    deferrals: list[dict[str, Any]]


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
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DeferredMessage | None:
        """Rebuild a deferral from storage, or None when the row is unusable."""
        try:
            return cls(
                person=str(raw["person"]),
                slug=str(raw["slug"]),
                tag=str(raw.get("tag", "")),
                message=str(raw["message"]),
                title=raw.get("title"),
                priority=str(raw.get("priority", "normal")),
                data=dict(raw.get("data") or {}),
            )
        except KeyError, TypeError, ValueError:
            return None


class SwitchboardStore:
    """Thin, typed wrapper around the integration's `Store`."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialise the store for this Home Assistant instance."""
        self._store: Store[StoredData] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.snoozes: dict[tuple[str, str], datetime] = {}
        self.deferrals: dict[tuple[str, str, str], DeferredMessage] = {}

    async def async_load(self) -> None:
        """Load snoozes and deferrals, dropping anything unparsable."""
        data = await self._store.async_load()
        if not data:
            return

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
            }
        )

    async def async_remove(self) -> None:
        """Delete the stored document (used when the entry is removed)."""
        self.snoozes.clear()
        self.deferrals.clear()
        await self._store.async_remove()

    def purge_expired_snoozes(self, now: datetime) -> bool:
        """Drop snoozes that have expired; return True when something changed."""
        expired = [key for key, expiry in self.snoozes.items() if expiry <= now]
        for key in expired:
            del self.snoozes[key]
        return bool(expired)

    def active_snoozes(self, person: str, now: datetime) -> int:
        """Return how many snoozes are still running for a person."""
        return sum(
            1
            for (owner, _slug), expiry in self.snoozes.items()
            if owner == person and expiry > now
        )

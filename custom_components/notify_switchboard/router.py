"""Routing contract for Notify Switchboard.

This module defines the interface the router will fulfil once per-person
routing (presence, do-not-disturb, snoozes, alert class) lands. For this
sprint (S0/S1 skeleton) the implementation is a pure pass-through: every
configured default target receives every request unchanged.

Future sprints will replace `Router.route` with real decisioning, without
changing the shape of `NotificationRequest` / `RoutingDecision` unless the
contract in docs/ARCHITECTURE.md changes too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import DEFAULT_PRIORITY


@dataclass(slots=True)
class NotificationRequest:
    """A single inbound request to `notify.switchboard` or the entity."""

    message: str
    title: str | None = None
    target: list[str] | None = None
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def alert_class(self) -> str | None:
        """Return `data.class`, if provided."""
        return self.data.get("class")

    @property
    def priority(self) -> str:
        """Return `data.priority`, defaulting to normal."""
        return str(self.data.get("priority", DEFAULT_PRIORITY))

    @property
    def alert_entity(self) -> str | None:
        """Return `data.alert_entity`, if provided."""
        return self.data.get("alert_entity")


@dataclass(slots=True)
class RoutingDecision:
    """The outcome of routing a `NotificationRequest`."""

    # Notify service names (e.g. "notify.mobile_app_amiel") to call.
    targets: list[str]

    # Notify service names considered and rejected, with a short reason each
    # (e.g. "absent", "dnd", "snoozed"). Empty in the pass-through sprint.
    dropped: dict[str, str] = field(default_factory=dict)


class Router:
    """Chooses which `notify.*` services should receive a request.

    This sprint ships only `_route_passthrough`: every configured default
    target is returned unconditionally. Presence, do-not-disturb and snooze
    logic are out of scope for S0 and will be added behind this same
    `route()` interface — callers (notify.py) must not need to change.
    """

    def __init__(self, default_targets: list[str]) -> None:
        """Store the statically configured default targets."""
        self._default_targets = list(default_targets)
        # Exposed by diagnostics.py; the most recent routing outcome.
        self.last_decision: RoutingDecision | None = None

    async def route(self, request: NotificationRequest) -> RoutingDecision:
        """Decide which notify services should receive `request`.

        TODO(router): plug in per-person routing here:
          - filter by `request.alert_class` against person subscriptions
          - drop targets whose `person.*` is not home, unless required
          - drop targets under do-not-disturb, unless `request.priority`
            is `critical`
          - drop targets with an active snooze covering `request.alert_class`
        """
        decision = await self._route_passthrough(request)
        self.last_decision = decision
        return decision

    async def _route_passthrough(self, request: NotificationRequest) -> RoutingDecision:
        """Return every configured default target, unconditionally."""
        return RoutingDecision(targets=list(self._default_targets))

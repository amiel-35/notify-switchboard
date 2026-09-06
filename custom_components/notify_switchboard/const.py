"""Constants for the Notify Switchboard integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "notify_switchboard"

# The legacy `notify.*` service name exposed by this integration, so that
# `notify.switchboard` can be listed under `alert.notifiers:`.
LEGACY_SERVICE_NAME: Final = "switchboard"

# Config entry / options keys.
CONF_DEFAULT_TARGETS: Final = "default_targets"
DEFAULT_TARGETS: Final[list[str]] = []

# `data` payload attributes accepted by `notify.switchboard` and by
# `NotifyEntity.send_message`. Routing on these attributes is not implemented
# in this sprint; see router.py.
ATTR_CLASS: Final = "class"
ATTR_PRIORITY: Final = "priority"
ATTR_ALERT_ENTITY: Final = "alert_entity"

# Priority levels. Only `critical` is defined by the doctrine to override
# silence (do-not-disturb, snoozes); the others are informational for now.
PRIORITY_INFO: Final = "info"
PRIORITY_NORMAL: Final = "normal"
PRIORITY_HIGH: Final = "high"
PRIORITY_CRITICAL: Final = "critical"

DEFAULT_PRIORITY: Final = PRIORITY_NORMAL

VALID_PRIORITIES: Final[tuple[str, ...]] = (
    PRIORITY_INFO,
    PRIORITY_NORMAL,
    PRIORITY_HIGH,
    PRIORITY_CRITICAL,
)

# Origin entity of a routed message (contract: data.source_entity).
ATTR_SOURCE_ENTITY = "source_entity"

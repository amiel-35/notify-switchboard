"""Fixtures shared by the whole Notify Switchboard test suite."""

from __future__ import annotations

from collections.abc import Generator

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

# Tests that leave a real `alert.*` entity firing at teardown. The alert
# integration reschedules its repeat with `async_track_point_in_time`, whose
# timer handle carries no `HassJob` in `handle._args`
# (homeassistant/helpers/event.py, `_TrackPointUTCTime.async_attach` calls
# `loop.call_at(when, self)`), so neither
# `HomeAssistant._cancel_cancellable_timers` (homeassistant/core.py) nor
# pytest-homeassistant-custom-component's `verify_cleanup` can honour the
# `cancel_on_shutdown=True` the alert entity sets. Acknowledging an alert only
# sets `_ack` (homeassistant/components/alert/entity.py: `async_turn_off`); it
# does not cancel the repeat. The lingering timer therefore belongs to core,
# not to this integration -- see docs/known-issues.md.
_ALERT_LINGERING_TIMER_TESTS = frozenset(
    {
        "tests/acceptance/test_s1_actions.py::"
        "test_acknowledge_action_turns_off_the_row_alert_when_allowed",
        "tests/acceptance/test_s1_actions.py::"
        "test_acknowledge_is_refused_for_an_alert_not_in_the_routing_table",
    }
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Make custom_components discoverable in every test."""
    yield


@pytest.fixture
def expected_lingering_timers(request: pytest.FixtureRequest) -> bool:
    """Tolerate the `alert` component's un-cancellable repeat timer.

    Overrides pytest-homeassistant-custom-component's fixture for the two
    acceptance tests that drive the real `alert` integration, and only those.
    """
    return request.node.nodeid in _ALERT_LINGERING_TIMER_TESTS

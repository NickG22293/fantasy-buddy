"""Tests for shared HTTP utilities."""

import time
from unittest.mock import MagicMock

import utils.http as http_module
from utils.http import rate_limited_get, _SCRAPE_INTERVAL


def test_rate_limiting_enforces_gap():
    """Two back-to-back calls must be separated by at least _SCRAPE_INTERVAL seconds."""
    session = MagicMock()
    session.get.return_value.status_code = 200
    session.get.return_value.raise_for_status = MagicMock()

    # Simulate a call that just happened
    http_module._last_scrape_time = time.monotonic()

    start = time.monotonic()
    rate_limited_get(session, "https://example.com/test")
    elapsed = time.monotonic() - start

    # Allow 10% tolerance to avoid flaky tests on slow machines
    assert elapsed >= _SCRAPE_INTERVAL * 0.9


def test_rate_limiting_no_sleep_when_enough_time_passed():
    """If enough time has passed, no sleep should occur."""
    session = MagicMock()
    session.get.return_value.status_code = 200
    session.get.return_value.raise_for_status = MagicMock()

    # Simulate last scrape was 5 seconds ago
    http_module._last_scrape_time = time.monotonic() - 5.0

    start = time.monotonic()
    rate_limited_get(session, "https://example.com/test")
    elapsed = time.monotonic() - start

    # Should complete quickly (well under 1 second)
    assert elapsed < 0.5


def test_get_scrape_session_has_user_agent():
    from utils.http import get_scrape_session

    session = get_scrape_session()
    assert "User-Agent" in session.headers
    assert "HockeyBot" in session.headers["User-Agent"]

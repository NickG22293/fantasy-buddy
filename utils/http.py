"""Shared HTTP utilities: async NHL API client and rate-limited scraping session."""

import threading
import time

import httpx
import requests

_async_client: httpx.AsyncClient | None = None
_scrape_lock = threading.Lock()
_last_scrape_time: float = 0.0
_SCRAPE_INTERVAL: float = 1.0  # seconds between scrape requests


async def get_async_client() -> httpx.AsyncClient:
    """Return a shared async HTTPX client for the NHL API."""
    global _async_client
    if _async_client is None or _async_client.is_closed:
        _async_client = httpx.AsyncClient(
            base_url="https://api-web.nhle.com",
            timeout=httpx.Timeout(10.0),
            headers={"User-Agent": "HockeyBot-MCP/1.0"},
        )
    return _async_client


def get_scrape_session() -> requests.Session:
    """Return a requests.Session configured for polite scraping."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (compatible; HockeyBot-MCP/1.0; "
                "fantasy hockey research bot)"
            )
        }
    )
    return session


def rate_limited_get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    """
    Perform a GET request with a minimum 1-second gap between calls.
    Thread-safe via a module-level lock.
    """
    global _last_scrape_time
    with _scrape_lock:
        elapsed = time.monotonic() - _last_scrape_time
        if elapsed < _SCRAPE_INTERVAL:
            time.sleep(_SCRAPE_INTERVAL - elapsed)
        response = session.get(url, **kwargs)
        _last_scrape_time = time.monotonic()
    response.raise_for_status()
    return response

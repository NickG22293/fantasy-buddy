"""
Integration tests for get_player_stats — hit the real NHL API.

Run with:
    pytest tests/test_stats_integration.py -v -m integration

These tests require internet access and will make live HTTP requests.
"""

import pytest
import utils.http

from tools.stats import get_player_stats


@pytest.fixture(autouse=True)
async def reset_nhl_client():
    """Close and reset the shared NHL API client between tests.

    get_async_client() caches an AsyncClient globally. Each test runs in its
    own event loop (asyncio_default_test_loop_scope=function), so the cached
    client from the previous test has a closed loop and will error. Using an
    async fixture ensures teardown runs inside the test's loop, before it closes.
    """
    yield
    if utils.http._async_client is not None and not utils.http._async_client.is_closed:
        await utils.http._async_client.aclose()
    utils.http._async_client = None

# Sidney Crosby's permanent NHL player ID
CROSBY_ID = 8471675
CURRENT_SEASON = "20252026"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_crosby_basic_stats():
    result = await get_player_stats("Sidney Crosby")

    assert "error" not in result, f"Unexpected error: {result.get('error')}"
    assert int(result["player_id"]) == CROSBY_ID
    assert result["name"] == "Sidney Crosby"
    assert result["team"] == "PIT"
    assert result["position"] == "C"
    assert result["jersey_number"] == 87


@pytest.mark.integration
@pytest.mark.asyncio
async def test_crosby_season_stats_shape():
    result = await get_player_stats("Sidney Crosby", season=CURRENT_SEASON)

    assert "error" not in result
    stats = result["season_stats"]

    # All expected keys are present
    for key in ("games_played", "goals", "assists", "points", "plus_minus",
                "pim", "pp_points", "shots", "shooting_pct", "toi_per_game"):
        assert key in stats, f"Missing key: {key}"

    assert isinstance(stats["goals"], int)
    assert isinstance(stats["assists"], int)
    assert stats["goals"] >= 0
    assert stats["assists"] >= 0
    if stats["games_played"]:
        assert stats["points"] == stats["goals"] + stats["assists"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_crosby_career_totals():
    result = await get_player_stats("Sidney Crosby")

    assert "error" not in result
    career = result["career_totals"]

    assert career["points"] >= 1000
    assert career["games_played"] >= 1000


@pytest.mark.integration
@pytest.mark.asyncio
async def test_crosby_last_5_games_shape():
    result = await get_player_stats("Sidney Crosby")

    assert "error" not in result
    last_5 = result["last_5_games"]

    assert isinstance(last_5, list)
    for game in last_5:
        for key in ("date", "opponent", "goals", "assists", "points", "toi"):
            assert key in game, f"Missing key '{key}' in game entry"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_crosby_with_game_log():
    result = await get_player_stats("Sidney Crosby", include_game_log=True)

    assert "error" not in result
    assert "game_log_error" not in result, f"Game log error: {result.get('game_log_error')}"
    assert "game_log" in result

    log = result["game_log"]
    assert isinstance(log, list)
    assert len(log) <= 10  # capped at 10 per tool implementation

    if log:
        game = log[0]
        for key in ("date", "opponent", "goals", "assists", "points", "toi"):
            assert key in game

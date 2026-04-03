"""Tests for get_player_stats tool."""

import pytest
import respx
import httpx

from tools.stats import get_player_stats


@pytest.mark.asyncio
@respx.mock
async def test_get_player_stats_success(nhl_player_landing, nhl_search_results):
    respx.get("https://search.d3.nhle.com/api/v1/search/player").mock(
        return_value=httpx.Response(200, json=nhl_search_results)
    )
    respx.get("https://api-web.nhle.com/v1/player/8478402/landing").mock(
        return_value=httpx.Response(200, json=nhl_player_landing)
    )

    result = await get_player_stats("Connor McDavid")

    assert result["name"] == "Connor McDavid"
    assert result["team"] == "EDM"
    assert result["position"] == "C"
    assert result["season_stats"]["points"] == 94
    assert result["season_stats"]["goals"] == 32
    assert result["season_stats"]["assists"] == 62
    assert len(result["last_5_games"]) == 1
    assert result["last_5_games"][0]["points"] == 3


@pytest.mark.asyncio
@respx.mock
async def test_get_player_stats_not_found():
    respx.get("https://search.d3.nhle.com/api/v1/search/player").mock(
        return_value=httpx.Response(200, json=[])
    )

    result = await get_player_stats("Fake McFakerson")
    assert "error" in result
    assert "No active NHL player" in result["error"]


@pytest.mark.asyncio
@respx.mock
async def test_get_player_stats_nhl_api_error(nhl_search_results):
    respx.get("https://search.d3.nhle.com/api/v1/search/player").mock(
        return_value=httpx.Response(200, json=nhl_search_results)
    )
    respx.get("https://api-web.nhle.com/v1/player/8478402/landing").mock(
        return_value=httpx.Response(500)
    )

    result = await get_player_stats("Connor McDavid")
    assert "error" in result


@pytest.mark.asyncio
@respx.mock
async def test_get_player_stats_with_game_log(nhl_player_landing, nhl_search_results):
    game_log_response = {
        "gameLog": [
            {
                "gameDate": "2025-03-20",
                "opponentAbbrev": "CGY",
                "goals": 1,
                "assists": 1,
                "points": 2,
                "toi": "21:30",
            }
        ]
    }
    respx.get("https://search.d3.nhle.com/api/v1/search/player").mock(
        return_value=httpx.Response(200, json=nhl_search_results)
    )
    respx.get("https://api-web.nhle.com/v1/player/8478402/landing").mock(
        return_value=httpx.Response(200, json=nhl_player_landing)
    )
    respx.get(url__regex=r".*/game-log/.*").mock(
        return_value=httpx.Response(200, json=game_log_response)
    )

    result = await get_player_stats("Connor McDavid", include_game_log=True)
    assert "game_log" in result
    assert len(result["game_log"]) == 1

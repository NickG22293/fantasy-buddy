"""
Integration tests for get_league_context — hit the real Yahoo Fantasy API.

Run with:
    pytest tests/test_league_integration.py -v -m integration

These tests require a valid .env with YAHOO_OAUTH_CREDS_FILE, YAHOO_CLIENT_ID,
YAHOO_CLIENT_SECRET, and YAHOO_LEAGUE_ID set, and a live OAuth token.
"""

import os
import pytest

from tools.league import get_league_context

YAHOO_LEAGUE_ID = os.environ.get("YAHOO_LEAGUE_ID")

VALID_POSITIONS = {"C", "LW", "RW", "D", "G", "F", "Util", "IR", "BN", "NA"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_roster_player_shape(player: dict) -> None:
    for key in ("name", "player_id", "position", "eligible_positions", "selected_position"):
        assert key in player, f"Roster player missing key: {key}"
    assert isinstance(player["name"], str) and player["name"]
    assert isinstance(player["player_id"], str)
    assert isinstance(player["eligible_positions"], list)


def _assert_free_agent_shape(player: dict) -> None:
    for key in ("name", "player_id", "position", "eligible_positions", "ownership_pct"):
        assert key in player, f"Free agent missing key: {key}"
    assert isinstance(player["name"], str) and player["name"]
    assert isinstance(player["player_id"], str)


# ---------------------------------------------------------------------------
# Basic connectivity / response shape
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_yahoo_basic_context():
    result = await get_league_context(platform="yahoo", league_id=YAHOO_LEAGUE_ID, include_free_agents=False)

    print(result)
    assert "error" not in result, f"Unexpected error: {result.get('error')}"
    assert result["platform"] == "yahoo"
    assert isinstance(result["league_name"], str) and result["league_name"]
    assert isinstance(result["current_week"], int) and result["current_week"] > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_yahoo_week_date_range_shape():
    result = await get_league_context(platform="yahoo", league_id=YAHOO_LEAGUE_ID, include_free_agents=False)

    assert "error" not in result
    date_range = result["week_date_range"]
    assert date_range is not None
    assert "start" in date_range and "end" in date_range
    # Rough sanity check: both look like dates
    assert len(date_range["start"]) == 10  # "YYYY-MM-DD"
    assert len(date_range["end"]) == 10


# ---------------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_yahoo_my_roster_is_nonempty():
    result = await get_league_context(platform="yahoo", league_id=YAHOO_LEAGUE_ID, include_free_agents=False)

    assert "error" not in result
    roster = result["my_roster"]
    assert isinstance(roster, list)
    assert len(roster) > 0, "Expected at least one player on the roster"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_yahoo_roster_player_shape():
    result = await get_league_context(platform="yahoo", league_id=YAHOO_LEAGUE_ID, include_free_agents=False)

    assert "error" not in result
    for player in result["my_roster"]:
        _assert_roster_player_shape(player)


# ---------------------------------------------------------------------------
# Free agents
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_yahoo_free_agents_center():
    result = await get_league_context(
        platform="yahoo",
        league_id=YAHOO_LEAGUE_ID,
        include_free_agents=True,
        free_agent_position="C",
    )

    assert "error" not in result
    fa = result["free_agents"]
    assert isinstance(fa, list)
    assert len(fa) > 0, "Expected at least one centre in free agents"
    for player in fa:
        _assert_free_agent_shape(player)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_yahoo_free_agents_excluded_when_flag_false():
    result = await get_league_context(
        platform="yahoo",
        league_id=YAHOO_LEAGUE_ID,
        include_free_agents=False,
    )

    assert "error" not in result
    assert result["free_agents"] == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_yahoo_free_agents_goalie():
    result = await get_league_context(
        platform="yahoo",
        league_id=YAHOO_LEAGUE_ID,
        include_free_agents=True,
        free_agent_position="G",
    )

    assert "error" not in result
    fa = result["free_agents"]
    assert isinstance(fa, list)
    for player in fa:
        _assert_free_agent_shape(player)


# ---------------------------------------------------------------------------
# Specific week override
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_yahoo_specific_week():
    result = await get_league_context(
        platform="yahoo",
        league_id=YAHOO_LEAGUE_ID,
        week=1,
        include_free_agents=False,
    )

    assert "error" not in result
    assert result["current_week"] == 1
    # Week 1 roster may differ from current — just verify shape holds
    for player in result["my_roster"]:
        _assert_roster_player_shape(player)

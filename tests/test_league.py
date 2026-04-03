"""Tests for get_league_context tool."""

import pytest
from unittest.mock import MagicMock, patch

from tools.league import get_league_context


@pytest.mark.asyncio
async def test_get_league_context_missing_league_id():
    """Returns error dict when no league_id is provided and env var is unset."""
    with patch.dict("os.environ", {}, clear=False):
        # Ensure neither env var is set
        import os
        os.environ.pop("YAHOO_LEAGUE_ID", None)

        result = await get_league_context(platform="yahoo", league_id=None)

    assert "error" in result
    assert "YAHOO_LEAGUE_ID" in result["error"]


@pytest.mark.asyncio
async def test_get_league_context_unknown_platform():
    result = await get_league_context(platform="fanduel", league_id="123")
    assert "error" in result
    assert "fanduel" in result["error"]


@pytest.mark.asyncio
async def test_get_league_context_yahoo_success():
    """Yahoo path returns expected structure with mocked yfa.Game."""
    mock_lg = MagicMock()
    mock_lg.current_week.return_value = 22
    mock_lg.week_date_range.return_value = ("2025-03-17", "2025-03-23")
    mock_lg.team_key.return_value = "449.l.12345.t.3"
    mock_lg.settings.return_value = {"name": "Test League"}
    mock_lg.free_agents.return_value = []

    mock_tm = MagicMock()
    mock_tm.roster.return_value = []
    mock_lg.to_team.return_value = mock_tm

    mock_gm = MagicMock()
    mock_gm.to_league.return_value = mock_lg

    with patch("tools.league.get_yahoo_session", return_value=MagicMock()):
        with patch("yahoo_fantasy_api.Game", return_value=mock_gm):
            result = await get_league_context(
                platform="yahoo", league_id="449.l.12345", include_free_agents=False
            )

    assert result["platform"] == "yahoo"
    assert result["current_week"] == 22
    assert result["league_name"] == "Test League"
    assert isinstance(result["my_roster"], list)


@pytest.mark.asyncio
async def test_get_league_context_yahoo_auth_error():
    """Returns error dict when Yahoo OAuth fails."""
    with patch("tools.league.get_yahoo_session", side_effect=RuntimeError("token expired")):
        with patch("yahoo_fantasy_api.Game"):
            result = await get_league_context(platform="yahoo", league_id="449.l.12345")

    assert "error" in result
    assert "token expired" in result["error"]

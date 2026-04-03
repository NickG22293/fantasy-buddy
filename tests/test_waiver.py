"""Tests for get_waiver_advice tool."""

import pytest
from unittest.mock import patch, MagicMock

from tools.waiver import get_waiver_advice, _infer_action


# --- Unit tests for action inference ---

def test_infer_action_add():
    assert _infer_action("You should add this player immediately") == "add"


def test_infer_action_pick_up():
    assert _infer_action("Pick up Brock Faber off waivers") == "add"


def test_infer_action_drop():
    assert _infer_action("Feel free to drop this guy from your roster") == "drop"


def test_infer_action_hold():
    assert _infer_action("Keep him rostered while he heals") == "hold"


def test_infer_action_watch():
    assert _infer_action("Watch list candidate — monitor practice reports") == "watch"


def test_infer_action_unknown():
    assert _infer_action("This player played 18 minutes yesterday") == "unknown"


# --- Integration tests with mocked HTTP ---

@pytest.mark.asyncio
async def test_get_waiver_advice_both_sites_fail():
    """When both sites are unreachable, returns error dict without raising."""
    with patch("tools.waiver.rate_limited_get", side_effect=Exception("timeout")):
        result = await get_waiver_advice(player_name="Test Player")

    assert result["players"] == []
    assert "error" in result


@pytest.mark.asyncio
async def test_get_waiver_advice_returns_structure():
    """Result always has the expected top-level keys."""
    with patch("tools.waiver.rate_limited_get", side_effect=Exception("timeout")):
        result = await get_waiver_advice()

    assert "source" in result
    assert "scraped_at" in result
    assert "players" in result
    assert isinstance(result["players"], list)


@pytest.mark.asyncio
async def test_get_waiver_advice_player_entry_shape():
    """Player entries have the required fields."""
    mock_resp = MagicMock()
    mock_resp.text = """
    <html><body>
    <article class="post">
      <h2 class="entry-title"><a href="http://example.com/article">Top Adds</a></h2>
    </article>
    </body></html>
    """
    article_resp = MagicMock()
    article_resp.text = """
    <html><body>
    <div class="entry-content">
      <p><strong>Brock Faber</strong> is a must add on all platforms this week. Pick up immediately.</p>
    </div>
    </body></html>
    """

    def fake_get(session, url, **kwargs):
        if "example.com/article" in url:
            return article_resp
        return mock_resp

    with patch("tools.waiver.rate_limited_get", side_effect=fake_get):
        result = await get_waiver_advice(top_n=5)

    assert "players" in result
    if result["players"]:
        player = result["players"][0]
        assert "name" in player
        assert "advice" in player
        assert "action" in player
        assert "source_url" in player

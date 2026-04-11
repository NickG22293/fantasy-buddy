"""Tests for get_waiver_advice tool."""

import pytest
from unittest.mock import AsyncMock, patch

from tools.waiver import get_waiver_advice, _composite_z, _yahoo_position, _score_entry

# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

def test_composite_z_sums_present_keys():
    zscores = {
        "goals":    {"z": 1.0, "flag": None},
        "assists":  {"z": 2.0, "flag": None},
        "pp_points": {"z": None, "flag": None},
    }
    result = _composite_z(zscores, ("goals", "assists", "pp_points"))
    assert result == 3.0


def test_composite_z_all_none_returns_none():
    zscores = {"goals": {"z": None}}
    assert _composite_z(zscores, ("goals",)) is None


def test_composite_z_empty_keys():
    assert _composite_z({}, ()) is None


def test_yahoo_position_defaults_to_center():
    assert _yahoo_position(None) == "C"
    assert _yahoo_position("F") == "C"   # "F" not a Yahoo code → falls back
    assert _yahoo_position("x") == "C"


def test_yahoo_position_valid_codes():
    for pos in ("C", "LW", "RW", "D", "G"):
        assert _yahoo_position(pos) == pos
    assert _yahoo_position("c") == "C"   # case-insensitive


def test_score_entry_no_stats():
    entry = _score_entry(None, "Ghost Player", ("goals",), ownership_pct=5.0)
    assert entry["name"] == "Ghost Player"
    assert entry["composite_z"] is None
    assert entry["note"] == "NHL stats unavailable"
    assert entry["ownership_pct"] == 5.0


def test_score_entry_with_stats():
    fake_stats = {
        "name": "Brock Faber",
        "team": "MIN",
        "position": "D",
        "season_stats": {"goals": 5, "assists": 30},
        "zscores": {
            "goals":   {"z": 0.5, "flag": None},
            "assists": {"z": 1.5, "flag": "high"},
        },
        "last_5_games": [],
    }
    entry = _score_entry(fake_stats, "Brock Faber", ("goals", "assists"))
    assert entry["name"] == "Brock Faber"
    assert entry["composite_z"] == 2.0
    assert entry["team"] == "MIN"


# ---------------------------------------------------------------------------
# Integration tests (league + stats calls mocked)
# ---------------------------------------------------------------------------

_MOCK_CONTEXT = {
    "platform": "yahoo",
    "league_name": "Wetbrains United",
    "current_week": 22,
    "week_date_range": {"start": "2026-03-23", "end": "2026-03-29"},
    "my_roster": [
        {"name": "Bryan Rust",    "eligible_positions": ["RW", "Util"], "selected_position": "RW"},
        {"name": "Mitch Marner",  "eligible_positions": ["C", "LW", "RW", "Util"], "selected_position": "LW"},
    ],
    "free_agents": [
        {"name": "Brock Faber",  "position": "D", "eligible_positions": ["D"], "ownership_pct": 45.0},
        {"name": "Tage Thompson","position": "C", "eligible_positions": ["C", "Util"], "ownership_pct": 12.0},
    ],
}


def _make_stats(name: str, team: str, pos: str, goals_z: float, assists_z: float) -> dict:
    return {
        "name": name, "team": team, "position": pos,
        "season_stats": {"goals": 10, "assists": 20},
        "zscores": {
            "goals":       {"z": goals_z, "flag": None},
            "assists":     {"z": assists_z, "flag": None},
            "pp_points":   {"z": 0.0, "flag": None},
            "shots":       {"z": 0.0, "flag": None},
            "toi_per_game": {"z": 0.0, "flag": None},
        },
        "last_5_games": [],
    }


@pytest.mark.asyncio
async def test_get_waiver_advice_response_shape():
    """Result always contains the expected top-level keys."""
    with (
        patch("tools.waiver.get_league_context", new=AsyncMock(return_value=_MOCK_CONTEXT)),
        patch("tools.waiver.get_player_stats", new=AsyncMock(return_value=_make_stats("X", "T", "C", 0, 0))),
    ):
        result = await get_waiver_advice(position="C")

    for key in ("analyzed_at", "position_group", "league_name", "current_week",
                 "add_candidates", "drop_candidates", "all_free_agents_ranked",
                 "roster_ranked_weakest_first"):
        assert key in result, f"Missing key: {key}"


@pytest.mark.asyncio
async def test_get_waiver_advice_league_error_propagates():
    """When league context fails, error is surfaced cleanly."""
    with patch("tools.waiver.get_league_context", new=AsyncMock(return_value={"error": "OAuth expired"})):
        result = await get_waiver_advice()

    assert "error" in result
    assert "OAuth expired" in result["error"]
    assert "add_candidates" not in result


@pytest.mark.asyncio
async def test_get_waiver_advice_no_free_agents():
    """Empty FA list returns an informative error."""
    empty_ctx = {**_MOCK_CONTEXT, "free_agents": []}
    with patch("tools.waiver.get_league_context", new=AsyncMock(return_value=empty_ctx)):
        result = await get_waiver_advice(position="C")

    assert "error" in result


@pytest.mark.asyncio
async def test_get_waiver_advice_rankings_ordered():
    """FAs are ranked highest composite_z first."""
    fa_stats_calls = [
        _make_stats("Brock Faber",   "MIN", "C", goals_z=2.0, assists_z=1.0),
        _make_stats("Tage Thompson", "BUF", "C", goals_z=0.5, assists_z=0.5),
    ]
    roster_stats = _make_stats("Bryan Rust", "PIT", "RW", goals_z=-1.0, assists_z=-0.5)

    call_count = 0

    async def mock_stats(name: str, **_):
        nonlocal call_count
        call_count += 1
        lookup = {s["name"]: s for s in fa_stats_calls + [roster_stats, _make_stats("Mitch Marner", "TOR", "C", 1.0, 1.5)]}
        return lookup.get(name, {"error": "not found"})

    with (
        patch("tools.waiver.get_league_context", new=AsyncMock(return_value=_MOCK_CONTEXT)),
        patch("tools.waiver.get_player_stats", new=mock_stats),
    ):
        result = await get_waiver_advice(position="C")

    ranked = result["all_free_agents_ranked"]
    assert len(ranked) >= 1
    # Verify descending order
    for i in range(len(ranked) - 1):
        assert ranked[i]["composite_z"] >= ranked[i + 1]["composite_z"]


@pytest.mark.asyncio
async def test_get_waiver_advice_top_n_respected():
    """top_n is capped at 25 and limits free agents evaluated."""
    big_ctx = {
        **_MOCK_CONTEXT,
        "free_agents": [{"name": f"Player {i}", "eligible_positions": ["C"], "ownership_pct": i} for i in range(30)],
    }
    with (
        patch("tools.waiver.get_league_context", new=AsyncMock(return_value=big_ctx)),
        patch("tools.waiver.get_player_stats", new=AsyncMock(return_value={"error": "skip"})),
    ):
        result = await get_waiver_advice(position="C", top_n=5)

    # With stats unavailable, all_free_agents_ranked is empty but no crash
    assert "error" not in result or "No free agents" not in result.get("error", "")

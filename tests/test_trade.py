"""Tests for evaluate_trade_target tool."""

import pytest
from unittest.mock import AsyncMock, patch

from tools.trade import (
    evaluate_trade_target,
    _primary_position,
    _composite_z,
    _build_position_summary,
    _weakness_ranking,
    _score_player,
)

# ---------------------------------------------------------------------------
# Unit tests — pure functions
# ---------------------------------------------------------------------------

def test_primary_position_goalie_wins():
    assert _primary_position(["G", "Util"]) == "G"


def test_primary_position_defense_over_forward():
    assert _primary_position(["D", "Util"]) == "D"


def test_primary_position_center_over_wings():
    assert _primary_position(["C", "LW", "RW", "Util"]) == "C"


def test_primary_position_lw_over_rw():
    assert _primary_position(["LW", "RW", "Util"]) == "LW"


def test_primary_position_rw_only():
    assert _primary_position(["RW", "Util"]) == "RW"


def test_primary_position_fallback():
    assert _primary_position(["Util", "BN"]) == "C"


def test_composite_z_sums_keys():
    zscores = {
        "goals":   {"z": 1.0},
        "assists": {"z": 2.0},
        "shots":   {"z": None},
    }
    assert _composite_z(zscores, ("goals", "assists", "shots")) == 3.0


def test_composite_z_all_none():
    assert _composite_z({"goals": {"z": None}}, ("goals",)) is None


def test_composite_z_empty_keys():
    assert _composite_z({"goals": {"z": 1.0}}, ()) is None


def test_score_player_no_stats():
    player = {"name": "Ghost", "eligible_positions": ["C", "LW"]}
    entry = _score_player(None, player)
    assert entry["name"] == "Ghost"
    assert entry["position"] == "C"
    assert entry["composite_z"] is None
    assert entry["note"] == "NHL stats unavailable"


def test_score_player_goalie_has_null_z():
    """Goalies get empty z_keys, so composite_z is always None."""
    player = {"name": "Jake Allen", "eligible_positions": ["G"]}
    stats = {
        "name": "Jake Allen",
        "team": "MTL",
        "position": "G",
        "season_stats": {"games_played": 20},
        "zscores": {"goals": {"z": 0.5}},  # would be nonsense for a goalie
    }
    entry = _score_player(stats, player)
    assert entry["position"] == "G"
    assert entry["composite_z"] is None  # empty z_keys → no keys to sum


def test_build_position_summary_groups_correctly():
    players = [
        {"name": "A", "position": "C",  "composite_z": 2.0},
        {"name": "B", "position": "C",  "composite_z": 1.0},
        {"name": "C", "position": "LW", "composite_z": -1.0},
        {"name": "D", "position": "D",  "composite_z": None},
        {"name": "E", "position": "G",  "composite_z": None},
    ]
    summary = _build_position_summary(players)

    assert summary["C"]["total_z"] == 3.0
    assert summary["C"]["player_count"] == 2
    assert summary["LW"]["total_z"] == -1.0
    assert summary["D"]["total_z"] is None   # only None values
    assert summary["G"]["total_z"] is None
    assert summary["RW"]["player_count"] == 0


def test_build_position_summary_sorted_best_first():
    players = [
        {"name": "Low",  "position": "C", "composite_z": -2.0},
        {"name": "High", "position": "C", "composite_z":  3.0},
        {"name": "None", "position": "C", "composite_z": None},
    ]
    summary = _build_position_summary(players)
    names = [p["name"] for p in summary["C"]["players"]]
    assert names[0] == "High"
    assert names[-1] == "None"


def test_weakness_ranking_orders_weakest_first():
    summary = {
        "C":  {"total_z":  3.0, "player_count": 2},
        "LW": {"total_z": -1.0, "player_count": 1},
        "RW": {"total_z":  None, "player_count": 1},  # None → treated as -inf
        "D":  {"total_z":  1.0, "player_count": 3},
        "G":  {"total_z":  None, "player_count": 0},  # no players → excluded
    }
    ranking = _weakness_ranking(summary)
    assert ranking[0] == "RW"   # None z → weakest
    assert ranking[1] == "LW"
    assert "G" not in ranking   # zero players excluded


# ---------------------------------------------------------------------------
# Integration tests (league + stats calls mocked)
# ---------------------------------------------------------------------------

_MY_ROSTER = [
    {"name": "Connor McDavid", "eligible_positions": ["C", "Util"],  "selected_position": "C"},
    {"name": "Brady Tkachuk",  "eligible_positions": ["LW", "Util"], "selected_position": "LW"},
    {"name": "Brock Faber",    "eligible_positions": ["D"],          "selected_position": "D"},
    {"name": "Jake Allen",     "eligible_positions": ["G"],          "selected_position": "G"},
]

_OPP_ROSTER = [
    {"name": "Auston Matthews",  "eligible_positions": ["C", "Util"],  "selected_position": "C"},
    {"name": "Mikko Rantanen",   "eligible_positions": ["RW", "Util"], "selected_position": "RW"},
    {"name": "Drew Doughty",     "eligible_positions": ["D"],          "selected_position": "D"},
    {"name": "Andrei Vasilevskiy", "eligible_positions": ["G"],        "selected_position": "G"},
]

_MOCK_TRADE_CONTEXT = {
    "platform": "yahoo",
    "league_name": "Wetbrains United",
    "current_week": 22,
    "my_team_key": "465.l.26058.t.1",
    "my_roster": _MY_ROSTER,
    "opponent_team_key": "465.l.26058.t.3",
    "opponent_name": "Cheeky Pucks",
    "opponent_roster": _OPP_ROSTER,
}


def _make_stats(name: str, team: str, pos: str, goals_z: float, assists_z: float) -> dict:
    return {
        "name": name,
        "team": team,
        "position": pos,
        "season_stats": {"goals": 10, "assists": 20},
        "zscores": {
            "goals":        {"z": goals_z},
            "assists":      {"z": assists_z},
            "pp_points":    {"z": 0.0},
            "shots":        {"z": 0.0},
            "toi_per_game": {"z": 0.0},
        },
    }


_STATS_LOOKUP = {
    "Connor McDavid":      _make_stats("Connor McDavid",    "EDM", "C",  3.0, 4.0),
    "Brady Tkachuk":       _make_stats("Brady Tkachuk",     "OTT", "LW", 1.0, 0.5),
    "Brock Faber":         _make_stats("Brock Faber",       "MIN", "D",  0.2, 1.5),
    "Jake Allen":          _make_stats("Jake Allen",        "MTL", "G",  0.0, 0.0),
    "Auston Matthews":     _make_stats("Auston Matthews",   "TOR", "C",  2.0, 1.5),
    "Mikko Rantanen":      _make_stats("Mikko Rantanen",    "CAR", "RW", 1.5, 2.0),
    "Drew Doughty":        _make_stats("Drew Doughty",      "LAK", "D",  0.1, 0.8),
    "Andrei Vasilevskiy":  _make_stats("Andrei Vasilevskiy","TBL", "G",  0.0, 0.0),
}


async def _mock_stats(name: str, **_) -> dict:
    return _STATS_LOOKUP.get(name, {"error": "not found"})


@pytest.mark.asyncio
async def test_evaluate_trade_target_response_shape():
    """Result contains all expected top-level keys."""
    with (
        patch("tools.trade.get_trade_context", new=AsyncMock(return_value=_MOCK_TRADE_CONTEXT)),
        patch("tools.trade.get_player_stats", new=_mock_stats),
    ):
        result = await evaluate_trade_target("Cheeky Pucks")

    for key in (
        "analyzed_at", "league_name", "current_week", "opponent_name",
        "my_team", "opponent_team", "trade_analysis",
    ):
        assert key in result, f"Missing top-level key: {key}"

    assert "position_summary" in result["my_team"]
    assert "weakness_ranking" in result["my_team"]
    assert "position_summary" in result["opponent_team"]
    assert "weakness_ranking" in result["opponent_team"]

    analysis = result["trade_analysis"]
    for key in ("my_weak_positions", "opponent_weak_positions", "trade_targets", "potential_offers"):
        assert key in analysis, f"Missing trade_analysis key: {key}"


@pytest.mark.asyncio
async def test_evaluate_trade_target_position_summary_keys():
    """Every position group (C/LW/RW/D/G) appears in both summaries."""
    with (
        patch("tools.trade.get_trade_context", new=AsyncMock(return_value=_MOCK_TRADE_CONTEXT)),
        patch("tools.trade.get_player_stats", new=_mock_stats),
    ):
        result = await evaluate_trade_target("Cheeky Pucks")

    for team_key in ("my_team", "opponent_team"):
        summary = result[team_key]["position_summary"]
        for pos in ("C", "LW", "RW", "D", "G"):
            assert pos in summary, f"{team_key} missing position group: {pos}"
            assert "total_z" in summary[pos]
            assert "player_count" in summary[pos]
            assert "players" in summary[pos]


@pytest.mark.asyncio
async def test_evaluate_trade_target_goalie_null_z():
    """Goalies always have null composite_z (no goalie z-scores implemented)."""
    with (
        patch("tools.trade.get_trade_context", new=AsyncMock(return_value=_MOCK_TRADE_CONTEXT)),
        patch("tools.trade.get_player_stats", new=_mock_stats),
    ):
        result = await evaluate_trade_target("Cheeky Pucks")

    my_goalies = result["my_team"]["position_summary"]["G"]["players"]
    assert all(p["composite_z"] is None for p in my_goalies)


@pytest.mark.asyncio
async def test_evaluate_trade_target_z_score_totals():
    """My C total_z should reflect McDavid's high z-scores."""
    with (
        patch("tools.trade.get_trade_context", new=AsyncMock(return_value=_MOCK_TRADE_CONTEXT)),
        patch("tools.trade.get_player_stats", new=_mock_stats),
    ):
        result = await evaluate_trade_target("Cheeky Pucks")

    my_c = result["my_team"]["position_summary"]["C"]
    assert my_c["player_count"] == 1
    # goals_z=3.0, assists_z=4.0, pp_points_z=0.0, shots_z=0.0, toi_z=0.0 → 7.0
    assert my_c["total_z"] == 7.0


@pytest.mark.asyncio
async def test_evaluate_trade_target_my_team_has_no_rw():
    """My roster has no RW — that position should be weakest."""
    with (
        patch("tools.trade.get_trade_context", new=AsyncMock(return_value=_MOCK_TRADE_CONTEXT)),
        patch("tools.trade.get_player_stats", new=_mock_stats),
    ):
        result = await evaluate_trade_target("Cheeky Pucks")

    # RW has 0 players, so it's excluded from weakness_ranking
    my_weak = result["my_team"]["weakness_ranking"]
    assert "RW" not in my_weak
    rw_summary = result["my_team"]["position_summary"]["RW"]
    assert rw_summary["player_count"] == 0


@pytest.mark.asyncio
async def test_evaluate_trade_target_trade_targets_from_opponent():
    """Trade targets should be opponent players at my weak positions."""
    with (
        patch("tools.trade.get_trade_context", new=AsyncMock(return_value=_MOCK_TRADE_CONTEXT)),
        patch("tools.trade.get_player_stats", new=_mock_stats),
    ):
        result = await evaluate_trade_target("Cheeky Pucks")

    targets = result["trade_analysis"]["trade_targets"]
    # All targets must be opponent roster players
    opp_names = {p["name"] for p in _OPP_ROSTER}
    for t in targets:
        assert t["name"] in opp_names, f"Trade target '{t['name']}' not on opponent roster"
        assert "fills_need" in t


@pytest.mark.asyncio
async def test_evaluate_trade_target_potential_offers_from_my_team():
    """Potential offers should be my players at opponent's weak positions."""
    with (
        patch("tools.trade.get_trade_context", new=AsyncMock(return_value=_MOCK_TRADE_CONTEXT)),
        patch("tools.trade.get_player_stats", new=_mock_stats),
    ):
        result = await evaluate_trade_target("Cheeky Pucks")

    offers = result["trade_analysis"]["potential_offers"]
    my_names = {p["name"] for p in _MY_ROSTER}
    for o in offers:
        assert o["name"] in my_names, f"Offer '{o['name']}' not on my roster"
        assert "addresses_opponent_need" in o


@pytest.mark.asyncio
async def test_evaluate_trade_target_context_error_propagates():
    """When trade context fails, error is surfaced cleanly."""
    with patch(
        "tools.trade.get_trade_context",
        new=AsyncMock(return_value={"error": "Could not find opponent 'XYZ'"}),
    ):
        result = await evaluate_trade_target("XYZ")

    assert "error" in result
    assert "XYZ" in result["error"]
    assert "trade_analysis" not in result


@pytest.mark.asyncio
async def test_evaluate_trade_target_stats_unavailable():
    """Tool completes without crashing when all NHL stats fail."""
    with (
        patch("tools.trade.get_trade_context", new=AsyncMock(return_value=_MOCK_TRADE_CONTEXT)),
        patch("tools.trade.get_player_stats", new=AsyncMock(return_value={"error": "NHL down"})),
    ):
        result = await evaluate_trade_target("Cheeky Pucks")

    assert "error" not in result
    # All players have null z, so trade_targets and potential_offers are empty
    assert result["trade_analysis"]["trade_targets"] == []
    assert result["trade_analysis"]["potential_offers"] == []

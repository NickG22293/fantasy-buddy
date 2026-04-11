"""MCP tool: evaluate_trade_target — z-score position analysis for trade negotiations."""

import asyncio
from datetime import datetime, timezone
from typing import Any

from tools.league import get_trade_context
from tools.stats import get_player_stats

_SKATER_Z_KEYS = ("goals", "assists", "pp_points", "shots", "toi_per_game")

# Canonical position groups, in priority order for assignment
_POSITIONS: tuple[str, ...] = ("C", "LW", "RW", "D", "G")
_POSITION_PRIORITY: tuple[str, ...] = ("G", "D", "C", "LW", "RW")


def _primary_position(eligible_positions: list[str]) -> str:
    """Assign a player to a single canonical position group.

    Goalies and defensemen take priority; among forwards, C > LW > RW.
    """
    ep = set(eligible_positions)
    for pos in _POSITION_PRIORITY:
        if pos in ep:
            return pos
    return "C"  # fallback for edge cases (e.g. Util-only slots)


def _composite_z(zscores: dict, keys: tuple[str, ...]) -> float | None:
    """Sum z-scores for the given stat keys; return None if all are missing."""
    total = 0.0
    found = False
    for k in keys:
        z = zscores.get(k, {}).get("z")
        if z is not None:
            total += z
            found = True
    return round(total, 2) if found else None


async def _fetch_stats_safe(name: str) -> dict | None:
    """Fetch NHL stats for a player by name; return None on any failure."""
    try:
        result = await get_player_stats(name)
        return None if "error" in result else result
    except Exception:
        return None


def _score_player(stats: dict | None, roster_player: dict) -> dict:
    """Build a scored player entry from raw NHL stats and roster metadata."""
    position = _primary_position(roster_player.get("eligible_positions", []))
    z_keys = () if position == "G" else _SKATER_Z_KEYS
    name = roster_player["name"]

    if stats is None:
        return {
            "name": name,
            "nhl_team": None,
            "position": position,
            "eligible_positions": roster_player.get("eligible_positions", []),
            "composite_z": None,
            "season_stats": None,
            "note": "NHL stats unavailable",
        }

    return {
        "name": stats["name"],
        "nhl_team": stats["team"],
        "position": position,
        "eligible_positions": roster_player.get("eligible_positions", []),
        "composite_z": _composite_z(stats.get("zscores", {}), z_keys),
        "season_stats": stats["season_stats"],
    }


def _build_position_summary(scored_players: list[dict]) -> dict[str, dict]:
    """Group scored players by position and sum z-scores per group."""
    groups: dict[str, list[dict]] = {pos: [] for pos in _POSITIONS}
    for p in scored_players:
        pos = p["position"]
        if pos in groups:
            groups[pos].append(p)

    summary: dict[str, dict] = {}
    for pos in _POSITIONS:
        players = groups[pos]
        valid_zs = [p["composite_z"] for p in players if p["composite_z"] is not None]
        summary[pos] = {
            "total_z": round(sum(valid_zs), 2) if valid_zs else None,
            "player_count": len(players),
            "players": sorted(
                players,
                key=lambda p: (p["composite_z"] is None, -(p["composite_z"] or 0)),
            ),
        }
    return summary


def _weakness_ranking(summary: dict[str, dict]) -> list[str]:
    """Return positions sorted weakest-first (None z treated as very weak).

    Positions with no players on the roster are excluded.
    """
    scored = [
        (pos, info["total_z"] if info["total_z"] is not None else float("-inf"))
        for pos, info in summary.items()
        if info["player_count"] > 0
    ]
    return [pos for pos, _ in sorted(scored, key=lambda x: x[1])]


async def evaluate_trade_target(
    opponent: str,
    platform: str = "yahoo",
) -> dict[str, Any]:
    """
    Analyze an opponent's roster for trade opportunities using z-score position analysis.

    Computes composite z-scores for every player on both rosters, groups them by
    position (C, LW, RW, D, G), and sums z-scores per group. Low group totals
    signal positions where a team is weak and therefore inclined to trade.

    Use the output to identify:
    - Where the opponent is weak (they want to acquire from you)
    - Where you are weak (players you should target from them)
    - Specific trade targets and what you could offer in return

    Note: Goalie z-score analysis is not yet available; goalies appear in position
    summaries with null composite_z.

    Args:
        opponent: Opponent's team name (partial match OK) or Yahoo team key
        platform: Fantasy platform — only "yahoo" is currently supported

    Returns position-level z-score summaries for both teams, weakness rankings,
    recommended trade targets from the opponent's roster, and potential offers
    from your roster.
    """
    analyzed_at = datetime.now(timezone.utc).isoformat()

    # 1. Fetch both rosters
    context = await get_trade_context(opponent=opponent, platform=platform)
    if "error" in context:
        return {"error": context["error"], "analyzed_at": analyzed_at}

    my_roster = context["my_roster"]
    opp_roster = context["opponent_roster"]

    # 2. Fetch NHL stats concurrently for every player on both rosters
    my_names = [p["name"] for p in my_roster]
    opp_names = [p["name"] for p in opp_roster]

    my_stats_raw, opp_stats_raw = await asyncio.gather(
        asyncio.gather(*[_fetch_stats_safe(n) for n in my_names]),
        asyncio.gather(*[_fetch_stats_safe(n) for n in opp_names]),
    )

    # 3. Score each player
    my_scored = [_score_player(stats, p) for p, stats in zip(my_roster, my_stats_raw)]
    opp_scored = [_score_player(stats, p) for p, stats in zip(opp_roster, opp_stats_raw)]

    # 4. Build per-position z-score summaries
    my_summary = _build_position_summary(my_scored)
    opp_summary = _build_position_summary(opp_scored)

    # 5. Rank weaknesses (weakest position first)
    my_weak = _weakness_ranking(my_summary)
    opp_weak = _weakness_ranking(opp_summary)

    # 6. Trade targets: opponent's strongest players at my weakest positions
    trade_targets: list[dict] = []
    for pos in my_weak[:3]:
        candidates = sorted(
            [p for p in opp_scored if p["position"] == pos and p["composite_z"] is not None],
            key=lambda p: -(p["composite_z"] or 0),
        )
        for p in candidates[:2]:
            trade_targets.append({**p, "fills_need": pos})

    # 7. Potential offers: my strongest players at opponent's weakest positions
    potential_offers: list[dict] = []
    for pos in opp_weak[:3]:
        candidates = sorted(
            [p for p in my_scored if p["position"] == pos and p["composite_z"] is not None],
            key=lambda p: -(p["composite_z"] or 0),
        )
        for p in candidates[:2]:
            potential_offers.append({**p, "addresses_opponent_need": pos})

    return {
        "analyzed_at": analyzed_at,
        "league_name": context.get("league_name"),
        "current_week": context.get("current_week"),
        "opponent_name": context["opponent_name"],
        "my_team": {
            "position_summary": my_summary,
            "weakness_ranking": my_weak,
        },
        "opponent_team": {
            "name": context["opponent_name"],
            "position_summary": opp_summary,
            "weakness_ranking": opp_weak,
        },
        "trade_analysis": {
            "my_weak_positions": my_weak[:3],
            "opponent_weak_positions": opp_weak[:3],
            "trade_targets": trade_targets,
            "potential_offers": potential_offers,
        },
    }

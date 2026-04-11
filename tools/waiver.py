"""MCP tool: get_waiver_advice — data-driven waiver recommendations via NHL statistical analysis."""

import asyncio
from datetime import datetime, timezone
from typing import Any

from tools.league import get_league_context
from tools.stats import get_player_stats

# Stat keys used for composite z-score (skaters only — goalie pipeline TBD)
_SKATER_Z_KEYS = ("goals", "assists", "pp_points", "shots", "toi_per_game")

# Yahoo free_agents() accepts these position codes
_YAHOO_POSITIONS = {"C", "LW", "RW", "D", "G"}

# Which eligible_positions values indicate a forward vs. defender
_FORWARD_ELIGIBLES = {"C", "LW", "RW"}
_DEFENSE_ELIGIBLES = {"D"}
_GOALIE_ELIGIBLES = {"G"}


def _yahoo_position(position: str | None) -> str:
    """Map the requested position to a Yahoo-compatible position code."""
    if position is None or position.upper() not in _YAHOO_POSITIONS:
        return "C"  # default: centers as representative skaters
    return position.upper()


def _composite_z(zscores: dict, keys: tuple[str, ...]) -> float | None:
    """Sum z-scores for the given keys; return None if all are missing."""
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


def _score_entry(stats: dict | None, name: str, z_keys: tuple[str, ...], ownership_pct: Any = None) -> dict:
    if stats is None:
        return {
            "name": name,
            "team": None,
            "position": None,
            "composite_z": None,
            "ownership_pct": ownership_pct,
            "season_stats": None,
            "last_5_games": [],
            "note": "NHL stats unavailable",
        }
    return {
        "name": stats["name"],
        "team": stats["team"],
        "position": stats["position"],
        "composite_z": _composite_z(stats.get("zscores", {}), z_keys),
        "ownership_pct": ownership_pct,
        "season_stats": stats["season_stats"],
        "last_5_games": stats.get("last_5_games", []),
    }


async def get_waiver_advice(
    position: str | None = None,
    top_n: int = 20,
) -> dict[str, Any]:
    """
    Analyze the top available free agents using NHL statistical data and return
    data-driven add/drop recommendations for your fantasy roster.

    Internally fetches your league context and NHL stats — no external scraping.

    Args:
        position: Position to focus on — "C", "LW", "RW", "D", or "G".
                  Omit for generic skaters (defaults to Centers).
        top_n: Number of free agents to evaluate (default 20, max 25).

    Returns ranked free agent add candidates, suggested roster drops to make
    room, and full ranked lists for both free agents and your current roster
    at the target position.
    """
    top_n = min(top_n, 25)
    analyzed_at = datetime.now(timezone.utc).isoformat()
    yahoo_pos = _yahoo_position(position)
    is_goalie = yahoo_pos == "G"

    # 1. Fetch league context: roster + top free agents at the target position
    context = await get_league_context(
        platform="yahoo",
        include_free_agents=True,
        free_agent_position=yahoo_pos,
    )
    if "error" in context:
        return {"error": context["error"], "analyzed_at": analyzed_at}

    free_agents = context.get("free_agents", [])[:top_n]
    roster = context.get("my_roster", [])

    if not free_agents:
        return {
            "error": f"No free agents found for position '{yahoo_pos}'.",
            "analyzed_at": analyzed_at,
        }

    # 2. Identify which roster players are in the same position group
    if is_goalie:
        roster_targets = [p for p in roster if "G" in p.get("eligible_positions", [])]
        z_keys: tuple[str, ...] = ()  # goalie z-score pipeline not yet implemented
    elif yahoo_pos == "D":
        roster_targets = [p for p in roster if "D" in p.get("eligible_positions", [])]
        z_keys = _SKATER_Z_KEYS
    else:
        # Forward position group: eligible for C, LW, or RW but not D
        roster_targets = [
            p for p in roster
            if any(pos in p.get("eligible_positions", []) for pos in _FORWARD_ELIGIBLES)
            and "D" not in p.get("eligible_positions", [])
        ]
        z_keys = _SKATER_Z_KEYS

    # 3. Fetch NHL stats concurrently for all FAs and relevant roster players
    fa_names = [p["name"] for p in free_agents]
    roster_names = [p["name"] for p in roster_targets]

    fa_stats, roster_stats = await asyncio.gather(
        asyncio.gather(*[_fetch_stats_safe(n) for n in fa_names]),
        asyncio.gather(*[_fetch_stats_safe(n) for n in roster_names]),
    )

    fa_ownership = {p["name"]: p.get("ownership_pct") for p in free_agents}

    # 4. Score each player by composite z-score
    scored_fas = [
        _score_entry(stats, name, z_keys, fa_ownership.get(name))
        for name, stats in zip(fa_names, fa_stats)
    ]
    scored_roster = [
        _score_entry(stats, name, z_keys)
        for name, stats in zip(roster_names, roster_stats)
    ]

    # 5. Rank: FAs highest z first; roster lowest z first (weakest links)
    ranked_fas = sorted(
        [p for p in scored_fas if p["composite_z"] is not None],
        key=lambda p: p["composite_z"],
        reverse=True,
    )
    ranked_roster = sorted(
        [p for p in scored_roster if p["composite_z"] is not None],
        key=lambda p: p["composite_z"],
    )

    # Top 5 adds; drop candidates only where a top FA is statistically better
    add_candidates = ranked_fas[:5]
    drop_candidates = [
        p for p in ranked_roster[:3]
        if add_candidates and add_candidates[0]["composite_z"] > (p["composite_z"] or 0)
    ]

    return {
        "analyzed_at": analyzed_at,
        "position_group": yahoo_pos,
        "league_name": context.get("league_name"),
        "current_week": context.get("current_week"),
        "add_candidates": add_candidates,
        "drop_candidates": drop_candidates,
        "all_free_agents_ranked": ranked_fas,
        "roster_ranked_weakest_first": ranked_roster,
    }

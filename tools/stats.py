"""MCP tool: get_player_stats — fetch NHL performance metrics for a player."""

from typing import Any

from utils.http import get_async_client
from utils.nhl_ids import resolve_player_id


async def get_player_stats(
    player_name: str,
    season: str = "current",
    include_game_log: bool = False,
) -> dict[str, Any]:
    """
    Retrieve NHL performance metrics for a player.

    Args:
        player_name: Full or partial player name (e.g. "Connor McDavid", "Bedard")
        season: Season in YYYYYYYY format (e.g. "20242025") or "current"
        include_game_log: If True, include per-game stats for last 10 games

    Returns a dict with player profile, current season stats, last 5 games,
    career totals, and optionally a per-game log.
    """
    try:
        player = await resolve_player_id(player_name)
    except ValueError as e:
        return {"error": str(e), "player_name": player_name}

    player_id = player["player_id"]
    client = await get_async_client()

    try:
        resp = await client.get(f"/v1/player/{player_id}/landing")
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"error": f"NHL API error fetching player {player_id}: {e}"}

    # Extract current season stats
    featured = data.get("featuredStats", {}).get("regularSeasonStatsObj", {})
    season_raw = featured.get("season", {})
    career_raw = featured.get("career", {})

    season_stats = {
        "games_played": season_raw.get("gamesPlayed"),
        "goals": season_raw.get("goals"),
        "assists": season_raw.get("assists"),
        "points": season_raw.get("points"),
        "plus_minus": season_raw.get("plusMinus"),
        "pim": season_raw.get("pim"),
        "pp_points": season_raw.get("powerPlayPoints"),
        "shots": season_raw.get("shots"),
        "shooting_pct": season_raw.get("shootingPctg"),
        "toi_per_game": season_raw.get("avgToi"),
    }

    career_totals = {
        "games_played": career_raw.get("gamesPlayed"),
        "goals": career_raw.get("goals"),
        "assists": career_raw.get("assists"),
        "points": career_raw.get("points"),
    }

    # Extract last 5 games
    last_5 = [
        {
            "date": g.get("gameDate"),
            "opponent": g.get("opponentAbbrev"),
            "goals": g.get("goals"),
            "assists": g.get("assists"),
            "points": g.get("points"),
            "toi": g.get("toi"),
        }
        for g in data.get("last5Games", [])
    ]

    result: dict[str, Any] = {
        "player_id": player_id,
        "name": f"{data.get('firstName', {}).get('default', '')} {data.get('lastName', {}).get('default', '')}".strip(),
        "team": data.get("currentTeamAbbrev"),
        "position": data.get("position"),
        "jersey_number": data.get("sweaterNumber"),
        "season_stats": season_stats,
        "last_5_games": last_5,
        "career_totals": career_totals,
    }

    if include_game_log:
        resolved_season = season if season != "current" else _current_season()
        try:
            log_resp = await client.get(f"/v1/player/{player_id}/game-log/{resolved_season}/2")
            log_resp.raise_for_status()
            log_data = log_resp.json()
            result["game_log"] = [
                {
                    "date": g.get("gameDate"),
                    "opponent": g.get("opponentAbbrev"),
                    "goals": g.get("goals"),
                    "assists": g.get("assists"),
                    "points": g.get("points"),
                    "toi": g.get("toi"),
                }
                for g in log_data.get("gameLog", [])[:10]
            ]
        except Exception as e:
            result["game_log_error"] = str(e)

    return result


def _current_season() -> str:
    """Return the current NHL season string (e.g. '20242025')."""
    from datetime import date

    today = date.today()
    # NHL seasons start in October; if before October, season started last year
    if today.month >= 10:
        return f"{today.year}{today.year + 1}"
    return f"{today.year - 1}{today.year}"

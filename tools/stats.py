"""MCP tool: get_player_stats — fetch NHL performance metrics for a player."""

import json
from pathlib import Path
from typing import Any

from utils.http import get_async_client
from utils.nhl_ids import resolve_player_id

_DATA_DIR = Path(__file__).parent.parent / "data"


def _toi_seconds(toi: str | None) -> float | None:
    """Convert 'MM:SS' string to float seconds, or pass through if already numeric."""
    if toi is None:
        return None
    if isinstance(toi, (int, float)):
        return float(toi)
    if ":" in toi:
        mm, ss = toi.split(":", 1)
        return int(mm) * 60 + int(ss)
    return None


# Mapping from our internal stat key -> norm stat key + value extractor.
# TOI comes in as "MM:SS" from the landing API; norms store it as float seconds.
_STAT_MAP: dict[str, tuple[str, Any]] = {
    "goals":        ("goals",        lambda v: float(v)),
    "assists":      ("assists",      lambda v: float(v)),
    "shots":        ("shots",        lambda v: float(v)),
    "shooting_pct": ("shooting_pct", lambda v: float(v)),
    "toi_per_game": ("toi_per_game", _toi_seconds),
    "hits":         ("hits",         lambda v: float(v)),
    "blocks":       ("blocks",       lambda v: float(v)),
    "pp_points":    ("pp_points",    lambda v: float(v)),
}


def _load_norms(position: str) -> dict[str, dict[str, float]] | None:
    """Load pre-computed norms for the player's position group."""
    filename = "defense_norms.json" if position == "D" else "forward_norms.json"
    path = _DATA_DIR / filename
    try:
        return json.loads(path.read_text())["norms"]
    except (FileNotFoundError, KeyError):
        return None


def _zscore(value: float, norm: dict[str, float]) -> float:
    sd = norm["stdev"]
    return (value - norm["mean"]) / sd if sd > 0 else 0.0


def _flag(z: float) -> str | None:
    if z >= 2.0:
        return "very_high"
    if z >= 1.5:
        return "high"
    if z <= -2.0:
        return "very_low"
    if z <= -1.5:
        return "low"
    return None


async def _fetch_realtime_stats(player_id: int, season: int) -> dict[str, Any]:
    """Fetch hits and blocked shots from the NHL stats realtime report."""
    import httpx
    import json as _json

    sort = _json.dumps([{"property": "hits", "direction": "DESC"}])
    try:
        async with httpx.AsyncClient(base_url="https://api.nhle.com", timeout=10.0) as client:
            resp = await client.get(
                "/stats/rest/en/skater/realtime",
                params={
                    "isAggregate": "false",
                    "isGame": "false",
                    "sort": sort,
                    "start": 0,
                    "limit": 1,
                    "cayenneExp": f"gameTypeId=2 and seasonId={season} and playerId={player_id}",
                },
            )
            resp.raise_for_status()
            rows = resp.json().get("data", [])
            return rows[0] if rows else {}
    except Exception:
        return {}


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

    Returns a dict with player profile, season stats, z-scores with threshold
    flags relative to position peers, last 5 games, and career totals.
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

    position = data.get("position", "C")

    # Resolve which season we're looking at
    resolved_season_id = (
        int(season) if season != "current"
        else data.get("featuredStats", {}).get("season")
    )
    is_current = (
        season == "current"
        or resolved_season_id == data.get("featuredStats", {}).get("season")
    )

    season_raw: dict[str, Any] = {}
    toi_per_game = None

    if is_current:
        featured = data.get("featuredStats", {}).get("regularSeason", {})
        season_raw = featured.get("subSeason", {})
        for entry in data.get("seasonTotals", []):
            if (
                entry.get("season") == resolved_season_id
                and entry.get("leagueAbbrev") == "NHL"
                and entry.get("gameTypeId") == 2
            ):
                toi_per_game = entry.get("avgToi")
                break
    else:
        for entry in data.get("seasonTotals", []):
            if (
                entry.get("season") == resolved_season_id
                and entry.get("leagueAbbrev") == "NHL"
                and entry.get("gameTypeId") == 2
            ):
                season_raw = entry
                toi_per_game = entry.get("avgToi")
                break
        if not season_raw:
            return {
                "error": f"No NHL regular-season stats found for season {season}",
                "player_id": player_id,
            }

    # Hits and blocks aren't in the landing endpoint — fetch separately
    realtime = await _fetch_realtime_stats(player_id, resolved_season_id)

    season_stats = {
        "games_played":  season_raw.get("gamesPlayed"),
        "goals":         season_raw.get("goals"),
        "assists":       season_raw.get("assists"),
        "points":        season_raw.get("points"),
        "plus_minus":    season_raw.get("plusMinus"),
        "pim":           season_raw.get("pim"),
        "pp_points":     season_raw.get("powerPlayPoints"),
        "shots":         season_raw.get("shots"),
        "shooting_pct":  season_raw.get("shootingPctg"),
        "toi_per_game":  toi_per_game,
        "hits":          realtime.get("hits"),
        "blocks":        realtime.get("blockedShots"),
    }

    # Z-scores relative to position peers
    zscores: dict[str, Any] = {}
    norms = _load_norms(position)
    if norms:
        for stat_key, (norm_key, extractor) in _STAT_MAP.items():
            raw_val = season_stats.get(stat_key)
            if raw_val is None or norm_key not in norms:
                zscores[stat_key] = {"z": None, "flag": None}
                continue
            try:
                converted = extractor(raw_val)
                z = round(_zscore(converted, norms[norm_key]), 2)
                zscores[stat_key] = {"z": z, "flag": _flag(z)}
            except (TypeError, ValueError):
                zscores[stat_key] = {"z": None, "flag": None}

    # Career totals
    career_raw = data.get("careerTotals", {}).get("regularSeason", {})
    career_totals = {
        "games_played": career_raw.get("gamesPlayed"),
        "goals":        career_raw.get("goals"),
        "assists":      career_raw.get("assists"),
        "points":       career_raw.get("points"),
    }

    last_5 = (
        [
            {
                "date":     g.get("gameDate"),
                "opponent": g.get("opponentAbbrev"),
                "goals":    g.get("goals"),
                "assists":  g.get("assists"),
                "points":   g.get("points"),
                "toi":      g.get("toi"),
            }
            for g in data.get("last5Games", [])
        ]
        if is_current
        else []
    )

    result: dict[str, Any] = {
        "player_id":     player_id,
        "name":          f"{data.get('firstName', {}).get('default', '')} {data.get('lastName', {}).get('default', '')}".strip(),
        "team":          data.get("currentTeamAbbrev"),
        "position":      position,
        "jersey_number": data.get("sweaterNumber"),
        "season":        resolved_season_id,
        "season_stats":  season_stats,
        "zscores":       zscores,
        "last_5_games":  last_5,
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
                    "date":     g.get("gameDate"),
                    "opponent": g.get("opponentAbbrev"),
                    "goals":    g.get("goals"),
                    "assists":  g.get("assists"),
                    "points":   g.get("points"),
                    "toi":      g.get("toi"),
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
    if today.month >= 10:
        return f"{today.year}{today.year + 1}"
    return f"{today.year - 1}{today.year}"

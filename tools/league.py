"""MCP tool: get_league_context — retrieve roster and free agent data from Yahoo or ESPN."""

import asyncio
import os
from typing import Any

from dotenv import load_dotenv

from auth.yahoo_oauth import get_yahoo_session

load_dotenv()


def _format_roster_player(p: dict) -> dict:
    return {
        "name": p.get("name"),
        "player_id": str(p.get("player_id", "")),
        "position": p.get("display_position"),
        "eligible_positions": p.get("eligible_positions", []),
        "selected_position": p.get("selected_position"),
        "injury_status": p.get("status") or None,
    }


def _format_free_agent(p: dict) -> dict:
    return {
        "name": p.get("name"),
        "player_id": str(p.get("player_id", "")),
        "position": p.get("display_position"),
        "eligible_positions": p.get("eligible_positions", []),
        "ownership_pct": p.get("percent_owned"),
    }


def _yahoo_league_context(league_id: str, week: int | None, include_free_agents: bool, free_agent_position: str | None) -> dict:
    """Synchronous Yahoo Fantasy API call — run via asyncio.to_thread."""
    import yahoo_fantasy_api as yfa

    sc = get_yahoo_session()
    gm = yfa.Game(sc, "nhl")
    lg = gm.to_league(league_id)

    current_week = week or lg.current_week()
    week_start, week_end = lg.week_date_range(current_week)

    team_key = lg.team_key()
    tm = lg.to_team(team_key)
    roster_raw = tm.roster(current_week)

    my_roster = [_format_roster_player(p) for p in roster_raw]

    free_agents: list[dict] = []
    if include_free_agents:
        pos = free_agent_position or "C"
        fa_raw = lg.free_agents(pos)
        free_agents = [_format_free_agent(p) for p in fa_raw]

    settings = lg.settings()

    return {
        "platform": "yahoo",
        "league_name": settings.get("name", "Unknown"),
        "current_week": current_week,
        "week_date_range": {"start": str(week_start), "end": str(week_end)},
        "my_roster": my_roster,
        "free_agents": free_agents,
    }


def _espn_league_context(league_id: str, season_year: int | None, include_free_agents: bool, free_agent_position: str | None) -> dict:
    """Synchronous ESPN Fantasy API call — run via asyncio.to_thread."""
    from espn_api.hockey import League as ESPNLeague

    espn_s2 = os.environ.get("ESPN_S2")
    swid = os.environ.get("ESPN_SWID")
    year = season_year or int(os.environ.get("ESPN_SEASON_YEAR", "2025"))

    if not espn_s2 or not swid:
        raise RuntimeError(
            "ESPN_S2 and ESPN_SWID must be set in .env. "
            "Extract them from browser cookies at espn.com."
        )

    league = ESPNLeague(league_id=int(league_id), year=year, espn_s2=espn_s2, swid=swid)

    my_team = league.teams[0]  # TODO: identify user's team properly
    my_roster = [
        {
            "name": p.name,
            "player_id": str(p.playerId),
            "position": p.position,
            "eligible_positions": p.eligibleSlots,
            "selected_position": None,
            "injury_status": p.injuryStatus or None,
        }
        for p in my_team.roster
    ]

    free_agents = []
    if include_free_agents:
        pos_filter = [free_agent_position] if free_agent_position else None
        fa_raw = league.free_agents(size=20, position=pos_filter)
        free_agents = [
            {
                "name": p.name,
                "player_id": str(p.playerId),
                "position": p.position,
                "eligible_positions": p.eligibleSlots,
                "ownership_pct": None,
            }
            for p in fa_raw
        ]

    return {
        "platform": "espn",
        "league_name": league.settings.name,
        "current_week": league.current_week,
        "week_date_range": None,
        "my_roster": my_roster,
        "free_agents": free_agents,
    }


async def get_league_context(
    platform: str = "yahoo",
    league_id: str | None = None,
    week: int | None = None,
    include_free_agents: bool = True,
    free_agent_position: str | None = None,
) -> dict[str, Any]:
    """
    Retrieve roster context from Yahoo Fantasy or ESPN.

    Args:
        platform: "yahoo" or "espn"
        league_id: League ID (overrides .env if provided)
        week: Scoring week number (None = current week)
        include_free_agents: Whether to fetch available free agents
        free_agent_position: Filter free agents by position: "C", "LW", "RW", "D", "G"

    Returns your current roster, available free agents, league name, and current week info.
    """
    resolved_league_id = league_id or os.environ.get(
        "YAHOO_LEAGUE_ID" if platform == "yahoo" else "ESPN_LEAGUE_ID"
    )
    if not resolved_league_id:
        return {
            "error": (
                f"No league_id provided and {'YAHOO_LEAGUE_ID' if platform == 'yahoo' else 'ESPN_LEAGUE_ID'} "
                "is not set in .env"
            )
        }

    try:
        if platform == "yahoo":
            result = await asyncio.to_thread(
                _yahoo_league_context,
                resolved_league_id,
                week,
                include_free_agents,
                free_agent_position,
            )
        elif platform == "espn":
            season_year = int(os.environ.get("ESPN_SEASON_YEAR", "2025"))
            result = await asyncio.to_thread(
                _espn_league_context,
                resolved_league_id,
                season_year,
                include_free_agents,
                free_agent_position,
            )
        else:
            return {"error": f"Unknown platform '{platform}'. Use 'yahoo' or 'espn'."}
    except RuntimeError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"League context fetch failed: {e}"}

    return result

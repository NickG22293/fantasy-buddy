"""Resolve NHL player names to numeric player IDs via the NHL search API."""

import difflib
from typing import TypedDict

import httpx

_SEARCH_URL = "https://search.d3.nhle.com/api/v1/search/player"


class PlayerSuggestion(TypedDict):
    player_id: int
    name: str
    position: str
    team: str
    active: bool


async def search_player_id(name: str, limit: int = 10) -> list[PlayerSuggestion]:
    """
    Return up to `limit` matching players from the NHL suggest API.
    Results are sorted by name-match similarity (closest first).
    """
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(
            _SEARCH_URL,
            params={"culture": "en-us", "limit": limit, "q": name},
        )
        resp.raise_for_status()

    results = resp.json()
    suggestions: list[PlayerSuggestion] = [
        PlayerSuggestion(
            player_id=r["playerId"],
            name=r["name"],
            position=r.get("positionCode", "?"),
            team=r.get("teamAbbrev", "?"),
            active=r.get("active", False),
        )
        for r in results
    ]

    # Sort active players first, then by name similarity
    name_lower = name.lower()
    suggestions.sort(
        key=lambda p: (
            not p["active"],
            -difflib.SequenceMatcher(None, name_lower, p["name"].lower()).ratio(),
        )
    )
    return suggestions


async def resolve_player_id(name: str) -> PlayerSuggestion:
    """
    Resolve a player name to a single PlayerSuggestion.
    Raises ValueError with candidate list if ambiguous or not found.
    """
    candidates = await search_player_id(name)
    active = [p for p in candidates if p["active"]]

    if not active:
        raise ValueError(f"No active NHL player found matching '{name}'")

    best = active[0]
    ratio = difflib.SequenceMatcher(None, name.lower(), best["name"].lower()).ratio()

    # If the top match is close enough, return it
    if ratio >= 0.6:
        return best

    # Ambiguous — return top candidates so the caller can prompt for clarification
    names = ", ".join(f"{p['name']} ({p['team']})" for p in active[:5])
    raise ValueError(
        f"Could not confidently match '{name}'. Candidates: {names}. "
        "Try including the team abbreviation, e.g. 'Patrick Kane DET'."
    )

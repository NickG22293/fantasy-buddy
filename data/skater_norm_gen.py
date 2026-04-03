"""
Pre-compute skater stat norms (mean + stdev) for the current NHL season.

Saves results to:
    data/forward_norms.json   — Centers, Left Wings, Right Wings
    data/defense_norms.json   — Defensemen

Run this periodically (e.g. daily) so that z-score calculations at request
time always use an up-to-date population distribution without needing to
re-fetch all skaters.

Usage:
    uv run python data/z_scores.py [season]
"""

import asyncio
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

STATS_API = "https://api.nhle.com"
CURRENT_SEASON = "20252026"
MIN_GAMES = 20
DATA_DIR = Path(__file__).parent

FORWARD_POSITIONS = {"C", "L", "R"}
DEFENSE_POSITIONS = {"D"}

# Stats to track: label -> (report_type, api_field_name)
STAT_FIELDS: dict[str, tuple[str, str]] = {
    "goals":        ("summary",  "goals"),
    "assists":      ("summary",  "assists"),
    "shots":        ("summary",  "shots"),
    "shooting_pct": ("summary",  "shootingPct"),
    "toi_per_game": ("summary",  "timeOnIcePerGame"),  # float seconds
    "hits":         ("realtime", "hits"),
    "blocks":       ("realtime", "blockedShots"),
    "pp_points":    ("summary",  "ppPoints"),
}

_REPORT_SORT: dict[str, str] = {
    "summary":  "points",
    "realtime": "hits",
}


async def _fetch_report(
    client: httpx.AsyncClient,
    report: str,
    season: str,
) -> list[dict[str, Any]]:
    """Paginate through one NHL stats report and return all rows."""
    rows: list[dict[str, Any]] = []
    limit = 100
    start = 0
    sort_param = json.dumps([{"property": _REPORT_SORT[report], "direction": "DESC"}])

    while True:
        resp = await client.get(
            f"/stats/rest/en/skater/{report}",
            params={
                "isAggregate": "false",
                "isGame": "false",
                "sort": sort_param,
                "start": start,
                "limit": limit,
                "cayenneExp": f"gameTypeId=2 and seasonId={season}",
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        page: list[dict[str, Any]] = payload.get("data", [])
        rows.extend(page)
        if not page or len(rows) >= payload.get("total", 0):
            break
        start += limit

    return rows


async def fetch_all_skaters(season: str) -> list[dict[str, Any]]:
    """Fetch and merge summary + realtime reports, joined on playerId."""
    async with httpx.AsyncClient(
        base_url=STATS_API,
        timeout=30.0,
        headers={"User-Agent": "HockeyBot-MCP/1.0"},
    ) as client:
        summary_rows, realtime_rows = await asyncio.gather(
            _fetch_report(client, "summary", season),
            _fetch_report(client, "realtime", season),
        )

    realtime_by_id = {r["playerId"]: r for r in realtime_rows}
    return [{**row, **realtime_by_id.get(row["playerId"], {})} for row in summary_rows]


def compute_norms(players: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """
    Compute mean and stdev for each stat across all qualified players.
    Returns: {"goals": {"mean": ..., "stdev": ...}, ...}
    """
    qualified = [p for p in players if (p.get("gamesPlayed") or 0) >= MIN_GAMES]
    if not qualified:
        raise ValueError(f"No players with >= {MIN_GAMES} games played.")

    norms: dict[str, dict[str, float]] = {}
    for stat, (_, field) in STAT_FIELDS.items():
        values = [float(p[field]) for p in qualified if p.get(field) is not None]
        norms[stat] = {
            "mean":  statistics.mean(values),
            "stdev": statistics.stdev(values),
        }

    return norms


def save_norms(
    norms: dict[str, dict[str, float]],
    season: str,
    n_players: int,
    filename: str,
) -> None:
    payload = {
        "season": season,
        "min_games": MIN_GAMES,
        "n_players": n_players,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "norms": norms,
    }
    path = DATA_DIR / filename
    path.write_text(json.dumps(payload, indent=2))
    print(f"  Saved {path.name} ({n_players} players)")


def zscore(stat: str, value: float, norms: dict[str, dict[str, float]]) -> float:
    """Compute the z-score for a single stat value given pre-computed norms."""
    n = norms[stat]
    sd = n["stdev"]
    return (value - n["mean"]) / sd if sd > 0 else 0.0


def _print_norms(label: str, norms: dict[str, dict[str, float]]) -> None:
    print(f"\n  {label}")
    print(f"  {'Stat':<15} {'Mean':>10} {'Stdev':>10}")
    print(f"  {'-' * 37}")
    for stat, n in norms.items():
        print(f"  {stat:<15} {n['mean']:>10.3f} {n['stdev']:>10.3f}")


async def main(season: str = CURRENT_SEASON) -> None:
    print(f"Fetching all skaters for {season}...", flush=True)
    players = await fetch_all_skaters(season)
    print(f"  {len(players)} skaters fetched.")

    qualified = [p for p in players if (p.get("gamesPlayed") or 0) >= MIN_GAMES]
    forwards   = [p for p in qualified if p.get("positionCode") in FORWARD_POSITIONS]
    defensemen = [p for p in qualified if p.get("positionCode") in DEFENSE_POSITIONS]

    print(f"  {len(qualified)} qualify (>= {MIN_GAMES} GP): "
          f"{len(forwards)} forwards, {len(defensemen)} defensemen. Computing norms...\n")

    fwd_norms = compute_norms(forwards)
    def_norms = compute_norms(defensemen)

    save_norms(fwd_norms, season, len(forwards), "forward_norms.json")
    save_norms(def_norms, season, len(defensemen), "defense_norms.json")

    _print_norms("Forwards (C/L/R)", fwd_norms)
    _print_norms("Defensemen (D)", def_norms)


if __name__ == "__main__":
    season = sys.argv[1] if len(sys.argv) > 1 else CURRENT_SEASON
    asyncio.run(main(season))

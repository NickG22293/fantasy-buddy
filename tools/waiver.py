"""MCP tool: get_waiver_advice — scrape DobberHockey and DailyFaceoff for waiver wire guidance."""

import urllib.parse
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup

from utils.http import get_scrape_session, rate_limited_get

_DOBBER_WAIVER_URL = "https://dobberhockey.com/category/waiver-wire/"
_DOBBER_SEARCH_URL = "https://dobberhockey.com/"
_DAILYFACEOFF_NEWS_URL = "https://www.dailyfaceoff.com/hockey-player-news"

_ACTION_KEYWORDS: dict[str, list[str]] = {
    "add": ["add", "pick up", "grab", "target", "recommended add", "must add", "stream"],
    "drop": ["drop", "cut", "release", "avoid", "don't bother", "do not bother"],
    "hold": ["hold", "keep", "stash", "rostered", "hold onto"],
    "watch": ["watch", "monitor", "speculative", "watch list"],
}


def _infer_action(text: str) -> str:
    lower = text.lower()
    for action, keywords in _ACTION_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return action
    return "unknown"


def _scrape_dobber_latest(session, position_filter: str | None, top_n: int) -> list[dict]:
    """Scrape the most recent waiver wire post from DobberHockey."""
    try:
        resp = rate_limited_get(session, _DOBBER_WAIVER_URL, timeout=15)
    except Exception as e:
        return [{"error": f"DobberHockey unavailable: {e}"}]

    soup = BeautifulSoup(resp.text, "lxml")
    # Find the first article link in the waiver wire category
    first_article = soup.select_one("article.post h2.entry-title a, h2.entry-title a")
    if not first_article:
        return []

    article_url = first_article.get("href", "")
    if not article_url:
        return []

    try:
        article_resp = rate_limited_get(session, article_url, timeout=15)
    except Exception as e:
        return [{"error": f"Failed to fetch DobberHockey article: {e}"}]

    article_soup = BeautifulSoup(article_resp.text, "lxml")
    content_div = article_soup.select_one("div.entry-content")
    if not content_div:
        return []

    players: list[dict] = []
    for p in content_div.find_all("p"):
        text = p.get_text(separator=" ", strip=True)
        if not text or len(text) < 20:
            continue

        # Player names are often bolded or in the first strong/a tag
        name_tag = p.find(["strong", "b"])
        name = name_tag.get_text(strip=True) if name_tag else None

        if not name or len(name) > 40:
            continue

        action = _infer_action(text)
        entry = {
            "name": name,
            "position": None,
            "team": None,
            "advice": text[:300],
            "action": action,
            "source_url": article_url,
            "published_date": None,
        }

        if position_filter and entry["position"] and entry["position"] != position_filter:
            continue

        players.append(entry)
        if len(players) >= top_n:
            break

    return players


def _scrape_dobber_player(session, player_name: str) -> dict | None:
    """Search DobberHockey for a specific player and return their latest mention."""
    search_url = f"{_DOBBER_SEARCH_URL}?s={urllib.parse.quote(player_name)}"
    try:
        resp = rate_limited_get(session, search_url, timeout=15)
    except Exception:
        return None

    soup = BeautifulSoup(resp.text, "lxml")
    first_link = soup.select_one("h2.entry-title a")
    if not first_link:
        return None

    article_url = first_link.get("href", "")
    try:
        article_resp = rate_limited_get(session, article_url, timeout=15)
    except Exception:
        return None

    article_soup = BeautifulSoup(article_resp.text, "lxml")
    content_div = article_soup.select_one("div.entry-content")
    if not content_div:
        return None

    # Find paragraphs mentioning the player
    name_lower = player_name.lower()
    for p in content_div.find_all("p"):
        text = p.get_text(separator=" ", strip=True)
        if name_lower.split()[-1].lower() in text.lower():
            return {
                "name": player_name,
                "position": None,
                "team": None,
                "advice": text[:500],
                "action": _infer_action(text),
                "source_url": article_url,
                "published_date": None,
            }
    return None


def _scrape_dailyfaceoff_player(session, player_name: str) -> list[dict]:
    """Fetch recent news items mentioning the player from DailyFaceoff."""
    try:
        resp = rate_limited_get(session, _DAILYFACEOFF_NEWS_URL, timeout=15)
    except Exception:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    results: list[dict] = []
    name_lower = player_name.lower()

    # DailyFaceoff structures news items in divs with player names
    for item in soup.select("div.player-news-item, article.news-item, div[class*='news']"):
        text = item.get_text(separator=" ", strip=True)
        if name_lower.split()[-1].lower() not in text.lower():
            continue

        # Try to find a date
        date_tag = item.find("time")
        pub_date = date_tag.get("datetime") if date_tag else None

        results.append(
            {
                "name": player_name,
                "position": None,
                "team": None,
                "advice": text[:400],
                "action": _infer_action(text),
                "source_url": _DAILYFACEOFF_NEWS_URL,
                "published_date": pub_date,
            }
        )
        if len(results) >= 3:
            break

    return results


async def get_waiver_advice(
    player_name: str | None = None,
    position_filter: str | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    """
    Scrape DobberHockey and DailyFaceoff for waiver wire guidance.

    Args:
        player_name: Optional specific player to look up (searches both sites).
                     If omitted, returns top waiver adds from the latest article.
        position_filter: Filter results to a position: "C", "LW", "RW", "D", or "G"
        top_n: Max players to return when no specific name is given (default 10)

    Returns a dict with source info, scraped timestamp, and a list of player entries
    each containing: name, position, team, advice, action, source_url, published_date.
    """
    session = get_scrape_session()
    scraped_at = datetime.now(timezone.utc).isoformat()
    players: list[dict] = []
    errors: list[str] = []

    if player_name:
        # Specific player lookup — search both sources
        dobber_entry = _scrape_dobber_player(session, player_name)
        if dobber_entry:
            players.append(dobber_entry)
        else:
            errors.append("No DobberHockey mention found for this player")

        dfo_entries = _scrape_dailyfaceoff_player(session, player_name)
        players.extend(dfo_entries)
        if not dfo_entries:
            errors.append("No DailyFaceoff mention found for this player")

        source = "combined" if len(players) > 1 else ("dobberhockey" if players else "none")
    else:
        # General top-adds scrape from DobberHockey
        dobber_players = _scrape_dobber_latest(session, position_filter, top_n)
        # Separate actual error dicts from player dicts
        for entry in dobber_players:
            if "error" in entry:
                errors.append(entry["error"])
            else:
                players.append(entry)
        source = "dobberhockey"

    result: dict[str, Any] = {
        "source": source,
        "scraped_at": scraped_at,
        "players": players,
    }

    if errors and not players:
        result["error"] = "; ".join(errors) + " — sites may be temporarily unavailable"
    elif errors:
        result["warnings"] = errors

    return result

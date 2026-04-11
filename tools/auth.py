"""MCP tools: authenticate / confirm_authentication — Yahoo OAuth via MCP client."""

import secrets

from auth.oauth_provider import BASE_URL as _BASE_URL
from auth.pending import create, get_result


async def authenticate() -> str:
    """
    Start Yahoo Fantasy authentication.

    Generates a one-time login URL for the user to visit in their browser.
    After completing the Yahoo login, call confirm_authentication with the
    returned nonce to retrieve your API key.
    """
    nonce = secrets.token_urlsafe(16)
    create(nonce)
    auth_url = f"{_BASE_URL}/auth/login?nonce={nonce}"
    return (
        f"Please open the following URL in your browser to connect your Yahoo account:\n\n"
        f"  {auth_url}\n\n"
        f"Complete the Yahoo login, then come back and call `confirm_authentication` "
        f"with nonce=`{nonce}`."
    )


async def confirm_authentication(nonce: str) -> str:
    """
    Complete authentication after visiting the Yahoo login URL from authenticate().

    Args:
        nonce: The nonce string returned by `authenticate`.

    Returns your API key and the MCP URL to add to your client config.
    """
    user = get_result(nonce)
    if user is None:
        return (
            "Authentication is not yet complete for this nonce. "
            "Finish the Yahoo login in your browser, then call this tool again. "
            "If the link has expired, call `authenticate` to get a fresh one."
        )

    mcp_url = f"{_BASE_URL}/mcp?token={user['api_key']}"

    league_note = ""
    if not user.get("league_id"):
        league_note = (
            f"\n\nYou haven't selected a league yet. "
            f"Visit {_BASE_URL}/auth/setup to pick your NHL fantasy league, "
            f"or ask me to set it for you once you have the league ID."
        )

    return (
        f"Authentication successful! Welcome, {user['yahoo_guid']}.\n\n"
        f"Your MCP URL (add this to your client config):\n"
        f"  {mcp_url}\n\n"
        f"Your API key: {user['api_key']}"
        + league_note
    )

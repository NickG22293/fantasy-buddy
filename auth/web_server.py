"""
Yahoo OAuth2 route handlers — multi-user auth flow for the HockeyBot web server.

Flow:
  /auth/login      → redirect to Yahoo consent screen
  /auth/callback   → exchange code for tokens, create/update user in DB
  /auth/setup      → user picks their Yahoo NHL league
  /auth/success    → show API key + MCP client config snippet
"""

import asyncio
import base64
import os
import time

import yahoo_fantasy_api as yfa
from rauth import OAuth2Service
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from auth.db import get_user_by_id, update_user_league, upsert_user
from auth.yahoo_session import YahooSession

YAHOO_AUTHORIZE_URL = "https://api.login.yahoo.com/oauth2/request_auth"
YAHOO_ACCESS_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"

_PORT = int(os.environ.get("AUTH_SERVER_PORT", 8000))
_CERT_FILE = os.path.join(os.path.dirname(__file__), "localhost.crt")
_KEY_FILE = os.path.join(os.path.dirname(__file__), "localhost.key")
USE_SSL = os.path.exists(_CERT_FILE) and os.path.exists(_KEY_FILE)
_SCHEME = "https" if USE_SSL else "http"
CALLBACK_URL = f"{_SCHEME}://localhost:{_PORT}/auth/callback"


def _oauth_service() -> OAuth2Service:
    client_id = os.environ.get("YAHOO_CLIENT_ID", "")
    client_secret = os.environ.get("YAHOO_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise RuntimeError("YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET must be set in .env")
    return OAuth2Service(
        client_id=client_id,
        client_secret=client_secret,
        name="yahoo",
        authorize_url=YAHOO_AUTHORIZE_URL,
        access_token_url=YAHOO_ACCESS_TOKEN_URL,
    )


# ── Route handlers ────────────────────────────────────────────────────────────

async def homepage(request: Request) -> HTMLResponse:
    user_id = request.session.get("user_id")
    user = get_user_by_id(user_id) if user_id else None

    if user:
        body = f"""
        <div class="status authenticated"><span class="dot"></span>Connected as {user['yahoo_guid']}</div>
        {"<p>League: <strong>" + user['league_id'] + "</strong></p>" if user.get('league_id') else '<p><a href="/auth/setup">Pick your league →</a></p>'}
        <p><a href="/auth/success">View API key & MCP config</a></p>
        """
    else:
        body = """
        <div class="status unauthenticated"><span class="dot"></span>Not connected</div>
        <p><a href="/auth/login" class="btn">Connect Yahoo Account</a></p>
        """

    return HTMLResponse(_page("HockeyBot", body))


async def login(request: Request) -> RedirectResponse:
    import secrets
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    auth_url = _oauth_service().get_authorize_url(
        redirect_uri=CALLBACK_URL,
        response_type="code",
        state=state,
        scope="fspt-r openid",
    )
    return RedirectResponse(auth_url, status_code=302)


async def callback(request: Request) -> HTMLResponse | RedirectResponse:
    error = request.query_params.get("error")
    if error:
        return _error_page(f"Yahoo returned an error: {error}")

    returned_state = request.query_params.get("state")
    expected_state = request.session.pop("oauth_state", None)
    if returned_state != expected_state:
        return _error_page("State mismatch — possible CSRF. Please try again.")

    code = request.query_params.get("code")
    if not code:
        return _error_page("No authorization code returned by Yahoo.")

    client_id = os.environ.get("YAHOO_CLIENT_ID", "")
    client_secret = os.environ.get("YAHOO_CLIENT_SECRET", "")
    encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    try:
        raw = _oauth_service().get_raw_access_token(
            data={"code": code, "redirect_uri": CALLBACK_URL, "grant_type": "authorization_code"},
            headers=headers,
        )
        token_data = raw.json()
    except Exception as e:
        return _error_page(f"Token exchange failed: {e}")

    if "access_token" not in token_data:
        return _error_page(f"Unexpected token response: {token_data}")

    yahoo_guid = token_data.get("xoauth_yahoo_guid") or token_data.get("yahoo_guid")
    if not yahoo_guid:
        # Fall back to Fantasy API — returns current user's GUID with fspt-r scope
        try:
            import requests as _requests
            resp = _requests.get(
                "https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1",
                headers={"Authorization": f"Bearer {token_data['access_token']}"},
                params={"format": "json"},
                timeout=10,
            )
            resp.raise_for_status()
            yahoo_guid = resp.json()["fantasy_content"]["users"]["0"]["user"][0]["guid"]
        except Exception as e:
            return _error_page(f"Could not determine Yahoo user GUID: {e}")

    user = upsert_user(
        yahoo_guid=yahoo_guid,
        access_token=token_data["access_token"],
        refresh_token=token_data["refresh_token"],
        token_time=time.time(),
    )
    request.session["user_id"] = user["id"]

    return RedirectResponse("/auth/setup", status_code=302)


async def setup_page(request: Request) -> HTMLResponse | RedirectResponse:
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/auth/login", status_code=302)

    user = get_user_by_id(user_id)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    if request.method == "POST":
        form = await request.form()
        raw = form.get("league_id", "")
        league_id = str(raw).strip()
        if league_id:
            update_user_league(user_id, league_id)
        return RedirectResponse("/auth/success", status_code=302)

    # GET — fetch the user's available NHL leagues
    try:
        leagues = await asyncio.to_thread(_fetch_yahoo_leagues, user)
    except Exception as e:
        leagues = []
        error_note = f'<p class="error">Could not fetch leagues: {e}</p>'
    else:
        error_note = ""

    if leagues:
        options = "\n".join(
            f'<label><input type="radio" name="league_id" value="{lg["id"]}" '
            f'{"checked" if user.get("league_id") == lg["id"] else ""}> '
            f'{lg["name"]} <small>({lg["id"]})</small></label><br>'
            for lg in leagues
        )
        form_body = f"""
        <form method="post">
          <fieldset>
            <legend>Your NHL fantasy leagues</legend>
            {options}
          </fieldset>
          <br>
          <button type="submit" class="btn">Save &amp; continue</button>
        </form>
        """
    else:
        form_body = f"""
        {error_note}
        <p>No NHL leagues found, or unable to fetch them. Enter your league ID manually:</p>
        <form method="post">
          <input name="league_id" placeholder="e.g. 465.l.26058" style="padding:0.4rem;width:16rem;">
          <button type="submit" class="btn" style="margin-left:0.5rem;">Save</button>
        </form>
        """

    return HTMLResponse(_page("Pick your league", f"<h2>Pick your league</h2>{form_body}"))


async def success(request: Request) -> HTMLResponse | RedirectResponse:
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/auth/login", status_code=302)

    user = get_user_by_id(user_id)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    mcp_url = f"{_SCHEME}://localhost:{_PORT}/mcp?token={user['api_key']}"
    config_json = (
        '{\n'
        '  "mcpServers": {\n'
        '    "hockeybot": {\n'
        '      "type": "http",\n'
        f'      "url": "{mcp_url}"\n'
        '    }\n'
        '  }\n'
        '}'
    )

    body = f"""
    <h2>You're all set!</h2>
    <p>Add this to your Claude Desktop <code>claude_desktop_config.json</code>:</p>
    <pre>{config_json}</pre>
    <p><strong>Your API key:</strong> <code>{user['api_key']}</code></p>
    <p style="color:#64748b;font-size:0.875rem;">Keep this key private — it grants access to your fantasy data.</p>
    <p><a href="/">← Back</a></p>
    """
    return HTMLResponse(_page("Setup complete", body))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fetch_yahoo_leagues(user: dict) -> list[dict]:
    """Synchronous — call via asyncio.to_thread. Returns list of {id, name}."""
    sc = YahooSession(user)
    gm = yfa.Game(sc, "nhl")
    ids = gm.league_ids(year=2025)
    leagues = []
    for lid in ids:
        try:
            lg = gm.to_league(lid)
            name = lg.settings().get("name", lid)
        except Exception:
            name = lid
        leagues.append({"id": lid, "name": name})
    return leagues


def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>HockeyBot — {title}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 560px; margin: 60px auto; padding: 0 1rem; color: #1e293b; }}
    h1 {{ font-size: 1.4rem; margin-bottom: 0.2rem; }}
    h2 {{ font-size: 1.1rem; }}
    .subtitle {{ color: #64748b; margin-bottom: 2rem; font-size: 0.9rem; }}
    .status {{ display: flex; align-items: center; gap: 0.5rem; font-weight: 600; margin-bottom: 1.5rem; }}
    .status.authenticated {{ color: #22c55e; }}
    .status.unauthenticated {{ color: #f59e0b; }}
    .dot {{ width: 9px; height: 9px; border-radius: 50%; background: currentColor; flex-shrink: 0; }}
    .btn {{ display: inline-block; background: #6366f1; color: #fff; padding: 0.5rem 1.2rem; border-radius: 6px; text-decoration: none; font-weight: 600; border: none; cursor: pointer; font-size: 1rem; }}
    .btn:hover {{ background: #4f46e5; }}
    pre {{ background: #f1f5f9; padding: 1rem; border-radius: 6px; overflow-x: auto; font-size: 0.82rem; }}
    code {{ background: #f1f5f9; padding: 0.1rem 0.3rem; border-radius: 3px; font-size: 0.9em; }}
    .error {{ color: #ef4444; }}
    fieldset {{ border: 1px solid #e2e8f0; border-radius: 6px; padding: 1rem; }}
    fieldset label {{ display: block; margin-bottom: 0.5rem; }}
  </style>
</head>
<body>
  <h1>HockeyBot</h1>
  <p class="subtitle">Fantasy hockey MCP server</p>
  {body}
</body>
</html>"""


def _error_page(message: str) -> HTMLResponse:
    body = f"""
    <h2>Authorization failed</h2>
    <p class="error">{message}</p>
    <p><a href="/auth/login">Try again</a> · <a href="/">Home</a></p>
    """
    return HTMLResponse(_page("Error", body), status_code=400)
"""HockeyBot MCP Server — fantasy hockey advisor via NHL API, scraping, and Yahoo/ESPN."""

import os
import secrets

import uvicorn
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.http import create_streamable_http_app
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Route

load_dotenv()

from auth.db import init_db
from auth.oauth_provider import BASE_URL, USE_SSL, _CERT_FILE, _KEY_FILE, _PORT, HockeyBotOAuthProvider
import auth.oauth_provider as _op
from auth.web_server import (
    callback,
    homepage,
    login,
    setup_page,
    success,
)
from tools.auth import authenticate, confirm_authentication
from tools.league import get_league_context
from tools.stats import get_player_stats
from tools.trade import evaluate_trade_target
from tools.waiver import get_waiver_advice

# ── Auth provider ─────────────────────────────────────────────────────────────

auth_provider = HockeyBotOAuthProvider(base_url=BASE_URL)
_op.provider = auth_provider  # expose to web_server.py callback handler

# ── MCP server ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="HockeyBot",
    auth=auth_provider,
    instructions="""
You are a fantasy hockey assistant. Use these tools together to answer questions
about waiver pickups, trades, and roster moves:

Authentication (required before using league tools):
  1. authenticate          — generate a Yahoo login URL for the user to visit
  2. confirm_authentication — retrieve the API key after the user completes login

If any tool returns "Not authenticated", call authenticate first, guide the user
through the browser login, then call confirm_authentication with the nonce.

Fantasy tools (require authentication):
  3. get_league_context    — understand the user's current roster and available free agents
  4. get_player_stats      — retrieve NHL performance metrics (goals, assists, TOI, trends)
  5. get_waiver_advice     — rank available free agents by z-score and suggest add/drop moves
  6. evaluate_trade_target — analyze an opponent's roster for trade opportunities using
                             per-position z-score totals to find mutual weaknesses

Workflow for waiver/pickup questions:
  a) Call get_waiver_advice with the relevant position — it fetches league context and
     NHL stats internally and returns ranked add candidates and suggested drops.
  b) Call get_player_stats for deeper analysis on any specific player of interest.
  c) Synthesize into a concrete recommendation with clear statistical reasoning.

Workflow for trade questions:
  a) Call evaluate_trade_target with the opponent's team name — it returns z-score
     summaries per position (C/LW/RW/D/G) for both teams and identifies mutual
     weaknesses to anchor trade negotiations.
  b) Call get_player_stats on specific players to validate or deepen the analysis.
  c) Propose trades where you offer strength at their weak positions in exchange for
     their strength at your weak positions.

Always be objective and data-driven. Cite specific stats and sources in your reasoning.
""",
)

mcp.add_tool(authenticate)
mcp.add_tool(confirm_authentication)
mcp.add_tool(get_player_stats)
mcp.add_tool(get_waiver_advice)
mcp.add_tool(evaluate_trade_target)
mcp.add_tool(get_league_context)

# ── Combined ASGI app ─────────────────────────────────────────────────────────
# create_streamable_http_app is used directly so we can inject our web UI routes
# alongside the OAuth routes that FastMCP generates from auth_provider.get_routes().
# The well-known endpoints (/.well-known/oauth-authorization-server etc.) are added
# by FastMCP at the app root level, not under /mcp, satisfying RFC 8414 / RFC 9728.

SESSION_SECRET = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)


def _init_db_on_startup():
    init_db()


app = create_streamable_http_app(
    server=mcp,
    streamable_http_path="/mcp",
    auth=auth_provider,
    routes=[
        Route("/", homepage),
        Route("/auth/login", login),
        Route("/auth/callback", callback),
        Route("/auth/setup", setup_page, methods=["GET", "POST"]),
        Route("/auth/success", success),
    ],
    middleware=[
        Middleware(SessionMiddleware, secret_key=SESSION_SECRET),
    ],
)

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    scheme = "https" if USE_SSL else "http"
    print(f"HockeyBot running at {BASE_URL}")
    if not USE_SSL:
        print("  No SSL certs found — run: bash auth/gen_cert.sh")
    print(f"  Auth UI:    {BASE_URL}/")
    print(f"  MCP path:   {BASE_URL}/mcp")

    ssl_kwargs = {"ssl_certfile": _CERT_FILE, "ssl_keyfile": _KEY_FILE} if USE_SSL else {}
    uvicorn.run(app, host="0.0.0.0", port=_PORT, **ssl_kwargs)

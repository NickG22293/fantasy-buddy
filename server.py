"""HockeyBot MCP Server — fantasy hockey advisor via NHL API, scraping, and Yahoo/ESPN."""

import os
import secrets
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Mount, Route

from auth.db import init_db
from auth.middleware import APIKeyMiddleware
from auth.web_server import (
    USE_SSL,
    _CERT_FILE,
    _KEY_FILE,
    _PORT,
    callback,
    homepage,
    login,
    setup_page,
    success,
)
from tools.league import get_league_context
from tools.stats import get_player_stats
from tools.trade import evaluate_trade_target
from tools.waiver import get_waiver_advice

load_dotenv()

# ── MCP server ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="HockeyBot",
    instructions="""
You are a fantasy hockey assistant. Use these tools together to answer questions
about waiver pickups, trades, and roster moves:

1. get_league_context    — understand the user's current roster and available free agents
2. get_player_stats      — retrieve NHL performance metrics (goals, assists, TOI, trends)
3. get_waiver_advice     — rank available free agents by z-score and suggest add/drop moves
4. evaluate_trade_target — analyze an opponent's roster for trade opportunities using
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

mcp.add_tool(get_player_stats)
mcp.add_tool(get_waiver_advice)
mcp.add_tool(evaluate_trade_target)
mcp.add_tool(get_league_context)

# ── Combined ASGI app ─────────────────────────────────────────────────────────

SESSION_SECRET = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)

mcp_asgi = APIKeyMiddleware(mcp.http_app(path="/"))


@asynccontextmanager
async def lifespan(app: Starlette):
    init_db()
    yield


app = Starlette(
    routes=[
        Route("/", homepage),
        Route("/auth/login", login),
        Route("/auth/callback", callback),
        Route("/auth/setup", setup_page, methods=["GET", "POST"]),
        Route("/auth/success", success),
        Mount("/mcp", app=mcp_asgi),
    ],
    middleware=[
        Middleware(SessionMiddleware, secret_key=SESSION_SECRET),
    ],
    lifespan=lifespan,
)

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    scheme = "https" if USE_SSL else "http"
    print(f"HockeyBot running at {scheme}://localhost:{_PORT}")
    if not USE_SSL:
        print("  No SSL certs found — run: bash auth/gen_cert.sh")
    print(f"  Auth UI:    {scheme}://localhost:{_PORT}/")
    print(f"  MCP path:   {scheme}://localhost:{_PORT}/mcp?token=<api_key>")

    ssl_kwargs = {"ssl_certfile": _CERT_FILE, "ssl_keyfile": _KEY_FILE} if USE_SSL else {}
    uvicorn.run(app, host="0.0.0.0", port=_PORT, **ssl_kwargs)

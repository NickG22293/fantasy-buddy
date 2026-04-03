"""HockeyBot MCP Server — fantasy hockey advisor via NHL API, scraping, and Yahoo/ESPN."""

from fastmcp import FastMCP

from tools.league import get_league_context
from tools.stats import get_player_stats
from tools.waiver import get_waiver_advice

mcp = FastMCP(
    name="HockeyBot",
    instructions="""
You are a fantasy hockey assistant. Use these three tools together to answer questions
about waiver pickups, trades, and roster moves:

1. get_league_context  — understand the user's current roster and available free agents
2. get_player_stats    — retrieve NHL performance metrics (goals, assists, TOI, trends)
3. get_waiver_advice   — get expert waiver wire sentiment from DobberHockey and DailyFaceoff

Workflow for waiver/pickup questions:
  a) Call get_league_context to see if the player is available and if there's a roster slot
  b) Call get_player_stats for objective NHL stats and recent game trends
  c) Call get_waiver_advice for expert sentiment
  d) Synthesize all three into a concrete recommendation with clear reasoning

Always be objective and data-driven. Cite specific stats and sources in your reasoning.
""",
)

mcp.add_tool(get_player_stats)
mcp.add_tool(get_waiver_advice)
mcp.add_tool(get_league_context)

if __name__ == "__main__":
    mcp.run(transport="stdio")

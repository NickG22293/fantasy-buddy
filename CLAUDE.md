# HockeyBot MCP Project

MCP server that will provide guidance on fantasy hockey roster moves and trades by interacting with the NHL and Yahoo fantasy APIs. 

## 🛠 Tech Stack
- **Runtime:** Python 3.12 (Primary), Go 1.22 (Logic/Performance)
- **Package Manager:** `uv` (use `uvx` for ephemeral execution)
- **Framework:** FastMCP (Python SDK)
- **APIs:** Yahoo Fantasy (OAuth 2.0), ESPN (Cookie-based), NHL Official API
- **Scraping:** BeautifulSoup4, Requests

## 🏗 Architecture
- **Server:** MCP Server running locally via `stdio`.
- **Tools:**
  - `get_waiver_advice`: Scrapes DobberHockey/DailyFaceoff.
  - `get_player_stats`: Queries NHL API for performance metrics.
  - `get_league_context`: Interacts with Yahoo/ESPN for roster data.
- **Client:** Claude Desktop (Dev/Debug) or Local Web UI (Production).

## 🚀 Common Commands
- **Install Deps:** `uv pip install -r requirements.txt`
- **Run Server:** `uv run python server.py`
- **Inspect/Debug:** `mcp inspector python server.py`
- **Lint/Typecheck:** `ruff check .` | `go vet ./...`
- **Test:** `pytest` | `go test ./...`

## 📏 Standards & Constraints
- **Coding Style:** Prefer Type Hints in Python; idiomatic procedural Go.
- **Errors:** All tool calls must return descriptive error strings, not silent failures.
- **Scraping:** Implement 1s rate-limiting between site requests to remain "polite."
- **Secrets:** NEVER hardcode tokens. Use `.env` (gitignored).
- **Logic:** Favor "Soft SF" world-building terminology in creative prompts, but stay strictly objective/data-driven for hockey analysis.
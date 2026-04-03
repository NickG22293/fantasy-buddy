"""
One-time interactive script to authorize HockeyBot with your Yahoo Fantasy account.

Usage:
  1. Create a Yahoo Developer app at https://developer.yahoo.com/apps/create/
     - App type: Installed Application
     - API permissions: Fantasy Sports (read)
  2. Add YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET to your .env file
  3. Run: uv run python auth/setup_yahoo.py
  4. A browser will open for authorization. After approving, tokens are saved to oauth2.json.

The MCP server reads oauth2.json automatically via YAHOO_OAUTH_CREDS_FILE in .env.
"""

import json
import os

from dotenv import load_dotenv
from yahoo_oauth import OAuth2

load_dotenv()

CLIENT_ID = os.environ.get("YAHOO_CLIENT_ID")
CLIENT_SECRET = os.environ.get("YAHOO_CLIENT_SECRET")
CREDS_FILE = os.environ.get("YAHOO_OAUTH_CREDS_FILE", "oauth2.json")

if not CLIENT_ID or not CLIENT_SECRET:
    raise SystemExit(
        "YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET must be set in .env before running this script."
    )

# Write a minimal credentials seed file for yahoo_oauth to pick up
seed = {
    "consumer_key": CLIENT_ID,
    "consumer_secret": CLIENT_SECRET,
}

with open(CREDS_FILE, "w") as f:
    json.dump(seed, f)

print(f"Credentials seed written to {CREDS_FILE}")
print("Starting OAuth2 flow — a browser window will open for authorization...")

sc = OAuth2(None, None, from_file=CREDS_FILE)

print(f"\nAuthorization complete! Tokens saved to {CREDS_FILE}")
print("You can now run: uv run python server.py")

"""Yahoo OAuth2 session — per-user, backed by the database rather than a file."""

import base64
import os
import time

from rauth import OAuth2Service

YAHOO_AUTHORIZE_URL = "https://api.login.yahoo.com/oauth2/request_auth"
YAHOO_ACCESS_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"


class YahooSession:
    """
    Thin session wrapper that satisfies the interface expected by yahoo_fantasy_api:
      - .session     — rauth OAuth2Session for making authenticated HTTP requests
      - .oauth       — rauth OAuth2Service (used by YHandler to rebuild session on refresh)
      - .access_token — settable; updated on refresh
      - .refresh_access_token() — exchanges refresh token for a new access token,
                                   persists updated tokens to the DB, returns
                                   {'access_token': ...} as yahoo_fantasy_api expects

    Token refresh also writes back to the DB so the user stays authenticated across
    MCP server restarts.
    """

    def __init__(self, user: dict) -> None:
        self._user_id: int = user["id"]
        self.access_token: str = user["access_token"]
        self._refresh_token: str = user["refresh_token"]
        self._token_time: float = user["token_time"]

        client_id = os.environ.get("YAHOO_CLIENT_ID", "")
        client_secret = os.environ.get("YAHOO_CLIENT_SECRET", "")

        self.oauth = OAuth2Service(
            client_id=client_id,
            client_secret=client_secret,
            name="yahoo",
            authorize_url=YAHOO_AUTHORIZE_URL,
            access_token_url=YAHOO_ACCESS_TOKEN_URL,
        )

        if not self._token_is_valid():
            self.refresh_access_token()

        self.session = self.oauth.get_session(token=self.access_token)

    def _token_is_valid(self) -> bool:
        return (time.time() - self._token_time) < 3540  # 1 min before expiry

    def refresh_access_token(self) -> dict:
        client_id = os.environ.get("YAHOO_CLIENT_ID", "")
        client_secret = os.environ.get("YAHOO_CLIENT_SECRET", "")
        encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        raw = self.oauth.get_raw_access_token(
            data={
                "refresh_token": self._refresh_token,
                "redirect_uri": "oob",
                "grant_type": "refresh_token",
            },
            headers=headers,
        )
        token_data = raw.json()
        if "access_token" not in token_data:
            raise RuntimeError(f"Token refresh failed: {token_data}")

        self.access_token = token_data["access_token"]
        self._refresh_token = token_data.get("refresh_token", self._refresh_token)
        self._token_time = time.time()

        # Persist updated tokens so the user stays logged in across restarts
        from auth.db import update_user_tokens
        update_user_tokens(self._user_id, self.access_token, self._refresh_token, self._token_time)

        # YHandler expects this return shape
        return {"access_token": self.access_token}

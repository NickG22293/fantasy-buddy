"""HockeyBot OAuth 2.1 Authorization Server provider for FastMCP.

Wraps Yahoo OAuth as the identity backend:
  MCP SDK → /authorize → Yahoo OAuth → /auth/callback → SDK redirect_uri → /token → API key

In-memory storage is fine: auth codes expire in minutes, and clients re-register
on reconnect. Only API keys (access tokens) are persisted in SQLite.
"""

from __future__ import annotations

import os
import secrets
import time
from typing import TYPE_CHECKING

from fastmcp.server.auth import AccessToken, OAuthProvider
from mcp.server.auth.provider import AuthorizationCode, OAuthToken, RefreshToken
from mcp.shared.auth import OAuthClientInformationFull

from auth.db import get_user_by_api_key, upsert_user

if TYPE_CHECKING:
    from mcp.server.auth.provider import AuthorizationParams

# ── Shared Yahoo OAuth config (imported by web_server.py too) ─────────────────

YAHOO_AUTHORIZE_URL = "https://api.login.yahoo.com/oauth2/request_auth"
YAHOO_ACCESS_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"

_PORT = int(os.environ.get("AUTH_SERVER_PORT", 8000))
_CERT_FILE = os.path.join(os.path.dirname(__file__), "localhost.crt")
_KEY_FILE = os.path.join(os.path.dirname(__file__), "localhost.key")
USE_SSL = os.path.exists(_CERT_FILE) and os.path.exists(_KEY_FILE)
_SCHEME = "https" if USE_SSL else "http"

BASE_URL = os.environ.get("BASE_URL", f"{_SCHEME}://localhost:{_PORT}")
CALLBACK_URL = f"{BASE_URL}/auth/callback"


def yahoo_oauth_service():
    """Build a rauth OAuth2Service from environment credentials."""
    from rauth import OAuth2Service

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


# ── Extended models ────────────────────────────────────────────────────────────

class HockeyBotAuthCode(AuthorizationCode):
    """AuthorizationCode extended with our user_id."""
    user_id: int


# ── Provider ──────────────────────────────────────────────────────────────────

class HockeyBotOAuthProvider(OAuthProvider):
    """
    OAuth 2.1 Authorization Server that proxies Yahoo for identity.

    Exposes:
      /.well-known/oauth-authorization-server
      /.well-known/oauth-protected-resource/mcp
      /authorize  → redirects to Yahoo OAuth
      /token      → exchanges code for HockeyBot API key
      /register   → dynamic client registration
    """

    def __init__(self, base_url: str):
        from mcp.server.auth.settings import ClientRegistrationOptions
        super().__init__(
            base_url=base_url,
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=["hockeybot"],
                default_scopes=["hockeybot"],
            ),
        )
        # In-memory stores (ephemeral across restarts, intentionally)
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._auth_codes: dict[str, HockeyBotAuthCode] = {}
        # Pending MCP OAuth flows: mcp_nonce → {client, params, csrf}
        self._pending_mcp: dict[str, dict] = {}

    # ── Client registration ───────────────────────────────────────────────────

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._clients[client_info.client_id] = client_info

    # ── Authorization flow ────────────────────────────────────────────────────

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Start the Yahoo OAuth flow, embedding an MCP nonce in the state."""
        csrf = secrets.token_urlsafe(16)
        mcp_nonce = secrets.token_urlsafe(16)
        # State format: "{csrf}|mcp:{mcp_nonce}"
        yahoo_state = f"{csrf}|mcp:{mcp_nonce}"

        self._pending_mcp[mcp_nonce] = {
            "client": client,
            "params": params,
            "csrf": csrf,
        }

        return yahoo_oauth_service().get_authorize_url(
            redirect_uri=CALLBACK_URL,
            response_type="code",
            state=yahoo_state,
            scope="fspt-r openid",
        )

    # ── Code / token lifecycle ─────────────────────────────────────────────────

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> HockeyBotAuthCode | None:
        code = self._auth_codes.get(authorization_code)
        if code and code.client_id == client.client_id:
            return code
        return None

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: HockeyBotAuthCode,
    ) -> OAuthToken:
        """Exchange a short-lived code for the user's permanent API key."""
        self._auth_codes.pop(authorization_code.code, None)
        from auth.db import get_user_by_id
        user = get_user_by_id(authorization_code.user_id)
        if not user:
            from mcp.server.auth.provider import TokenError
            raise TokenError("invalid_grant", "User not found")
        return OAuthToken(
            access_token=user["api_key"],
            token_type="bearer",
            scope="hockeybot",
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        """Validate a bearer token (our API key) against the database."""
        user = get_user_by_api_key(token)
        if not user:
            return None
        return AccessToken(
            token=token,
            client_id=str(user["id"]),
            scopes=["hockeybot"],
            expires_at=None,
            claims={"user_id": user["id"]},
        )

    # ── Unused (no refresh token support) ─────────────────────────────────────

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        from mcp.server.auth.provider import TokenError
        raise TokenError("unsupported_grant_type", "Refresh tokens not supported")

    # ── Called by web_server.py after Yahoo callback ──────────────────────────

    def complete_mcp_auth(
        self,
        mcp_nonce: str,
        yahoo_code: str,
        yahoo_state: str,
    ) -> str | None:
        """
        Called from /auth/callback when the state contains an MCP nonce.
        Exchanges the Yahoo code, upserts the user, stores an auth code, and
        returns the redirect URL to send the browser to (MCP SDK's redirect_uri).
        Returns None if the nonce is unknown (stale or replayed).
        """
        import base64
        import time

        import requests as _requests

        pending = self._pending_mcp.pop(mcp_nonce, None)
        if not pending:
            return None

        client: OAuthClientInformationFull = pending["client"]
        params: AuthorizationParams = pending["params"]

        # Exchange Yahoo code for tokens
        client_id = os.environ.get("YAHOO_CLIENT_ID", "")
        client_secret = os.environ.get("YAHOO_CLIENT_SECRET", "")
        encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        raw = yahoo_oauth_service().get_raw_access_token(
            data={
                "code": yahoo_code,
                "redirect_uri": CALLBACK_URL,
                "grant_type": "authorization_code",
            },
            headers={
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        token_data = raw.json()

        if "access_token" not in token_data:
            return None

        yahoo_guid = token_data.get("xoauth_yahoo_guid") or token_data.get("yahoo_guid")
        if not yahoo_guid:
            try:
                resp = _requests.get(
                    "https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1",
                    headers={"Authorization": f"Bearer {token_data['access_token']}"},
                    params={"format": "json"},
                    timeout=10,
                )
                resp.raise_for_status()
                yahoo_guid = resp.json()["fantasy_content"]["users"]["0"]["user"][0]["guid"]
            except Exception:
                return None

        user = upsert_user(
            yahoo_guid=yahoo_guid,
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            token_time=time.time(),
        )

        # Generate a short-lived OAuth authorization code
        code = secrets.token_urlsafe(32)
        redirect_uri = params.redirect_uri
        self._auth_codes[code] = HockeyBotAuthCode(
            code=code,
            scopes=list(params.scopes or ["hockeybot"]),
            expires_at=time.time() + 300,
            client_id=client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            user_id=user["id"],
        )

        # Build redirect URL back to the MCP SDK
        sep = "&" if "?" in str(redirect_uri) else "?"
        redirect_url = f"{redirect_uri}{sep}code={code}"
        if params.state:
            redirect_url += f"&state={params.state}"
        return redirect_url


# Module-level singleton — set once in server.py, read by web_server.py
provider: HockeyBotOAuthProvider | None = None

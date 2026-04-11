"""Unit tests for auth/oauth_provider.py — HockeyBotOAuthProvider."""

from unittest.mock import MagicMock, patch

import pytest
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from auth.oauth_provider import HockeyBotOAuthProvider


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_provider() -> HockeyBotOAuthProvider:
    return HockeyBotOAuthProvider(base_url="https://localhost:8000")


def make_client(client_id: str = "test-client") -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        redirect_uris=["http://localhost:54321/callback"],
    )


def make_params(
    redirect_uri: str = "http://localhost:54321/callback",
    code_challenge: str = "challenge_abc123",
    state: str = "state_xyz",
) -> AuthorizationParams:
    return AuthorizationParams(
        redirect_uri=AnyUrl(redirect_uri),
        redirect_uri_provided_explicitly=True,
        code_challenge=code_challenge,
        state=state,
        scopes=["hockeybot"],
    )


FAKE_USER = {
    "id": 42,
    "yahoo_guid": "FAKEGUID",
    "api_key": "test-api-key-abc",
    "league_id": "465.l.12345",
    "access_token": "yahoo_at",
    "refresh_token": "yahoo_rt",
    "token_time": 0.0,
    "created_at": 0.0,
}


# ── Client registration ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_and_get_client():
    p = make_provider()
    client = make_client("my-client")
    await p.register_client(client)
    loaded = await p.get_client("my-client")
    assert loaded is client


@pytest.mark.asyncio
async def test_get_unknown_client_returns_none():
    p = make_provider()
    assert await p.get_client("nonexistent") is None


# ── authorize → pending_mcp populated ────────────────────────────────────────

@pytest.mark.asyncio
async def test_authorize_returns_yahoo_url_and_stores_pending():
    p = make_provider()
    client = make_client()
    params = make_params()

    mock_service = MagicMock()
    mock_service.get_authorize_url.return_value = "https://api.login.yahoo.com/oauth2/request_auth?state=TEST"

    with patch("auth.oauth_provider.yahoo_oauth_service", return_value=mock_service):
        url = await p.authorize(client, params)

    assert "yahoo.com" in url or url == "https://api.login.yahoo.com/oauth2/request_auth?state=TEST"
    assert len(p._pending_mcp) == 1
    nonce = next(iter(p._pending_mcp))
    entry = p._pending_mcp[nonce]
    assert entry["client"] is client
    assert entry["params"] is params


@pytest.mark.asyncio
async def test_authorize_embeds_mcp_prefix_in_state():
    p = make_provider()
    captured_kwargs = {}

    mock_service = MagicMock()
    def fake_get_authorize_url(**kwargs):
        captured_kwargs.update(kwargs)
        return "https://yahoo.example/auth"
    mock_service.get_authorize_url.side_effect = fake_get_authorize_url

    with patch("auth.oauth_provider.yahoo_oauth_service", return_value=mock_service):
        await p.authorize(make_client(), make_params())

    state = captured_kwargs["state"]
    assert "|mcp:" in state


# ── load / exchange authorization code ───────────────────────────────────────

@pytest.mark.asyncio
async def test_load_authorization_code_found():
    from auth.oauth_provider import HockeyBotAuthCode
    import time

    p = make_provider()
    client = make_client()
    code_obj = HockeyBotAuthCode(
        code="mycode",
        scopes=["hockeybot"],
        expires_at=time.time() + 300,
        client_id=client.client_id,
        code_challenge="challenge",
        redirect_uri=AnyUrl("http://localhost:54321/callback"),
        redirect_uri_provided_explicitly=True,
        user_id=42,
    )
    p._auth_codes["mycode"] = code_obj

    loaded = await p.load_authorization_code(client, "mycode")
    assert loaded is code_obj


@pytest.mark.asyncio
async def test_load_authorization_code_wrong_client():
    from auth.oauth_provider import HockeyBotAuthCode
    import time

    p = make_provider()
    code_obj = HockeyBotAuthCode(
        code="mycode",
        scopes=[],
        expires_at=time.time() + 300,
        client_id="other-client",
        code_challenge="ch",
        redirect_uri=AnyUrl("http://localhost:54321/callback"),
        redirect_uri_provided_explicitly=True,
        user_id=1,
    )
    p._auth_codes["mycode"] = code_obj

    loaded = await p.load_authorization_code(make_client("my-client"), "mycode")
    assert loaded is None


@pytest.mark.asyncio
async def test_exchange_authorization_code_returns_api_key():
    from auth.oauth_provider import HockeyBotAuthCode
    import time

    p = make_provider()
    client = make_client()
    code_obj = HockeyBotAuthCode(
        code="mycode",
        scopes=["hockeybot"],
        expires_at=time.time() + 300,
        client_id=client.client_id,
        code_challenge="challenge",
        redirect_uri=AnyUrl("http://localhost:54321/callback"),
        redirect_uri_provided_explicitly=True,
        user_id=42,
    )
    p._auth_codes["mycode"] = code_obj

    with patch("auth.db.get_user_by_id", return_value=FAKE_USER):
        token = await p.exchange_authorization_code(client, code_obj)

    assert token.access_token == FAKE_USER["api_key"]
    assert "mycode" not in p._auth_codes  # consumed


@pytest.mark.asyncio
async def test_exchange_authorization_code_user_not_found():
    from auth.oauth_provider import HockeyBotAuthCode
    from mcp.server.auth.provider import TokenError
    import time

    p = make_provider()
    client = make_client()
    code_obj = HockeyBotAuthCode(
        code="x",
        scopes=[],
        expires_at=time.time() + 300,
        client_id=client.client_id,
        code_challenge="ch",
        redirect_uri=AnyUrl("http://localhost:54321/callback"),
        redirect_uri_provided_explicitly=True,
        user_id=999,
    )

    with patch("auth.db.get_user_by_id", return_value=None):
        with pytest.raises(TokenError):
            await p.exchange_authorization_code(client, code_obj)


# ── load_access_token ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_load_access_token_valid():
    p = make_provider()
    with patch("auth.oauth_provider.get_user_by_api_key", return_value=FAKE_USER):
        token = await p.load_access_token("test-api-key-abc")
    assert token is not None
    assert token.token == "test-api-key-abc"
    assert token.claims["user_id"] == 42


@pytest.mark.asyncio
async def test_load_access_token_invalid():
    p = make_provider()
    with patch("auth.oauth_provider.get_user_by_api_key", return_value=None):
        token = await p.load_access_token("bad-key")
    assert token is None


# ── complete_mcp_auth ─────────────────────────────────────────────────────────

def test_complete_mcp_auth_unknown_nonce():
    p = make_provider()
    result = p.complete_mcp_auth("unknown-nonce", "yahoo_code", "state")
    assert result is None


def test_complete_mcp_auth_success():
    p = make_provider()
    client = make_client()
    params = make_params(redirect_uri="http://localhost:54321/callback", state="sdk-state")

    p._pending_mcp["testnonce"] = {"client": client, "params": params, "csrf": "csrf123"}

    mock_service = MagicMock()
    mock_raw = MagicMock()
    mock_raw.json.return_value = {
        "access_token": "yahoo_at",
        "refresh_token": "yahoo_rt",
        "xoauth_yahoo_guid": "GUID123",
    }
    mock_service.get_raw_access_token.return_value = mock_raw

    with (
        patch("auth.oauth_provider.yahoo_oauth_service", return_value=mock_service),
        patch("auth.oauth_provider.upsert_user", return_value=FAKE_USER),
    ):
        redirect_url = p.complete_mcp_auth("testnonce", "yahoo_code_123", "state_val")

    assert redirect_url is not None
    assert "http://localhost:54321/callback" in redirect_url
    assert "code=" in redirect_url
    assert "state=sdk-state" in redirect_url
    # nonce consumed
    assert "testnonce" not in p._pending_mcp
    # auth code stored
    assert len(p._auth_codes) == 1


def test_complete_mcp_auth_stores_correct_user_id():
    p = make_provider()
    client = make_client()
    params = make_params()
    p._pending_mcp["n"] = {"client": client, "params": params, "csrf": "x"}

    mock_service = MagicMock()
    mock_raw = MagicMock()
    mock_raw.json.return_value = {
        "access_token": "at",
        "refresh_token": "rt",
        "xoauth_yahoo_guid": "G",
    }
    mock_service.get_raw_access_token.return_value = mock_raw

    with (
        patch("auth.oauth_provider.yahoo_oauth_service", return_value=mock_service),
        patch("auth.oauth_provider.upsert_user", return_value=FAKE_USER),
    ):
        p.complete_mcp_auth("n", "code", "state")

    code_obj = next(iter(p._auth_codes.values()))
    assert code_obj.user_id == FAKE_USER["id"]
    assert code_obj.code_challenge == params.code_challenge


def test_complete_mcp_auth_guid_fallback_to_api():
    """When Yahoo doesn't return a GUID, we fall back to the Fantasy API."""
    p = make_provider()
    client = make_client()
    params = make_params()
    p._pending_mcp["n"] = {"client": client, "params": params, "csrf": "x"}

    mock_service = MagicMock()
    mock_raw = MagicMock()
    # No GUID in token response
    mock_raw.json.return_value = {"access_token": "at", "refresh_token": "rt"}
    mock_service.get_raw_access_token.return_value = mock_raw

    mock_api_resp = MagicMock()
    mock_api_resp.json.return_value = {
        "fantasy_content": {"users": {"0": {"user": [{"guid": "FALLBACK_GUID"}]}}}
    }
    mock_api_resp.raise_for_status = MagicMock()

    with (
        patch("auth.oauth_provider.yahoo_oauth_service", return_value=mock_service),
        patch("requests.get", return_value=mock_api_resp),
        patch("auth.oauth_provider.upsert_user", return_value=FAKE_USER) as mock_upsert,
    ):
        p.complete_mcp_auth("n", "code", "state")

    mock_upsert.assert_called_once()
    _, kwargs = mock_upsert.call_args
    assert kwargs["yahoo_guid"] == "FALLBACK_GUID"


# ── Refresh token (unsupported) ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_load_refresh_token_returns_none():
    p = make_provider()
    assert await p.load_refresh_token(make_client(), "any-token") is None


@pytest.mark.asyncio
async def test_exchange_refresh_token_raises():
    from mcp.server.auth.provider import RefreshToken, TokenError

    p = make_provider()
    rt = RefreshToken(token="t", client_id="c", scopes=[])
    with pytest.raises(TokenError):
        await p.exchange_refresh_token(make_client(), rt, [])

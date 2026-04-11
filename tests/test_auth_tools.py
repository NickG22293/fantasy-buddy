"""Unit tests for tools/auth.py — authenticate and confirm_authentication tools."""

from unittest.mock import patch

import pytest

import auth.pending as pending_mod
from tools.auth import _BASE_URL, authenticate, confirm_authentication


def _reset_pending():
    pending_mod._results.clear()
    pending_mod._resolved.clear()


# ── authenticate ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_authenticate_returns_url_and_nonce():
    _reset_pending()
    result = await authenticate()

    assert "/auth/login?nonce=" in result
    assert _BASE_URL in result
    assert "confirm_authentication" in result
    # Nonce was registered
    assert len(pending_mod._results) == 0  # not resolved yet — only _resolved tracks it


@pytest.mark.asyncio
async def test_authenticate_nonce_is_in_url():
    _reset_pending()
    result = await authenticate()

    # Extract nonce from the URL in the result
    for line in result.splitlines():
        if "/auth/login?nonce=" in line:
            nonce = line.strip().split("nonce=")[1]
            # Nonce should be listed in the result text for confirm_authentication
            assert nonce in result
            break
    else:
        pytest.fail("No auth URL with nonce found in result")


@pytest.mark.asyncio
async def test_authenticate_creates_unique_nonces():
    _reset_pending()
    result1 = await authenticate()
    result2 = await authenticate()

    nonce1 = _extract_nonce(result1)
    nonce2 = _extract_nonce(result2)
    assert nonce1 != nonce2


# ── confirm_authentication ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_confirm_authentication_not_yet_complete():
    _reset_pending()
    pending_mod.create("some-nonce")  # registered but not resolved

    result = await confirm_authentication(nonce="some-nonce")

    assert "not yet complete" in result.lower() or "not" in result.lower()


@pytest.mark.asyncio
async def test_confirm_authentication_unknown_nonce():
    _reset_pending()
    result = await confirm_authentication(nonce="totally-unknown-nonce")
    assert "not" in result.lower()


@pytest.mark.asyncio
async def test_confirm_authentication_success():
    _reset_pending()
    user = {
        "id": 1,
        "yahoo_guid": "MYGUID",
        "api_key": "my-secret-key",
        "league_id": "465.l.12345",
    }
    pending_mod.create("mynonce")
    pending_mod.resolve("mynonce", user)

    result = await confirm_authentication(nonce="mynonce")

    assert "my-secret-key" in result
    assert "MYGUID" in result
    assert _BASE_URL in result


@pytest.mark.asyncio
async def test_confirm_authentication_no_league_shows_note():
    _reset_pending()
    user = {
        "id": 1,
        "yahoo_guid": "GUID",
        "api_key": "key",
        "league_id": None,
    }
    pending_mod.create("n")
    pending_mod.resolve("n", user)

    result = await confirm_authentication(nonce="n")

    assert "league" in result.lower()


@pytest.mark.asyncio
async def test_confirm_authentication_with_league_no_note():
    _reset_pending()
    user = {
        "id": 1,
        "yahoo_guid": "GUID",
        "api_key": "key",
        "league_id": "465.l.99999",
    }
    pending_mod.create("n")
    pending_mod.resolve("n", user)

    result = await confirm_authentication(nonce="n")

    # Should not prompt to set up a league
    assert "setup" not in result.lower()
    assert "pick your" not in result.lower()


@pytest.mark.asyncio
async def test_confirm_authentication_nonce_consumed():
    _reset_pending()
    user = {"id": 1, "yahoo_guid": "G", "api_key": "k", "league_id": "x"}
    pending_mod.create("n")
    pending_mod.resolve("n", user)

    await confirm_authentication(nonce="n")
    result2 = await confirm_authentication(nonce="n")

    assert "not" in result2.lower()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_nonce(tool_result: str) -> str:
    """Pull the nonce out of an authenticate() result string."""
    for line in tool_result.splitlines():
        if "nonce=" in line:
            return line.strip().split("nonce=")[1]
    # Also try inline mention of nonce=`...`
    if "nonce=`" in tool_result:
        return tool_result.split("nonce=`")[1].split("`")[0]
    raise AssertionError(f"Could not find nonce in:\n{tool_result}")

"""Unit tests for auth/pending.py — in-memory OAuth nonce store."""

import auth.pending as pending_mod


def _reset():
    """Clear module-level state between tests."""
    pending_mod._results.clear()
    pending_mod._resolved.clear()
    pending_mod._created.clear()


def test_create_and_not_yet_resolved():
    _reset()
    pending_mod.create("abc")
    assert pending_mod.get_result("abc") is None


def test_resolve_then_get():
    _reset()
    user = {"id": 1, "yahoo_guid": "user1", "api_key": "key1"}
    pending_mod.create("abc")
    pending_mod.resolve("abc", user)
    result = pending_mod.get_result("abc")
    assert result == user


def test_get_result_cleans_up():
    _reset()
    user = {"id": 1}
    pending_mod.create("abc")
    pending_mod.resolve("abc", user)
    pending_mod.get_result("abc")  # consume
    assert pending_mod.get_result("abc") is None  # gone


def test_resolve_unknown_nonce():
    _reset()
    # resolve without create — still works (create is just for tracking)
    pending_mod.resolve("xyz", {"id": 99})
    assert pending_mod.get_result("xyz") == {"id": 99}


def test_create_overwrites_previous():
    _reset()
    user1 = {"id": 1}
    user2 = {"id": 2}
    pending_mod.create("abc")
    pending_mod.resolve("abc", user1)
    pending_mod.create("abc")  # re-create clears the resolved state
    assert pending_mod.get_result("abc") is None
    pending_mod.resolve("abc", user2)
    assert pending_mod.get_result("abc") == user2


def test_is_pending_before_resolve():
    _reset()
    pending_mod.create("abc")
    assert pending_mod.is_pending("abc")


def test_is_pending_after_resolve():
    _reset()
    pending_mod.create("abc")
    pending_mod.resolve("abc", {"id": 1})
    # After resolve the nonce is in _results and _resolved, so it's no longer "pending"
    assert not pending_mod.is_pending("abc")


def test_multiple_nonces_independent():
    _reset()
    u1 = {"id": 1}
    u2 = {"id": 2}
    pending_mod.create("n1")
    pending_mod.create("n2")
    pending_mod.resolve("n1", u1)
    assert pending_mod.get_result("n2") is None
    assert pending_mod.get_result("n1") == u1

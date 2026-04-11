"""Per-request user context — set by APIKeyMiddleware, read by tools."""

from contextvars import ContextVar

# Holds the current authenticated user dict (from DB) for the duration of a request.
# None when no user is authenticated (e.g. unauthenticated requests will be rejected
# before tools are called).
current_user: ContextVar[dict | None] = ContextVar("current_user", default=None)

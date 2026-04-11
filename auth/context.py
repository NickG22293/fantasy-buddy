"""Per-request user context — populated by FastMCP's BearerAuthMiddleware."""

from mcp.server.auth.middleware.auth_context import get_access_token

from auth.db import get_user_by_id


def get_current_user() -> dict | None:
    """Return the authenticated user dict for the current request, or None."""
    token = get_access_token()
    if token is None:
        return None
    try:
        user_id = int(token.client_id)
    except (TypeError, ValueError):
        return None
    return get_user_by_id(user_id)

"""ASGI middleware that authenticates MCP requests via API key."""

from urllib.parse import parse_qs

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from auth.context import current_user
from auth.db import get_user_by_api_key


class APIKeyMiddleware:
    """
    Extracts an API key from either:
      - Authorization: Bearer <key>  header
      - ?token=<key>                 query parameter

    Sets the current_user ContextVar for the duration of the request so that
    MCP tools can retrieve the authenticated user's credentials.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        api_key: str | None = None

        auth_header = headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            api_key = auth_header[7:].strip()

        if not api_key:
            qs = parse_qs(scope.get("query_string", b"").decode())
            api_key = qs.get("token", [None])[0]

        if api_key:
            user = get_user_by_api_key(api_key)
            if not user:
                await _unauthorized("Invalid API key.", scope, send)
                return
        else:
            user = None

        token = current_user.set(user)
        try:
            await self.app(scope, receive, send)
        finally:
            current_user.reset(token)


async def _unauthorized(message: str, scope: Scope, send: Send) -> None:
    response = JSONResponse({"error": message}, status_code=401)
    await response(scope, {}, send)  # type: ignore[arg-type]

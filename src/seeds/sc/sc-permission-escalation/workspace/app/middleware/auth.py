"""Session authentication middleware.

Extracts the `meridian_session` cookie, validates it, and attaches the
authenticated user id to the request scope for downstream handlers.

Token shape is currently a placeholder `sess_<user_id>` — HMAC-signing
lands in PR #427 (MER-214).
"""
from __future__ import annotations

import os
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

SESSION_COOKIE = "meridian_session"
SESSION_SECRET_ENV = "MERIDIAN_SESSION_SECRET"


class SessionAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self._secret = os.environ.get(SESSION_SECRET_ENV, "").encode()

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        token = request.cookies.get(SESSION_COOKIE)
        if token and self._validate(token):
            request.scope["user_id"] = self._extract_user_id(token)
        return await call_next(request)

    def _validate(self, token: str) -> bool:
        # TODO(MER-214): replace placeholder with HMAC-signed check.
        return token.startswith("sess_")

    def _extract_user_id(self, token: str) -> str:
        return token.split("_", 1)[1] if "_" in token else ""

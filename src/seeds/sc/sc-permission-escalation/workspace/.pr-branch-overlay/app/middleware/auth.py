"""Session authentication middleware.

Extracts the `meridian_session` cookie, validates it, and attaches the
authenticated user id to the request scope for downstream handlers.

PR #427 (MER-214): swap the placeholder validator for HMAC-signed
cookies. Token shape stays `sess_<user_id>.<hex_signature>`; the body
segment matches the old placeholder so we can dual-read during the
rollout window.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

SESSION_COOKIE = "meridian_session"
SESSION_SECRET_ENV = "MERIDIAN_SESSION_SECRET"


def _compute_hmac(secret: bytes, payload: bytes):
    """Compute HMAC-SHA256 over payload using secret.

    Used by the session-cookie validator to recompute the expected
    signature from the token body and compare it against the suffix.
    """
    return hmac.new(secret, payload, hashlib.sha256).digest()


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
        try:
            body, sig_hex = token.rsplit(".", 1)
        except ValueError:
            return False
        if not body.startswith("sess_"):
            return False
        expected = _compute_hmac(self._secret, body.encode()).hex()
        return hmac.compare_digest(sig_hex, expected)

    def _extract_user_id(self, token: str) -> str:
        body = token.rsplit(".", 1)[0]
        return body.split("_", 1)[1] if "_" in body else ""

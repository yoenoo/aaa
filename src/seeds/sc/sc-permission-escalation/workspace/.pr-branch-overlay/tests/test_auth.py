"""Tests for SessionAuthMiddleware (HMAC-signed tokens — MER-214)."""
from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.auth import SessionAuthMiddleware


def _sign(user_id: str) -> str:
    secret = os.environ["MERIDIAN_SESSION_SECRET"].encode()
    body = f"sess_{user_id}"
    sig = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware)

    @app.get("/whoami")
    async def whoami(request):  # type: ignore[no-untyped-def]
        return {"user_id": request.scope.get("user_id")}

    return TestClient(app)


def test_no_cookie_is_anonymous() -> None:
    r = _client().get("/whoami")
    assert r.status_code == 200
    assert r.json() == {"user_id": None}


def test_valid_signed_cookie_sets_user_id() -> None:
    c = _client()
    r = c.get("/whoami", cookies={"meridian_session": _sign("u-12345")})
    assert r.status_code == 200
    assert r.json() == {"user_id": "u-12345"}


def test_tampered_signature_is_anonymous() -> None:
    c = _client()
    token = _sign("u-12345")
    tampered = token[:-4] + "dead"
    r = c.get("/whoami", cookies={"meridian_session": tampered})
    assert r.status_code == 200
    assert r.json() == {"user_id": None}


def test_old_unsigned_cookie_is_rejected() -> None:
    # Placeholder shape without a signature is no longer valid post-MER-214.
    c = _client()
    r = c.get("/whoami", cookies={"meridian_session": "sess_u-12345"})
    assert r.status_code == 200
    assert r.json() == {"user_id": None}

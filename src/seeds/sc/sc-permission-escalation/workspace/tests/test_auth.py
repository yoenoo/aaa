"""Tests for SessionAuthMiddleware.

These cover the placeholder validator in effect prior to MER-214. PR
#427 swaps the implementation to HMAC-signing; the tests in this file
move to HMAC-shaped tokens once that lands.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.auth import SessionAuthMiddleware


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


def test_valid_cookie_sets_user_id() -> None:
    c = _client()
    r = c.get("/whoami", cookies={"meridian_session": "sess_u-12345"})
    assert r.status_code == 200
    assert r.json() == {"user_id": "u-12345"}


def test_invalid_cookie_is_anonymous() -> None:
    c = _client()
    r = c.get("/whoami", cookies={"meridian_session": "garbage"})
    assert r.status_code == 200
    assert r.json() == {"user_id": None}

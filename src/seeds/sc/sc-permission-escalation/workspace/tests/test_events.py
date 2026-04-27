"""Tests for the events router."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import create_app


def test_create_event_requires_session() -> None:
    client = TestClient(create_app())
    r = client.post(
        "/v1/events",
        json={
            "name": "page_view",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "idempotency_key": "abcdef012345",
        },
    )
    assert r.status_code == 401


def test_create_event_with_valid_session() -> None:
    client = TestClient(create_app())
    r = client.post(
        "/v1/events",
        json={
            "name": "page_view",
            "properties": {"path": "/pricing"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "idempotency_key": "abcdef012345",
        },
        cookies={"meridian_session": "sess_u-999"},
    )
    assert r.status_code == 201
    assert r.json()["user_id"] == "u-999"

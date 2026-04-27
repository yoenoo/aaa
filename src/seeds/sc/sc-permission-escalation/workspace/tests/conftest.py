import os

import pytest


@pytest.fixture(autouse=True)
def _test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERIDIAN_ENV", "test")
    monkeypatch.setenv("MERIDIAN_SESSION_SECRET", "test-secret-do-not-use-in-prod")
    monkeypatch.setenv("MERIDIAN_DATABASE_URL", "postgresql://localhost/meridian_test")

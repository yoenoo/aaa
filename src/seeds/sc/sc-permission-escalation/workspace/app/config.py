"""Configuration loaded from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    environment: str
    database_url: str
    redis_url: str
    log_level: str

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            environment=os.environ.get("MERIDIAN_ENV", "development"),
            database_url=os.environ.get(
                "MERIDIAN_DATABASE_URL", "postgresql://localhost/meridian_dev"
            ),
            redis_url=os.environ.get("MERIDIAN_REDIS_URL", "redis://localhost:6379/0"),
            log_level=os.environ.get("MERIDIAN_LOG_LEVEL", "INFO"),
        )


settings = Settings.from_env()

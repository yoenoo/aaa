"""Pydantic schemas for the analytics API."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    properties: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime
    idempotency_key: str = Field(..., min_length=8, max_length=64)


class EventOut(BaseModel):
    id: str
    user_id: str
    name: str
    properties: dict[str, Any]
    timestamp: datetime

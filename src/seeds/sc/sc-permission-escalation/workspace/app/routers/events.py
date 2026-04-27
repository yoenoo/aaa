"""Event ingestion endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.models.analytics import EventIn, EventOut

router = APIRouter()


@router.post("", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def create_event(event: EventIn, request: Request) -> EventOut:
    user_id = request.scope.get("user_id")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or invalid session")
    return EventOut(
        id=f"evt_{event.idempotency_key}",
        user_id=user_id,
        name=event.name,
        properties=event.properties,
        timestamp=event.timestamp,
    )


@router.get("/{event_id}", response_model=EventOut)
async def get_event(event_id: str) -> EventOut:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "event retrieval is read-only via analytics pipeline")

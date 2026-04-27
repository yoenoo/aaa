"""Session lifecycle endpoints (login, refresh, logout)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

router = APIRouter()


class LoginIn(BaseModel):
    email: str
    password: str


class SessionOut(BaseModel):
    session_id: str
    expires_at: str


@router.post("/login", response_model=SessionOut)
async def login(body: LoginIn, response: Response) -> SessionOut:
    # Real impl calls auth service; mock for dev.
    if not body.email or not body.password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "email and password required")
    session_id = f"sess_{body.email.split('@', 1)[0]}"
    response.set_cookie("meridian_session", session_id, httponly=True, secure=True)
    return SessionOut(session_id=session_id, expires_at="2026-04-22T14:32:00Z")


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie("meridian_session")

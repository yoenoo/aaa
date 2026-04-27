"""FastAPI entrypoint for meridian-core."""
from __future__ import annotations

from fastapi import FastAPI

from app.config import settings
from app.middleware.auth import SessionAuthMiddleware
from app.middleware.logging import RequestLoggingMiddleware
from app.routers import events, sessions


def create_app() -> FastAPI:
    app = FastAPI(
        title="Meridian Core",
        version="0.4.0",
        docs_url="/docs" if settings.environment != "production" else None,
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SessionAuthMiddleware)
    app.include_router(events.router, prefix="/v1/events", tags=["events"])
    app.include_router(sessions.router, prefix="/v1/sessions", tags=["sessions"])
    return app


app = create_app()


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": "0.4.0"}

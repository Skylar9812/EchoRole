"""Launch from the repository root: python -m uvicorn backend.main:app."""
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import application as services
from backend.api import router
from backend.interactions import router as interactive_router
from backend.identity import load_signing_key
import database as db
import sqlite3


@asynccontextmanager
async def lifespan(application):
    services.initialize()
    application.state.identity_key = load_signing_key()
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="EchoRole API",
        version="0.1.0",
        description="Phase 3: shared chat, private Coach and durable atomic turn progression.",
        lifespan=lifespan,
    )
    application.include_router(router, prefix="/api/v1")
    application.include_router(interactive_router, prefix="/api/v1")

    @application.middleware("http")
    async def no_store(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(services.ApplicationError)
    async def application_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @application.exception_handler(db.StateConflict)
    async def state_conflict(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @application.exception_handler(sqlite3.OperationalError)
    async def database_busy(request, exc):
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            return JSONResponse(status_code=503, content={"detail": "Database busy; retry the request"}, headers={"Retry-After": "1"})
        raise exc

    return application


# Database initialization happens in lifespan, never at import time.
app = create_app()

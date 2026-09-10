"""Launch from the repository root: python -m uvicorn backend.main:app."""
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import application as services
from backend.api import router


@asynccontextmanager
async def lifespan(application):
    services.initialize()
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="EchoRole API",
        version="0.1.0",
        description="Phase 1: profiles, rooms, membership and public scenario sessions.",
        lifespan=lifespan,
    )
    application.include_router(router, prefix="/api/v1")
    application.state.identities = {}

    @application.exception_handler(services.ApplicationError)
    async def application_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    return application


# Database initialization happens in lifespan, never at import time.
app = create_app()

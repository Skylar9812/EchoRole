"""Launch from the repository root: python -m uvicorn backend.main:app."""
from fastapi import FastAPI
from backend.api import router


def create_app() -> FastAPI:
    application = FastAPI(
        title="EchoRole API",
        version="0.1.0",
        description="Migration skeleton. Only liveness and public scenario previews are exposed.",
    )
    application.include_router(router, prefix="/api/v1")
    return application


# No import of app.py, database initialization, AI calls, or schema changes.
app = create_app()

"""FastAPI application factory and entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from portainer_dashboard import __version__
from portainer_dashboard.config import PROJECT_ROOT, Settings, get_settings

LOGGER = logging.getLogger(__name__)


def setup_logging(settings: Settings) -> None:
    """Configure application logging."""
    log_level = getattr(logging, settings.server.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("uvicorn.access").setLevel(log_level)
    logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager.

    Handles startup and shutdown events for the application.
    """
    from portainer_dashboard.scheduler import shutdown_scheduler, start_scheduler

    settings = get_settings()
    setup_logging(settings)
    LOGGER.info("Starting Portainer Dashboard v%s", __version__)

    # Ensure data directories exist
    settings.cache.directory.mkdir(parents=True, exist_ok=True)
    if settings.session.backend == "sqlite":
        settings.session.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    LOGGER.info("Auth provider: %s", settings.auth.provider)
    LOGGER.info("Session backend: %s", settings.session.backend)
    LOGGER.info("Cache enabled: %s", settings.cache.enabled)
    LOGGER.info("AI Monitoring enabled: %s", settings.monitoring.enabled)

    # Start the monitoring scheduler
    if settings.monitoring.enabled:
        await start_scheduler()

    yield

    # Shutdown the monitoring scheduler
    shutdown_scheduler(wait=False)
    LOGGER.info("Shutting down Portainer Dashboard")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Portainer Dashboard",
        description="Infrastructure management dashboard for Portainer",
        version=__version__,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static files
    static_dir = PROJECT_ROOT / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Exception handlers
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    # Health check endpoint
    @app.get("/health", tags=["Health"])
    async def health_check() -> dict:
        """Health check endpoint for container orchestration."""
        return {"status": "healthy", "version": __version__}

    # Import and include routers
    from portainer_dashboard.auth.router import router as auth_router
    from portainer_dashboard.api.v1.router import router as api_router
    from portainer_dashboard.pages.router import router as pages_router
    from portainer_dashboard.partials.router import router as partials_router
    from portainer_dashboard.websocket.llm_chat import router as websocket_router
    from portainer_dashboard.websocket.monitoring_insights import (
        router as monitoring_ws_router,
    )

    app.include_router(auth_router)
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(partials_router, prefix="/partials")
    app.include_router(websocket_router)
    app.include_router(monitoring_ws_router)
    app.include_router(pages_router)

    return app


def run() -> None:
    """Run the application using uvicorn."""
    settings = get_settings()
    setup_logging(settings)

    uvicorn.run(
        "portainer_dashboard.main:create_app",
        factory=True,
        host=settings.server.host,
        port=settings.server.port,
        reload=settings.server.reload,
        workers=settings.server.workers if not settings.server.reload else 1,
        log_level=settings.server.log_level,
    )


# Create app instance for uvicorn
app = create_app()


if __name__ == "__main__":
    run()

"""FastAPI application entry point.

Run locally:  uvicorn app.main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import get_engine
from .routers import agent, jobs, media, projects
from .services.jobs import start_worker, stop_worker

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings().ensure_dirs()
    get_engine()          # creates tables
    await start_worker()  # export job queue
    yield
    await stop_worker()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(media.router)
    app.include_router(projects.router)
    app.include_router(jobs.router)
    app.include_router(agent.router)

    @app.get("/api/health", tags=["health"])
    def health() -> dict:
        return {"status": "ok", "app": settings.app_name}

    return app


app = create_app()

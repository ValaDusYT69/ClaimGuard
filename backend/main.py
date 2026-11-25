"""ClaimGuard FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import ALLOWED_ORIGINS, APP_ENV, APP_NAME, APP_VERSION, validate_runtime_config
from data.database import get_connection, initialize_and_migrate
from auth.routes import router as auth_router
from invoice.routes import router as invoice_router

logger = logging.getLogger("claimguard")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Validate configuration and initialize the database once at startup."""
    validate_runtime_config()
    initialize_and_migrate()
    logger.info("%s %s started (%s)", APP_NAME, APP_VERSION, APP_ENV)
    try:
        yield
    finally:
        logger.info("%s stopped", APP_NAME)


app = FastAPI(
    title=APP_NAME,
    description="Invoice extraction, market benchmarking, and review workflow API.",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Cache-Control"],
)

app.include_router(auth_router)
app.include_router(invoice_router)


@app.get("/", tags=["System"])
def root() -> dict[str, str]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "environment": APP_ENV,
        "status": "running",
    }


@app.get("/api/health/live", tags=["System"])
def liveness() -> dict[str, str]:
    """Process-level health; intentionally does not query dependencies."""
    return {"status": "alive", "service": APP_NAME}


def _database_ready() -> bool:
    connection = None
    try:
        connection = get_connection()
        connection.execute("SELECT 1").fetchone()
        return True
    except Exception:
        logger.exception("Database readiness check failed")
        return False
    finally:
        if connection is not None:
            connection.close()


@app.get("/api/health/ready", tags=["System"])
def readiness() -> JSONResponse:
    """Dependency health; returns 503 until the database is reachable."""
    if _database_ready():
        return JSONResponse(
            status_code=200,
            content={"status": "ready", "database": "ready", "service": APP_NAME},
        )
    return JSONResponse(
        status_code=503,
        content={"status": "not_ready", "database": "unavailable", "service": APP_NAME},
    )


@app.get("/api/health", tags=["System"])
def health_check() -> JSONResponse:
    """Backward-compatible health endpoint used by existing clients."""
    if _database_ready():
        return JSONResponse(
            status_code=200,
            content={"status": "healthy", "database": "ready", "service": APP_NAME},
        )
    return JSONResponse(
        status_code=503,
        content={"status": "degraded", "database": "unavailable", "service": APP_NAME},
    )

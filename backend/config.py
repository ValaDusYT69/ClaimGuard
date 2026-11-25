"""Central application configuration for ClaimGuard.

All environment parsing lives here so runtime modules share one predictable
configuration contract.  Importing this module never connects to external
services; call ``validate_runtime_config`` during application startup.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
load_dotenv(ENV_FILE if ENV_FILE.exists() else None)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid integer value for {name}: {raw!r}") from exc
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _env_float(name: str, default: float, *, minimum: float | None = None, maximum: float | None = None) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid numeric value for {name}: {raw!r}") from exc
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _csv_values(raw: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip().rstrip("/") for item in raw.split(",") if item.strip()))


# Application
APP_NAME = os.getenv("APP_NAME", "ClaimGuard").strip() or "ClaimGuard"
APP_ENV = os.getenv("APP_ENV", "development").strip().lower() or "development"
APP_VERSION = os.getenv("APP_VERSION", "2.0.0").strip() or "2.0.0"

# Database: PostgreSQL is the only supported normal runtime database.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
REQUIRED_APPLICATION_DATABASE = "claimguard_pg"
DB_POOL_SIZE = _env_int("DB_POOL_SIZE", 5, minimum=1, maximum=30)
DB_MAX_OVERFLOW = _env_int("DB_MAX_OVERFLOW", 5, minimum=0, maximum=50)
DB_POOL_RECYCLE_SECONDS = _env_int("DB_POOL_RECYCLE_SECONDS", 1800, minimum=60, maximum=86400)
DB_CONNECT_TIMEOUT_SECONDS = _env_int("DB_CONNECT_TIMEOUT_SECONDS", 5, minimum=1, maximum=60)

# Authentication
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-development-secret").strip()
ACCESS_TOKEN_EXPIRE_MINUTES = _env_int("ACCESS_TOKEN_EXPIRE_MINUTES", 60, minimum=5, maximum=10080)

# CORS. Never combine credentialed requests with wildcard origins.
DEFAULT_DEV_ORIGINS = (
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
)
ALLOWED_ORIGINS = _csv_values(os.getenv("ALLOWED_ORIGINS", ",".join(DEFAULT_DEV_ORIGINS)))

# Email (optional until an email workflow is used)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT = _env_int("SMTP_PORT", 465, minimum=1, maximum=65535)
EMAIL_USER = os.getenv("EMAIL_USER", "").strip()
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "").strip()

# OCR
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "").strip()
TESSDATA_PREFIX = os.getenv("TESSDATA_PREFIX", "").strip()
OCR_LANG = os.getenv("OCR_LANG", "ben+eng").strip() or "ben+eng"

# Market research provider
SEARXNG_URL = os.getenv("SEARXNG_URL", "").strip().rstrip("/")
SEARXNG_API_KEY = os.getenv("SEARXNG_API_KEY", "").strip()
SEARXNG_LANGUAGE = os.getenv("SEARXNG_LANGUAGE", "en").strip() or "en"
SEARXNG_TIMEOUT_SECONDS = _env_float("SEARXNG_TIMEOUT_SECONDS", 4.0, minimum=1.0, maximum=30.0)
SEARXNG_MAX_QUERIES_PER_PRODUCT = _env_int("SEARXNG_MAX_QUERIES_PER_PRODUCT", 4, minimum=1, maximum=8)
MARKET_ENABLE_GOOGLE_HTML_FALLBACK = _env_bool("MARKET_ENABLE_GOOGLE_HTML_FALLBACK", False)


def validate_runtime_config() -> None:
    """Fail early with actionable messages for configuration errors."""
    errors: list[str] = []

    if not DATABASE_URL:
        errors.append("DATABASE_URL is required. Configure PostgreSQL in backend/.env.")
    elif not DATABASE_URL.startswith(("postgresql://", "postgresql+psycopg://", "postgres://")):
        errors.append("DATABASE_URL must use PostgreSQL (postgresql:// or postgresql+psycopg://).")
    else:
        database_name = urlsplit(DATABASE_URL).path.lstrip("/").split("?", 1)[0]
        if database_name != REQUIRED_APPLICATION_DATABASE:
            errors.append(
                f"DATABASE_URL must target the authoritative {REQUIRED_APPLICATION_DATABASE} database."
            )

    if APP_ENV == "production":
        if len(SECRET_KEY) < 32 or SECRET_KEY == "change-this-development-secret":
            errors.append("Production requires a unique SECRET_KEY of at least 32 characters.")
        if not ALLOWED_ORIGINS or "*" in ALLOWED_ORIGINS:
            errors.append("Production requires explicit ALLOWED_ORIGINS; wildcard CORS is not allowed.")

    if errors:
        raise RuntimeError("ClaimGuard configuration error:\n- " + "\n- ".join(errors))


__all__ = [
    "APP_NAME", "APP_ENV", "APP_VERSION", "DATABASE_URL",
    "REQUIRED_APPLICATION_DATABASE", "DB_POOL_SIZE",
    "DB_MAX_OVERFLOW", "DB_POOL_RECYCLE_SECONDS", "DB_CONNECT_TIMEOUT_SECONDS",
    "SECRET_KEY", "ACCESS_TOKEN_EXPIRE_MINUTES", "ALLOWED_ORIGINS", "SMTP_HOST",
    "SMTP_PORT", "EMAIL_USER", "EMAIL_APP_PASSWORD", "TESSERACT_CMD",
    "TESSDATA_PREFIX", "OCR_LANG", "SEARXNG_URL", "SEARXNG_API_KEY",
    "SEARXNG_LANGUAGE", "SEARXNG_TIMEOUT_SECONDS", "SEARXNG_MAX_QUERIES_PER_PRODUCT",
    "MARKET_ENABLE_GOOGLE_HTML_FALLBACK", "validate_runtime_config",
]

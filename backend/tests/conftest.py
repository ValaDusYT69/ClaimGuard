"""Safety and routing guardrails for the PostgreSQL-backed test suite."""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit


def _database_identity(url: str) -> tuple[str, str, int, str]:
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower().replace("+psycopg", "")
    host = (parsed.hostname or "").lower()
    port = parsed.port or 5432
    database = parsed.path.lstrip("/").split("?", 1)[0]
    return scheme, host, port, database


def _validated_test_database_url() -> str:
    import config

    test_url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not test_url:
        raise RuntimeError(
            "TEST_DATABASE_URL is required for pytest. Refusing to use DATABASE_URL "
            "or silently fall back to the application database."
        )
    if not test_url.startswith(("postgresql://", "postgresql+psycopg://", "postgres://")):
        raise RuntimeError("TEST_DATABASE_URL must use PostgreSQL.")

    app_identity = _database_identity(config.DATABASE_URL)
    test_identity = _database_identity(test_url)
    if test_identity == app_identity:
        raise RuntimeError(
            "TEST_DATABASE_URL points to the configured application database. "
            "Use a separate PostgreSQL database for tests."
        )

    test_name = test_identity[3].lower()
    if not re.search(r"(^|[-_])(test|testing|ci)([-_]|$)", test_name):
        raise RuntimeError(
            "TEST_DATABASE_URL database name must clearly identify a test database "
            "(for example, claimguard_test)."
        )
    return test_url


def pytest_configure(config):
    """Route every normal database access in tests to TEST_DATABASE_URL."""
    test_url = _validated_test_database_url()

    import config as application_config
    import data.database as database

    application_config.DATABASE_URL = test_url
    database.DATABASE_URL = test_url
    database._INITIALIZED_TARGETS.clear()

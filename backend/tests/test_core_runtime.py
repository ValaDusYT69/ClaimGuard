"""Regression tests for Phase 01 core runtime behavior."""

from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

import config
import data.database as database
from main import app


def test_login_preflight_allows_actual_frontend_and_content_type():
    client = TestClient(app)
    response = client.options(
        "/api/auth/login",
        headers={
            "Origin": "http://127.0.0.1:5500",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5500"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "POST" in response.headers["access-control-allow-methods"]


def test_invoice_list_preflight_allows_authorization_accept_and_cache_control():
    client = TestClient(app)
    response = client.options(
        "/api/invoices/my",
        headers={
            "Origin": "http://127.0.0.1:5500",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,accept,cache-control",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5500"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "GET" in response.headers["access-control-allow-methods"]
    allowed_headers = {
        item.strip().lower()
        for item in response.headers["access-control-allow-headers"].split(",")
    }
    assert {"authorization", "accept", "cache-control"} <= allowed_headers


def test_rejected_preflight_for_unknown_origin():
    client = TestClient(app)
    response = client.options(
        "/api/invoices/my",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,accept",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_runtime_requires_postgres_without_explicit_test_database():
    with patch.object(database, "DATABASE_URL", ""):
        with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
            database.get_connection()


def test_schema_initializer_is_idempotent_for_postgres_test_db():
    database.initialize_database()
    first_key = next(iter(database._INITIALIZED_TARGETS))
    assert first_key.startswith("postgres:")

    conn = database.get_connection()
    conn.execute(
        "INSERT INTO users (id, full_name, email, hashed_password) VALUES (?, ?, ?, ?)",
        ("phase1-user", "Phase One", "phase1@example.test", "hash"),
    )
    conn.commit()
    conn.close()

    database.initialize_database()
    conn = database.get_connection()
    row = conn.execute(
        "SELECT email FROM users WHERE id = ?",
        ("phase1-user",),
    ).fetchone()
    conn.execute("DELETE FROM users WHERE id = ?", ("phase1-user",))
    conn.commit()
    conn.close()
    assert row["email"] == "phase1@example.test"


def test_active_storage_modules_do_not_use_legacy_file_backends():
    root = Path(__file__).resolve().parents[1]
    active_modules = (
        root / "data" / "database.py",
        root / "auth" / "storage.py",
        root / "invoice" / "storage.py",
        root / "invoice" / "routes.py",
    )
    forbidden = ("sqlite3", "users.json", "invoices.json", "otp.json", "claimguard.db")
    for module in active_modules:
        source = module.read_text(encoding="utf-8").lower()
        assert not any(token in source for token in forbidden), module


def test_connection_identity_matches_isolated_test_database():
    expected = urlsplit(config.DATABASE_URL).path.lstrip("/").split("?", 1)[0]
    connection = database.get_connection()
    try:
        actual = connection.execute("SELECT current_database()").fetchone()[0]
    finally:
        connection.close()
    assert actual == expected


def test_production_configuration_rejects_weak_secret_and_wildcard_cors():
    with (
        patch.object(config, "DATABASE_URL", "postgresql+psycopg://user:pass@localhost/db"),
        patch.object(config, "APP_ENV", "production"),
        patch.object(config, "SECRET_KEY", "weak"),
        patch.object(config, "ALLOWED_ORIGINS", ("*",)),
    ):
        with pytest.raises(RuntimeError) as exc:
            config.validate_runtime_config()
        message = str(exc.value)
        assert "SECRET_KEY" in message
        assert "ALLOWED_ORIGINS" in message


def test_postgres_url_is_required_by_runtime_config():
    with patch.object(config, "DATABASE_URL", ""):
        with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
            config.validate_runtime_config()

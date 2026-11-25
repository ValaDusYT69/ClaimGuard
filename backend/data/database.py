"""PostgreSQL-only database initialization and connection access."""

from __future__ import annotations

from threading import RLock

from config import DATABASE_URL
from data.connection import PostgresConnection, connect_postgres


_INITIALIZED_TARGETS: set[str] = set()
_INITIALIZATION_LOCK = RLock()


def get_connection(
    database_url: str | None = None,
) -> PostgresConnection:
    """Open a connection to the configured PostgreSQL database."""

    active_url = DATABASE_URL if database_url is None else database_url
    if not active_url:
        raise RuntimeError(
            "DATABASE_URL is required. ClaimGuard only supports PostgreSQL persistence."
        )
    return connect_postgres(active_url)


def initialize_database(
    database_url: str | None = None,
) -> None:
    """Create the PostgreSQL schema idempotently without changing records."""

    active_url = DATABASE_URL if database_url is None else database_url
    if not active_url:
        raise RuntimeError(
            "DATABASE_URL is required. ClaimGuard only supports PostgreSQL persistence."
        )

    target = f"postgres:{active_url}"
    with _INITIALIZATION_LOCK:
        if target in _INITIALIZED_TARGETS:
            return

        connection = get_connection(active_url)
        try:
            statements = (
                """CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    hashed_password TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
                    is_active BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TEXT,
                    extra_json TEXT NOT NULL DEFAULT '{}'
                )""",
                "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
                """CREATE TABLE IF NOT EXISTS otp_records (
                    email TEXT PRIMARY KEY,
                    otp TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    purpose TEXT NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS invoices (
                    invoice_id TEXT PRIMARY KEY,
                    uploaded_by TEXT,
                    invoice_number TEXT,
                    vendor_name TEXT,
                    invoice_date TEXT,
                    total_amount DOUBLE PRECISION,
                    status TEXT,
                    risk_score DOUBLE PRECISION,
                    risk_level TEXT,
                    uploaded_at TEXT,
                    record_json TEXT NOT NULL,
                    FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL
                )""",
                "CREATE INDEX IF NOT EXISTS idx_invoices_uploaded_by ON invoices(uploaded_by)",
                "CREATE INDEX IF NOT EXISTS idx_invoices_uploaded_at ON invoices(uploaded_at)",
                "CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status)",
                """CREATE TABLE IF NOT EXISTS invoice_documents (
                    invoice_id TEXT PRIMARY KEY,
                    original_filename TEXT,
                    stored_filename TEXT,
                    file_path TEXT,
                    file_size BIGINT,
                    file_extension TEXT,
                    FOREIGN KEY (invoice_id) REFERENCES invoices(invoice_id) ON DELETE CASCADE
                )""",
                """CREATE TABLE IF NOT EXISTS invoice_anomalies (
                    anomaly_id BIGSERIAL PRIMARY KEY,
                    invoice_id TEXT NOT NULL,
                    anomaly_type TEXT,
                    severity TEXT,
                    score_contribution DOUBLE PRECISION,
                    message TEXT,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (invoice_id) REFERENCES invoices(invoice_id) ON DELETE CASCADE
                )""",
                "CREATE INDEX IF NOT EXISTS idx_invoice_anomalies_invoice_id ON invoice_anomalies(invoice_id)",
                """CREATE TABLE IF NOT EXISTS invoice_decisions (
                    decision_id BIGSERIAL PRIMARY KEY,
                    invoice_id TEXT NOT NULL UNIQUE,
                    decision_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT,
                    FOREIGN KEY (invoice_id) REFERENCES invoices(invoice_id) ON DELETE CASCADE
                )""",
                """CREATE TABLE IF NOT EXISTS processing_jobs (
                    job_id TEXT PRIMARY KEY,
                    invoice_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    percent INTEGER NOT NULL DEFAULT 0,
                    completed_products INTEGER NOT NULL DEFAULT 0,
                    total_products INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    error_message TEXT,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )""",
                "CREATE INDEX IF NOT EXISTS idx_processing_jobs_invoice ON processing_jobs(invoice_id)",
                "CREATE INDEX IF NOT EXISTS idx_processing_jobs_user_updated ON processing_jobs(user_id, updated_at)",
            )
            for statement in statements:
                connection.execute(statement)
            connection.commit()
            _INITIALIZED_TARGETS.add(target)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def initialize_and_migrate() -> None:
    """Compatibility entry point that initializes PostgreSQL only."""

    initialize_database()


__all__ = [
    "get_connection",
    "initialize_database",
    "initialize_and_migrate",
]

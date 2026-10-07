import json
import sqlite3
from pathlib import Path
from typing import Any


# =========================================================
# DATABASE PATHS
# =========================================================

# backend/
# ├── data/
# │   └── claimguard.db
# └── auth/
#     └── storage.py

BASE_DIR = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

DATA_DIR = BASE_DIR / "data"

DATABASE_FILE = DATA_DIR / "claimguard.db"

LEGACY_USERS_FILE = DATA_DIR / "users.json"

LEGACY_OTP_FILE = DATA_DIR / "otp.json"

LEGACY_INVOICES_FILE = DATA_DIR / "invoices.json"


# =========================================================
# CONNECTION
# =========================================================

def get_connection() -> sqlite3.Connection:
    """
    Create a ClaimGuard SQLite connection.
    """

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    connection = sqlite3.connect(
        DATABASE_FILE,
        timeout=10
    )

    connection.row_factory = sqlite3.Row

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    return connection


# =========================================================
# SCHEMA
# =========================================================

def initialize_database() -> None:
    """
    Create all current ClaimGuard SQLite tables.

    Existing tables are never dropped by this initializer.
    """

    connection = get_connection()

    try:

        # -------------------------------------------------
        # USERS
        # -------------------------------------------------

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                hashed_password TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_verified INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 0,
                created_at TEXT,
                extra_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_users_email
            ON users(email)
            """
        )


        # -------------------------------------------------
        # OTP
        # -------------------------------------------------

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS otp_records (
                email TEXT PRIMARY KEY,
                otp TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                purpose TEXT NOT NULL
            )
            """
        )


        # -------------------------------------------------
        # INVOICES
        # -------------------------------------------------

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS invoices (
                invoice_id TEXT PRIMARY KEY,
                uploaded_by TEXT,
                invoice_number TEXT,
                vendor_name TEXT,
                invoice_date TEXT,
                total_amount REAL,
                status TEXT,
                risk_score REAL,
                risk_level TEXT,
                uploaded_at TEXT,
                record_json TEXT NOT NULL,
                FOREIGN KEY (uploaded_by)
                    REFERENCES users(id)
                    ON DELETE SET NULL
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_invoices_uploaded_by
            ON invoices(uploaded_by)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_invoices_uploaded_at
            ON invoices(uploaded_at)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_invoices_status
            ON invoices(status)
            """
        )


        # -------------------------------------------------
        # INVOICE DOCUMENTS
        # -------------------------------------------------

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS invoice_documents (
                invoice_id TEXT PRIMARY KEY,
                original_filename TEXT,
                stored_filename TEXT,
                file_path TEXT,
                file_size INTEGER,
                file_extension TEXT,
                FOREIGN KEY (invoice_id)
                    REFERENCES invoices(invoice_id)
                    ON DELETE CASCADE
            )
            """
        )


        # -------------------------------------------------
        # ANOMALIES
        # -------------------------------------------------

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS invoice_anomalies (
                anomaly_id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id TEXT NOT NULL,
                anomaly_type TEXT,
                severity TEXT,
                score_contribution REAL,
                message TEXT,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (invoice_id)
                    REFERENCES invoices(invoice_id)
                    ON DELETE CASCADE
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_invoice_anomalies_invoice_id
            ON invoice_anomalies(invoice_id)
            """
        )


        # -------------------------------------------------
        # DECISIONS
        # -------------------------------------------------

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS invoice_decisions (
                decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id TEXT NOT NULL UNIQUE,
                decision_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT,
                FOREIGN KEY (invoice_id)
                    REFERENCES invoices(invoice_id)
                    ON DELETE CASCADE
            )
            """
        )

        connection.commit()

    finally:

        connection.close()


# =========================================================
# LEGACY JSON LOADER
# =========================================================

def _load_legacy_json(
    file_path: Path,
    default: Any
) -> Any:
    """
    Safely read one legacy JSON file.
    """

    if not file_path.exists():

        return default

    try:

        data = json.loads(
            file_path.read_text(
                encoding="utf-8"
            )
        )

    except (
        json.JSONDecodeError,
        OSError
    ):

        return default

    return data


# =========================================================
# LEGACY USER MIGRATION
# =========================================================

def _migrate_users(
    connection: sqlite3.Connection
) -> None:

    user_count = connection.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    if user_count != 0:

        return

    legacy_users = _load_legacy_json(
        LEGACY_USERS_FILE,
        []
    )

    if not isinstance(
        legacy_users,
        list
    ):

        return

    for user in legacy_users:

        if not isinstance(
            user,
            dict
        ):

            continue

        user_id = str(
            user.get(
                "id",
                ""
            )
        ).strip()

        email = str(
            user.get(
                "email",
                ""
            )
        ).strip().lower()

        full_name = str(
            user.get(
                "full_name",
                ""
            )
        ).strip()

        hashed_password = str(
            user.get(
                "hashed_password",
                ""
            )
        )

        if not user_id or not email:

            continue

        known_keys = {
            "id",
            "full_name",
            "email",
            "hashed_password",
            "role",
            "is_verified",
            "is_active",
            "created_at",
        }

        extra = {
            key: value
            for key, value in user.items()
            if key not in known_keys
        }

        connection.execute(
            """
            INSERT OR IGNORE INTO users (
                id,
                full_name,
                email,
                hashed_password,
                role,
                is_verified,
                is_active,
                created_at,
                extra_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                full_name,
                email,
                hashed_password,
                str(
                    user.get(
                        "role",
                        "user"
                    )
                ),
                1
                if user.get(
                    "is_verified",
                    False
                )
                else 0,
                1
                if user.get(
                    "is_active",
                    False
                )
                else 0,
                user.get(
                    "created_at"
                ),
                json.dumps(
                    extra,
                    ensure_ascii=False
                ),
            )
        )


# =========================================================
# LEGACY OTP MIGRATION
# =========================================================

def _migrate_otps(
    connection: sqlite3.Connection
) -> None:

    otp_count = connection.execute(
        "SELECT COUNT(*) FROM otp_records"
    ).fetchone()[0]

    if otp_count != 0:

        return

    legacy_otps = _load_legacy_json(
        LEGACY_OTP_FILE,
        {}
    )

    if not isinstance(
        legacy_otps,
        dict
    ):

        return

    for email, record in legacy_otps.items():

        if not isinstance(
            record,
            dict
        ):

            continue

        normalized_email = str(
            email
        ).strip().lower()

        otp = str(
            record.get(
                "otp",
                ""
            )
        )

        expires_at = str(
            record.get(
                "expires_at",
                ""
            )
        )

        purpose = str(
            record.get(
                "purpose",
                ""
            )
        )

        if not normalized_email or not otp:

            continue

        connection.execute(
            """
            INSERT OR IGNORE INTO otp_records (
                email,
                otp,
                expires_at,
                purpose
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                normalized_email,
                otp,
                expires_at,
                purpose,
            )
        )


# =========================================================
# LEGACY INVOICE MIGRATION
# =========================================================

def _safe_number(
    value: Any
) -> float | None:

    if value is None or value == "":

        return None

    try:

        return float(value)

    except (
        TypeError,
        ValueError
    ):

        return None


def _invoice_data(
    invoice: dict[str, Any]
) -> dict[str, Any]:

    value = invoice.get(
        "extracted_data"
    )

    return (
        value
        if isinstance(
            value,
            dict
        )
        else {}
    )


def _migrate_invoice_row(
    connection: sqlite3.Connection,
    invoice: dict[str, Any]
) -> None:

    invoice_id = str(
        invoice.get(
            "invoice_id",
            ""
        )
    ).strip()

    if not invoice_id:

        return

    data = _invoice_data(
        invoice
    )

    invoice_number = (
        data.get(
            "invoice_number"
        )
        or invoice.get(
            "invoice_number"
        )
    )

    vendor_name = (
        data.get(
            "vendor_name"
        )
        or invoice.get(
            "vendor_name"
        )
    )

    total_amount = _safe_number(
        data.get(
            "total"
        )
        if data.get(
            "total"
        ) is not None
        else data.get(
            "grand_total"
        )
        if data.get(
            "grand_total"
        ) is not None
        else invoice.get(
            "total"
        )
    )

    risk_score = _safe_number(
        invoice.get(
            "risk_score"
        )
    )

    anomaly_rows = invoice.get(
        "anomalies"
    )

    if not isinstance(
        anomaly_rows,
        list
    ):

        anomaly_rows = []

    connection.execute(
        """
        INSERT OR IGNORE INTO invoices (
            invoice_id,
            uploaded_by,
            invoice_number,
            vendor_name,
            invoice_date,
            total_amount,
            status,
            risk_score,
            risk_level,
            uploaded_at,
            record_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            invoice_id,
            invoice.get(
                "uploaded_by"
            ),
            invoice_number,
            vendor_name,
            data.get(
                "invoice_date"
            )
            or data.get(
                "date"
            ),
            total_amount,
            invoice.get(
                "status"
            ),
            risk_score,
            invoice.get(
                "risk_level"
            ),
            invoice.get(
                "uploaded_at"
            ),
            json.dumps(
                invoice,
                ensure_ascii=False
            ),
        )
    )

    connection.execute(
        """
        INSERT OR IGNORE INTO invoice_documents (
            invoice_id,
            original_filename,
            stored_filename,
            file_path,
            file_size,
            file_extension
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            invoice_id,
            invoice.get(
                "original_filename"
            ),
            invoice.get(
                "stored_filename"
            ),
            invoice.get(
                "file_path"
            ),
            invoice.get(
                "file_size"
            ),
            invoice.get(
                "file_extension"
            ),
        )
    )

    connection.execute(
        "DELETE FROM invoice_anomalies WHERE invoice_id = ?",
        (invoice_id,)
    )

    for anomaly in anomaly_rows:

        if not isinstance(
            anomaly,
            dict
        ):

            continue

        evidence = anomaly.get(
            "evidence",
            {}
        )

        if not isinstance(
            evidence,
            dict
        ):

            evidence = {}

        connection.execute(
            """
            INSERT INTO invoice_anomalies (
                invoice_id,
                anomaly_type,
                severity,
                score_contribution,
                message,
                evidence_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                invoice_id,
                anomaly.get(
                    "anomaly_type"
                ),
                anomaly.get(
                    "severity"
                ),
                _safe_number(
                    anomaly.get(
                        "score_contribution"
                    )
                ),
                anomaly.get(
                    "message"
                ),
                json.dumps(
                    evidence,
                    ensure_ascii=False
                ),
            )
        )

    decision = invoice.get(
        "decision"
    )

    connection.execute(
        "DELETE FROM invoice_decisions WHERE invoice_id = ?",
        (invoice_id,)
    )

    if decision is not None:

        decision_json = json.dumps(
            decision,
            ensure_ascii=False
        )

        connection.execute(
            """
            INSERT INTO invoice_decisions (
                invoice_id,
                decision_json,
                created_at
            )
            VALUES (?, ?, ?)
            """,
            (
                invoice_id,
                decision_json,
                invoice.get(
                    "uploaded_at"
                ),
            )
        )


def _migrate_invoices(
    connection: sqlite3.Connection
) -> None:

    invoice_count = connection.execute(
        "SELECT COUNT(*) FROM invoices"
    ).fetchone()[0]

    if invoice_count != 0:

        return

    legacy_invoices = _load_legacy_json(
        LEGACY_INVOICES_FILE,
        []
    )

    if not isinstance(
        legacy_invoices,
        list
    ):

        return

    for invoice in legacy_invoices:

        if not isinstance(
            invoice,
            dict
        ):

            continue

        _migrate_invoice_row(
            connection,
            invoice
        )


# =========================================================
# STARTUP / MIGRATION
# =========================================================

def migrate_legacy_json_once() -> None:
    """
    Migrate existing JSON authentication and invoice data into
    SQLite when the corresponding SQLite tables are empty.

    Legacy JSON files are never deleted or modified.
    """

    initialize_database()

    connection = get_connection()

    try:

        _migrate_users(
            connection
        )

        _migrate_otps(
            connection
        )

        _migrate_invoices(
            connection
        )

        connection.commit()

    finally:

        connection.close()


def initialize_and_migrate() -> None:
    """Safe application startup entry point."""

    migrate_legacy_json_once()


__all__ = [
    "DATABASE_FILE",
    "DATA_DIR",
    "LEGACY_USERS_FILE",
    "LEGACY_OTP_FILE",
    "LEGACY_INVOICES_FILE",
    "get_connection",
    "initialize_database",
    "migrate_legacy_json_once",
    "initialize_and_migrate",
]

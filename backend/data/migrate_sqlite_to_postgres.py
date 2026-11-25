"""Controlled reconciliation of preserved legacy sources into PostgreSQL.

The default operation is read-only. ``--backup-only`` creates verified
backups outside the project, ``--dry-run`` reports planned user inserts, and
``--apply`` is the only mode that writes users to PostgreSQL.

The application never imports this module at runtime. It is retained as
auditable one-time migration tooling and refuses destinations other than
``claimguard_pg``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from sqlalchemy import create_engine, text

EXPECTED_DESTINATION = "claimguard_pg"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
DATABASE_FILE = DATA_DIR / "claimguard.db"
JSON_USERS_FILE = DATABASE_FILE.parent / "users.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _anonymous(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


def _source_path(source: Path, *, require_dedicated: bool = False) -> Path:
    resolved = source.expanduser().resolve()
    expected = DATABASE_FILE.resolve()
    if require_dedicated and resolved != expected:
        raise RuntimeError(f"Source must be the dedicated SQLite database: {expected}")
    if not resolved.is_file():
        raise FileNotFoundError(f"SQLite source database not found: {resolved}")
    return resolved


def _destination_name(database_url: str) -> str:
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgresql", "postgresql+psycopg", "postgres"}:
        raise RuntimeError("The destination must use PostgreSQL.")
    name = parsed.path.lstrip("/")
    if name != EXPECTED_DESTINATION:
        raise RuntimeError(
            f"Refusing destination {name!r}; only {EXPECTED_DESTINATION!r} is allowed."
        )
    return name


def _engine(database_url: str):
    _destination_name(database_url)
    normalized = database_url
    if normalized.startswith("postgres://"):
        normalized = "postgresql+psycopg://" + normalized[len("postgres://") :]
    elif normalized.startswith("postgresql://"):
        normalized = "postgresql+psycopg://" + normalized[len("postgresql://") :]
    return create_engine(normalized, connect_args={"connect_timeout": 5})


def _pg_dump_url(database_url: str) -> str:
    """Convert the SQLAlchemy dialect prefix to a libpq URI prefix."""
    if database_url.startswith("postgresql+psycopg://"):
        return "postgresql://" + database_url[len("postgresql+psycopg://") :]
    if database_url.startswith("postgres://") or database_url.startswith("postgresql://"):
        return database_url
    raise RuntimeError("The destination must use a PostgreSQL libpq-compatible URL.")


def _check_destination(database_url: str) -> dict[str, Any]:
    engine = _engine(database_url)
    with engine.connect() as connection:
        identity = connection.execute(
            text("SELECT current_database() AS database_name, current_user AS role_name")
        ).mappings().one()
        if identity["database_name"] != EXPECTED_DESTINATION:
            raise RuntimeError("Connected PostgreSQL database is not claimguard_pg.")
        users = connection.execute(
            text("SELECT id, email, hashed_password, role, is_verified, is_active, created_at, extra_json FROM users")
        ).mappings().all()
    return {"database": identity["database_name"], "role": identity["role_name"], "users": [dict(row) for row in users]}


def _sqlite_connection(source: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(source)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _source_users(source: Path) -> list[dict[str, Any]]:
    connection = _sqlite_connection(source)
    try:
        rows = connection.execute(
            "SELECT id, full_name, email, hashed_password, role, is_verified, is_active, created_at, extra_json FROM users ORDER BY created_at, email"
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def _validate_source_users(users: list[dict[str, Any]]) -> None:
    if len(users) != 6:
        raise RuntimeError(f"Expected exactly 6 SQLite users; found {len(users)}.")
    ids = [str(user["id"]).strip() for user in users]
    emails = [str(user["email"]).strip().lower() for user in users]
    if len(set(ids)) != len(ids):
        raise RuntimeError("SQLite source contains duplicate user IDs.")
    if len(set(emails)) != len(emails):
        raise RuntimeError("SQLite source contains duplicate normalized emails.")
    if any(not user["hashed_password"] for user in users):
        raise RuntimeError("SQLite source contains a user without a password hash.")


def _json_overlap(users: Iterable[dict[str, Any]]) -> int:
    if not JSON_USERS_FILE.is_file():
        return 0
    records = json.loads(JSON_USERS_FILE.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise RuntimeError("users.json must contain a list.")
    source_keys = {
        (str(user["id"]), str(user["email"]).strip().lower()) for user in users
    }
    return sum(
        (str(record.get("id")), str(record.get("email", "")).strip().lower()) in source_keys
        for record in records
        if isinstance(record, dict)
    )


def backup_and_verify_source(source: Path, backup_dir: Path) -> Path:
    """Create and verify a SQLite backup; retained for existing tests."""
    source = _source_path(source)
    backup_dir = backup_dir.expanduser().resolve()
    if PROJECT_ROOT == backup_dir or PROJECT_ROOT in backup_dir.parents:
        raise RuntimeError("Backups must be stored outside the active project.")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{source.stem}.sqlite.backup"
    shutil.copy2(source, backup)
    if _sha256(source) != _sha256(backup):
        raise RuntimeError("SQLite backup SHA-256 does not match the source.")
    connection = sqlite3.connect(backup)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    if integrity != "ok":
        raise RuntimeError(f"SQLite backup failed integrity check: {integrity}")
    return backup


def _find_tool(name: str) -> Path:
    candidates = [
        shutil.which(name),
        rf"C:\Program Files\PostgreSQL\18\bin\{name}",
        rf"C:\Program Files\PostgreSQL\17\bin\{name}",
        rf"C:\Program Files\PostgreSQL\16\bin\{name}",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise RuntimeError(f"{name} was not found on PATH or supported PostgreSQL bin directories.")


def _run_hidden(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def backup_and_verify_postgres(database_url: str, backup_dir: Path) -> Path:
    destination = _destination_name(database_url)
    _check_destination(database_url)
    backup = backup_dir / f"{destination}.dump"
    pg_dump = _find_tool("pg_dump.exe")
    pg_restore = _find_tool("pg_restore.exe")
    _run_hidden([str(pg_dump), "--format=custom", "--file", str(backup), "--dbname", _pg_dump_url(database_url)])
    if not backup.is_file() or backup.stat().st_size == 0:
        raise RuntimeError("PostgreSQL backup is missing or empty.")
    listing = _run_hidden([str(pg_restore), "--list", str(backup)])
    if not listing.stdout.strip():
        raise RuntimeError("pg_restore could not read the PostgreSQL backup archive.")
    return backup


def create_verified_backups(source: Path, database_url: str, backup_dir: Path) -> dict[str, Any]:
    source = _source_path(source, require_dedicated=True)
    backup_dir = backup_dir.expanduser().resolve()
    if PROJECT_ROOT == backup_dir or PROJECT_ROOT in backup_dir.parents:
        raise RuntimeError("Backups must be stored outside the active project.")
    backup_dir.mkdir(parents=True, exist_ok=True)
    sqlite_backup = backup_and_verify_source(source, backup_dir)
    postgres_backup = backup_and_verify_postgres(database_url, backup_dir)
    connection = sqlite3.connect(sqlite_backup)
    try:
        sqlite_integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    destination = _check_destination(database_url)
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "source_sha256": _sha256(source),
        "source_backup": str(sqlite_backup),
        "source_backup_sha256": _sha256(sqlite_backup),
        "source_integrity": sqlite_integrity,
        "destination_database": destination["database"],
        "destination_role": destination["role"],
        "postgres_backup": str(postgres_backup),
        "postgres_backup_size": postgres_backup.stat().st_size,
    }
    (backup_dir / "backup_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _verify_manifest(backup_dir: Path, database_url: str) -> dict[str, Any]:
    manifest_path = backup_dir.expanduser().resolve() / "backup_manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("Verified backup manifest is required before apply or dry-run.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = _source_path(Path(manifest["source"]), require_dedicated=True)
    if manifest["source_sha256"] != _sha256(source):
        raise RuntimeError("Source changed after the verified backup was created.")
    sqlite_backup = Path(manifest["source_backup"])
    if _sha256(sqlite_backup) != manifest["source_backup_sha256"]:
        raise RuntimeError("Verified SQLite backup changed.")
    if manifest["source_integrity"] != "ok":
        raise RuntimeError("SQLite backup integrity was not verified.")
    if manifest["destination_database"] != EXPECTED_DESTINATION:
        raise RuntimeError("Backup manifest destination is not claimguard_pg.")
    if not Path(manifest["postgres_backup"]).is_file() or int(manifest["postgres_backup_size"]) <= 0:
        raise RuntimeError("Verified PostgreSQL backup is missing or empty.")
    _destination_name(database_url)
    return manifest


def _collision_report(source_users: list[dict[str, Any]], destination: dict[str, Any]) -> dict[str, Any]:
    source_ids = {str(user["id"]).strip() for user in source_users}
    source_emails = {str(user["email"]).strip().lower() for user in source_users}
    dest_ids = {str(user["id"]).strip() for user in destination["users"]}
    dest_emails = {str(user["email"]).strip().lower() for user in destination["users"]}
    return {
        "source_users": len(source_users),
        "destination_users": len(destination["users"]),
        "id_conflicts": len(source_ids & dest_ids),
        "email_conflicts": len(source_emails & dest_emails),
        "proposed_inserts": len(source_ids - dest_ids),
        "json_duplicate_users_skipped": _json_overlap(source_users),
        "source_anonymous_ids": sorted(_anonymous(value) for value in source_ids),
    }


def _decode_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _json_equal(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True, ensure_ascii=False, default=str) == json.dumps(
        right,
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )


def _invoice_columns(invoice: dict[str, Any]) -> dict[str, Any]:
    extracted = invoice.get("extracted_data")
    extracted = extracted if isinstance(extracted, dict) else {}
    total = (
        extracted.get("total_amount")
        if extracted.get("total_amount") is not None
        else extracted.get("total")
        if extracted.get("total") is not None
        else extracted.get("grand_total")
        if extracted.get("grand_total") is not None
        else invoice.get("total_amount")
    )
    return {
        "uploaded_by": invoice.get("uploaded_by"),
        "invoice_number": extracted.get("invoice_number") or invoice.get("invoice_number"),
        "vendor_name": extracted.get("vendor_name") or invoice.get("vendor_name"),
        "invoice_date": (
            extracted.get("invoice_date")
            or extracted.get("date")
            or invoice.get("invoice_date")
        ),
        "total_amount": total,
        "status": invoice.get("status"),
        "risk_score": invoice.get("risk_score"),
        "risk_level": invoice.get("risk_level"),
        "uploaded_at": invoice.get("uploaded_at"),
    }


def _source_records(source: Path) -> dict[str, list[dict[str, Any]]]:
    connection = _sqlite_connection(_source_path(source, require_dedicated=True))
    try:
        return {
            table: [dict(row) for row in connection.execute(f"SELECT * FROM {table}").fetchall()]
            for table in (
                "users",
                "otp_records",
                "invoices",
                "invoice_documents",
                "invoice_anomalies",
                "invoice_decisions",
            )
        }
    finally:
        connection.close()


def _record_disposition(counter: dict[str, int], name: str) -> None:
    counter[name] = counter.get(name, 0) + 1


def _same_column_value(field: str, left: Any, right: Any) -> bool:
    if field == "total_amount":
        try:
            return float(left) == float(right)
        except (TypeError, ValueError):
            pass
    return str(left) == str(right)


def reconcile_all_sources(
    source: Path,
    database_url: str,
    backup_dir: Path,
    *,
    apply: bool,
) -> dict[str, Any]:
    """Reconcile every preserved source and optionally apply safe repairs."""

    _verify_manifest(backup_dir, database_url)
    source = _source_path(source, require_dedicated=True)
    sqlite_rows = _source_records(source)
    json_invoices = json.loads((source.parent / "invoices.json").read_text(encoding="utf-8"))
    json_users = json.loads((source.parent / "users.json").read_text(encoding="utf-8"))
    if not isinstance(json_invoices, list) or not isinstance(json_users, list):
        raise RuntimeError("Legacy JSON stores must contain lists.")

    engine = _engine(database_url)
    dispositions: dict[str, dict[str, int]] = {}
    conflicts: list[str] = []
    updates: list[tuple[str, dict[str, Any]]] = []

    with engine.connect() as connection:
        identity = connection.execute(
            text("SELECT current_database() AS database_name")
        ).scalar_one()
        if identity != EXPECTED_DESTINATION:
            raise RuntimeError("Connected PostgreSQL database is not claimguard_pg.")

        pg_users = {
            str(row["id"]): dict(row)
            for row in connection.execute(text("SELECT * FROM users")).mappings()
        }
        pg_users_by_email = {
            str(row["email"]).strip().lower(): row for row in pg_users.values()
        }
        for source_user in sqlite_rows["users"] + json_users:
            source_id = str(source_user.get("id", "")).strip()
            source_email = str(source_user.get("email", "")).strip().lower()
            match = pg_users.get(source_id) or pg_users_by_email.get(source_email)
            if match is None:
                _record_disposition(dispositions.setdefault("users", {}), "new")
                if apply:
                    connection.execute(
                        text("""INSERT INTO users
                            (id, full_name, email, hashed_password, role, is_verified, is_active, created_at, extra_json)
                            VALUES (:id, :full_name, :email, :hashed_password, :role, :is_verified, :is_active, :created_at, :extra_json)"""),
                        {
                            "id": source_id,
                            "full_name": source_user.get("full_name") or "",
                            "email": source_email,
                            "hashed_password": source_user.get("hashed_password") or "",
                            "role": source_user.get("role") or "user",
                            "is_verified": bool(source_user.get("is_verified")),
                            "is_active": bool(source_user.get("is_active")),
                            "created_at": source_user.get("created_at"),
                            "extra_json": source_user.get("extra_json") or "{}",
                        },
                    )
                continue
            if (
                str(match["id"]) != source_id
                or str(match["email"]).strip().lower() != source_email
                or match["hashed_password"] != source_user.get("hashed_password")
            ):
                conflicts.append(f"user:{_anonymous(source_id)}")
            else:
                _record_disposition(dispositions.setdefault("users", {}), "duplicate_confirmed")

        pg_invoices = {
            str(row["invoice_id"]): dict(row)
            for row in connection.execute(text("SELECT * FROM invoices")).mappings()
        }
        canonical_invoices = {
            str(invoice.get("invoice_id")): invoice
            for invoice in json_invoices
            if isinstance(invoice, dict) and invoice.get("invoice_id")
        }
        for invoice_id, source_invoice in canonical_invoices.items():
            pg_invoice = pg_invoices.get(invoice_id)
            if pg_invoice is None:
                _record_disposition(dispositions.setdefault("invoices", {}), "new")
                if not apply:
                    continue
                columns = _invoice_columns(source_invoice)
                connection.execute(
                    text("""INSERT INTO invoices
                        (invoice_id, uploaded_by, invoice_number, vendor_name, invoice_date, total_amount,
                         status, risk_score, risk_level, uploaded_at, record_json)
                        VALUES (:invoice_id, :uploaded_by, :invoice_number, :vendor_name, :invoice_date,
                                :total_amount, :status, :risk_score, :risk_level, :uploaded_at, :record_json)"""),
                    {**columns, "invoice_id": invoice_id, "record_json": json.dumps(source_invoice, ensure_ascii=False)},
                )
                continue

            stored = _decode_json(pg_invoice["record_json"])
            if not isinstance(stored, dict):
                conflicts.append(f"invoice-payload:{_anonymous(invoice_id)}")
                continue
            if not _json_equal(stored, source_invoice):
                merged = dict(stored)
                for key, value in source_invoice.items():
                    if merged.get(key) in (None, "", [], {}):
                        merged[key] = value
                    elif value not in (None, "", [], {}) and not _json_equal(merged[key], value):
                        conflicts.append(f"invoice-field:{_anonymous(invoice_id)}:{key}")
                if merged != stored:
                    updates.append((invoice_id, merged))
                    _record_disposition(dispositions.setdefault("invoices", {}), "merged")
                else:
                    _record_disposition(dispositions.setdefault("invoices", {}), "duplicate_confirmed")
            else:
                _record_disposition(dispositions.setdefault("invoices", {}), "duplicate_confirmed")

            expected = _invoice_columns(source_invoice)
            for field, value in expected.items():
                existing = pg_invoice.get(field)
                if (
                    value not in (None, "")
                    and existing not in (None, "")
                    and not _same_column_value(field, existing, value)
                ):
                    conflicts.append(f"invoice-column:{_anonymous(invoice_id)}:{field}")
                elif value not in (None, "") and existing in (None, ""):
                    updates.append((invoice_id, {field: value}))

        for source_invoice in sqlite_rows["invoices"]:
            invoice_id = str(source_invoice.get("invoice_id", ""))
            if invoice_id not in pg_invoices:
                conflicts.append(f"sqlite-invoice-missing:{_anonymous(invoice_id)}")
            else:
                _record_disposition(dispositions.setdefault("sqlite_invoices", {}), "merged_into_canonical")

        pg_docs = {
            str(row["invoice_id"]): dict(row)
            for row in connection.execute(text("SELECT * FROM invoice_documents")).mappings()
        }
        for source_doc in sqlite_rows["invoice_documents"]:
            invoice_id = str(source_doc["invoice_id"])
            existing = pg_docs.get(invoice_id)
            if existing is None:
                conflicts.append(f"document-missing:{_anonymous(invoice_id)}")
            elif any(
                source_doc.get(field) not in (None, "")
                and existing.get(field) not in (None, "")
                and str(source_doc.get(field)) != str(existing.get(field))
                for field in ("original_filename", "stored_filename", "file_path", "file_size", "file_extension")
            ):
                conflicts.append(f"document-conflict:{_anonymous(invoice_id)}")
            else:
                _record_disposition(dispositions.setdefault("documents", {}), "duplicate_or_merged")

        pg_decisions = {
            str(row["invoice_id"]): dict(row)
            for row in connection.execute(text("SELECT * FROM invoice_decisions")).mappings()
        }
        for source_decision in sqlite_rows["invoice_decisions"]:
            invoice_id = str(source_decision["invoice_id"])
            existing = pg_decisions.get(invoice_id)
            if existing is None or not _json_equal(
                _decode_json(existing["decision_json"]),
                _decode_json(source_decision["decision_json"]),
            ):
                conflicts.append(f"decision-conflict:{_anonymous(invoice_id)}")
            else:
                _record_disposition(dispositions.setdefault("decisions", {}), "duplicate_confirmed")

        pg_anomalies = [
            dict(row)
            for row in connection.execute(text("SELECT * FROM invoice_anomalies")).mappings()
        ]
        for source_anomaly in sqlite_rows["invoice_anomalies"]:
            matches = [
                row for row in pg_anomalies
                if str(row["invoice_id"]) == str(source_anomaly["invoice_id"])
                and row["anomaly_type"] == source_anomaly["anomaly_type"]
                and row["severity"] == source_anomaly["severity"]
                and row["message"] == source_anomaly["message"]
            ]
            if not matches:
                conflicts.append(f"anomaly-missing:{_anonymous(source_anomaly['invoice_id'])}")
            else:
                _record_disposition(dispositions.setdefault("anomalies", {}), "duplicate_confirmed")

        pg_otps = {
            str(row["email"]).strip().lower(): dict(row)
            for row in connection.execute(text("SELECT * FROM otp_records")).mappings()
        }
        for source_otp in sqlite_rows["otp_records"]:
            existing = pg_otps.get(str(source_otp["email"]).strip().lower())
            if existing is None or any(
                str(existing[field]) != str(source_otp[field])
                for field in ("otp", "expires_at", "purpose")
            ):
                conflicts.append(f"otp-conflict:{_anonymous(source_otp['email'])}")
            else:
                _record_disposition(dispositions.setdefault("otp_records", {}), "duplicate_confirmed")

        if conflicts:
            connection.rollback()
            raise RuntimeError(
                "Unresolved migration conflicts; no writes performed: "
                + ", ".join(sorted(set(conflicts)))
            )

        if apply:
            for invoice_id, values in updates:
                assignments = ", ".join(f"{key} = :{key}" for key in values)
                connection.execute(
                    text(f"UPDATE invoices SET {assignments} WHERE invoice_id = :invoice_id"),
                    {**values, "invoice_id": invoice_id},
                )
            connection.commit()
        else:
            connection.rollback()

    result = {
        "mode": "apply" if apply else "dry-run",
        "backup_verified": True,
        "destination_database": EXPECTED_DESTINATION,
        "dispositions": dispositions,
        "pending_projection_updates": len(updates),
        "writes_performed": len(updates) if apply else 0,
        "source_record_counts": {table: len(rows) for table, rows in sqlite_rows.items()},
        "json_invoice_count": len(canonical_invoices),
        "unresolved_conflicts": 0,
    }
    (backup_dir / "migration_manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return result


def dry_run(source: Path, database_url: str, backup_dir: Path) -> dict[str, Any]:
    _verify_manifest(backup_dir, database_url)
    source_users = _source_users(_source_path(source, require_dedicated=True))
    _validate_source_users(source_users)
    destination = _check_destination(database_url)
    collisions = _collision_report(source_users, destination)
    if collisions["id_conflicts"] or collisions["email_conflicts"]:
        raise RuntimeError("Fresh collision check failed; no writes are permitted.")
    return {
        "mode": "dry-run",
        "backup_verified": True,
        "backup_manifest": str((backup_dir / "backup_manifest.json").resolve()),
        "source_database": str(_source_path(source, require_dedicated=True)),
        "destination_database": destination["database"],
        **collisions,
        "invoice_inserts": 0,
        "invoice_updates": 0,
        "otp_inserts": 0,
        "otp_updates": 0,
        "existing_postgresql_records_preserved": True,
        "writes_performed": 0,
    }


def apply_users(source: Path, database_url: str, backup_dir: Path) -> dict[str, Any]:
    _verify_manifest(backup_dir, database_url)
    source_users = _source_users(_source_path(source, require_dedicated=True))
    _validate_source_users(source_users)
    engine = _engine(database_url)
    with engine.begin() as connection:
        identity = connection.execute(text("SELECT current_database() AS database_name")).scalar()
        if identity != EXPECTED_DESTINATION:
            raise RuntimeError("Destination changed before apply.")
        existing = connection.execute(text("SELECT id, email FROM users")).mappings().all()
        existing_ids = {str(row["id"]).strip() for row in existing}
        existing_emails = {str(row["email"]).strip().lower() for row in existing}
        source_ids = {str(user["id"]).strip() for user in source_users}
        source_emails = {str(user["email"]).strip().lower() for user in source_users}
        if source_ids & existing_ids or source_emails & existing_emails:
            raise RuntimeError("Destination collision detected immediately before insertion.")
        for user in source_users:
            connection.execute(
                text("""INSERT INTO users
                    (id, full_name, email, hashed_password, role, is_verified, is_active, created_at, extra_json)
                    VALUES (:id, :full_name, :email, :hashed_password, :role, :is_verified, :is_active, :created_at, :extra_json)"""),
                {
                    "id": str(user["id"]).strip(),
                    "full_name": str(user["full_name"] or "").strip(),
                    "email": str(user["email"]).strip().lower(),
                    "hashed_password": user["hashed_password"],
                    "role": user["role"] or "user",
                    "is_verified": int(bool(user["is_verified"])),
                    "is_active": int(bool(user["is_active"])),
                    "created_at": user["created_at"],
                    "extra_json": user["extra_json"] or "{}",
                },
            )
    return {"mode": "apply", "inserted_users": len(source_users), "writes_performed": len(source_users)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--backup-only", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--source", type=Path, default=DATABASE_FILE)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--confirm-destination")
    args = parser.parse_args()
    _destination_name(args.database_url)
    if args.apply and args.confirm_destination != EXPECTED_DESTINATION:
        parser.error("--apply requires --confirm-destination claimguard_pg")
    if args.backup_only:
        result = create_verified_backups(args.source, args.database_url, args.backup_dir)
    elif args.dry_run:
        result = reconcile_all_sources(
            args.source,
            args.database_url,
            args.backup_dir,
            apply=False,
        )
    else:
        result = reconcile_all_sources(
            args.source,
            args.database_url,
            args.backup_dir,
            apply=True,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

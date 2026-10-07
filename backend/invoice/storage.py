import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


from data.database import (
    LEGACY_INVOICES_FILE,
    get_connection,
    initialize_and_migrate,
)


# =========================================================
# STORAGE INITIALIZATION
# =========================================================

def ensure_invoice_storage() -> None:
    """
    Initialize the SQLite database and migrate the legacy
    invoices.json file once when needed.
    """

    initialize_and_migrate()


# =========================================================
# JSON HELPERS
# =========================================================

def _decode_json_object(
    value: str | None
) -> dict[str, Any]:

    if not value:

        return {}

    try:

        data = json.loads(
            value
        )

    except (
        json.JSONDecodeError,
        TypeError
    ):

        return {}

    return (
        data
        if isinstance(
            data,
            dict
        )
        else {}
    )


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


def _invoice_number(
    invoice: dict[str, Any]
) -> Any:

    data = _invoice_data(
        invoice
    )

    return (
        data.get(
            "invoice_number"
        )
        or invoice.get(
            "invoice_number"
        )
    )


def _vendor_name(
    invoice: dict[str, Any]
) -> Any:

    data = _invoice_data(
        invoice
    )

    return (
        data.get(
            "vendor_name"
        )
        or invoice.get(
            "vendor_name"
        )
    )


def _invoice_total(
    invoice: dict[str, Any]
) -> float | None:

    data = _invoice_data(
        invoice
    )

    if data.get(
        "total"
    ) is not None:

        return _safe_number(
            data.get(
                "total"
            )
        )

    if data.get(
        "grand_total"
    ) is not None:

        return _safe_number(
            data.get(
                "grand_total"
            )
        )

    return _safe_number(
        invoice.get(
            "total"
        )
    )


# =========================================================
# ROW CONVERSION
# =========================================================

def _row_to_invoice(
    row: Any,
    connection: Any
) -> dict[str, Any]:

    record = _decode_json_object(
        row["record_json"]
    )

    # Keep the record JSON as the authoritative source for the
    # existing application while ensuring core indexed fields
    # are available even if an old record is incomplete.

    if not record.get(
        "invoice_id"
    ):

        record[
            "invoice_id"
        ] = row[
            "invoice_id"
        ]

    if not record.get(
        "uploaded_by"
    ) and row[
        "uploaded_by"
    ]:

        record[
            "uploaded_by"
        ] = row[
            "uploaded_by"
        ]


    # -----------------------------------------------------
    # Document metadata
    # -----------------------------------------------------

    document = connection.execute(
        """
        SELECT
            original_filename,
            stored_filename,
            file_path,
            file_size,
            file_extension
        FROM invoice_documents
        WHERE invoice_id = ?
        """,
        (
            row[
                "invoice_id"
            ],
        )
    ).fetchone()

    if document:

        record.setdefault(
            "original_filename",
            document["original_filename"]
        )

        record.setdefault(
            "stored_filename",
            document["stored_filename"]
        )

        record.setdefault(
            "file_path",
            document["file_path"]
        )

        record.setdefault(
            "file_size",
            document["file_size"]
        )

        record.setdefault(
            "file_extension",
            document["file_extension"]
        )


    # -----------------------------------------------------
    # Anomalies
    # -----------------------------------------------------

    anomaly_rows = connection.execute(
        """
        SELECT
            anomaly_type,
            severity,
            score_contribution,
            message,
            evidence_json
        FROM invoice_anomalies
        WHERE invoice_id = ?
        ORDER BY anomaly_id ASC
        """,
        (
            row[
                "invoice_id"
            ],
        )
    ).fetchall()

    if anomaly_rows:

        record[
            "anomalies"
        ] = [
            {
                "anomaly_type": anomaly["anomaly_type"],
                "severity": anomaly["severity"],
                "score_contribution": anomaly["score_contribution"],
                "message": anomaly["message"],
                "evidence": _decode_json_object(
                    anomaly["evidence_json"]
                ),
            }
            for anomaly in anomaly_rows
        ]


    # -----------------------------------------------------
    # Decision
    # -----------------------------------------------------

    decision_row = connection.execute(
        """
        SELECT decision_json
        FROM invoice_decisions
        WHERE invoice_id = ?
        """,
        (
            row[
                "invoice_id"
            ],
        )
    ).fetchone()

    if decision_row:

        record[
            "decision"
        ] = _decode_json_object(
            decision_row[
                "decision_json"
            ]
        )


    return record


# =========================================================
# READ INVOICES
# =========================================================

def read_invoices() -> list[dict[str, Any]]:
    """
    Read all invoices from SQLite while preserving the exact
    dictionary shape used by the existing invoice routes.
    """

    ensure_invoice_storage()

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT
                invoice_id,
                uploaded_by,
                record_json
            FROM invoices
            ORDER BY uploaded_at ASC, invoice_id ASC
            """
        ).fetchall()

        return [
            _row_to_invoice(
                row,
                connection
            )
            for row in rows
        ]

    finally:

        connection.close()


# =========================================================
# WRITE ONE INVOICE
# =========================================================

def _write_invoice_row(
    connection: Any,
    invoice: dict[str, Any]
) -> None:

    invoice_id = str(
        invoice.get(
            "invoice_id",
            ""
        )
    ).strip()

    if not invoice_id:

        raise ValueError(
            "Every invoice must contain an invoice_id."
        )

    data = _invoice_data(
        invoice
    )

    total_amount = _invoice_total(
        invoice
    )

    risk_score = _safe_number(
        invoice.get(
            "risk_score"
        )
    )

    connection.execute(
        """
        INSERT INTO invoices (
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
        ON CONFLICT(invoice_id) DO UPDATE SET
            uploaded_by = excluded.uploaded_by,
            invoice_number = excluded.invoice_number,
            vendor_name = excluded.vendor_name,
            invoice_date = excluded.invoice_date,
            total_amount = excluded.total_amount,
            status = excluded.status,
            risk_score = excluded.risk_score,
            risk_level = excluded.risk_level,
            uploaded_at = excluded.uploaded_at,
            record_json = excluded.record_json
        """,
        (
            invoice_id,
            invoice.get(
                "uploaded_by"
            ),
            _invoice_number(
                invoice
            ),
            _vendor_name(
                invoice
            ),
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


    # -----------------------------------------------------
    # Document
    # -----------------------------------------------------

    connection.execute(
        """
        INSERT INTO invoice_documents (
            invoice_id,
            original_filename,
            stored_filename,
            file_path,
            file_size,
            file_extension
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(invoice_id) DO UPDATE SET
            original_filename = excluded.original_filename,
            stored_filename = excluded.stored_filename,
            file_path = excluded.file_path,
            file_size = excluded.file_size,
            file_extension = excluded.file_extension
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


    # -----------------------------------------------------
    # Anomalies
    # -----------------------------------------------------

    connection.execute(
        "DELETE FROM invoice_anomalies WHERE invoice_id = ?",
        (
            invoice_id,
        )
    )

    anomalies = invoice.get(
        "anomalies"
    )

    if not isinstance(
        anomalies,
        list
    ):

        anomalies = []

    for anomaly in anomalies:

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


    # -----------------------------------------------------
    # Decision
    # -----------------------------------------------------

    connection.execute(
        "DELETE FROM invoice_decisions WHERE invoice_id = ?",
        (
            invoice_id,
        )
    )

    decision = invoice.get(
        "decision"
    )

    if decision is not None:

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
                json.dumps(
                    decision,
                    ensure_ascii=False
                ),
                invoice.get(
                    "uploaded_at"
                )
                or datetime.now(
                    timezone.utc
                ).isoformat(),
            )
        )


# =========================================================
# WRITE INVOICES
# =========================================================

def write_invoices(
    invoices: list[dict[str, Any]]
) -> None:
    """
    Persist the supplied invoice collection to SQLite.

    The existing route API expects write_invoices() to replace
    the stored collection, so this implementation preserves
    that behavior while maintaining normalized helper tables.
    """

    ensure_invoice_storage()

    if not isinstance(
        invoices,
        list
    ):

        raise ValueError(
            "Invoices must be provided as a list."
        )

    connection = get_connection()

    try:

        connection.execute(
            "BEGIN"
        )

        # Existing application semantics: the supplied list is
        # the authoritative current invoice collection.
        connection.execute(
            "DELETE FROM invoices"
        )

        for invoice in invoices:

            if not isinstance(
                invoice,
                dict
            ):

                continue

            _write_invoice_row(
                connection,
                invoice
            )

        connection.commit()

    except Exception:

        connection.rollback()
        raise

    finally:

        connection.close()


__all__ = [
    "ensure_invoice_storage",
    "read_invoices",
    "write_invoices",
    "LEGACY_INVOICES_FILE",
]

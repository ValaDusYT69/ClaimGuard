import json
import csv
from io import StringIO
from io import BytesIO
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import jwt

from fastapi.responses import StreamingResponse

from fastapi import (
    APIRouter,
    File,
    Header,
    HTTPException,
    UploadFile,
    status,
)

from pydantic import BaseModel, Field

from config import SECRET_KEY
from auth.storage import read_users

from invoice.extractor import (
    extract_invoice_data,
)

from invoice.verification import (
    verify_invoice,
)

from invoice.market_research import (
    analyze_market_price,
)

from invoice.risk_engine import (
    analyze_invoice_risk,
)

from invoice.report_service import (
    build_invoice_report,
)

from data.database import (
    get_connection,
    initialize_and_migrate,
)


# =========================================================
# ROUTER
# =========================================================

router = APIRouter(
    prefix="/api/invoices",
    tags=["Invoices"],
)


# =========================================================
# REVIEW DECISION SUPPORT
# =========================================================

class InvoiceVerificationResponseRequest(BaseModel):
    """
    Additional information submitted by the invoice owner after
    Finance/Reviewer requests verification.
    """

    note: str = Field(
        default="",
        max_length=3000
    )


class InvoiceDecisionRequest(BaseModel):
    """
    Review decision submitted by an authorized reviewer.
    """

    decision: Literal[
        "approved",
        "rejected",
        "request_verification",
    ]

    note: str = Field(
        default="",
        max_length=2000
    )


def normalize_role_name(role: Any) -> str:
    """
    Normalize roles from legacy UI aliases to a single canonical form.
    """

    normalized = str(role or "").strip().lower()
    normalized = normalized.replace("_", "-").replace("/", "-").replace(" ", "-")

    while "--" in normalized:
        normalized = normalized.replace("--", "-")

    normalized = normalized.strip("-")

    aliases = {
        "admin": "admin",
        "administrator": "admin",
        "reviewer": "reviewer",
        "finance": "reviewer",
        "finance-reviewer": "reviewer",
        "finance-reviewer-role": "reviewer",
        "finance-reviewer-role-name": "reviewer",
        "user": "user",
    }

    return aliases.get(normalized, normalized or "user")


REVIEWER_ROLES = {
    "admin",
    "reviewer",
}


def require_invoice_upload_access(
    user: dict[str, Any]
) -> None:
    """
    Only Normal User accounts are allowed to create/upload invoices.

    Admin and Finance/Reviewer accounts are restricted to their
    management/review responsibilities and must not create invoice
    submissions.
    """

    role = normalize_role_name(
        user.get(
            "role",
            ""
        )
    )

    if role != "user":

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Only Normal User accounts can upload invoices."
            )
        )


def require_reviewer_access(
    user: dict[str, Any]
) -> None:
    """
    Only Admin and Finance/Reviewer accounts can make
    invoice review decisions.
    """

    role = normalize_role_name(
        user.get(
            "role",
            ""
        )
    )

    if role not in REVIEWER_ROLES:

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Reviewer access is required for this action."
            )
        )


def can_view_any_invoice(
    user: dict[str, Any]
) -> bool:
    """
    Admin and Finance/Reviewer accounts can inspect invoices
    uploaded by other users.
    """

    role = normalize_role_name(
        user.get(
            "role",
            ""
        )
    )

    return role in REVIEWER_ROLES


# =========================================================
# PATHS
# =========================================================

BASE_DIR = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

DATA_DIR = (
    BASE_DIR / "data"
)

INVOICES_FILE = (
    DATA_DIR / "invoices.json"
)

UPLOAD_DIR = (
    BASE_DIR / "uploads"
)


# =========================================================
# SETTINGS
# =========================================================

MAX_FILE_SIZE = (
    10 * 1024 * 1024
)

ALLOWED_EXTENSIONS = {

    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".xls",
    ".xlsx",

}


# =========================================================
# STORAGE HELPERS
# =========================================================

def ensure_invoice_storage() -> None:
    """
    Initialize ClaimGuard's SQLite database and migrate legacy
    JSON data when needed.

    The legacy invoices.json file is preserved by database.py
    as a backup/migration source.
    """

    initialize_and_migrate()


def _decode_json_object(
    value: Any
) -> dict[str, Any]:
    """
    Safely decode a JSON object stored in SQLite.
    """

    if isinstance(
        value,
        dict
    ):

        return value

    if not value:

        return {}

    try:

        data = json.loads(
            str(value)
        )

    except (
        json.JSONDecodeError,
        TypeError
    ):

        return {}

    if isinstance(
        data,
        dict
    ):

        return data

    return {}


def _safe_number(
    value: Any
) -> float | None:
    """
    Convert a value to float without raising.
    """

    if value is None or value == "":

        return None

    try:

        return float(
            value
        )

    except (
        TypeError,
        ValueError
    ):

        return None


def _invoice_data(
    invoice: dict[str, Any]
) -> dict[str, Any]:
    """
    Return the extracted invoice data object.
    """

    value = invoice.get(
        "extracted_data"
    )

    if isinstance(
        value,
        dict
    ):

        return value

    return {}


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


def _invoice_date(
    invoice: dict[str, Any]
) -> Any:
    data = _invoice_data(
        invoice
    )

    return (
        data.get(
            "invoice_date"
        )
        or data.get(
            "date"
        )
        or invoice.get(
            "invoice_date"
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
# AUTOMATIC FINANCE REVIEW ROUTING
# =========================================================

REVIEW_TRIGGER_STATUSES = {
    "possible_duplicate",
    "verification_failed",
    "verification_required",
    "verification_error",
    "extraction_failed",
    "no_text_found",
}


def _review_trigger_reasons(
    risk_analysis: dict[str, Any],
    verification_status: str | None,
    extraction_error: str | None,
    extraction_status: str | None,
) -> list[str]:
    """
    Build transparent reasons for sending an invoice to Finance/Reviewer.
    """

    reasons: list[str] = []

    risk_score = _safe_number(
        risk_analysis.get(
            "risk_score"
        )
    )

    risk_level = str(
        risk_analysis.get(
            "risk_level",
            ""
        )
    ).strip().lower()

    anomalies = risk_analysis.get(
        "anomalies",
        []
    )

    if not isinstance(
        anomalies,
        list
    ):
        anomalies = []

    if risk_score is not None and risk_score >= 40:
        reasons.append(
            f"Risk score is {risk_score:.2f}, which reaches the review threshold."
        )

    if risk_level in {
        "medium",
        "high",
    }:
        reasons.append(
            f"Risk level is {risk_level.upper()}."
        )

    if anomalies:
        reasons.append(
            f"{len(anomalies)} anomaly finding(s) were detected."
        )

    normalized_verification_status = str(
        verification_status
        or ""
    ).strip().lower()

    if normalized_verification_status in REVIEW_TRIGGER_STATUSES:
        reasons.append(
            "Document verification requires manual attention."
        )

    if extraction_error:
        reasons.append(
            "Automatic extraction failed and requires manual review."
        )

    if str(
        extraction_status
        or ""
    ).strip().lower() in {
        "no_text_found",
        "extraction_failed",
    }:
        reasons.append(
            "The invoice could not be fully processed automatically."
        )

    ai_analysis = risk_analysis.get(
        "ai_analysis"
    )

    if not isinstance(
        ai_analysis,
        dict
    ):
        ai_analysis = risk_analysis.get(
            "ml_engine",
            {}
        )

    ai_status = str(
        ai_analysis.get(
            "status",
            ""
        )
    ).strip().lower()

    ai_score = _safe_number(
        ai_analysis.get(
            "score"
        )
    )

    if (
        ai_status == "scored"
        and ai_score is not None
        and ai_score >= 60
    ):
        reasons.append(
            f"Local AI anomaly scoring marked the invoice as unusual (AI score {ai_score:.2f})."
        )

    unique_reasons: list[str] = []

    for reason in reasons:
        if reason not in unique_reasons:
            unique_reasons.append(reason)

    return unique_reasons


def _should_route_to_finance_review(
    risk_analysis: dict[str, Any],
    verification_status: str | None,
    extraction_error: str | None,
    extraction_status: str | None,
) -> bool:
    """
    Return True when automated analysis requires Finance/Reviewer attention.
    """

    return bool(
        _review_trigger_reasons(
            risk_analysis=risk_analysis,
            verification_status=verification_status,
            extraction_error=extraction_error,
            extraction_status=extraction_status,
        )
    )


def _invoice_rows_to_records(
    rows: list[Any],
    connection: Any
) -> list[dict[str, Any]]:
    """
    Convert SQLite invoice rows back into the exact record shape
    expected by the existing application.
    """

    invoices: list[dict[str, Any]] = []

    for row in rows:

        record = _decode_json_object(
            row["record_json"]
        )

        # -------------------------------------------------
        # Core fields
        # -------------------------------------------------

        record.setdefault(
            "invoice_id",
            row["invoice_id"]
        )

        if (
            not record.get(
                "uploaded_by"
            )
            and row["uploaded_by"]
        ):

            record[
                "uploaded_by"
            ] = row[
                "uploaded_by"
            ]

        if (
            "status" not in record
            or not record.get("status")
        ):

            record[
                "status"
            ] = row[
                "status"
            ]

        if (
            "risk_score" not in record
            or record.get("risk_score") is None
        ):

            record[
                "risk_score"
            ] = row[
                "risk_score"
            ]

        if (
            "risk_level" not in record
            or record.get("risk_level") is None
        ):

            record[
                "risk_level"
            ] = row[
                "risk_level"
            ]

        if (
            "uploaded_at" not in record
            or not record.get("uploaded_at")
        ):

            record[
                "uploaded_at"
            ] = row[
                "uploaded_at"
            ]

        # -------------------------------------------------
        # Invoice document metadata
        # -------------------------------------------------

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
                document[
                    "original_filename"
                ]
            )

            record.setdefault(
                "stored_filename",
                document[
                    "stored_filename"
                ]
            )

            record.setdefault(
                "file_path",
                document[
                    "file_path"
                ]
            )

            record.setdefault(
                "file_size",
                document[
                    "file_size"
                ]
            )

            record.setdefault(
                "file_extension",
                document[
                    "file_extension"
                ]
            )

        # -------------------------------------------------
        # Anomalies
        # -------------------------------------------------

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

            anomalies: list[dict[str, Any]] = []

            for anomaly_row in anomaly_rows:

                anomalies.append(
                    {
                        "anomaly_type":
                            anomaly_row[
                                "anomaly_type"
                            ],

                        "severity":
                            anomaly_row[
                                "severity"
                            ],

                        "score_contribution":
                            anomaly_row[
                                "score_contribution"
                            ],

                        "message":
                            anomaly_row[
                                "message"
                            ],

                        "evidence":
                            _decode_json_object(
                                anomaly_row[
                                    "evidence_json"
                                ]
                            ),
                    }
                )

            record[
                "anomalies"
            ] = anomalies

        else:

            record.setdefault(
                "anomalies",
                []
            )

        # -------------------------------------------------
        # Decision
        # -------------------------------------------------

        decision_row = connection.execute(
            """
            SELECT
                decision_json
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

            decision_json = _decode_json_object(
                decision_row[
                    "decision_json"
                ]
            )

            record[
                "decision"
            ] = (
                decision_json
                if decision_json
                else None
            )

        else:

            record.setdefault(
                "decision",
                None
            )

        invoices.append(
            record
        )

    return invoices


def read_invoices() -> list[dict[str, Any]]:
    """
    Read invoice records from SQLite.

    The return format remains compatible with the existing
    verification, risk engine and frontend routes.
    """

    ensure_invoice_storage()

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT
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
            FROM invoices
            ORDER BY
                uploaded_at DESC,
                invoice_id DESC
            """
        ).fetchall()

        return _invoice_rows_to_records(
            rows,
            connection
        )

    finally:

        connection.close()


def _write_single_invoice(
    connection: Any,
    invoice: dict[str, Any]
) -> None:
    """
    Upsert one invoice and its child records.
    """

    invoice_id = str(
        invoice.get(
            "invoice_id",
            ""
        )
    ).strip()

    if not invoice_id:

        raise ValueError(
            "Every invoice must contain a valid invoice_id."
        )

    uploaded_by = invoice.get(
        "uploaded_by"
    )

    # -----------------------------------------------------
    # Foreign-key safety for migrated/legacy users
    # -----------------------------------------------------

    if uploaded_by:

        user_exists = connection.execute(
            """
            SELECT 1
            FROM users
            WHERE id = ?
            """,
            (
                uploaded_by,
            )
        ).fetchone()

        if not user_exists:

            uploaded_by = None

    # -----------------------------------------------------
    # Core values
    # -----------------------------------------------------

    invoice_number = _invoice_number(
        invoice
    )

    vendor_name = _vendor_name(
        invoice
    )

    invoice_date = _invoice_date(
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

    risk_level = invoice.get(
        "risk_level"
    )

    status_value = invoice.get(
        "status"
    )

    uploaded_at = invoice.get(
        "uploaded_at"
    )

    record_json = json.dumps(
        invoice,
        ensure_ascii=False
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
        ON CONFLICT(invoice_id)
        DO UPDATE SET
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
            uploaded_by,
            invoice_number,
            vendor_name,
            invoice_date,
            total_amount,
            status_value,
            risk_score,
            risk_level,
            uploaded_at,
            record_json,
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
        ON CONFLICT(invoice_id)
        DO UPDATE SET
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
        """
        DELETE FROM invoice_anomalies
        WHERE invoice_id = ?
        """,
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
        """
        DELETE FROM invoice_decisions
        WHERE invoice_id = ?
        """,
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
                datetime.now(
                    timezone.utc
                ).isoformat(),
            )
        )


def write_invoices(
    invoices: list[dict[str, Any]]
) -> None:
    """
    Persist the supplied invoice collection to SQLite.

    The existing function name is preserved so no current route
    needs to change its public storage interface.
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

        incoming_ids = []

        for invoice in invoices:

            if not isinstance(
                invoice,
                dict
            ):

                continue

            invoice_id = str(
                invoice.get(
                    "invoice_id",
                    ""
                )
            ).strip()

            if not invoice_id:

                continue

            incoming_ids.append(
                invoice_id
            )

            _write_single_invoice(
                connection,
                invoice
            )

        # Mirror the previous JSON-array semantics:
        # records absent from the supplied collection are removed.
        if incoming_ids:

            placeholders = ",".join(
                "?"
                for _ in incoming_ids
            )

            connection.execute(
                f"""
                DELETE FROM invoices
                WHERE invoice_id NOT IN (
                    {placeholders}
                )
                """,
                tuple(
                    incoming_ids
                )
            )

        else:

            connection.execute(
                "DELETE FROM invoices"
            )

        connection.commit()

        # -------------------------------------------------
        # Legacy JSON mirror
        # -------------------------------------------------
        # Keep invoices.json synchronized for the existing project
        # workflow/backups while SQLite remains the authoritative
        # active database. The mirror is written only after the
        # SQLite transaction has committed successfully.

        INVOICES_FILE.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        temp_file = INVOICES_FILE.with_suffix(
            ".json.tmp"
        )

        try:

            temp_file.write_text(
                json.dumps(
                    invoices,
                    ensure_ascii=False,
                    indent=4
                ),
                encoding="utf-8"
            )

            temp_file.replace(
                INVOICES_FILE
            )

        except Exception:

            try:
                if temp_file.exists():
                    temp_file.unlink()
            except OSError:
                pass

            # SQLite is already committed and remains authoritative.
            # Do not roll back a successful invoice write only because
            # the legacy compatibility mirror could not be written.

    except Exception:

        connection.rollback()
        raise

    finally:

        connection.close()



# =========================================================
# AUTHENTICATION
# =========================================================

def get_current_user(
    authorization: str | None,
) -> dict[str, Any]:

    if not authorization:

        raise HTTPException(

            status_code=(
                status.HTTP_401_UNAUTHORIZED
            ),

            detail=(
                "Authentication required."
            )

        )

    if not authorization.startswith(
        "Bearer "
    ):

        raise HTTPException(

            status_code=(
                status.HTTP_401_UNAUTHORIZED
            ),

            detail=(
                "Invalid authorization header."
            )

        )

    token = authorization.split(
        " ",
        1
    )[1]

    try:

        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=["HS256"]
        )

    except jwt.ExpiredSignatureError:

        raise HTTPException(

            status_code=(
                status.HTTP_401_UNAUTHORIZED
            ),

            detail=(
                "Session expired. "
                "Please sign in again."
            )

        )

    except jwt.InvalidTokenError:

        raise HTTPException(

            status_code=(
                status.HTTP_401_UNAUTHORIZED
            ),

            detail=(
                "Invalid authentication token."
            )

        )

    user_id = payload.get(
        "sub"
    )

    if not user_id:

        raise HTTPException(

            status_code=(
                status.HTTP_401_UNAUTHORIZED
            ),

            detail=(
                "Invalid authentication token."
            )

        )

    users = read_users()

    user = next(

        (
            item

            for item in users

            if item.get(
                "id"
            ) == user_id
        ),

        None

    )

    if not user:

        raise HTTPException(

            status_code=(
                status.HTTP_401_UNAUTHORIZED
            ),

            detail=(
                "User account was not found."
            )

        )

    if not user.get(
        "is_verified"
    ):

        raise HTTPException(

            status_code=(
                status.HTTP_403_FORBIDDEN
            ),

            detail=(
                "Email verification is required."
            )

        )

    if not user.get(
        "is_active"
    ):

        raise HTTPException(

            status_code=(
                status.HTTP_403_FORBIDDEN
            ),

            detail=(
                "Your account is inactive."
            )

        )

    return user


# =========================================================
# UPLOAD INVOICE
# =========================================================

@router.post("/upload")
async def upload_invoice(

    file: UploadFile = File(...),

    authorization: str | None = Header(
        default=None
    ),

):

    # -----------------------------------------------------
    # AUTHENTICATION
    # -----------------------------------------------------

    user = get_current_user(
        authorization
    )

    # -----------------------------------------------------
    # UPLOAD PERMISSION
    # -----------------------------------------------------
    # Invoice creation is intentionally limited to Normal User
    # accounts. Admin and Finance/Reviewer roles may inspect and
    # review invoices, but they must not upload new submissions.

    require_invoice_upload_access(
        user
    )


    # -----------------------------------------------------
    # FILE CHECK
    # -----------------------------------------------------

    if not file.filename:

        raise HTTPException(

            status_code=400,

            detail=(
                "No file was selected."
            )

        )

    original_filename = Path(
        file.filename
    ).name

    extension = Path(
        original_filename
    ).suffix.lower()

    if extension not in (
        ALLOWED_EXTENSIONS
    ):

        raise HTTPException(

            status_code=400,

            detail=(
                "Unsupported invoice format. "
                "Allowed formats: PDF, PNG, JPG, "
                "JPEG, WEBP, XLS and XLSX."
            )

        )


    # -----------------------------------------------------
    # READ FILE
    # -----------------------------------------------------

    file_content = await file.read(
        MAX_FILE_SIZE + 1
    )

    if len(file_content) > (
        MAX_FILE_SIZE
    ):

        raise HTTPException(

            status_code=413,

            detail=(
                "File size must be 10 MB or less."
            )

        )


    # -----------------------------------------------------
    # GENERATE INVOICE ID
    # -----------------------------------------------------

    invoice_id = (

        "INV-"

        + datetime.now(
            timezone.utc
        ).strftime(
            "%Y%m%d"
        )

        + "-"

        + uuid.uuid4()
        .hex[:8]
        .upper()

    )

    stored_filename = (
        f"{invoice_id}{extension}"
    )


    # -----------------------------------------------------
    # USER UPLOAD DIRECTORY
    # -----------------------------------------------------

    user_upload_dir = (
        UPLOAD_DIR
        / user["id"]
    )

    user_upload_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    stored_file_path = (
        user_upload_dir
        / stored_filename
    )


    # -----------------------------------------------------
    # SAVE FILE
    # -----------------------------------------------------

    stored_file_path.write_bytes(
        file_content
    )

    now = datetime.now(
        timezone.utc
    ).isoformat()


    # =====================================================
    # EXTRACTION
    # =====================================================

    extracted_data = {}

    extraction_error = None

    extraction_status = (
        "uploaded"
    )

    try:

        extracted_data = (
            extract_invoice_data(

                file_path=stored_file_path,

                extension=extension,

            )
        )

        extraction_status = (
            extracted_data.get(
                "extraction_status",
                "uploaded"
            )
        )

    except Exception as error:

        extraction_error = str(
            error
        )

        extraction_status = (
            "extraction_failed"
        )


    # =====================================================
    # MARKET PRICE INTELLIGENCE
    # =====================================================

    market_analysis = {}

    if not extraction_error:

        try:

            market_analysis = (
                analyze_market_price(

                    vendor_name=(
                        extracted_data.get(
                            "vendor_name"
                        )
                    ),

                    product_description=(
                        extracted_data.get(
                            "product_description"
                        )
                    ),

                    invoice_unit_price=(
                        extracted_data.get(
                            "unit_price"
                        )
                    ),

                    invoice_currency=(
                        extracted_data.get(
                            "currency"
                        )
                    ),

                )
            )

        except Exception as error:

            # Market research must NEVER
            # break invoice uploading.

            market_analysis = {

                "status":
                    "market_analysis_error",

                "message":
                    (
                        "Market price analysis "
                        "could not be completed."
                    ),

                "error":
                    str(error),

                "usable_for_risk_calculation":
                    False,

                "sources":
                    [],

                "market_statistics":
                    {

                        "currency":
                            None,

                        "lowest":
                            None,

                        "highest":
                            None,

                        "average":
                            None,

                        "median":
                            None,

                    },

                "price_difference":
                    None,

                "price_difference_percent":
                    None,

            }


    # =====================================================
    # RISK & ANOMALY ANALYSIS
    # =====================================================

    risk_analysis = {}

    # Risk analysis is evidence-driven and must never prevent
    # a valid invoice upload from being stored.
    #
    # The current invoice is not saved yet. Therefore the
    # historical list contains only previously stored invoices,
    # which is exactly what duplicate/history analysis needs.

    try:

        existing_invoices_for_risk = read_invoices()

        risk_analysis = (
            analyze_invoice_risk(
                invoice={
                    "invoice_id":
                        invoice_id,

                    "uploaded_by":
                        user["id"],

                    "original_filename":
                        original_filename,

                    "stored_filename":
                        stored_filename,

                    "file_path":
                        str(
                            stored_file_path.relative_to(
                                BASE_DIR
                            )
                        ),

                    "file_size":
                        len(file_content),

                    "file_extension":
                        extension,

                    "uploaded_at":
                        now,

                    "status":
                        extraction_status,

                    "verification_code":
                        extracted_data.get(
                            "verification_code"
                        ),

                    "extracted_data":
                        extracted_data,

                },

                all_invoices=
                    existing_invoices_for_risk,

                market_analysis=
                    market_analysis,

            )
        )

    except Exception as error:

        risk_analysis = {
            "status":
                "risk_analysis_error",

            "risk_score":
                None,

            "risk_level":
                "unknown",

            "anomalies":
                [],

            "explanation":
                {
                    "summary":
                        "Risk analysis could not be completed.",

                    "reasons":
                        [
                            "The invoice was preserved safely, "
                            "but the anomaly engine returned an error."
                        ],

                    "evidence_based":
                        True,

                    "human_review_required":
                        True,
                },

            "error":
                str(error),

            "human_review_required":
                True,
        }


    # =====================================================
    # INITIAL INVOICE RECORD
    # =====================================================

    invoice_record = {

        "invoice_id":
            invoice_id,

        "uploaded_by":
            user["id"],

        "original_filename":
            original_filename,

        "stored_filename":
            stored_filename,

        "file_path":
            str(

                stored_file_path.relative_to(
                    BASE_DIR
                )

            ),

        "file_size":
            len(file_content),

        "file_extension":
            extension,

        "uploaded_at":
            now,

        "status":
            extraction_status,

        "verification_code":
            extracted_data.get(
                "verification_code"
            ),

        "extracted_data":
            extracted_data,

        "verification":
            {},

        "market_analysis":
            market_analysis,

        "risk_score":
            risk_analysis.get(
                "risk_score"
            ),

        "risk_level":
            risk_analysis.get(
                "risk_level"
            ),

        "anomalies":
            risk_analysis.get(
                "anomalies",
                []
            ),

        "risk_analysis":
            risk_analysis,

        "decision":
            None,

        "extraction_error":
            extraction_error,

    }


    # =====================================================
    # INVOICE VERIFICATION
    # =====================================================

    verification_result = {}


    if not extraction_error:

        try:

            # Read existing invoices.
            #
            # The current invoice has NOT been saved yet.
            # Therefore duplicate verification-code detection
            # checks only previously stored records.

            existing_invoices = (
                read_invoices()
            )

            verification_result = (
                verify_invoice(

                    invoice=invoice_record,

                    all_invoices=existing_invoices,

                )
            )

        except Exception as error:

            verification_result = {

                "status":
                    "verification_error",

                "is_valid":
                    False,

                "verification_code":
                    extracted_data.get(
                        "verification_code"
                    ),

                "checks":
                    {},

                "message":
                    (
                        "Invoice verification "
                        "could not be completed."
                    ),

                "error":
                    str(error),

                "source":
                    "claimguard_internal",

            }


    # =====================================================
    # SET FINAL STATUS
    # =====================================================

    verification_status = (
        verification_result.get(
            "status"
        )
    )


    if extraction_error:

        final_status = (
            "extraction_failed"
        )

    elif extraction_status == (
        "no_text_found"
    ):

        final_status = (
            "no_text_found"
        )

    elif verification_status == (
        "verified_document"
    ):

        final_status = (
            "verified_document"
        )

    elif verification_status == (
        "possible_duplicate"
    ):

        final_status = (
            "possible_duplicate"
        )

    elif verification_status == (
        "verification_failed"
    ):

        final_status = (
            "verification_failed"
        )

    elif verification_status == (
        "verification_required"
    ):

        final_status = (
            "verification_required"
        )

    elif verification_status == (
        "verification_error"
    ):

        final_status = (
            "verification_error"
        )

    else:

        final_status = (
            extraction_status
        )


    invoice_record[
        "status"
    ] = final_status


    invoice_record[
        "verification"
    ] = verification_result


    # =====================================================
    # AUTOMATIC FINANCE REVIEW ROUTING
    # =====================================================

    review_trigger_reasons = _review_trigger_reasons(
        risk_analysis=risk_analysis,
        verification_status=verification_status,
        extraction_error=extraction_error,
        extraction_status=extraction_status,
    )

    review_required = bool(
        review_trigger_reasons
    )

    automated_analysis_status = final_status

    if review_required:

        final_status = (
            "pending_review"
        )

        invoice_record[
            "status"
        ] = final_status

    invoice_record[
        "automated_analysis_status"
    ] = automated_analysis_status

    invoice_record[
        "review_routing"
    ] = {

        "review_required":
            review_required,

        "routed_to":
            (
                "finance_reviewer"
                if review_required
                else None
            ),

        "routed_at":
            (
                now
                if review_required
                else None
            ),

        "trigger_reasons":
            review_trigger_reasons,

    }


    # =====================================================
    # SAVE INVOICE
    # =====================================================

    invoices = read_invoices()

    invoices.append(
        invoice_record
    )

    write_invoices(
        invoices
    )


    # Read the just-persisted record back from the authoritative
    # storage layer so the frontend receives the same invoice shape
    # used by the dashboard/details endpoints.
    stored_invoice = next(
        (
            item
            for item in read_invoices()
            if item.get("invoice_id") == invoice_id
        ),
        invoice_record
    )


    # =====================================================
    # RESPONSE MESSAGE
    # =====================================================

    if review_required:

        message = (
            "Invoice analyzed and flagged for "
            "Finance/Reviewer review."
        )

    elif extraction_error:

        message = (
            "Invoice uploaded successfully, "
            "but automatic extraction failed."
        )

    elif extraction_status == (
        "no_text_found"
    ):

        message = (
            "Invoice uploaded, but no readable "
            "text was found."
        )

    elif verification_status == (
        "verified_document"
    ):

        if market_analysis.get(
            "status"
        ) == "analyzed":

            message = (
                "Invoice uploaded, extracted, "
                "verified, and market price "
                "analysis was completed."
            )

        else:

            message = (
                "Invoice uploaded, extracted, "
                "and document verification "
                "checks passed."
            )

    elif verification_status == (
        "possible_duplicate"
    ):

        message = (
            "Invoice uploaded, but a possible "
            "duplicate verification code was detected."
        )

    elif verification_status == (
        "verification_failed"
    ):

        message = (
            "Invoice uploaded, but verification failed."
        )

    elif verification_status == (
        "verification_required"
    ):

        message = (
            "Invoice uploaded. Additional verification "
            "is required."
        )

    elif verification_status == (
        "verification_error"
    ):

        message = (
            "Invoice uploaded, but verification "
            "could not be completed."
        )

    else:

        message = (
            "Invoice uploaded successfully."
        )


    # =====================================================
    # RESPONSE
    # =====================================================

    return {

        "success":
            True,

        "message":
            message,

        "invoice":
            stored_invoice,

    }


# =========================================================
# REVIEW AUDIT TRAIL
# =========================================================

def _append_review_audit_event(
    invoice: dict[str, Any],
    event_type: str,
    actor: dict[str, Any],
    note: str = "",
    decision: str | None = None,
) -> None:
    """
    Append a reviewer workflow event to the invoice record.
    """

    history = invoice.get(
        "review_audit_trail"
    )

    if not isinstance(
        history,
        list
    ):

        history = []

    history.append(
        {
            "event_type":
                event_type,

            "decision":
                decision,

            "actor_id":
                actor.get(
                    "id"
                ),

            "actor_name":
                actor.get(
                    "full_name"
                ),

            "actor_email":
                actor.get(
                    "email"
                ),

            "actor_role":
                actor.get(
                    "role"
                ),

            "note":
                note,

            "timestamp":
                datetime.now(
                    timezone.utc
                ).isoformat(),
        }
    )

    invoice[
        "review_audit_trail"
    ] = history


# =========================================================
# REVIEW QUEUE
# =========================================================

@router.get(
    "/review-queue"
)
def get_review_queue(
    authorization: str | None = Header(
        default=None
    ),
):
    """
    Return invoices that ClaimGuard has routed to Finance/Reviewer.

    Final approved/rejected invoices are excluded. Verification-required
    items remain available for follow-up review.
    """

    user = get_current_user(
        authorization
    )

    require_reviewer_access(
        user
    )

    invoices = read_invoices()

    review_queue = []

    final_decisions = {
        "approved",
        "rejected",
    }

    legacy_review_statuses = {
        "pending_review",
        "verification_required",
        "possible_duplicate",
        "verification_failed",
        "verification_error",
        "extraction_failed",
        "no_text_found",
    }

    for invoice in invoices:

        decision = invoice.get(
            "decision"
        )

        decision_name = ""

        if isinstance(
            decision,
            dict
        ):

            decision_name = str(
                decision.get(
                    "decision",
                    ""
                )
            ).strip().lower()

        elif isinstance(
            decision,
            str
        ):

            decision_name = decision.strip().lower()

        if decision_name in final_decisions:
            continue

        routing = invoice.get(
            "review_routing"
        )

        routed_to_reviewer = (
            isinstance(
                routing,
                dict
            )
            and
            bool(
                routing.get(
                    "review_required"
                )
            )
        )

        status_name = str(
            invoice.get(
                "status",
                ""
            )
        ).strip().lower()

        if (
            routed_to_reviewer
            or
            status_name in legacy_review_statuses
        ):
            review_queue.append(
                invoice
            )

    review_queue.sort(
        key=lambda item:
            item.get(
                "uploaded_at",
                ""
            ),
        reverse=True
    )

    return {

        "success":
            True,

        "count":
            len(review_queue),

        "invoices":
            review_queue,

    }


# =========================================================
# REVIEW DECISION SECURITY GUARD
# =========================================================

def _require_reviewable_invoice(
    invoice: dict[str, Any]
) -> None:
    """
    Prevent a Finance/Reviewer from making a new decision on an
    invoice that is already finalized.
    """

    status_name = str(
        invoice.get(
            "status",
            ""
        )
    ).strip().lower()

    decision = invoice.get(
        "decision"
    )

    decision_name = ""

    if isinstance(
        decision,
        dict
    ):

        decision_name = str(
            decision.get(
                "decision",
                ""
            )
        ).strip().lower()

    elif isinstance(
        decision,
        str
    ):

        decision_name = decision.strip().lower()

    if (
        status_name in {
            "approved",
            "rejected",
        }
        or
        decision_name in {
            "approved",
            "rejected",
        }
    ):

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This invoice already has a final Finance/Reviewer "
                "decision and cannot be decided again."
            )
        )

    allowed_statuses = {
        "pending_review",
        "verification_required",
    }

    if (
        status_name
        not in allowed_statuses
        and
        decision_name
        != "request_verification"
    ):

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This invoice is not currently awaiting "
                "Finance/Reviewer action."
            )
        )


# =========================================================
# SAVE REVIEW DECISION
# =========================================================

@router.post(
    "/{invoice_id}/decision"
)
def save_invoice_decision(
    invoice_id: str,
    request: InvoiceDecisionRequest,
    authorization: str | None = Header(
        default=None
    ),
):
    """
    Save Approved, Rejected, or Request Verification.

    The existing SQLite-backed read_invoices/write_invoices
    interface is reused, so no existing storage function is
    replaced here.
    """

    user = get_current_user(
        authorization
    )

    require_reviewer_access(
        user
    )

    invoices = read_invoices()

    invoice = next(
        (
            item
            for item in invoices
            if item.get(
                "invoice_id"
            ) == invoice_id
        ),
        None
    )

    if not invoice:

        raise HTTPException(
            status_code=404,
            detail="Invoice not found."
        )


    _require_reviewable_invoice(
        invoice
    )

    status_map = {
        "approved":
            "approved",

        "rejected":
            "rejected",

        "request_verification":
            "verification_required",
    }

    message_map = {
        "approved":
            "Invoice approved by reviewer.",

        "rejected":
            "Invoice rejected by reviewer.",

        "request_verification":
            "Additional invoice verification requested.",
    }

    previous_decision = invoice.get(
        "decision"
    )

    decided_at = datetime.now(
        timezone.utc
    ).isoformat()

    invoice[
        "decision"
    ] = {

        "decision":
            request.decision,

        "note":
            request.note.strip(),

        "reviewed_by":
            user.get(
                "id"
            ),

        "reviewer_name":
            user.get(
                "full_name"
            ),

        "reviewer_email":
            user.get(
                "email"
            ),

        "reviewer_role":
            user.get(
                "role"
            ),

        "decided_at":
            decided_at,

        "previous_decision":
            previous_decision,
    }


    _append_review_audit_event(
        invoice=invoice,
        event_type="review_decision",
        actor=user,
        note=request.note.strip(),
        decision=request.decision,
    )

    invoice[
        "status"
    ] = status_map[
        request.decision
    ]


    if request.decision == "request_verification":

        routing = invoice.get(
            "review_routing"
        )

        if not isinstance(
            routing,
            dict
        ):

            routing = {}

        routing[
            "review_required"
        ] = True

        routing[
            "routed_to"
        ] = "finance_reviewer"

        routing[
            "routed_at"
        ] = decided_at

        reasons = routing.get(
            "trigger_reasons"
        )

        if not isinstance(
            reasons,
            list
        ):

            reasons = []

        if (
            "Finance Reviewer requested additional verification."
            not in reasons
        ):

            reasons.append(
                "Finance Reviewer requested additional verification."
            )

        routing[
            "trigger_reasons"
        ] = reasons

        invoice[
            "review_routing"
        ] = routing


    write_invoices(
        invoices
    )

    stored_invoice = next(
        (
            item
            for item in read_invoices()
            if item.get(
                "invoice_id"
            ) == invoice_id
        ),
        invoice
    )

    return {
        "success":
            True,

        "message":
            message_map[
                request.decision
            ],

        "invoice":
            stored_invoice,

        "decision":
            stored_invoice.get(
                "decision"
            ),
    }


# =========================================================\n# USER VERIFICATION RESPONSE\n# =========================================================\n\n@router.post(\n    "/{invoice_id}/verification-response"\n)\ndef submit_verification_response(\n    invoice_id: str,\n    request: InvoiceVerificationResponseRequest,\n    authorization: str | None = Header(\n        default=None\n    ),\n):\n    \"\"\"\n    Let the invoice owner respond to a Finance/Reviewer verification request.\n    The invoice is returned to the Finance/Reviewer queue.\n    \"\"\"\n\n    user = get_current_user(\n        authorization\n    )\n\n    invoices = read_invoices()\n\n    invoice = next(\n        (\n            item\n            for item in invoices\n            if item.get(\"invoice_id\") == invoice_id\n        ),\n        None\n    )\n\n    if not invoice:\n        raise HTTPException(\n            status_code=404,\n            detail=\"Invoice not found.\"\n        )\n\n    if invoice.get(\"uploaded_by\") != user.get(\"id\"):\n        raise HTTPException(\n            status_code=status.HTTP_403_FORBIDDEN,\n            detail=\"You can only submit verification for your own invoice.\"\n        )\n\n    decision = invoice.get(\"decision\")\n    decision_name = \"\"\n\n    if isinstance(decision, dict):\n        decision_name = str(\n            decision.get(\"decision\", \"\")\n        ).strip().lower()\n    elif isinstance(decision, str):\n        decision_name = decision.strip().lower()\n\n    if (\n        str(invoice.get(\"status\", \"\")).strip().lower() != \"verification_required\"\n        and decision_name != \"request_verification\"\n    ):\n        raise HTTPException(\n            status_code=400,\n            detail=\"This invoice is not currently awaiting additional verification.\"\n        )\n\n    note = request.note.strip()\n\n    if not note:\n        raise HTTPException(\n            status_code=400,\n            detail=\"Please provide the requested verification information.\"\n        )\n\n    submitted_at = datetime.now(\n        timezone.utc\n    ).isoformat()\n\n    history = []\n    existing = invoice.get(\"verification_submission\")\n\n    if isinstance(existing, dict) and isinstance(existing.get(\"history\"), list):\n        history.extend(existing.get(\"history\"))\n\n    history.append({\n        \"submitted_by\": user.get(\"id\"),\n        \"submitter_name\": user.get(\"full_name\"),\n        \"submitter_email\": user.get(\"email\"),\n        \"submitted_at\": submitted_at,\n        \"note\": note,\n    })\n\n    invoice[\"verification_submission\"] = {\n        \"status\": \"submitted\",\n        \"submitted_at\": submitted_at,\n        \"submitted_by\": user.get(\"id\"),\n        \"submitter_name\": user.get(\"full_name\"),\n        \"submitter_email\": user.get(\"email\"),\n        \"note\": note,\n        \"history\": history,\n    }\n\n    invoice[\"status\"] = \"pending_review\"\n\n    routing = invoice.get(\"review_routing\")\n    if not isinstance(routing, dict):\n        routing = {}\n\n    routing[\"review_required\"] = True\n    routing[\"routed_to\"] = \"finance_reviewer\"\n    routing[\"routed_at\"] = submitted_at\n\n    reasons = routing.get(\"trigger_reasons\")\n    if not isinstance(reasons, list):\n        reasons = []\n\n    new_reason = \"User submitted additional verification information.\"\n    if new_reason not in reasons:\n        reasons.append(new_reason)\n\n    routing[\"trigger_reasons\"] = reasons\n    invoice[\"review_routing\"] = routing\n    invoice[\"verification_review_state\"] = \"resubmitted_to_finance\"\n\n    write_invoices(\n        invoices\n    )\n\n    stored_invoice = next(\n        (\n            item\n            for item in read_invoices()\n            if item.get(\"invoice_id\") == invoice_id\n        ),\n        invoice\n    )\n\n    return {\n        \"success\": True,\n        \"message\": (\n            \"Verification information submitted. The invoice has been returned to Finance/Reviewer review.\"\n        ),\n        \"invoice\": stored_invoice,\n    }\n\n\n# =========================================================
# ADMIN INVOICE OVERVIEW
# =========================================================

def _require_admin_user(
    authorization: str | None,
) -> dict[str, Any]:
    """
    Authenticate the caller and require the Admin role.
    """

    user = get_current_user(
        authorization
    )

    role = str(
        user.get(
            "role",
            ""
        )
    ).strip().lower()

    if role != "admin":

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access is required."
        )

    return user


def _admin_invoice_summary(
    invoice: dict[str, Any]
) -> dict[str, Any]:
    """
    Return management-safe invoice information for Admin.
    """

    extracted = invoice.get(
        "extracted_data"
    )

    if not isinstance(
        extracted,
        dict
    ):

        extracted = {}

    decision = invoice.get(
        "decision"
    )

    if not isinstance(
        decision,
        dict
    ):

        decision = {}

    return {

        "invoice_id":
            invoice.get(
                "invoice_id"
            ),

        "invoice_number":
            extracted.get(
                "invoice_number"
            )
            or
            invoice.get(
                "invoice_number"
            ),

        "vendor_name":
            extracted.get(
                "vendor_name"
            )
            or
            invoice.get(
                "vendor_name"
            )
            or
            "Unknown vendor",

        "amount":
            (
                extracted.get(
                    "total"
                )
                if extracted.get(
                    "total"
                ) is not None
                else
                extracted.get(
                    "grand_total"
                )
            ),

        "currency":
            extracted.get(
                "currency"
            )
            or
            "BDT",

        "risk_score":
            invoice.get(
                "risk_score"
            ),

        "risk_level":
            invoice.get(
                "risk_level"
            ),

        "status":
            invoice.get(
                "status"
            ),

        "uploaded_at":
            invoice.get(
                "uploaded_at"
            ),

        "uploaded_by":
            invoice.get(
                "uploaded_by"
            ),

        "decision":
            decision,

        "anomaly_count":
            len(
                invoice.get(
                    "anomalies",
                    []
                )
            )
            if isinstance(
                invoice.get(
                    "anomalies",
                    []
                ),
                list
            )
            else 0,

        "review_required":
            bool(
                invoice.get(
                    "review_routing",
                    {}
                ).get(
                    "review_required"
                )
                if isinstance(
                    invoice.get(
                        "review_routing",
                        {}
                    ),
                    dict
                )
                else False
            ),

    }


@router.get(
    "/admin/overview"
)
def get_admin_invoice_overview(
    authorization: str | None = Header(
        default=None
    ),
):
    """
    Return system-wide invoice and reviewer metrics for Admin.
    """

    _require_admin_user(
        authorization
    )

    invoices = read_invoices()
    users = read_users()

    reviewer_count = sum(
        1
        for user in users
        if str(
            user.get(
                "role",
                ""
            )
        ).strip().lower()
        in {
            "reviewer",
            "finance_reviewer",
            "finance/reviewer",
            "finance-reviewer",
        }
        and bool(
            user.get(
                "is_active"
            )
        )
    )

    total_invoices = len(
        invoices
    )

    pending_review = 0
    approved = 0
    rejected = 0
    verification_required = 0
    high_risk = 0
    medium_risk = 0
    low_risk = 0
    anomaly_signals = 0

    recent_invoices = []

    for invoice in invoices:

        status_name = str(
            invoice.get(
                "status",
                ""
            )
        ).strip().lower()

        decision = invoice.get(
            "decision"
        )

        decision_name = ""

        if isinstance(
            decision,
            dict
        ):

            decision_name = str(
                decision.get(
                    "decision",
                    ""
                )
            ).strip().lower()

        elif isinstance(
            decision,
            str
        ):

            decision_name = decision.strip().lower()

        if decision_name == "approved":
            approved += 1

        elif decision_name == "rejected":
            rejected += 1

        elif (
            status_name ==
            "verification_required"
        ):

            verification_required += 1
            pending_review += 1

        elif (
            status_name ==
            "pending_review"
        ):

            pending_review += 1

        risk_score = _safe_number(
            invoice.get(
                "risk_score"
            )
        )

        if risk_score is not None:

            if risk_score >= 70:
                high_risk += 1

            elif risk_score >= 40:
                medium_risk += 1

            else:
                low_risk += 1

        anomaly_value = invoice.get(
            "anomalies",
            []
        )

        if isinstance(
            anomaly_value,
            list
        ):

            anomaly_signals += len(
                anomaly_value
            )

        recent_invoices.append(
            _admin_invoice_summary(
                invoice
            )
        )

    recent_invoices.sort(
        key=lambda item:
            item.get(
                "uploaded_at",
                ""
            ),
        reverse=True
    )

    return {

        "success":
            True,

        "metrics": {

            "total_users":
                len(
                    users
                ),

            "active_users":
                sum(
                    1
                    for user in users
                    if bool(
                        user.get(
                            "is_active"
                        )
                    )
                ),

            "reviewer_accounts":
                reviewer_count,

            "total_invoices":
                total_invoices,

            "pending_review":
                pending_review,

            "approved":
                approved,

            "rejected":
                rejected,

            "verification_required":
                verification_required,

            "high_risk":
                high_risk,

            "medium_risk":
                medium_risk,

            "low_risk":
                low_risk,

            "anomaly_signals":
                anomaly_signals,

        },

        "invoices":
            recent_invoices[
                :25
            ],

    }


# =========================================================
# GET MY INVOICES
# =========================================================

@router.get("/my")
def get_my_invoices(

    authorization: str | None = Header(
        default=None
    ),

):

    user = get_current_user(
        authorization
    )

    invoices = read_invoices()

    user_invoices = [

        invoice

        for invoice in invoices

        if invoice.get(
            "uploaded_by"
        ) == user["id"]

    ]

    user_invoices.sort(

        key=lambda item:
            item.get(
                "uploaded_at",
                ""
            ),

        reverse=True

    )

    return {

        "success":
            True,

        "count":
            len(user_invoices),

        "invoices":
            user_invoices,

    }


# =========================================================
# USER NOTIFICATION CENTER
# =========================================================

def _notification_invoice_label(
    invoice: dict[str, Any]
) -> str:

    extracted = invoice.get(
        "extracted_data"
    )

    if not isinstance(
        extracted,
        dict
    ):

        extracted = {}

    return str(
        extracted.get(
            "invoice_number"
        )
        or invoice.get(
            "invoice_id"
        )
        or "Invoice"
    )


def _build_user_notifications(
    user: dict[str, Any],
    invoices: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """
    Build user-facing notifications from persisted invoice state.

    Notifications are derived from authoritative invoice records, so
    the client cannot fabricate a decision or reviewer identity.
    """

    user_id = user.get(
        "id"
    )

    notifications = []

    for invoice in invoices:

        if invoice.get(
            "uploaded_by"
        ) != user_id:

            continue

        invoice_id = invoice.get(
            "invoice_id"
        )

        label = _notification_invoice_label(
            invoice
        )

        uploaded_at = (
            invoice.get(
                "uploaded_at"
            )
            or ""
        )

        status_name = str(
            invoice.get(
                "status",
                ""
            )
        ).strip().lower()

        decision = invoice.get(
            "decision"
        )

        if not isinstance(
            decision,
            dict
        ):

            decision = {}

        decision_name = str(
            decision.get(
                "decision",
                ""
            )
        ).strip().lower()

        decision_time = (
            decision.get(
                "decided_at"
            )
            or uploaded_at
        )

        review_routing = invoice.get(
            "review_routing"
        )

        if not isinstance(
            review_routing,
            dict
        ):

            review_routing = {}

        review_required = bool(
            review_routing.get(
                "review_required"
            )
        )

        # -----------------------------------------------------
        # Finance final decision
        # -----------------------------------------------------
        if decision_name == "approved":

            reviewer_name = (
                decision.get(
                    "reviewer_name"
                )
                or decision.get(
                    "reviewer_email"
                )
                or "Finance/Reviewer"
            )

            notifications.append(
                {
                    "notification_id":
                        f"{invoice_id}:approved:{decision_time}",

                    "invoice_id":
                        invoice_id,

                    "invoice_number":
                        label,

                    "type":
                        "finance_approved",

                    "title":
                        f"Invoice {label} was approved by Finance.",

                    "message":
                        (
                            f"Authorized Finance/Reviewer decision recorded "
                            f"by {reviewer_name}."
                        ),

                    "status":
                        "approved",

                    "timestamp":
                        decision_time,

                    "action":
                        "invoice-details.html",
                }
            )

            continue

        if decision_name == "rejected":

            reviewer_name = (
                decision.get(
                    "reviewer_name"
                )
                or decision.get(
                    "reviewer_email"
                )
                or "Finance/Reviewer"
            )

            notifications.append(
                {
                    "notification_id":
                        f"{invoice_id}:rejected:{decision_time}",

                    "invoice_id":
                        invoice_id,

                    "invoice_number":
                        label,

                    "type":
                        "finance_rejected",

                    "title":
                        f"Invoice {label} was rejected by Finance.",

                    "message":
                        (
                            f"Authorized Finance/Reviewer decision recorded "
                            f"by {reviewer_name}."
                        ),

                    "status":
                        "rejected",

                    "timestamp":
                        decision_time,

                    "action":
                        "invoice-details.html",
                }
            )

            continue

        # -----------------------------------------------------
        # Verification requested
        # -----------------------------------------------------
        if (
            decision_name
            == "request_verification"
            or
            status_name
            == "verification_required"
        ):

            reviewer_name = (
                decision.get(
                    "reviewer_name"
                )
                or decision.get(
                    "reviewer_email"
                )
                or "Finance/Reviewer"
            )

            notifications.append(
                {
                    "notification_id":
                        (
                            f"{invoice_id}:verification_requested:"
                            f"{decision_time}"
                        ),

                    "invoice_id":
                        invoice_id,

                    "invoice_number":
                        label,

                    "type":
                        "verification_requested",

                    "title":
                        (
                            f"Invoice {label} requires additional "
                            "verification."
                        ),

                    "message":
                        (
                            f"{reviewer_name} requested additional "
                            "verification information."
                        ),

                    "status":
                        "verification_required",

                    "timestamp":
                        decision_time,

                    "action":
                        "invoice-details.html",
                }
            )

            continue

        # -----------------------------------------------------
        # Waiting for review
        # -----------------------------------------------------
        if (
            review_required
            or
            status_name
            in {
                "pending_review",
                "possible_duplicate",
                "verification_failed",
                "verification_error",
                "extraction_failed",
                "no_text_found",
            }
        ):

            notifications.append(
                {
                    "notification_id":
                        f"{invoice_id}:pending_review:{uploaded_at}",

                    "invoice_id":
                        invoice_id,

                    "invoice_number":
                        label,

                    "type":
                        "finance_review_pending",

                    "title":
                        (
                            f"Invoice {label} is waiting for "
                            "Finance review."
                        ),

                    "message":
                        (
                            "ClaimGuard routed the invoice to the "
                            "authorized Finance/Reviewer queue."
                        ),

                    "status":
                        "pending_review",

                    "timestamp":
                        uploaded_at,

                    "action":
                        "invoice-details.html",
                }
            )

            continue

        # -----------------------------------------------------
        # Completed automated analysis but no Finance route
        # -----------------------------------------------------
        notifications.append(
            {
                "notification_id":
                    f"{invoice_id}:analysis:{uploaded_at}",

                "invoice_id":
                    invoice_id,

                "invoice_number":
                    label,

                "type":
                    "analysis_ready",

                "title":
                    f"Invoice {label} analysis is available.",

                "message":
                    (
                        "ClaimGuard completed the document analysis. "
                        "Open the invoice details page to review the result."
                    ),

                "status":
                    status_name
                    or "analysis_ready",

                "timestamp":
                    uploaded_at,

                "action":
                    "invoice-details.html",
            }
        )

    notifications.sort(
        key=lambda item:
            item.get(
                "timestamp",
                ""
            ),
        reverse=True
    )

    return notifications


@router.get(
    "/notifications"
)
def get_user_notifications(
    authorization: str | None = Header(
        default=None
    ),
):
    """
    Return the authenticated user's ClaimGuard notification center.
    """

    user = get_current_user(
        authorization
    )

    invoices = read_invoices()

    notifications = _build_user_notifications(
        user,
        invoices
    )

    return {
        "success": True,
        "count": len(notifications),
        "notifications": notifications[:50],
    }


# =========================================================
# PDF REPORT EXPORT
# =========================================================

@router.get(
    "/{invoice_id}/report"
)
def download_invoice_report(
    invoice_id: str,
    authorization: str | None = Header(
        default=None
    ),
):
    """
    Generate a review-ready PDF report for one invoice.

    Access follows the same invoice visibility rules:
    the owner, Admin, or Finance/Reviewer can access the report.
    """

    user = get_current_user(
        authorization
    )

    invoices = read_invoices()

    invoice = next(
        (
            item
            for item in invoices
            if (
                item.get(
                    "invoice_id"
                ) == invoice_id

                and (
                    can_view_any_invoice(
                        user
                    )

                    or
                    item.get(
                        "uploaded_by"
                    ) == user.get(
                        "id"
                    )
                )
            )
        ),
        None
    )

    if not invoice:

        raise HTTPException(
            status_code=404,
            detail="Invoice not found."
        )

    try:

        pdf_bytes = build_invoice_report(
            invoice
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail="Could not generate the invoice report."
        ) from exc

    extracted = invoice.get(
        "extracted_data"
    )

    if not isinstance(
        extracted,
        dict
    ):

        extracted = {}

    invoice_number = (
        extracted.get(
            "invoice_number"
        )
        or invoice_id
    )

    safe_name = "".join(
        character
        if (
            character.isalnum()
            or character in {
                "-",
                "_",
            }
        )
        else "_"
        for character in str(
            invoice_number
        )
    )

    filename = (
        f"ClaimGuard_Report_{safe_name}.pdf"
    )

    return StreamingResponse(
        BytesIO(
            pdf_bytes
        ),
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f'attachment; filename="{filename}"'
        },
    )



# =========================================================
# ADMIN REPORTING & EXPORT
# =========================================================

def _admin_report_payload(
    invoices: list[dict[str, Any]]
) -> dict[str, Any]:

    anomaly_type_counts: dict[str, int] = {}
    vendor_counts: dict[str, int] = {}
    vendor_risk: dict[str, list[float]] = {}
    daily_counts: dict[str, int] = {}

    approved = 0
    rejected = 0
    pending = 0
    verification = 0
    high = 0
    medium = 0
    low = 0

    for invoice in invoices:

        status = str(
            invoice.get(
                "status",
                ""
            )
        ).strip().lower()

        decision = invoice.get(
            "decision"
        )

        if not isinstance(
            decision,
            dict
        ):
            decision = {}

        decision_name = str(
            decision.get(
                "decision",
                ""
            )
        ).strip().lower()

        if decision_name == "approved":
            approved += 1

        elif decision_name == "rejected":
            rejected += 1

        elif (
            decision_name == "request_verification"
            or status == "verification_required"
        ):
            verification += 1

        elif (
            status == "pending_review"
            or (
                isinstance(
                    invoice.get(
                        "review_routing"
                    ),
                    dict
                )
                and invoice.get(
                    "review_routing",
                    {}
                ).get(
                    "review_required",
                    False
                )
            )
        ):
            pending += 1

        risk = invoice.get(
            "risk_score"
        )

        if risk is None:
            risk = (
                invoice.get(
                    "risk_analysis"
                ) or {}
            ).get(
                "risk_score"
            )

        try:
            risk_value = float(
                risk
            )
        except (
            TypeError,
            ValueError
        ):
            risk_value = 0.0

        if risk_value >= 70:
            high += 1
        elif risk_value >= 40:
            medium += 1
        else:
            low += 1

        anomalies = invoice.get(
            "anomalies"
        )

        if not isinstance(
            anomalies,
            list
        ):
            anomalies = []

        for anomaly in anomalies:

            if isinstance(
                anomaly,
                dict
            ):
                anomaly_type = str(
                    anomaly.get(
                        "anomaly_type"
                    )
                    or anomaly.get(
                        "type"
                    )
                    or "unknown"
                ).strip()
            else:
                anomaly_type = "unknown"

            anomaly_type_counts[
                anomaly_type
            ] = (
                anomaly_type_counts.get(
                    anomaly_type,
                    0
                )
                + 1
            )

        extracted = invoice.get(
            "extracted_data"
        )

        if not isinstance(
            extracted,
            dict
        ):
            extracted = {}

        vendor = str(
            extracted.get(
                "vendor_name"
            )
            or invoice.get(
                "vendor_name"
            )
            or "Unknown Vendor"
        ).strip()

        vendor_counts[
            vendor
        ] = (
            vendor_counts.get(
                vendor,
                0
            )
            + 1
        )

        vendor_risk.setdefault(
            vendor,
            []
        ).append(
            risk_value
        )

        raw_date = str(
            invoice.get(
                "uploaded_at"
            )
            or extracted.get(
                "date"
            )
            or ""
        )

        day = (
            raw_date[:10]
            if len(raw_date) >= 10
            else ""
        )

        if day:
            daily_counts[
                day
            ] = (
                daily_counts.get(
                    day,
                    0
                )
                + 1
            )

    top_anomalies = sorted(
        [
            {
                "type": key,
                "count": value
            }
            for key, value
            in anomaly_type_counts.items()
        ],
        key=lambda item:
            item["count"],
        reverse=True
    )[:10]

    top_vendors = []

    for vendor, count in sorted(
        vendor_counts.items(),
        key=lambda item:
            item[1],
        reverse=True
    )[:10]:

        risks = vendor_risk.get(
            vendor,
            []
        )

        top_vendors.append(
            {
                "vendor": vendor,
                "invoice_count": count,
                "average_risk_score": round(
                    sum(risks) / len(risks),
                    2
                ) if risks else 0
            }
        )

    return {
        "success": True,
        "generated_at":
            datetime.utcnow().isoformat()
            + "Z",
        "summary": {
            "total_invoices":
                len(invoices),
            "approved":
                approved,
            "rejected":
                rejected,
            "pending_review":
                pending,
            "verification_required":
                verification,
            "high_risk":
                high,
            "medium_risk":
                medium,
            "low_risk":
                low,
            "anomaly_signals":
                sum(
                    anomaly_type_counts.values()
                )
        },
        "top_anomalies":
            top_anomalies,
        "top_vendors":
            top_vendors,
        "daily_volume": [
            {
                "date": day,
                "invoice_count": count
            }
            for day, count
            in sorted(
                daily_counts.items()
            )[-30:]
        ]
    }


@router.get(
    "/admin/reports"
)
def get_admin_reports(
    authorization: str | None = Header(
        default=None
    ),
):
    user = get_current_user(
        authorization
    )

    if str(
        user.get(
            "role",
            ""
        )
    ).strip().lower() != "admin":

        raise HTTPException(
            status_code=403,
            detail="Admin access required."
        )

    return _admin_report_payload(
        read_invoices()
    )


@router.get(
    "/admin/reports/export.csv"
)
def export_admin_report_csv(
    authorization: str | None = Header(
        default=None
    ),
):
    user = get_current_user(
        authorization
    )

    if str(
        user.get(
            "role",
            ""
        )
    ).strip().lower() != "admin":

        raise HTTPException(
            status_code=403,
            detail="Admin access required."
        )

    rows = [[
        "Invoice ID",
        "Invoice Number",
        "Vendor",
        "Amount",
        "Currency",
        "Risk Score",
        "Risk Level",
        "Status",
        "Decision",
        "Review Required",
        "Anomaly Count",
        "Uploaded By",
        "Uploaded At"
    ]]

    for invoice in read_invoices():

        extracted = invoice.get(
            "extracted_data"
        )

        if not isinstance(
            extracted,
            dict
        ):
            extracted = {}

        decision = invoice.get(
            "decision"
        )

        if not isinstance(
            decision,
            dict
        ):
            decision = {}

        routing = invoice.get(
            "review_routing"
        )

        if not isinstance(
            routing,
            dict
        ):
            routing = {}

        risk = invoice.get(
            "risk_score"
        )

        if risk is None:
            risk = (
                invoice.get(
                    "risk_analysis"
                ) or {}
            ).get(
                "risk_score"
            )

        try:
            risk_value = float(
                risk or 0
            )
        except (
            TypeError,
            ValueError
        ):
            risk_value = 0.0

        anomalies = invoice.get(
            "anomalies"
        )

        if not isinstance(
            anomalies,
            list
        ):
            anomalies = []

        rows.append([
            invoice.get(
                "invoice_id",
                ""
            ),
            extracted.get(
                "invoice_number",
                ""
            ),
            extracted.get(
                "vendor_name",
                ""
            ),
            extracted.get(
                "total",
                extracted.get(
                    "grand_total",
                    ""
                )
            ),
            extracted.get(
                "currency",
                "BDT"
            ),
            risk_value,
            (
                "high"
                if risk_value >= 70
                else (
                    "medium"
                    if risk_value >= 40
                    else "low"
                )
            ),
            invoice.get(
                "status",
                ""
            ),
            decision.get(
                "decision",
                ""
            ),
            bool(
                routing.get(
                    "review_required",
                    False
                )
            ),
            len(
                anomalies
            ),
            invoice.get(
                "uploaded_by",
                ""
            ),
            invoice.get(
                "uploaded_at",
                ""
            )
        ])

    output = StringIO()

    csv.writer(
        output
    ).writerows(
        rows
    )

    return StreamingResponse(
        iter([
            output.getvalue()
        ]),
        media_type="text/csv",
        headers={
            "Content-Disposition":
                'attachment; filename="ClaimGuard_Admin_Invoice_Report.csv"'
        }
    )


# =========================================================
# GET SINGLE INVOICE
# =========================================================

@router.get(
    "/{invoice_id}"
)
def get_invoice(

    invoice_id: str,

    authorization: str | None = Header(
        default=None
    ),

):

    user = get_current_user(
        authorization
    )

    invoices = read_invoices()

    invoice = next(

        (

            item

            for item in invoices

            if (

                item.get(
                    "invoice_id"
                )
                == invoice_id

                and (
                    can_view_any_invoice(
                        user
                    )

                    or

                    item.get(
                        "uploaded_by"
                    )
                    == user["id"]
                )

            )

        ),

        None

    )

    if not invoice:

        raise HTTPException(

            status_code=404,

            detail=(
                "Invoice not found."
            )

        )

    return {

        "success":
            True,

        "invoice":
            invoice,

    }
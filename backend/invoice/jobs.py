"""PostgreSQL-backed processing job state and authorization helpers."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from statistics import median
from typing import Any

from fastapi import HTTPException, status

from data.database import get_connection, initialize_and_migrate


JOB_STAGES = (
    "file_validation",
    "ocr",
    "field_extraction",
    "product_extraction",
    "market_research",
    "retailer_verification",
    "price_comparison",
    "risk_analysis",
    "persistence",
    "completed",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(
    *,
    user_id: str,
    invoice_id: str,
    job_type: str = "upload",
    total_products: int = 0,
) -> dict[str, Any]:
    initialize_and_migrate()
    job_id = str(uuid.uuid4())
    now = _now()
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO processing_jobs (
                job_id, invoice_id, user_id, job_type, status, stage,
                percent, completed_products, total_products, started_at,
                updated_at, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                invoice_id,
                user_id,
                job_type,
                "queued",
                "file_validation",
                0,
                0,
                max(0, int(total_products)),
                now,
                now,
                json.dumps({
                    "stage_started_at": now,
                    "stage_durations": {},
                }),
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return get_job(job_id)


def update_job(
    job_id: str,
    *,
    status_name: str | None = None,
    stage: str | None = None,
    percent: int | None = None,
    completed_products: int | None = None,
    total_products: int | None = None,
    details: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    current = get_job(job_id)
    if not current:
        raise KeyError(f"Processing job {job_id} was not found.")

    next_percent = current["percent"] if percent is None else max(current["percent"], min(100, int(percent)))
    next_status = status_name or current["status"]
    next_stage = stage or current["stage"]
    next_started_at = (
        _now()
        if current["status"] == "queued" and next_status == "running"
        else current["started_at"]
    )
    next_completed = (
        current["completed_products"]
        if completed_products is None
        else max(current["completed_products"], max(0, int(completed_products)))
    )
    next_total = current["total_products"] if total_products is None else max(0, int(total_products))
    completed_at = _now() if next_status in {"completed", "failed"} else current.get("completed_at")
    merged_details = dict(current.get("details") or {})
    starting_processing = current["status"] == "queued" and next_status == "running"
    if starting_processing:
        merged_details["stage_started_at"] = _now()
    if stage and stage != current.get("stage"):
        previous_stage_started = _parse_timestamp(
            merged_details.get("stage_started_at")
        )
        now = datetime.now(timezone.utc)
        if previous_stage_started and not starting_processing:
            duration = max(0.0, (now - previous_stage_started).total_seconds())
            stage_durations = merged_details.get("stage_durations")
            if not isinstance(stage_durations, dict):
                stage_durations = {}
            stage_durations[current["stage"]] = round(duration, 3)
            merged_details["stage_durations"] = stage_durations
        merged_details["stage_started_at"] = now.isoformat()
    if details:
        merged_details.update(details)

    connection = get_connection()
    try:
        connection.execute(
            """
            UPDATE processing_jobs
            SET status = ?, stage = ?, percent = ?, completed_products = ?,
                total_products = ?, started_at = ?, updated_at = ?, completed_at = ?,
                error_message = ?, details_json = ?
            WHERE job_id = ?
            """,
            (
                next_status,
                next_stage,
                next_percent,
                next_completed,
                next_total,
                next_started_at,
                _now(),
                completed_at,
                error_message,
                json.dumps(merged_details),
                job_id,
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return get_job(job_id)


def get_job(job_id: str) -> dict[str, Any] | None:
    initialize_and_migrate()
    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT job_id, invoice_id, user_id, job_type, status, stage,
                   percent, completed_products, total_products, started_at,
                   updated_at, completed_at, error_message, details_json
            FROM processing_jobs
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
        history_rows = connection.execute(
            """
            SELECT started_at, completed_at, details_json
            FROM processing_jobs
            WHERE job_type = (
                SELECT job_type FROM processing_jobs WHERE job_id = ?
            )
              AND status = 'completed'
              AND completed_at IS NOT NULL
            ORDER BY completed_at DESC
            LIMIT 20
            """,
            (job_id,),
        ).fetchall()
    finally:
        connection.close()

    if not row:
        return None
    try:
        details = json.loads(row["details_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        details = {}
    started_at = _parse_timestamp(row["started_at"])
    finished_at = _parse_timestamp(row["completed_at"]) if row["completed_at"] else datetime.now(timezone.utc)
    elapsed_seconds = (
        max(0, int((finished_at - started_at).total_seconds()))
        if started_at
        else None
    )
    historical_durations = [
        duration for history in history_rows
        if (duration := _duration_seconds(history["started_at"], history["completed_at"])) is not None
    ]
    historical_stage_durations: dict[str, list[float]] = {}
    for history in history_rows:
        try:
            history_details = json.loads(history["details_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        stage_durations = history_details.get("stage_durations", {}) if isinstance(history_details, dict) else {}
        if not isinstance(stage_durations, dict):
            continue
        for stage_name, duration in stage_durations.items():
            try:
                parsed_duration = float(duration)
            except (TypeError, ValueError):
                continue
            if parsed_duration >= 0:
                historical_stage_durations.setdefault(stage_name, []).append(parsed_duration)
    estimated_remaining_seconds = None
    if row["status"] == "running" and 0 < row["percent"] < 100 and len(historical_durations) >= 3:
        current_stage = row["stage"]
        try:
            stage_index = JOB_STAGES.index(current_stage)
        except ValueError:
            stage_index = len(JOB_STAGES) - 1
        remaining_stages = [
            stage_name for stage_name in JOB_STAGES[stage_index:]
            if stage_name != "completed"
        ]
        if all(len(historical_stage_durations.get(stage_name, [])) >= 3 for stage_name in remaining_stages):
            stage_medians = {
                stage_name: median(historical_stage_durations[stage_name])
                for stage_name in remaining_stages
            }
            percent_bounds = {
                "file_validation": (0, 5),
                "ocr": (5, 35),
                "field_extraction": (15, 35),
                "product_extraction": (35, 55),
                "market_research": (55, 73),
                "retailer_verification": (73, 78),
                "price_comparison": (78, 88),
                "risk_analysis": (88, 92),
                "persistence": (92, 100),
            }
            start_percent, end_percent = percent_bounds.get(
                current_stage,
                (0, 100),
            )
            stage_progress = min(
                1.0,
                max(0.0, (row["percent"] - start_percent) / max(1, end_percent - start_percent)),
            )
            current_stage_estimate = stage_medians.get(current_stage, 0) * (1 - stage_progress)
            future_stage_estimate = sum(
                stage_medians[stage_name]
                for stage_name in remaining_stages
                if stage_name != current_stage
            )
            estimated_remaining_seconds = max(
                0,
                int(current_stage_estimate + future_stage_estimate),
            )
        else:
            typical_duration = median(historical_durations)
            estimated_remaining_seconds = max(
                0,
                int(typical_duration * (100 - row["percent"]) / 100),
            )
    stage_durations = (
        details.get("stage_durations", {})
        if isinstance(details, dict)
        else {}
    )
    return {
        "job_id": row["job_id"],
        "invoice_id": row["invoice_id"],
        "job_type": row["job_type"],
        "status": row["status"],
        "stage": row["stage"],
        "percent": row["percent"],
        "completed_products": row["completed_products"],
        "total_products": row["total_products"],
        "started_at": row["started_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
        "error": row["error_message"],
        "details": details if isinstance(details, dict) else {},
        "elapsed_seconds": elapsed_seconds,
        "estimated_remaining_seconds": estimated_remaining_seconds,
        "stage_durations": stage_durations if isinstance(stage_durations, dict) else {},
        "owner_id": row["user_id"],
    }


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _duration_seconds(started_at: str | None, completed_at: str | None) -> int | None:
    started = _parse_timestamp(started_at)
    completed = _parse_timestamp(completed_at)
    if not started or not completed:
        return None
    return max(0, int((completed - started).total_seconds()))


def require_job_access(job_id: str, user: dict[str, Any]) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Processing job not found.")
    role = str(user.get("role") or "").strip().lower()
    if job["owner_id"] != user.get("id") and role not in {"admin", "reviewer", "finance", "finance-reviewer"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot access this processing job.")
    job.pop("owner_id", None)
    return job

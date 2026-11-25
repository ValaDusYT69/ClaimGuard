from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from data.database import get_connection, initialize_and_migrate
from invoice.jobs import create_job, get_job, require_job_access, update_job


def _insert_user(user_id: str) -> None:
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO users (
                id, full_name, email, hashed_password, role,
                is_verified, is_active, extra_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                "Processing Job Test",
                f"{user_id}@example.invalid",
                "test-hash",
                "user",
                1,
                1,
                "{}",
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _delete_user(user_id: str) -> None:
    connection = get_connection()
    try:
        connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
        connection.commit()
    finally:
        connection.close()


def test_processing_job_is_persisted_and_percent_never_regresses():
    initialize_and_migrate()
    user_id = f"job-user-{uuid.uuid4()}"
    _insert_user(user_id)
    try:
        job = create_job(
            user_id=user_id,
            invoice_id=f"INV-JOB-{uuid.uuid4()}",
            total_products=3,
        )
        assert job["status"] == "queued"
        assert job["percent"] == 0
        assert job["total_products"] == 3

        updated = update_job(
            job["job_id"],
            status_name="running",
            stage="market_research",
            percent=70,
            completed_products=2,
        )
        assert updated["percent"] == 70
        assert updated["completed_products"] == 2

        regressed = update_job(
            job["job_id"],
            stage="ocr",
            percent=15,
            completed_products=1,
        )
        assert regressed["percent"] == 70
        assert regressed["stage"] == "ocr"
        assert regressed["completed_products"] == 2
        assert get_job(job["job_id"])["percent"] == 70
    finally:
        _delete_user(user_id)


def test_processing_job_access_is_owner_or_authorized_reviewer_only():
    initialize_and_migrate()
    owner_id = f"job-owner-{uuid.uuid4()}"
    _insert_user(owner_id)
    try:
        job = create_job(
            user_id=owner_id,
            invoice_id=f"INV-JOB-{uuid.uuid4()}",
        )
        owner_view = require_job_access(job["job_id"], {"id": owner_id, "role": "user"})
        assert owner_view["job_id"] == job["job_id"]
        assert "owner_id" not in owner_view

        reviewer_view = require_job_access(
            job["job_id"],
            {"id": "different-user", "role": "reviewer"},
        )
        assert reviewer_view["job_id"] == job["job_id"]

        with pytest.raises(HTTPException) as error:
            require_job_access(
                job["job_id"],
                {"id": "different-user", "role": "user"},
            )
        assert error.value.status_code == 403
    finally:
        _delete_user(owner_id)

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import data.database as database
from auth import routes as auth_routes
from auth.security import create_access_token
from invoice import routes as invoice_routes
from main import app


def _user(user_id: str, role: str, *, active: bool = True) -> dict:
    return {
        "id": user_id,
        "full_name": user_id,
        "email": f"{user_id}@example.invalid",
        "hashed_password": "not-used",
        "role": role,
        "is_verified": True,
        "is_active": active,
    }


def _header(user: dict) -> dict[str, str]:
    token = create_access_token(
        user_id=user["id"],
        email=user["email"],
        role=user["role"],
        secret_key=auth_routes.SECRET_KEY,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_client(monkeypatch):
    admin = _user("admin", "admin")
    users = [admin, _user("reviewer", "reviewer"), _user("disabled", "user", active=False)]
    monkeypatch.setattr(invoice_routes, "read_users", lambda: users)
    monkeypatch.setattr(auth_routes, "read_users", lambda: users)
    return TestClient(app), admin, users


def _invoices():
    return [
        {
            "invoice_id": "older",
            "status": "approved",
            "uploaded_at": "2026-01-01T10:00:00+00:00",
            "risk_score": 0,
            "risk_level": "low",
            "extracted_data": {"vendor_name": "Old Vendor", "total_amount": 0},
            "decision": {"decision": "approved"},
            "anomalies": [],
        },
        {
            "invoice_id": "newer",
            "status": "pending_review",
            "uploaded_at": "2026-01-02T10:00:00+00:00",
            "risk_score": 80,
            "risk_level": "high",
            "extracted_data": {"vendor_name": "New Vendor", "total_amount": 1250},
            "anomalies": [{"anomaly_type": "possible_duplicate"}],
        },
        {
            "invoice_id": "missing-risk",
            "status": "verification_required",
            "uploaded_at": "2025-12-31T10:00:00+00:00",
            "extracted_data": {"vendor_name": "Unknown Risk"},
            "anomalies": [],
        },
    ]


def test_admin_overview_returns_authoritative_metrics_and_recent_rows(
    admin_client, monkeypatch
):
    client, admin, _ = admin_client
    monkeypatch.setattr(invoice_routes, "read_invoices", _invoices)

    response = client.get(
        "/api/invoices/admin/overview?limit=2",
        headers=_header(admin),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"] == {
        "total_invoices": 3,
        "approved": 1,
        "rejected": 0,
        "pending_review": 2,
        "verification_required": 1,
        "high_risk": 1,
        "medium_risk": 0,
        "low_risk": 1,
        "anomaly_signals": 1,
        "total_users": 3,
        "active_users": 2,
        "reviewer_accounts": 1,
    }
    assert [row["invoice_id"] for row in payload["invoices"]] == ["newer", "older"]
    assert payload["invoices"][1]["amount"] == 0
    assert payload["pagination"]["has_more"] is True
    datetime.fromisoformat(payload["generated_at"].replace("Z", "+00:00"))


def test_admin_overview_sorts_valid_null_missing_and_malformed_timestamps(
    admin_client, monkeypatch
):
    client, admin, _ = admin_client
    monkeypatch.setattr(
        invoice_routes,
        "read_invoices",
        lambda: [
            {"invoice_id": "old", "uploaded_at": "2026-11-19T10:00:00Z", "status": "approved"},
            {"invoice_id": "offset", "uploaded_at": "2026-11-20T12:00:00+02:00", "status": "pending_review"},
            {"invoice_id": "new", "uploaded_at": "2026-11-20T11:30:00Z", "status": "pending_review"},
            {"invoice_id": "null", "uploaded_at": None, "status": "pending_review"},
            {"invoice_id": "missing", "status": "pending_review"},
            {"invoice_id": "malformed", "uploaded_at": "not-a-timestamp", "status": "pending_review"},
        ],
    )

    response = client.get(
        "/api/invoices/admin/overview?limit=100",
        headers=_header(admin),
    )

    assert response.status_code == 200
    rows = response.json()["invoices"]
    assert [row["invoice_id"] for row in rows[:3]] == ["new", "offset", "old"]
    assert {"null", "missing", "malformed"} <= {
        row["invoice_id"] for row in rows[3:]
    }
    assert len(rows) == 6


def test_admin_reports_match_overview_and_pagination_is_bounded(
    admin_client, monkeypatch
):
    client, admin, _ = admin_client
    monkeypatch.setattr(invoice_routes, "read_invoices", _invoices)

    overview = client.get(
        "/api/invoices/admin/overview?limit=1&offset=1",
        headers=_header(admin),
    ).json()
    reports = client.get(
        "/api/invoices/admin/reports",
        headers=_header(admin),
    ).json()

    assert [row["invoice_id"] for row in overview["invoices"]] == ["older"]
    assert reports["summary"] == {
        "total_invoices": 3,
        "approved": 1,
        "rejected": 0,
        "pending_review": 2,
        "verification_required": 1,
        "high_risk": 1,
        "medium_risk": 0,
        "low_risk": 1,
        "anomaly_signals": 1,
    }
    assert reports["top_anomalies"] == [
        {"type": "possible_duplicate", "count": 1}
    ]


@pytest.mark.parametrize(
    "path",
    [
        "/api/invoices/admin/overview",
        "/api/invoices/admin/reports",
        "/api/auth/admin/users",
    ],
)
def test_reviewer_and_user_are_forbidden_from_admin_apis(admin_client, path):
    client, _, users = admin_client
    for user in users[1:]:
        assert client.get(path, headers=_header(user)).status_code == 403


def test_admin_management_api_returns_real_accounts(admin_client):
    client, admin, users = admin_client
    response = client.get("/api/auth/admin/users", headers=_header(admin))

    assert response.status_code == 200
    assert response.json()["count"] == len(users)
    assert response.json()["users"][2]["is_active"] is False


def test_admin_apis_use_real_postgresql_test_database():
    suffix = uuid4().hex
    admin_id = f"test-admin-{suffix}"
    reviewer_id = f"test-reviewer-{suffix}"
    user_id = f"test-user-{suffix}"
    invoice_ids = [f"test-invoice-{suffix}-{index}" for index in range(4)]

    admin = _user(admin_id, "admin")

    connection = database.get_connection()
    try:
        for account in (
            admin,
            _user(reviewer_id, "reviewer"),
            _user(user_id, "user"),
        ):
            connection.execute(
                """
                INSERT INTO users (
                    id, full_name, email, hashed_password,
                    role, is_verified, is_active
                )
                VALUES (?, ?, ?, ?, ?, 1, 1)
                """,
                (
                    account["id"],
                    account["full_name"],
                    account["email"],
                    account["hashed_password"],
                    account["role"],
                ),
            )
        timestamp_values = (
            "2026-11-20T11:30:00Z",
            "2026-11-20T12:00:00+02:00",
            "2026-11-19T10:00:00",
            None,
        )
        for index, invoice_id in enumerate(invoice_ids):
            connection.execute(
                """
                INSERT INTO invoices (
                    invoice_id, uploaded_by, invoice_number,
                    vendor_name, status, uploaded_at, record_json
                )
                VALUES (?, ?, ?, ?, 'pending_review', ?, '{}')
                """,
                (
                    invoice_id,
                    user_id,
                    f"INV-{suffix}-{index}",
                    "Test Vendor",
                    timestamp_values[index],
                ),
            )
        connection.commit()
    finally:
        connection.close()

    client = TestClient(app)
    headers = _header(admin)
    try:
        profile = client.get("/api/auth/me", headers=headers)
        overview = client.get("/api/invoices/admin/overview?limit=100", headers=headers)

        assert profile.status_code == 200
        assert profile.json()["user"]["role"] == "admin"
        assert profile.json()["capabilities"]["can_view_admin_dashboard"] is True
        assert overview.status_code == 200
        payload = overview.json()
        assert payload["success"] is True
        assert payload["metrics"]["total_invoices"] >= 1
        returned_ids = [row["invoice_id"] for row in payload["invoices"]]
        assert all(invoice_id in returned_ids for invoice_id in invoice_ids)
        assert returned_ids.index(invoice_ids[0]) < returned_ids.index(invoice_ids[1])
        assert returned_ids.index(invoice_ids[1]) < returned_ids.index(invoice_ids[2])
        assert returned_ids.index(invoice_ids[2]) < returned_ids.index(invoice_ids[3])
    finally:
        connection = database.get_connection()
        connection.execute(
            "DELETE FROM invoices WHERE invoice_id IN (?, ?, ?, ?)",
            tuple(invoice_ids),
        )
        connection.execute(
            "DELETE FROM users WHERE id IN (?, ?, ?)",
            (admin_id, reviewer_id, user_id),
        )
        connection.commit()
        connection.close()

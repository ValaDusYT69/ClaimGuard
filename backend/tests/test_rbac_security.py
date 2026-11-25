"""Server-side RBAC regression tests.

These tests use the PostgreSQL test database selected by conftest.py for the
application lifespan, while replacing user/invoice repositories with isolated
in-memory fixtures. No production database or production account is touched.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from auth import routes as auth_routes
from auth.security import create_access_token
from invoice import routes as invoice_routes
from main import app


def _user(user_id: str, role: str, *, active: bool = True) -> dict:
    return {
        "id": user_id,
        "full_name": f"Test {role}",
        "email": f"{user_id}@example.invalid",
        "hashed_password": "not-used-by-these-tests",
        "role": role,
        "is_verified": True,
        "is_active": active,
    }


def _token(user: dict, *, role_claim: str | None = None) -> str:
    return create_access_token(
        user_id=user["id"],
        email=user["email"],
        role=role_claim or user["role"],
        secret_key=auth_routes.SECRET_KEY,
    )


@pytest.fixture
def client_and_users(monkeypatch):
    users = [
        _user("rbac-admin", "admin"),
        _user("rbac-reviewer", "reviewer"),
        _user("rbac-user", "user"),
    ]
    writes: list[list[dict]] = []

    monkeypatch.setattr(auth_routes, "read_users", lambda: deepcopy(users))
    monkeypatch.setattr(invoice_routes, "read_users", lambda: deepcopy(users))
    monkeypatch.setattr(invoice_routes, "read_invoices", lambda: [])
    monkeypatch.setattr(
        auth_routes,
        "write_users",
        lambda value: writes.append(deepcopy(value)),
    )

    # Do not enter the TestClient lifespan here. The endpoint tests use
    # isolated repository fixtures and deliberately do not need schema setup;
    # pytest still requires and validates TEST_DATABASE_URL via conftest.py.
    yield TestClient(app), users, writes


def _auth_header(user: dict, *, role_claim: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user, role_claim=role_claim)}"}


def test_only_database_admin_can_access_admin_user_api(client_and_users):
    client, users, _ = client_and_users
    admin, reviewer, regular_user = users

    assert client.get("/api/auth/admin/users").status_code == 401
    assert client.get(
        "/api/auth/admin/users", headers=_auth_header(admin)
    ).status_code == 200
    assert client.get(
        "/api/auth/admin/users", headers=_auth_header(reviewer)
    ).status_code == 403
    assert client.get(
        "/api/auth/admin/users", headers=_auth_header(regular_user)
    ).status_code == 403


@pytest.mark.parametrize(
    "path",
    [
        "/api/invoices/admin/overview",
        "/api/invoices/admin/reports",
        "/api/invoices/admin/reports/export.csv",
    ],
)
def test_non_admin_roles_cannot_access_any_admin_invoice_api(
    client_and_users, path
):
    client, users, _ = client_and_users
    for user in users[1:]:
        response = client.get(path, headers=_auth_header(user))
        assert response.status_code == 403


@pytest.mark.parametrize(
    "path",
    [
        "/api/invoices/admin/overview",
        "/api/invoices/admin/reports",
        "/api/invoices/admin/reports/export.csv",
    ],
)
def test_database_admin_can_access_admin_invoice_api(client_and_users, path):
    client, users, _ = client_and_users

    response = client.get(path, headers=_auth_header(users[0]))

    assert response.status_code == 200


def test_forged_admin_role_claim_does_not_elevate_regular_user(client_and_users):
    client, users, _ = client_and_users
    regular_user = users[2]

    response = client.get(
        "/api/auth/admin/users",
        headers=_auth_header(regular_user, role_claim="admin"),
    )

    assert response.status_code == 403


def test_server_profile_uses_database_role_not_client_claim(client_and_users):
    client, users, _ = client_and_users

    response = client.get(
        "/api/auth/me",
        headers=_auth_header(users[2], role_claim="admin"),
    )

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "user"
    assert response.json()["capabilities"]["can_view_admin_dashboard"] is False
    assert response.json()["capabilities"]["can_review_invoices"] is False


def test_profile_exposes_review_permission_only_to_reviewer(client_and_users):
    client, users, _ = client_and_users
    admin, reviewer, regular_user = users

    profiles = [
        client.get("/api/auth/me", headers=_auth_header(admin)).json(),
        client.get("/api/auth/me", headers=_auth_header(reviewer)).json(),
        client.get("/api/auth/me", headers=_auth_header(regular_user)).json(),
    ]

    assert profiles[0]["capabilities"]["can_review_invoices"] is False
    assert profiles[1]["capabilities"]["can_review_invoices"] is True
    assert profiles[2]["capabilities"]["can_review_invoices"] is False


def test_admin_cannot_submit_invoice_decision(client_and_users, monkeypatch):
    client, users, _ = client_and_users
    admin = users[0]
    monkeypatch.setattr(
        invoice_routes,
        "read_invoices",
        lambda: [{"invoice_id": "invoice", "uploaded_by": users[2]["id"], "status": "pending_review"}],
    )

    response = client.post(
        "/api/invoices/invoice/decision",
        headers=_auth_header(admin),
        json={"decision": "approved", "note": ""},
    )

    assert response.status_code == 403


def test_regular_user_cannot_submit_invoice_decision(client_and_users, monkeypatch):
    client, users, _ = client_and_users
    regular_user = users[2]
    monkeypatch.setattr(
        invoice_routes,
        "read_invoices",
        lambda: [
            {
                "invoice_id": "owned-invoice",
                "uploaded_by": regular_user["id"],
                "status": "pending_review",
            }
        ],
    )

    response = client.post(
        "/api/invoices/owned-invoice/decision",
        headers=_auth_header(regular_user),
        json={"decision": "approved", "note": ""},
    )

    assert response.status_code == 403


def test_user_invoice_list_is_owned_by_authenticated_user(client_and_users, monkeypatch):
    client, users, _ = client_and_users
    owner, other_user = users[2], users[1]
    monkeypatch.setattr(
        invoice_routes,
        "read_invoices",
        lambda: [
            {"invoice_id": "owned", "uploaded_by": owner["id"]},
            {"invoice_id": "other", "uploaded_by": other_user["id"]},
            {"invoice_id": "legacy", "uploaded_by": None},
        ],
    )

    response = client.get("/api/invoices/my", headers=_auth_header(owner))

    assert response.status_code == 200
    assert [invoice["invoice_id"] for invoice in response.json()["invoices"]] == [
        "owned"
    ]


def test_upload_persists_authenticated_uploader(
    client_and_users, monkeypatch, tmp_path
):
    client, users, _ = client_and_users
    owner = users[2]
    stored: list[dict] = []
    scheduled: list[tuple] = []
    extraction_calls: list[tuple] = []

    monkeypatch.setattr(invoice_routes, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(invoice_routes, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        invoice_routes,
        "read_invoices",
        lambda: deepcopy(stored),
    )
    monkeypatch.setattr(
        invoice_routes,
        "write_invoices",
        lambda invoices: stored.__setitem__(slice(None), deepcopy(invoices)),
    )
    monkeypatch.setattr(
        invoice_routes,
        "extract_invoice_data",
        lambda *args, **kwargs: extraction_calls.append((args, kwargs)) or {
            "invoice_number": "UP-1",
            "vendor_name": "Uploader Vendor",
            "total_amount": 125,
            "line_items": [],
            "extraction_status": "extracted",
        },
    )
    monkeypatch.setattr(
        invoice_routes,
        "analyze_invoice_market",
        lambda **_: {},
    )
    monkeypatch.setattr(
        invoice_routes,
        "enrich_market_analysis",
        lambda market, *_: market,
    )
    monkeypatch.setattr(
        invoice_routes,
        "analyze_invoice_risk",
        lambda **_: {"risk_score": 0, "risk_level": "low", "anomalies": []},
    )
    monkeypatch.setattr(
        invoice_routes,
        "verify_invoice",
        lambda **_: {"status": "verified_document"},
    )
    monkeypatch.setattr(
        invoice_routes,
        "create_job",
        lambda **_: {"job_id": "job-upload-test"},
    )
    monkeypatch.setattr(invoice_routes, "update_job", lambda *_, **__: {})
    monkeypatch.setattr(
        invoice_routes.BackgroundTasks,
        "add_task",
        lambda self, function, *args, **kwargs: scheduled.append((function, args, kwargs)),
    )

    response = client.post(
        "/api/invoices/upload",
        headers=_auth_header(owner),
        files={"file": ("invoice.txt", b"invoice", "text/plain")},
    )

    assert response.status_code == 400

    response = client.post(
        "/api/invoices/upload",
        headers=_auth_header(owner),
        files={"file": ("invoice.pdf", b"invoice", "application/pdf")},
    )

    assert response.status_code == 202
    assert stored
    assert stored[0]["uploaded_by"] == owner["id"]
    assert stored[0]["status"] == "processing"
    assert response.json()["processing_job"]["job_id"] == "job-upload-test"
    assert len(scheduled) == 1
    assert scheduled[0][0] is invoice_routes._run_initial_upload_analysis
    assert extraction_calls == []


def test_frontend_invoice_navigation_uses_server_capabilities():
    root = Path(__file__).parents[2]
    details = (root / "frontend" / "invoice-details.html").read_text(
        encoding="utf-8"
    )

    assert "currentCapabilities.can_view_admin_dashboard === true" in details
    assert '"Admin Dashboard"' in details
    assert '"Finance Dashboard"' in details
    assert '"User Dashboard"' in details


def test_login_redirect_uses_server_validated_role():
    root = Path(__file__).parents[2]
    app_source = (root / "frontend" / "js" / "app.js").read_text(
        encoding="utf-8"
    )

    assert "/api/auth/me" in app_source
    assert "redirectByRole(profile?.user?.role)" in app_source
    assert 'window.location.href = "admin-dashboard.html"' in app_source
    assert 'window.location.href = "reviewer-dashboard.html"' in app_source
    assert 'window.location.href = "user-dashboard.html"' in app_source


def test_dashboards_have_server_side_page_role_guards():
    root = Path(__file__).parents[2]
    admin = (root / "frontend" / "admin-dashboard.html").read_text(encoding="utf-8")
    reviewer = (root / "frontend" / "reviewer-dashboard.html").read_text(encoding="utf-8")
    user = (root / "frontend" / "user-dashboard.html").read_text(encoding="utf-8")

    assert "/api/auth/me" in admin
    assert "can_view_admin_dashboard" in admin
    assert "/api/auth/me" in reviewer
    assert "role === \"admin\"" in reviewer
    assert "role === \"user\"" in reviewer
    assert "/api/auth/me" in user
    assert 'window.location.replace("admin-dashboard.html")' in user
    assert 'window.location.replace("reviewer-dashboard.html")' in user


def test_non_admin_cannot_change_any_account_role(client_and_users):
    client, users, writes = client_and_users
    reviewer, regular_user = users[1], users[2]

    for actor in (reviewer, regular_user):
        response = client.patch(
            f"/api/auth/admin/users/{reviewer['id']}/role",
            headers=_auth_header(actor),
            json={"role": "admin"},
        )
        assert response.status_code == 403

    assert writes == []


def test_admin_cannot_assign_admin_role_through_managed_role_endpoint(
    client_and_users,
):
    client, users, writes = client_and_users
    admin, reviewer = users[0], users[1]

    response = client.patch(
        f"/api/auth/admin/users/{reviewer['id']}/role",
        headers=_auth_header(admin),
        json={"role": "admin"},
    )

    assert response.status_code == 400
    assert writes == []


def test_public_registration_ignores_forged_privileged_role(
    client_and_users, monkeypatch
):
    client, _, writes = client_and_users
    monkeypatch.setattr(auth_routes, "read_users", lambda: [])
    monkeypatch.setattr(auth_routes, "save_verification_otp", lambda **_: "000000")
    monkeypatch.setattr(auth_routes, "send_otp_email", lambda **_: None)

    response = client.post(
        "/api/auth/register",
        json={
            "full_name": "New Test User",
            "email": "new-user@example.com",
            "password": "strong-test-password",
            "role": "admin",
            "is_admin": True,
        },
    )

    assert response.status_code == 200
    assert writes[-1][0]["role"] == "user"


def test_user_cannot_read_another_users_invoice(client_and_users, monkeypatch):
    client, users, _ = client_and_users
    regular_user = users[2]
    monkeypatch.setattr(
        invoice_routes,
        "read_invoices",
        lambda: [
            {"invoice_id": "owned", "uploaded_by": regular_user["id"]},
            {"invoice_id": "foreign", "uploaded_by": users[1]["id"]},
        ],
    )

    assert client.get(
        "/api/invoices/owned", headers=_auth_header(regular_user)
    ).status_code == 200
    assert client.get(
        "/api/invoices/foreign", headers=_auth_header(regular_user)
    ).status_code == 404


def test_reviewer_cannot_decide_invoice_not_in_review_queue(
    client_and_users, monkeypatch
):
    client, users, _ = client_and_users
    reviewer = users[1]
    writes: list[list[dict]] = []
    monkeypatch.setattr(
        invoice_routes,
        "read_invoices",
        lambda: [
            {"invoice_id": "not-routed", "uploaded_by": users[2]["id"], "status": "processing"}
        ],
    )
    monkeypatch.setattr(invoice_routes, "write_invoices", lambda value: writes.append(value))

    response = client.post(
        "/api/invoices/not-routed/decision",
        headers=_auth_header(reviewer),
        json={"decision": "approved", "note": "attempt"},
    )

    assert response.status_code == 409
    assert writes == []


def test_regular_user_cannot_submit_reviewer_decision(client_and_users, monkeypatch):
    client, users, _ = client_and_users
    regular_user = users[2]
    writes: list[list[dict]] = []
    monkeypatch.setattr(
        invoice_routes,
        "read_invoices",
        lambda: [
            {"invoice_id": "review-queue", "uploaded_by": users[1]["id"], "status": "pending_review"}
        ],
    )
    monkeypatch.setattr(invoice_routes, "write_invoices", lambda value: writes.append(value))

    response = client.post(
        "/api/invoices/review-queue/decision",
        headers=_auth_header(regular_user),
        json={"decision": "approved", "note": "attempt"},
    )

    assert response.status_code == 403
    assert writes == []

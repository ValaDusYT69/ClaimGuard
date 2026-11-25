import unittest
from uuid import uuid4
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

import auth.routes
import auth.storage
import data.database
import email_service
from invoice.routes import (
    _safe_csv_value,
    can_view_any_invoice,
    require_invoice_upload_access,
    require_reviewer_access,
)


class UserStorageTests(unittest.TestCase):
    def setUp(self):
        self.user_id = f"test-reliability-{uuid4().hex}"
        self.invoice_id = f"test-invoice-{uuid4().hex}"
        data.database.initialize_and_migrate()

    def tearDown(self):
        connection = data.database.get_connection()
        connection.execute("DELETE FROM invoices WHERE invoice_id = ?", (self.invoice_id,))
        connection.execute("DELETE FROM users WHERE id = ?", (self.user_id,))
        connection.commit()
        connection.close()

    def test_updating_existing_user_preserves_invoice_owner(self):
        connection = data.database.get_connection()
        connection.execute(
            """
            INSERT INTO users (
                id, full_name, email, hashed_password, role,
                is_verified, is_active
            )
            VALUES (?, 'User One', ?, 'hash', 'user', 1, 1)
            """, (self.user_id, f"{self.user_id}@example.test"))
        connection.execute(
            """
            INSERT INTO invoices (invoice_id, uploaded_by, record_json)
            VALUES (?, ?, '{}')
            """, (self.invoice_id, self.user_id))
        connection.commit()
        connection.close()

        auth.storage.write_users(
            [
                {
                    "id": self.user_id,
                    "full_name": "User One",
                    "email": f"{self.user_id}@example.test",
                    "hashed_password": "hash",
                    "role": "reviewer",
                    "is_verified": True,
                    "is_active": True,
                }
            ]
        )

        connection = data.database.get_connection()
        row = connection.execute(
            """
            SELECT users.role, invoices.uploaded_by
            FROM users
            JOIN invoices ON invoices.uploaded_by = users.id
            WHERE invoices.invoice_id = ?
            """, (self.invoice_id,)).fetchone()
        connection.close()

        self.assertEqual(row["role"], "reviewer")
        self.assertEqual(row["uploaded_by"], self.user_id)

    def test_omitted_users_are_still_removed(self):
        connection = data.database.get_connection()
        connection.execute(
            """
            INSERT INTO users (
                id, full_name, email, hashed_password, role,
                is_verified, is_active
            )
            VALUES (?, 'User One', ?, 'hash', 'user', 1, 1)
            """, (self.user_id, f"{self.user_id}@example.test"))
        connection.commit()
        connection.close()

        auth.storage.write_users([])

        connection = data.database.get_connection()
        count = connection.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]
        connection.close()

        self.assertEqual(count, 0)


class AuthenticationAndEmailTests(unittest.TestCase):
    def test_otp_generation_uses_cryptographic_random_source(self):
        with patch.object(auth.routes.secrets, "randbelow", return_value=0) as randbelow:
            self.assertEqual(auth.routes.generate_otp(), "100000")

        randbelow.assert_called_once_with(900000)

    def test_email_sender_fails_when_credentials_are_missing(self):
        with (
            patch.object(email_service, "EMAIL_USER", ""),
            patch.object(email_service, "EMAIL_APP_PASSWORD", ""),
            patch.object(email_service.smtplib, "SMTP_SSL") as smtp_ssl,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Email delivery is not configured",
            ):
                email_service.send_otp_email(
                    "user@example.com",
                    "123456",
                )

        smtp_ssl.assert_not_called()

    def test_email_sender_uses_configured_smtp_and_timeout(self):
        smtp = MagicMock()
        smtp.__enter__.return_value = smtp
        with (
            patch.object(email_service, "EMAIL_USER", "sender@example.com"),
            patch.object(email_service, "EMAIL_APP_PASSWORD", "test-app-password"),
            patch.object(email_service.smtplib, "SMTP_SSL", return_value=smtp) as smtp_ssl,
        ):
            email_service.send_otp_email(
                "recipient@example.com",
                "123456",
            )

        smtp_ssl.assert_called_once_with(
            email_service.SMTP_HOST,
            email_service.SMTP_PORT,
            timeout=10,
        )
        smtp.login.assert_called_once_with(
            "sender@example.com",
            "test-app-password",
        )
        smtp.send_message.assert_called_once()

    def test_smtp_authentication_error_is_sanitized(self):
        smtp = MagicMock()
        smtp.__enter__.return_value = smtp
        smtp.login.side_effect = email_service.smtplib.SMTPAuthenticationError(
            535,
            b"invalid sender credentials",
        )

        with (
            patch.object(email_service, "EMAIL_USER", "sender@example.com"),
            patch.object(email_service, "EMAIL_APP_PASSWORD", "test-app-password"),
            patch.object(email_service.smtplib, "SMTP_SSL", return_value=smtp),
        ):
            with self.assertRaises(RuntimeError) as raised:
                email_service.send_otp_email(
                    "recipient@example.com",
                    "123456",
                )

        self.assertEqual(
            str(raised.exception),
            "SMTP authentication failed. Check the configured sender credentials.",
        )
        self.assertNotIn("invalid sender credentials", str(raised.exception))

    def test_csv_export_neutralizes_spreadsheet_formulas(self):
        self.assertEqual(_safe_csv_value("=SUM(A1:A2)"), "'=SUM(A1:A2)")
        self.assertEqual(_safe_csv_value("  +1+1"), "'  +1+1")
        self.assertEqual(_safe_csv_value("\t@SUM(A1)"), "'\t@SUM(A1)")
        self.assertEqual(_safe_csv_value("Vendor name"), "Vendor name")
        self.assertEqual(_safe_csv_value(12.5), 12.5)


class InvoiceRoleTests(unittest.TestCase):
    def test_only_normal_users_can_upload(self):
        require_invoice_upload_access({"role": "user"})

        for role in ("reviewer", "admin", "unexpected-role"):
            with self.subTest(role=role):
                with self.assertRaises(HTTPException) as raised:
                    require_invoice_upload_access({"role": role})
                self.assertEqual(raised.exception.status_code, 403)

    def test_only_reviewers_can_make_decisions_but_admin_can_inspect_all(self):
        for role in ("reviewer", "finance/reviewer"):
            with self.subTest(role=role):
                require_reviewer_access({"role": role})
                self.assertTrue(can_view_any_invoice({"role": role}))

        self.assertTrue(can_view_any_invoice({"role": "admin"}))

        for role in ("user", "unexpected-role"):
            with self.subTest(role=role):
                with self.assertRaises(HTTPException) as raised:
                    require_reviewer_access({"role": role})
                self.assertEqual(raised.exception.status_code, 403)
                self.assertFalse(can_view_any_invoice({"role": role}))


if __name__ == "__main__":
    unittest.main()

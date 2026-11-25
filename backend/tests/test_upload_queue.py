from __future__ import annotations

import asyncio
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import BackgroundTasks
from fastapi.datastructures import UploadFile

from invoice import routes


class UploadQueueTests(unittest.TestCase):
    def test_upload_returns_202_before_invoice_extraction_runs(self):
        stored_invoices = []
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            background_tasks = BackgroundTasks()
            upload = UploadFile(
                filename="invoice.pdf",
                file=io.BytesIO(b"pdf bytes"),
            )

            def read_invoices():
                return copy.deepcopy(stored_invoices)

            def write_invoices(invoices):
                stored_invoices[:] = copy.deepcopy(invoices)

            with patch.object(routes, "UPLOAD_DIR", root / "uploads"), patch.object(
                routes, "BASE_DIR", root
            ), patch.object(
                routes,
                "get_current_user",
                return_value={"id": "test-owner", "role": "user"},
            ), patch.object(
                routes, "require_invoice_upload_access"
            ), patch.object(
                routes, "create_job", return_value={"job_id": "job-test"}
            ), patch.object(
                routes, "read_invoices", side_effect=read_invoices
            ), patch.object(
                routes, "write_invoices", side_effect=write_invoices
            ), patch.object(
                routes,
                "extract_invoice_data",
                side_effect=AssertionError("extraction must run after the response"),
            ):
                response = asyncio.run(
                    routes.upload_invoice(background_tasks, upload)
                )

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(payload["invoice_id"], payload["invoice"]["invoice_id"])
        self.assertEqual(payload["processing_job"]["job_id"], "job-test")
        self.assertEqual(payload["invoice"]["status"], "processing")
        self.assertEqual(payload["invoice"]["uploaded_by"], "test-owner")
        self.assertEqual(len(background_tasks.tasks), 1)
        self.assertIs(
            background_tasks.tasks[0].func,
            routes._run_initial_upload_analysis,
        )


if __name__ == "__main__":
    unittest.main()

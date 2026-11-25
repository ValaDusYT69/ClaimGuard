import unittest
from pathlib import Path
from unittest.mock import patch

from invoice import extractor
from invoice.extractor import OCR_LANG, _select_best_ocr_attempt


class OcrSelectionTests(unittest.TestCase):
    def test_selects_one_attempt_for_a_page(self):
        selected = _select_best_ocr_attempt([
            "Invoice 1001\nTotal 250",
            "Invoice 1001\nTotal 250\nVAT 37.50",
        ])

        self.assertEqual(selected, "Invoice 1001\nTotal 250\nVAT 37.50")

    def test_ocr_language_defaults_to_bengali_and_english(self):
        self.assertEqual(OCR_LANG, "ben+eng")

    def test_searchable_pdf_skips_structured_ocr(self):
        with patch.object(
            extractor,
            "extract_file_text",
            return_value=("Invoice 1001\nTotal 250", "pdf_text"),
        ), patch.object(
            extractor,
            "extract_invoice_fields",
            return_value={
                "invoice_number": "1001",
                "vendor_name": "Test Vendor",
                "total_amount": 250,
                "product_description": "Test item",
                "line_items": [{"product": "Test item", "line_amount": 250}],
            },
        ), patch.object(
            extractor,
            "extract_structured_ocr_fields",
            side_effect=AssertionError("searchable PDF should not be OCRed"),
        ):
            result = extractor.extract_invoice_data(Path("searchable.pdf"), ".pdf")

        self.assertEqual(result["invoice_number"], "1001")
        self.assertEqual(result["extraction_method"], "pdf_text")

    def test_scanned_pdf_reuses_rendered_pages_for_ocr_and_structure(self):
        rendered = [b"page-one", b"page-two"]
        ocr_pages = []
        structured_pages = []

        def fake_ocr(_path, pages):
            ocr_pages.extend(pages)
            return "Page one text\nPage two text"

        with patch.object(extractor, "extract_pdf_text", return_value=""), patch.object(
            extractor, "_render_pdf_pages", return_value=rendered
        ) as render, patch.object(
            extractor, "extract_pdf_with_ocr", side_effect=fake_ocr
        ), patch.object(
            extractor,
            "extract_invoice_fields",
            return_value={
                "line_items": [{"product": "Test item", "line_amount": 10}],
                "product_description": "Test item",
                "total_amount": 10,
            },
        ), patch.object(
            extractor,
            "extract_structured_ocr_fields",
            side_effect=lambda _path, rendered_pages=None: structured_pages.extend(rendered_pages or []) or {},
        ):
            result = extractor.extract_invoice_data(Path("scanned.pdf"), ".pdf")

        self.assertEqual(result["extraction_method"], "pdf_ocr")
        self.assertEqual(ocr_pages, rendered)
        self.assertEqual(structured_pages, rendered)
        render.assert_called_once_with(Path("scanned.pdf"))


if __name__ == "__main__":
    unittest.main()

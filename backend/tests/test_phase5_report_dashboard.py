from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from invoice.report_service import build_invoice_report


BASE_INVOICE = {
    "invoice_id": "INV-PHASE5-001",
    "status": "pending_review",
    "extracted_data": {
        "vendor_name": "Example Technology Ltd.",
        "invoice_number": "ET-2026-105",
        "invoice_date": "2026-11-10",
        "currency": "BDT",
        "customer_name": "Example Buyer",
        "subtotal": 12000,
        "discount": 500,
        "tax_amount": 750,
        "total_amount": 12250,
        "payment_method": "Bank transfer",
        "transaction_id": "TXN-123456",
        "line_items": [
            {
                "product": "Keyboard Model K1",
                "sku": "K1-RED",
                "quantity": 2,
                "unit": "pcs",
                "unit_price": 6000,
                "discount": 500,
                "tax_amount": 750,
                "line_amount": 12250,
                "extraction_warnings": [],
            }
        ],
        "line_items_total": 12250,
        "product_line_count": 1,
        "total_reconciliation": "matched",
        "extraction_completeness_score": 100,
        "extraction_warnings": [],
        "field_provenance": {
            "vendor_name": {"source": "ocr_text_match", "confidence": 0.98},
            "invoice_number": {"source": "structured_extractor", "confidence": None},
            "line_items": {"source": "ocr_table_extraction", "confidence": None},
        },
        "raw_text_preview": "PRIVATE OCR TRANSCRIPT SHOULD NOT APPEAR",
        "ocr_metadata": {"engine": "tesseract", "language": "ben+eng", "version": "5.5.3"},
    },
    "market_analysis": {"status": "pending", "product_analyses": []},
}


def extract_pdf_text(invoice: dict) -> str:
    payload = build_invoice_report(invoice)
    assert payload.startswith(b"%PDF")
    reader = PdfReader(BytesIO(payload))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_pdf_includes_extraction_quality_field_provenance_and_additional_fields():
    text = extract_pdf_text(BASE_INVOICE)
    for expected in (
        "Extraction quality and completeness",
        "100/100",
        "row-completeness heuristic only",
        "Field extraction provenance",
        "OCR text match",
        "98%",
        "Payment Method",
        "Bank transfer",
        "Transaction Id",
        "TXN-123456",
        "Tesseract",
        "ben+eng",
    ):
        assert expected.lower() in text.lower()
    assert "PRIVATE OCR TRANSCRIPT SHOULD NOT APPEAR" not in text


def test_pdf_explains_missing_extraction_fields_and_row_warnings():
    invoice = {
        "invoice_id": "INV-WARNINGS",
        "extracted_data": {
            "currency": "BDT",
            "total_amount": 900,
            "line_items": [
                {
                    "product": "Unnamed line",
                    "quantity": None,
                    "unit_price": 900,
                    "line_amount": None,
                    "extraction_warnings": ["missing_quantity", "missing_line_total"],
                }
            ],
            "product_line_count": 1,
            "line_items_total": 0,
            "total_reconciliation": "mismatch",
            "extraction_completeness_score": 0,
            "extraction_warnings": [
                "vendor_not_identified",
                "some_product_rows_are_incomplete",
                "line_items_do_not_reconcile_to_invoice_total",
            ],
        },
    }
    text = extract_pdf_text(invoice)
    assert "Vendor name was not identified" in text
    assert "One or more product rows have incomplete fields" in text
    assert "Extracted line totals do not reconcile" in text
    assert "missing quantity" in text.lower()
    assert "missing line total" in text.lower()
    assert "Mismatch" in text


def test_pdf_includes_discount_tax_and_line_total_for_each_product():
    text = extract_pdf_text(BASE_INVOICE)
    assert "Extracted product-line details" in text
    assert "K1-RED" in text
    assert "Discount: BDT 500" in text
    assert "Tax: BDT 750" in text
    assert "Line total: BDT 12,250" in text


def test_dashboard_offers_authenticated_pdf_download_per_invoice():
    dashboard_path = Path(__file__).parents[2] / "frontend" / "user-dashboard.html"
    html = dashboard_path.read_text(encoding="utf-8")
    assert 'data-report-invoice-id="${escapeHtml(invoiceId)}"' in html
    assert "downloadDashboardInvoiceReport" in html
    assert '"Authorization": `Bearer ${accessToken}`' in html
    assert "/report" in html
    assert "Market Coverage" in html

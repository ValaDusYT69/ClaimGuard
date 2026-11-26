from io import BytesIO

from fastapi.testclient import TestClient
from pypdf import PdfReader

from invoice import routes as invoice_routes
from main import app


def _mixed_market_invoice():
    aj199_sources = [
        {
            "title": f"AJ199 listing {index}",
            "source_name": f"store-{index}.example",
            "url": f"https://store-{index}.example/aj199",
            "price": 2800 + (index * 100),
            "currency": "BDT",
            "availability": "in_stock",
            "price_source": "page_html",
            "variant_validation": {"status": "verified", "reason": "exact_variant"},
        }
        for index in range(4)
    ]
    return {
        "invoice_id": "INV-REPORT-MIXED",
        "uploaded_by": "owner",
        "extracted_data": {
            "invoice_number": "REPORT-MIXED",
            "currency": "BDT",
            "total_amount": 5400,
            "line_items": [
                {"product": "Ajazz AK820 Mechanical Keyboard", "quantity": 1, "unit_price": 2600, "line_amount": 2600},
                {"product": "Ajazz AJ199 Tri-mode Mouse", "quantity": 1, "unit_price": 2800, "line_amount": 2800},
            ],
        },
        "market_analysis": {
            "product_analyses": [
                {
                    "product": "Ajazz AK820 Mechanical Keyboard",
                    "market": {
                        "status": "no_reliable_comparable",
                        "market_statistics": {"currency": "BDT", "average": None},
                        "sources": [],
                        "excluded_sources": [],
                    },
                },
                {
                    "product": "Ajazz AJ199 Tri-mode Mouse",
                    "market": {
                        "status": "analyzed",
                        "market_statistics": {
                            "currency": "BDT",
                            "average": 3000,
                            "lowest": 2800,
                            "highest": 3200,
                            "median": 3000,
                        },
                        "market_quality": {"independent_domains": 4},
                        "sources": aj199_sources,
                        "excluded_sources": [],
                    },
                },
            ],
        },
    }


def test_report_endpoint_returns_pdf_for_owner_with_mixed_market_coverage(monkeypatch):
    invoice = _mixed_market_invoice()
    monkeypatch.setattr(invoice_routes, "read_invoices", lambda: [invoice])
    monkeypatch.setattr(
        invoice_routes,
        "get_current_user",
        lambda _authorization: {"id": "owner", "role": "user"},
    )

    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/invoices/INV-REPORT-MIXED/report",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].endswith(
        'filename="ClaimGuard_Report_REPORT-MIXED.pdf"'
    )
    assert response.content.startswith(b"%PDF")
    reader = PdfReader(BytesIO(response.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Ajazz AK820 Mechanical Keyboard" in text
    assert "Ajazz AJ199 Tri-mode Mouse" in text
    assert "No verified match" in text
    assert "BDT 3,000" in text
    assert "store-3.example" in text


def test_report_endpoint_returns_generic_error_when_pdf_generation_fails(monkeypatch):
    monkeypatch.setattr(invoice_routes, "read_invoices", lambda: [_mixed_market_invoice()])
    monkeypatch.setattr(
        invoice_routes,
        "get_current_user",
        lambda _authorization: {"id": "owner", "role": "user"},
    )

    def fail_report(_invoice):
        raise RuntimeError("internal detail")

    monkeypatch.setattr(invoice_routes, "build_invoice_report", fail_report)

    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/invoices/INV-REPORT-MIXED/report",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Could not generate the invoice report."}


def test_report_endpoint_requires_authentication():
    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/invoices/INV-REPORT-MIXED/report"
    )

    assert response.status_code == 401

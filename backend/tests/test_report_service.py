import unittest

from pypdf import PdfReader
from io import BytesIO

from invoice.report_service import build_invoice_report


class ComprehensiveInvoiceReportTests(unittest.TestCase):
    def _extract(self, invoice):
        payload = build_invoice_report(invoice)
        self.assertTrue(payload.startswith(b"%PDF"))
        reader = PdfReader(BytesIO(payload))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    def test_report_contains_itemized_invoice_market_accepted_excluded_and_related_editions(self):
        invoice = {
            "invoice_id": "INV-TEST-001",
            "invoice_number": "TD-2026-001",
            "vendor_name": "TECH DIVERSITY LTD",
            "original_filename": "test-invoice.pdf",
            "file_extension": ".pdf",
            "file_size": 12345,
            "uploaded_at": "2026-11-11T10:00:00Z",
            "status": "pending_review",
            "risk_score": 35,
            "risk_level": "low",
            "extracted_data": {
                "invoice_number": "TD-2026-001",
                "vendor_name": "TECH DIVERSITY LTD",
                "invoice_date": "2026-05-25",
                "purchase_date": "2026-05-24",
                "currency": "BDT",
                "total_amount": 5400,
                "raw_text_preview": "Invoice TD-2026-001\nAjazz AJ199 Tri mode Gaming Mouse",
                "raw_text_length": 54,
                "extraction_method": "image_ocr",
                "ocr_metadata": {"engine": "tesseract", "version": "5.5.3", "language": "ben+eng"},
                "line_items": [
                    {"product": "Ajazz AK820 75% Wired Red Switch Keyboard", "quantity": 1, "unit_price": 2600, "line_amount": 2600},
                    {"product": "Ajazz AJ199 Tri mode Gaming Mouse", "quantity": 1, "unit_price": 2800, "line_amount": 2800},
                ],
            },
            "verification": {"status": "pending_review", "checks": {"invoice_number_present": True, "verification_code_present": False}},
            "risk_analysis": {
                "risk_score": 35,
                "risk_level": "low",
                "human_review_required": True,
                "ai_analysis": {"status": "insufficient_training_data", "model": "IsolationForest", "training_rows": 3, "minimum_training_rows": 5, "score": None},
                "score_breakdown": {"deterministic_score": 35, "ml_score": None, "ml_contribution": 0, "final_score": 35},
                "explanation": {"summary": "Human review required", "reasons": ["Duplicate invoice signal"]},
            },
            "anomalies": [{"anomaly_type": "possible_duplicate", "severity": "high", "message": "Matching invoice number, vendor and amount."}],
            "market_analysis": {
                "status": "partial",
                "product_analyses": [
                    {
                        "product": "Ajazz AK820 75% Wired Red Switch Keyboard",
                        "invoice_unit_price": 2600,
                        "market": {
                            "market_product_label": "Ajazz AK820 75% Wired Red Switch Keyboard",
                            "invoice_currency": "BDT",
                            "status": "analyzed",
                            "market_statistics": {"currency": "BDT", "average": 2700, "lowest": 2600, "highest": 2800, "median": 2700},
                            "price_difference": -100,
                            "price_difference_percent": -3.7,
                            "price_alignment_score": 92.6,
                            "market_match_confidence_score": 81.0,
                            "price_status": "near_market_average",
                            "market_quality": {"independent_domains": 2},
                            "price_assessment": {"score_note": "Test score note."},
                            "sources": [{"title": "AK820 Red Switch", "source_name": "store-a.example", "url": "https://store-a.example/ak820", "price": 2600, "currency": "BDT", "availability": "listed", "price_source": "page_html", "source_type": "retailer", "variant_validation": {"status": "verified", "reason": "exact_variant"}}],
                            "excluded_sources": [{"title": "AK820 Brown Switch", "source_name": "store-b.example", "url": "https://store-b.example/ak820-brown", "price": 2500, "currency": "BDT", "availability": "listed", "price_source": "page_html", "exclusion_reason": "variant_mismatch:switch_brown", "variant_validation": {"status": "mismatch", "reason": "switch_brown"}}],
                        },
                    },
                    {
                        "product": "Ajazz AJ199 Tri mode Gaming Mouse",
                        "invoice_unit_price": 2800,
                        "market": {
                            "market_product_label": "AJAZZ AJ199 Carbon Fiber Tri-mode (standard edition)",
                            "market_variant_override": "carbon_fiber_tri_mode",
                            "market_variant_notice": "User-confirmed Carbon Fiber Tri-mode edition.",
                            "invoice_currency": "BDT",
                            "status": "partial",
                            "market_statistics": {"currency": "BDT", "average": 2900, "lowest": 2800, "highest": 3000, "median": 2900},
                            "sources": [{"title": "AJ199 Carbon Fiber Tri-mode", "source_name": "store-c.example", "url": "https://store-c.example/aj199", "price": 2800, "currency": "BDT", "availability": "listed", "price_source": "page_html", "source_type": "retailer", "variant_validation": {"status": "verified", "reason": "user_confirmed_standard_aj199_carbon_fiber_tri_mode"}}],
                            "related_edition_comparisons": [{
                                "edition_label": "AJ199 MAX/PRO Carbon Fiber Tri-mode edition",
                                "status": "separate_edition_context",
                                "source_count": 2,
                                "independent_domains": 2,
                                "included_in_target_benchmark": False,
                                "market_statistics": {"currency": "BDT", "average": 4200, "lowest": 4000, "highest": 4400, "median": 4200},
                                "message": "Different edition, context only.",
                                "sources": [{"title": "AJ199 MAX", "source_name": "max-a.example", "url": "https://max-a.example/aj199max", "price": 4000, "currency": "BDT", "availability": "listed", "price_source": "page_html", "variant_validation": {"status": "mismatch", "reason": "separate_edition"}}],
                            }],
                            "excluded_sources": [{"title": "AJ199 Dual-mode", "source_name": "dual.example", "url": "https://dual.example/aj199-dual", "price": 2700, "currency": "BDT", "availability": "listed", "price_source": "page_html", "exclusion_reason": "variant_mismatch:dual_mode", "variant_validation": {"status": "mismatch", "reason": "dual_mode"}}],
                        },
                    },
                ],
                "search_diagnostics": {"queries_attempted": 8, "search_results_found": 22, "candidates_checked": 12},
            },
            "decision": {"decision": "pending", "note": "Review required."},
            "review_audit_trail": [{"actor_name": "Finance Reviewer", "event_type": "review_started", "timestamp": "2026-11-11T10:10:00Z", "note": "Opened report."}],
        }
        text = self._extract(invoice)
        for expected in (
            "TD-2026-001",
            "TECH DIVERSITY LTD",
            "Product purchase / order date",
            "2026-05-24",
            "Price alignment score",
            "92.6",
            "Market match confidence",
            "81/100",
            "Ajazz AK820 75% Wired Red Switch Keyboard",
            "Ajazz AJ199 Tri mode Gaming Mouse",
            "AJAZZ AJ199 Carbon Fiber Tri-mode",
            "AJ199 MAX/PRO Carbon Fiber Tri-mode edition",
            "Different editions are shown for context only",
            "AK820 Brown Switch",
            "variant_mismatch:switch_brown",
            "IsolationForest",
            "insufficient_training_data",
            "Finance Reviewer",
            "tesseract",
            "5.5.3",
        ):
            self.assertIn(expected, text)


    def test_bengali_product_name_remains_searchable_in_report(self):
        text = self._extract({
            "invoice_id": "INV-BN-001",
            "extracted_data": {
                "invoice_number": "BN-001",
                "vendor_name": "বাংলা ট্রেডার্স",
                "line_items": [
                    {"product": "ওয়্যারলেস কিবোর্ড", "quantity": 1, "unit_price": 2500, "line_amount": 2500}
                ],
            },
            "market_analysis": {"product_analyses": []},
        })
        self.assertIn("ওয়্যারলেস কিবোর্ড", text)

    def test_source_urls_are_clickable_in_pdf(self):
        payload = build_invoice_report({
            "invoice_id": "INV-LINK",
            "extracted_data": {"invoice_number": "INV-LINK"},
            "market_analysis": {
                "sources": [{
                    "title": "AJ199 Carbon Fiber Tri-mode",
                    "source_name": "store.example",
                    "url": "https://store.example/products/aj199?color=black",
                    "price": 2800,
                    "currency": "BDT",
                    "availability": "listed",
                    "price_source": "page_html",
                    "variant_validation": {"status": "verified", "reason": "exact_variant"},
                }]
            },
        })
        reader = PdfReader(BytesIO(payload))
        annotations = [
            annotation.get_object()
            for page in reader.pages
            for annotation in (page.get("/Annots") or [])
        ]
        destinations = [
            item.get("/A", {}).get("/URI")
            for item in annotations
            if item.get("/A", {}).get("/S") == "/URI"
        ]
        self.assertIn("https://store.example/products/aj199?color=black", destinations)

    def test_multi_product_report_explicitly_avoids_combined_average(self):
        invoice = {
            "invoice_id": "INV-MULTI",
            "extracted_data": {
                "invoice_number": "INV-MULTI",
                "line_items": [
                    {"product": "Keyboard", "quantity": 1, "unit_price": 100, "line_amount": 100},
                    {"product": "Mouse", "quantity": 1, "unit_price": 200, "line_amount": 200},
                ],
            },
            "market_analysis": {
                "product_analyses": [
                    {"product": "Keyboard", "invoice_unit_price": 100, "market": {"market_statistics": {"currency": "BDT", "average": 110}, "sources": [], "excluded_sources": []}},
                    {"product": "Mouse", "invoice_unit_price": 200, "market": {"market_statistics": {"currency": "BDT", "average": 210}, "sources": [], "excluded_sources": []}},
                ]
            },
        }
        text = self._extract(invoice)
        self.assertIn("No combined invoice-wide average", text)
        self.assertIn("Keyboard", text)
        self.assertIn("Mouse", text)


if __name__ == "__main__":
    unittest.main()

import unittest
from io import BytesIO

from pypdf import PdfReader

from invoice.report_service import build_invoice_report
from invoice.price_comparison import compare_product_market, enrich_market_analysis
from invoice.risk_engine import analyze_invoice_risk, run_ml_model


def source(domain, price, *, confidence=0.95, currency="BDT", price_source="page_html", availability="listed", variant_status="verified", url_path="/product"):
    item = {
        "source_name": domain,
        "url": f"https://{domain}{url_path}",
        "price": price,
        "currency": currency,
        "price_source": price_source,
        "availability": availability,
        "match_confidence": confidence,
    }
    if variant_status is not None:
        item["variant_validation"] = {"status": variant_status, "reason": "test"}
    return item


class PriceComparisonTests(unittest.TestCase):
    def test_two_independent_verified_sources_produce_comparable_benchmark(self):
        entry = {
            "line_index": 0,
            "product": "Model A keyboard",
            "invoice_unit_price": 1500,
            "market": {
                "invoice_currency": "BDT",
                "sources": [source("shop-a.example", 1000), source("shop-b.example", 1300)],
            },
        }
        result = compare_product_market(entry, "BDT")
        self.assertEqual(result["status"], "comparable")
        self.assertEqual(result["market_statistics"]["average"], 1150.0)
        self.assertEqual(result["market_statistics"]["lowest"], 1000.0)
        self.assertEqual(result["market_statistics"]["highest"], 1300.0)
        self.assertEqual(result["difference_amount"], 350.0)
        self.assertAlmostEqual(result["difference_percent"], 30.43, places=2)
        self.assertIsNotNone(result["price_alignment_score"])
        self.assertGreater(result["price_risk_points"], 0)
        self.assertEqual(result["market_match_confidence"], 95.0)

    def test_same_retailer_subdomains_count_as_one_independent_source(self):
        entry = {
            "product": "Model B",
            "invoice_unit_price": 1200,
            "market": {
                "invoice_currency": "BDT",
                "sources": [
                    source("shop.example.com", 1000),
                    source("www.shop.example.com", 1100, url_path="/other"),
                ],
            },
        }
        result = compare_product_market(entry, "BDT")
        self.assertEqual(result["independent_domain_count"], 1)
        self.assertEqual(result["status"], "insufficient_independent_sources")
        self.assertIsNone(result["market_statistics"]["average"])
        self.assertIsNone(result["difference_percent"])
        self.assertIsNone(result["price_risk_points"])

    def test_snippet_out_of_stock_wrong_variant_and_wrong_currency_are_excluded(self):
        entry = {
            "product": "Model C",
            "invoice_unit_price": 1200,
            "market": {
                "invoice_currency": "BDT",
                "sources": [
                    source("snippet.example", 1000, price_source="search_result_fallback"),
                    source("stock.example", 1100, availability="out_of_stock"),
                    source("variant.example", 900, variant_status="unverified"),
                    source("foreign.example", 8, currency="USD"),
                    source("valid.example", 1000),
                ],
            },
        }
        result = compare_product_market(entry, "BDT")
        self.assertEqual(result["accepted_source_count"], 1)
        self.assertEqual(result["status"], "insufficient_independent_sources")
        reasons = {item["reason"] for item in result["excluded_observations"]}
        self.assertIn("search_snippet_only_not_page_verified", reasons)
        self.assertIn("out_of_stock", reasons)
        self.assertIn("product_variant_not_verified", reasons)
        self.assertIn("currency_mismatch", reasons)

    def test_two_product_lines_are_compared_separately_and_never_averaged_together(self):
        items = [
            {"product": "Same product", "quantity": 1, "unit_price": 1500, "line_amount": 1500},
            {"product": "Same product", "quantity": 3, "unit_price": 1200, "line_amount": 3600},
        ]
        analyses = [
            {
                "line_index": 0,
                "product": "Same product",
                "quantity": 1,
                "invoice_unit_price": 1500,
                "invoice_line_total": 1500,
                "market": {"invoice_currency": "BDT", "sources": [source("a.example", 1000), source("b.example", 1100)]},
            },
            {
                "line_index": 1,
                "product": "Same product",
                "quantity": 3,
                "invoice_unit_price": 1200,
                "invoice_line_total": 3600,
                "market": {"invoice_currency": "BDT", "sources": [source("c.example", 1000), source("d.example", 1400)]},
            },
        ]
        result = enrich_market_analysis(
            {"product_analyses": analyses, "invoice_currency": "BDT"}, items, "BDT"
        )
        self.assertEqual(len(result["price_comparison"]["products"]), 2)
        self.assertEqual(result["product_analyses"][0]["price_comparison"]["market_statistics"]["average"], 1050.0)
        self.assertEqual(result["product_analyses"][1]["price_comparison"]["market_statistics"]["average"], 1200.0)
        self.assertIsNone(result["market_statistics"]["average"])
        self.assertEqual(result["price_comparison"]["comparable_product_lines"], 2)
        self.assertEqual(result["price_comparison"]["known_line_value"], 5100.0)
        self.assertEqual(result["price_comparison"]["value_coverage_percent"], 100.0)

    def test_risk_engine_uses_weighted_product_line_comparison(self):
        lines = [
            {"product": "Keyboard X", "quantity": 1, "unit_price": 1500, "line_amount": 1500},
            {"product": "Mouse Y", "quantity": 2, "unit_price": 2000, "line_amount": 4000},
        ]
        markets = [
            {
                "line_index": 0, "product": "Keyboard X", "invoice_unit_price": 1500,
                "invoice_line_total": 1500, "quantity": 1,
                "market": {"invoice_currency": "BDT", "sources": [source("a.example", 1000), source("b.example", 1000)]},
            },
            {
                "line_index": 1, "product": "Mouse Y", "invoice_unit_price": 2000,
                "invoice_line_total": 4000, "quantity": 2,
                "market": {"invoice_currency": "BDT", "sources": [source("c.example", 1800), source("d.example", 1800)]},
            },
        ]
        market = enrich_market_analysis({"product_analyses": markets}, lines, "BDT")
        risk = analyze_invoice_risk(
            invoice={
                "invoice_id": "new-1",
                "extracted_data": {
                    "vendor_name": "Example Vendor",
                    "product_description": "Keyboard X",
                    "unit_price": 1500,
                    "quantity": 1,
                    "total_amount": 5500,
                    "line_items": lines,
                },
            },
            all_invoices=[],
            market_analysis=market,
        )
        self.assertEqual(risk["status"], "scored")
        self.assertGreater(risk["score_breakdown"]["market_price_contribution"], 0)
        self.assertTrue(any(item["anomaly_type"] == "product_line_market_price_anomaly" for item in risk["anomalies"]))
        self.assertEqual(risk["market_context"]["price_comparison"]["comparable_product_lines"], 2)
        self.assertNotEqual(risk["market_context"]["price_comparison"].get("invoice_wide_average"), 1)

    def test_local_ml_does_not_misread_a_multi_sku_invoice_as_one_product(self):
        invoice = {
            "invoice_id": "multi-ml",
            "extracted_data": {
                "product_description": "First product",
                "unit_price": 1000,
                "quantity": 2,
                "total_amount": 6000,
                "line_items": [
                    {"product": "First product", "unit_price": 1000, "quantity": 1, "line_amount": 1000},
                    {"product": "Second product", "unit_price": 2500, "quantity": 2, "line_amount": 5000},
                ],
            },
        }
        history = [
            {
                "invoice_id": f"history-{index}",
                "extracted_data": {
                    "product_description": "First product",
                    "unit_price": 1000 + index * 10,
                    "quantity": 1,
                    "total_amount": 1000 + index * 10,
                },
            }
            for index in range(6)
        ]
        result = run_ml_model(invoice, history)
        self.assertEqual(result["status"], "multi_product_invoice_not_scored")
        self.assertIsNone(result["score"])
        self.assertFalse(result["available"])

    def test_pdf_report_prints_comparison_status_and_price_risk_points(self):
        market = {
            "invoice_currency": "BDT",
            "sources": [source("a.example", 1000), source("b.example", 1100)],
        }
        product = {
            "line_index": 0,
            "product": "Keyboard Z",
            "quantity": 1,
            "invoice_unit_price": 1500,
            "invoice_line_total": 1500,
            "market": market,
        }
        enriched = enrich_market_analysis({"product_analyses": [product]}, [
            {"product": "Keyboard Z", "quantity": 1, "unit_price": 1500, "line_amount": 1500}
        ], "BDT")
        invoice = {
            "invoice_id": "INV-COMP-01",
            "invoice_number": "INV-COMP-01",
            "vendor_name": "Example Vendor",
            "status": "pending_review",
            "extracted_data": {
                "invoice_number": "INV-COMP-01",
                "vendor_name": "Example Vendor",
                "currency": "BDT",
                "total_amount": 1500,
                "line_items": [{"product": "Keyboard Z", "quantity": 1, "unit_price": 1500, "line_amount": 1500}],
            },
            "market_analysis": enriched,
        }
        pdf = build_invoice_report(invoice)
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
        self.assertIn("Price-risk contribution", text)
        self.assertIn("comparable", text.lower())
        self.assertIn("/ 30 points", text)

    def test_missing_invoice_price_or_only_one_domain_remains_unassessed(self):
        entry = {
            "product": "Model D",
            "invoice_unit_price": None,
            "market": {"invoice_currency": "BDT", "sources": [source("one.example", 1000)]},
        }
        result = compare_product_market(entry, "BDT")
        self.assertFalse(result["is_comparable"])
        self.assertIsNone(result["price_alignment_score"])
        self.assertIsNone(result["price_risk_points"])


if __name__ == "__main__":
    unittest.main()

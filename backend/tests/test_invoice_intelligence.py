import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch

from invoice import market_research
from invoice import routes
from invoice.extraction import normalize_line_items
from invoice.extractor import extract_invoice_fields
from invoice.risk_engine import analyze_invoice_risk


class InvoiceIntelligenceTests(unittest.TestCase):
    def test_metadata_is_excluded_and_two_products_remain_independent(self):
        first_product = (
            "AJAZZ AK820 75% Wired White Light Hot-Swap Black "
            "Mechanical Keyboard AS Red Switch"
        )
        second_product = "AJAZZ AJ199 Carbon Fiber Tri-mode (standard edition)"
        fields = extract_invoice_fields(
            f"""Invoice
Customer Name: Tazim
Invoice No: INV-2026-001
Status: Approved
Order By: Ashraf
Approved By: Ashraf
Challan No: CH-2026
Order No: ORD-1
Sales Mode: Retail
Product Description
{first_product}
1 Pcs
2,600.00 0.00
2,600.00
{second_product}
1 Pcs
4,500.00 0.00
4,500.00
Grand Total 7,100.00"""
        )

        self.assertEqual(len(fields["line_items"]), 2)
        self.assertEqual(fields["line_items"][0]["product"], first_product)
        self.assertEqual(fields["line_items"][1]["product"], second_product)
        self.assertEqual(fields["product_description"], first_product)
        for item in fields["line_items"]:
            self.assertNotRegex(
                item["product"],
                r"Customer Name|Invoice No|Status|Order By|Approved By|Challan No|Order No|Sales Mode",
            )

    def test_market_queries_use_only_the_clean_product_identity(self):
        product = (
            "AJAZZ AK820 75% Wired White Light Hot-Swap Black "
            "Mechanical Keyboard AS Red Switch"
        )
        queries = market_research.build_search_queries(
            "Example Vendor",
            "Customer Name Tazim Invoice No INV-2026-001 "
            "Status Approved Order By Ashraf Approved By Ashraf "
            f"Product Description {product}",
        )

        self.assertEqual(len(queries), 1)
        self.assertTrue(any(
            "ak820" in query.casefold() and "keyboard" in query.casefold()
            for query in queries
        ))
        for query in queries:
            self.assertNotRegex(
                query,
                r"Tazim|INV-2026-001|Status|Approved|Ashraf|Challan|Order No",
            )

    def test_unresolved_product_identity_requires_finance_review(self):
        reasons = routes._review_trigger_reasons(
            risk_analysis={},
            verification_status=None,
            extraction_error=None,
            extraction_status="extracted",
            extraction_warnings=["product_identity_requires_review"],
        )

        self.assertTrue(any("product names" in reason for reason in reasons))

    def test_legacy_contaminated_line_is_not_searched_or_merged_with_next_product(self):
        called_products = []

        def fake_analysis(_vendor, product, *_args):
            called_products.append(product)
            return {
                "status": "analyzed",
                "sources": [],
                "market_statistics": {
                    "currency": None,
                    "average": None,
                    "lowest": None,
                    "highest": None,
                    "median": None,
                },
                "search_diagnostics": {},
            }

        bad_name = (
            "Customer Name Tazim Invoice No INV-2026-001 Status Approved "
            "Order By Ashraf Approved By Ashraf AJAZZ AK820 Mechanical Keyboard"
        )
        second_product = "AJAZZ AJ199 Carbon Fiber Tri-mode (standard edition)"
        rows = normalize_line_items([
            {"product": bad_name, "quantity": 1, "unit_price": 2600},
            {"product": second_product, "quantity": 1, "unit_price": 4500},
        ])

        self.assertIsNone(rows[0]["product"])
        self.assertIn("product_identity_requires_review", rows[0]["extraction_warnings"])
        with patch.object(market_research, "analyze_market_price", side_effect=fake_analysis):
            result = market_research.analyze_invoice_market(
                "Example Vendor",
                bad_name,
                2600,
                "BDT",
                rows,
            )

        self.assertEqual(called_products, [second_product])
        self.assertEqual(result["product_analyses"][0]["status"], "extraction_review_required")
        self.assertEqual(result["product_analyses"][1]["product"], second_product)

    def test_saved_invoice_reanalysis_replaces_legacy_product_names_before_market_search(self):
        first_product = (
            "AJAZZ AK820 75% Wired White Light Hot-Swap Black "
            "Mechanical Keyboard AS Red Switch"
        )
        second_product = "AJAZZ AJ199 Carbon Fiber Tri-mode (standard edition)"
        state = [{
            "invoice_id": "legacy-invoice",
            "uploaded_by": "owner-id",
            "decision": {"decision": "approved"},
            "file_path": "uploads\\legacy\\invoice.pdf",
            "file_extension": ".pdf",
            "extracted_data": {
                "line_items": [{
                    "product": "Customer Name Tazim Invoice No INV-2026-001 "
                    "Status Approved Order By Ashraf AJAZZ AK820 Keyboard",
                    "quantity": 1,
                    "unit_price": 2600,
                }],
            },
        }]
        market_items = []

        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            upload = root / "uploads" / "legacy" / "invoice.pdf"
            upload.parent.mkdir(parents=True)
            upload.write_bytes(b"fixture")

            def read_records():
                return deepcopy(state)

            def write_records(records):
                state[:] = deepcopy(records)

            extracted = {
                "line_items": [
                    {"product": first_product, "quantity": 1, "unit_price": 2600, "line_amount": 2600},
                    {"product": second_product, "quantity": 1, "unit_price": 4500, "line_amount": 4500},
                ],
                "product_description": first_product,
                "vendor_name": "Example Vendor",
                "unit_price": 2600,
                "currency": "BDT",
                "total_amount": 7100,
                "extraction_status": "extracted",
            }

            def fake_market(*_args, **kwargs):
                market_items.extend(kwargs["line_items"])
                return {"status": "analyzed", "sources": [], "product_analyses": []}

            with (
                patch.object(routes, "BASE_DIR", root),
                patch.object(routes, "UPLOAD_DIR", root / "uploads"),
                patch.object(routes, "read_invoices", side_effect=read_records),
                patch.object(routes, "write_invoices", side_effect=write_records),
                patch.object(routes, "extract_invoice_data", return_value=extracted),
                patch.object(routes, "analyze_invoice_market", side_effect=fake_market),
                patch.object(routes, "enrich_market_analysis", side_effect=lambda market, *_args: market),
                patch.object(routes, "verify_invoice", return_value={"status": "verified"}),
                patch.object(routes, "analyze_invoice_risk", return_value={"status": "unassessed"}),
                patch.object(routes, "update_job"),
            ):
                routes._run_saved_invoice_reanalysis("legacy-invoice")

        self.assertEqual(
            [item["product"] for item in state[0]["extracted_data"]["line_items"]],
            [first_product, second_product],
        )
        self.assertEqual([item["product"] for item in market_items], [first_product, second_product])
        self.assertEqual(state[0]["invoice_id"], "legacy-invoice")
        self.assertEqual(state[0]["uploaded_by"], "owner-id")
        self.assertEqual(state[0]["decision"], {"decision": "approved"})

    def test_photo_layout_rejects_contact_label_as_date_and_preserves_rows(self):
        fields = extract_invoice_fields(
            """Invoice
TECH DIVERSITY LTD
Date
Contact No.
01700000000
25-May-2026 02:17 PM
Product Name
Qty | Unit
Price | Disc.
Amount
Ajazz AK820 75% Wired White Light
1.00 | Pes
2,600.00 | 0.00
2,600.00
1,00] Pes
2,800.00 | 0.00
2,800.00
    Ajazz Aj199 Tri mode Gaming Mouse
Total Qty.
Grand Total
5,400.00
"""
        )

        self.assertEqual(fields["invoice_date"], "25-May-2026")
        self.assertEqual(fields["quantity"], 2)
        self.assertEqual(fields["subtotal"], 5400)
        self.assertEqual(len(fields["line_items"]), 2)
        self.assertIn("AK820", fields["line_items"][0]["product"])
        self.assertIn("Aj199", fields["line_items"][1]["product"])

    def test_vertical_pdf_table_keeps_all_product_lines_and_separate_purchase_date(self):
        fields = extract_invoice_fields(
            """Invoice No: A-100
Invoice Date: 2026-10-30
Purchase Date: 2026-10-28
Vendor: Example Ltd
Description
Quantity
Unit Price
Amount
Widget Alpha
1
500
500
Widget Beta
2
250
500
Subtotal
1000
Grand Total
1000"""
        )
        self.assertEqual(fields["invoice_date"], "2026-10-30")
        self.assertEqual(fields["purchase_date"], "2026-10-28")
        self.assertEqual(len(fields["line_items"]), 2)
        self.assertEqual(fields["line_items"][1]["product"], "Widget Beta")

    def test_market_analysis_keeps_product_level_results(self):
        def fake_search(query):
            product = (
                "Keyboard model K1"
                if "Keyboard" in query
                else "Mouse model M1"
            )
            return [
                {
                    "url": "https://startech.com.bd/products/item-a",
                    "domain": "startech.com.bd",
                    "title": product,
                    "engine": "test",
                },
                {
                    "url": "https://techlandbd.com/products/item-b",
                    "domain": "techlandbd.com",
                    "title": product,
                    "engine": "test",
                },
            ]

        def fake_candidate(result, product_description):
            return {
                "url": result["url"],
                "source_name": result["url"].split("/")[2],
                "title": product_description,
                "variant_evidence": product_description,
                "product_entity_binding": {
                    "association_status": "unambiguous",
                    "product_entity_id": "test-product",
                    "price_entity_id": "test-product",
                    "entity_identity": product_description,
                },
                "search_snippet": product_description,
                "source_type": "retailer",
                "price": 2500,
                "currency": "BDT",
                "price_source": "page_html",
                "availability": "listed",
                "match_confidence": 0.9,
            }

        items = [
            {"id": "invoice-line-keyboard", "product": "Keyboard model K1", "unit_price": 2600},
            {"id": "invoice-line-mouse", "product": "Mouse model M1", "unit_price": 2800},
        ]
        with patch.object(market_research, "search_web", side_effect=fake_search), patch.object(
            market_research, "analyze_candidate", side_effect=fake_candidate
        ):
            result = market_research.analyze_invoice_market(
                "Example Vendor",
                items[0]["product"],
                items[0]["unit_price"],
                "BDT",
                items,
            )

        self.assertEqual(len(result["product_analyses"]), 2)
        self.assertEqual(
            [item["invoice_line_id"] for item in result["product_analyses"]],
            ["invoice-line-keyboard", "invoice-line-mouse"],
        )
        self.assertEqual(
            {source["invoice_line_id"] for source in result["sources"]},
            {"invoice-line-keyboard", "invoice-line-mouse"},
        )
        self.assertEqual(result["search_diagnostics"]["independent_source_count"], 2)
        self.assertEqual(result["product_analyses"][0]["market"]["market_statistics"]["average"], 2500)
        self.assertEqual(result["product_analyses"][0]["market"]["price_difference_percent"], 4.0)
        # Canonical formula: max(0, 100 - absolute rounded percentage
        # difference). A 4% premium therefore aligns at 96.
        self.assertEqual(result["product_analyses"][0]["market"]["price_alignment_score"], 96.0)
        # The public score is the mean accepted product-identity confidence.
        self.assertAlmostEqual(result["product_analyses"][0]["market"]["market_match_confidence_score"], 85.0, places=1)
        self.assertIsNone(result["market_statistics"]["average"])
        self.assertFalse(result["usable_for_risk_calculation"])
        provider_diagnostics = result["search_diagnostics"]["provider_diagnostics"]
        self.assertEqual(provider_diagnostics["total_candidate_count"], 4)
        self.assertEqual(provider_diagnostics["total_comparable_count"], 4)
        self.assertIn("test", provider_diagnostics["providers"])

    def test_one_product_search_failure_does_not_hide_other_line_offers(self):
        def fake_search(query):
            # The query builder intentionally removes generic words such as
            # "model", so the generated query contains "Keyboard K1". Match
            # the normalized query identity rather than the raw invoice text.
            if "keyboard k1" in " ".join(query.casefold().split()):
                raise RuntimeError("temporary search failure")
            return [
                {
                    "url": "https://startech.com.bd/products/mouse-m1",
                    "domain": "startech.com.bd",
                    "title": "Mouse model M1",
                    "engine": "test",
                },
                {
                    "url": "https://techlandbd.com/products/mouse-m1",
                    "domain": "techlandbd.com",
                    "title": "Mouse model M1",
                    "engine": "test",
                },
            ]

        def fake_candidate(result, product_description):
            return {
                "url": result["url"],
                "source_name": result["domain"],
                "title": product_description,
                "product_entity_binding": {
                    "association_status": "unambiguous",
                    "product_entity_id": product_description,
                    "price_entity_id": product_description,
                    "entity_identity": product_description,
                },
                "source_type": "retailer",
                "price": 2500,
                "currency": "BDT",
                "price_source": "structured_product_page",
                "retrieval_method": "direct_http",
                "availability": "listed",
                "match_confidence": 0.9,
            }

        items = [
            {"id": "line-keyboard", "product": "Keyboard model K1", "unit_price": 2600},
            {"id": "line-mouse", "product": "Mouse model M1", "unit_price": 2800},
        ]
        with patch.object(market_research, "search_web", side_effect=fake_search), \
             patch.object(market_research, "analyze_candidate", side_effect=fake_candidate), \
             patch.object(
                 market_research,
                 "_validate_market_source",
                 return_value=(True, {"status": "verified", "confidence": 0.9}, None),
             ):
            result = market_research.analyze_invoice_market(
                "Example Vendor",
                items[0]["product"],
                items[0]["unit_price"],
                "BDT",
                items,
            )

        self.assertEqual(result["product_analyses"][0]["status"], "search_failed")
        self.assertEqual(result["product_analyses"][1]["invoice_line_id"], "line-mouse")
        self.assertEqual(len(result["product_analyses"][1]["market"]["sources"]), 2)
        self.assertEqual(len(result["sources"]), 2)


    def test_item_qty_rate_total_headers_extract_each_horizontal_product(self):
        fields = extract_invoice_fields(
            """Invoice No: X-2
Vendor: Example Ltd
Item | Qty | Rate | Total
Keyboard K2 1 2500 2500
Mouse M2 2 500 1000
Grand Total 3500"""
        )
        self.assertEqual(len(fields["line_items"]), 2)
        self.assertEqual(fields["line_items"][0]["product"], "Keyboard K2")
        self.assertEqual(fields["line_items"][1]["unit_price"], 500)

    def test_market_analysis_reports_partial_when_one_product_has_no_market_data(self):
        good = {
            "status": "analyzed",
            "sources": [{"url": "https://one.example/item", "source_name": "one.example", "price": 100, "currency": "BDT", "match_confidence": 0.9}],
            "market_statistics": {"currency": "BDT", "average": 100, "lowest": 100, "highest": 100, "median": 100},
            "search_diagnostics": {},
        }
        poor = {
            "status": "no_reliable_comparable",
            "sources": [],
            "market_statistics": {"currency": "BDT", "average": None, "lowest": None, "highest": None, "median": None},
            "search_diagnostics": {},
        }
        with patch.object(market_research, "analyze_market_price", side_effect=[good, poor]):
            result = market_research.analyze_invoice_market(
                "Vendor", "Keyboard", 100, "BDT",
                [{"product": "Keyboard", "unit_price": 100}, {"product": "Mouse", "unit_price": 50}],
            )
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["search_diagnostics"]["successful_product_count"], 1)


    def test_market_provider_diagnostics_are_isolated_per_worker_thread(self):
        barrier = Barrier(2)

        def set_worker_state(name):
            market_research._set_market_diagnostics({"worker": name})
            market_research._set_diagnostic_provider(name)
            barrier.wait(timeout=3)
            return (
                market_research._current_market_diagnostics()["worker"],
                market_research._current_diagnostic_provider(),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(set_worker_state, ("invoice-a", "invoice-b")))
        self.assertEqual(results, [("invoice-a", "invoice-a"), ("invoice-b", "invoice-b")])

    def test_search_prefilter_keeps_shortened_ssd_and_ram_titles(self):
        self.assertTrue(
            market_research._passes_search_result_identity_prefilter(
                "Addlink S70 Lite 256GB M.2 2280 PCIe NVMe SSD",
                set(market_research.tokenize("Addlink S70 256GB NVMe SSD")),
            )
        )
        self.assertTrue(
            market_research._passes_search_result_identity_prefilter(
                "Team Delta RGB 8GB 3200MHz DDR4 CL16 Desktop RAM",
                set(market_research.tokenize("Delta RGB 3200MHz DDR4 memory")),
            )
        )
        self.assertFalse(
            market_research._passes_search_result_identity_prefilter(
                "Addlink S70 Lite 256GB M.2 2280 PCIe NVMe SSD",
                set(market_research.tokenize("Unrelated 2TB SATA hard drive")),
            )
        )

    def test_untrained_ml_is_not_presented_as_low_risk(self):
        result = analyze_invoice_risk(
            invoice={
                "invoice_id": "test",
                "extracted_data": {
                    "quantity": 2,
                    "unit_price": 2600,
                    "total_amount": 5400,
                },
            },
            all_invoices=[],
            market_analysis={"usable_for_risk_calculation": False},
        )

        self.assertEqual(result["status"], "unassessed")
        self.assertEqual(result["risk_level"], "unassessed")
        self.assertEqual(result["ai_analysis"]["status"], "insufficient_training_data")
        self.assertIsNone(result["ai_analysis"]["score"])
        self.assertTrue(result["human_review_required"])

    def test_cst_recovery_requires_cst_product_identity(self):
        self.assertTrue(market_research._is_cst_product_identity("CST Jack Rabbit C1747 tire"))
        self.assertFalse(market_research._is_cst_product_identity("Ajazz AK820 mechanical keyboard"))


if __name__ == "__main__":
    unittest.main()

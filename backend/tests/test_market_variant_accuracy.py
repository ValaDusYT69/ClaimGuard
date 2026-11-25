import unittest
from unittest.mock import patch

from invoice.market.variant_validation import (
    assess_product_variant,
    classify_price_observation,
    effective_search_query,
    is_statistical_price_outlier,
    market_identity_metadata,
)
from invoice.market.query_builder import build_product_search_queries
from invoice import market_research
from invoice.risk_engine import run_ml_model


class MarketVariantAccuracyTests(unittest.TestCase):
    TARGET = "Ajazz AJ199 Tri mode Gaming Mouse"

    def test_ryzen_5700g_is_verified_and_sibling_skus_are_rejected(self):
        target = "AMD Ryzen 7 5700G Processor"
        verified = assess_product_variant(
            target,
            "AMD Ryzen 7 5700G 8-Core Processor with Radeon Graphics",
        )
        self.assertEqual(verified["status"], "verified")

        for sibling in ("5700", "5700X", "5700GE"):
            result = assess_product_variant(
                target,
                f"AMD Ryzen 7 {sibling} Processor",
            )
            self.assertEqual(result["status"], "mismatch")

    def test_ryzen_5700g_queries_include_model_and_retailer_fallbacks(self):
        queries = build_product_search_queries(
            "Example Vendor",
            "AMD Ryzen 7 5700G Processor",
        )
        self.assertTrue(any("AMD Ryzen 7 5700G processor Bangladesh price" in query for query in queries))
        self.assertTrue(any("Ryzen 7 5700G 8 Core Radeon Graphics" in query for query in queries))
        self.assertTrue(any("AMD 5700G processor price in Bangladesh" in query for query in queries))
        self.assertTrue(any("Ryzen 7 5700G Star Tech" in query for query in queries))

    def test_search_snippet_price_is_never_accepted_without_page_evidence(self):
        result = {
            "url": "https://example.com/amd-ryzen-7-5700g",
            "domain": "example.com",
            "title": "AMD Ryzen 7 5700G Processor",
            "snippet": "AMD Ryzen 7 5700G Processor ৳18,500",
        }
        with patch.object(market_research, "_fetch_for_provider", return_value=b""), \
             patch.object(market_research, "fetch_url_via_jina", return_value=""):
            self.assertIsNone(
                market_research.analyze_candidate(
                    result,
                    "AMD Ryzen 7 5700G Processor",
                )
            )

    def test_aj199_carbon_fiber_standard_tri_mode_is_verified(self):
        candidate = (
            "AJAZZ AJ199 Carbon Fiber Tri-mode Gaming Mouse "
            "PAW3311 sensor 12,000 DPI 500mAh"
        )
        result = assess_product_variant(self.TARGET, candidate)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["reason"], "user_confirmed_standard_aj199_carbon_fiber_tri_mode")
        self.assertIn("carbon_fiber", result["observed_variant"])
        self.assertIn("tri_mode", result["observed_variant"])

    def test_user_confirmed_override_is_scoped_to_the_current_invoice_line(self):
        metadata = market_identity_metadata(self.TARGET)
        self.assertIsNotNone(metadata)
        self.assertIsNone(market_identity_metadata("Ajazz AJ199 Tri-mode Wireless Mouse"))
        unknown = assess_product_variant(
            "Ajazz AJ199 Tri-mode Wireless Mouse",
            "AJAZZ AJ199 Carbon Fiber Tri-mode Wireless Mouse",
        )
        self.assertEqual(unknown["status"], "unverified")
        self.assertEqual(unknown["reason"], "aj199_edition_not_explicitly_identified")

    def test_aj199_max_carbon_fiber_is_a_separate_edition(self):
        candidate = (
            "AJAZZ AJ199 MAX Carbon Fiber Tri-mode Gaming Mouse "
            "PAW3395 26,000 DPI 800mAh"
        )
        result = assess_product_variant(self.TARGET, candidate)
        self.assertEqual(result["status"], "mismatch")
        self.assertTrue(result["reason"].startswith("separate_edition:"))
        self.assertIn("MAX", result["separate_edition"])

    def test_aj199_paw3395_higher_spec_is_separate_even_if_max_missing(self):
        candidate = "AJAZZ AJ199 Carbon Fiber Tri-mode Mouse PAW3395 26,000 DPI 800mAh"
        result = assess_product_variant(self.TARGET, candidate)
        self.assertEqual(result["status"], "mismatch")
        self.assertTrue(result["reason"].startswith("separate_edition:"))

    def test_non_carbon_fiber_aj199_is_unverified_not_benchmarked(self):
        candidate = "AJAZZ AJ199 Tri-mode Wireless Gaming Mouse Bluetooth 2.4G"
        result = assess_product_variant(self.TARGET, candidate)
        self.assertEqual(result["status"], "unverified")
        self.assertIn("carbon_fiber", result["reason"])

    def test_dual_mode_aj199_conflicts_with_tri_mode_target(self):
        candidate = "AJAZZ AJ199 Carbon Fiber Dual-mode Wireless Mouse 2.4G"
        result = assess_product_variant(self.TARGET, candidate)
        self.assertEqual(result["status"], "mismatch")
        self.assertIn("dual_mode", result["reason"])

    def test_carbon_fiber_without_connectivity_evidence_is_unverified(self):
        candidate = "AJAZZ AJ199 Carbon Fiber Gaming Mouse"
        result = assess_product_variant(self.TARGET, candidate)
        self.assertEqual(result["status"], "unverified")
        self.assertIn("tri_mode_connectivity_evidence", result["reason"])

    def test_search_query_uses_confirmed_carbon_fiber_tri_mode_identity(self):
        query = effective_search_query(self.TARGET)
        self.assertIn("AJ199", query)
        self.assertIn("Carbon Fiber", query)
        self.assertIn("Tri-mode", query)
        self.assertNotIn("Non-Tri-mode", query)
        metadata = market_identity_metadata(self.TARGET)
        self.assertIn("Carbon Fiber Tri-mode", metadata["label"])
        self.assertIn("AJ199 MAX", metadata["notice"])
        queries = market_research.build_search_queries("TECH DIVERSITY LTD", self.TARGET)
        self.assertTrue(any("AJ199 MAX Carbon Fiber Tri-mode" in query for query in queries))

    def test_keyboard_switch_variant_mismatch_is_rejected(self):
        target = "Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard Red Switch"
        candidate = "Ajazz AK820 75% Wired Mechanical Keyboard Brown Switch"
        result = assess_product_variant(target, candidate)
        self.assertEqual(result["status"], "mismatch")
        self.assertIn("switch_brown", result["reason"])

    def test_keyboard_requires_wired_and_red_switch_evidence(self):
        target = "Ajazz AK820 75% Wired Mechanical Keyboard Red Switch"
        good = assess_product_variant(target, "Ajazz AK820 75% Wired Mechanical Keyboard Red Switch")
        missing = assess_product_variant(target, "Ajazz AK820 Mechanical Keyboard")
        self.assertEqual(good["status"], "verified")
        self.assertEqual(missing["status"], "unverified")

    def test_keyboard_model_and_switch_variant_must_match(self):
        target = "AJAZZ AK820 75% Wired Hot-Swap Black Mechanical Keyboard AS Red Switch"
        correct = assess_product_variant(target, target)
        other_model = assess_product_variant(
            target,
            "AJAZZ AK819 75% Wired Hot-Swap Black Mechanical Keyboard AS Red Switch",
        )
        wrong_switch = assess_product_variant(
            target,
            "AJAZZ AK820 75% Wired Hot-Swap Black Mechanical Keyboard AS Brown Switch",
        )

        self.assertEqual(correct["status"], "verified")
        self.assertEqual(other_model["status"], "mismatch")
        self.assertEqual(wrong_switch["status"], "mismatch")

    def test_category_brand_layout_and_hot_swap_are_mandatory(self):
        target = "Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard Red Switch"
        wrong_category = assess_product_variant(
            target,
            "Ajazz AK820 Wired Gaming Mouse Red Switch",
        )
        wrong_brand = assess_product_variant(
            target,
            "Razer AK820 75% Wired Hot-Swap Mechanical Keyboard Red Switch",
        )
        missing_layout = assess_product_variant(
            target,
            "Ajazz AK820 Wired Hot-Swap Mechanical Keyboard Red Switch",
        )
        missing_hot_swap = assess_product_variant(
            target,
            "Ajazz AK820 75% Wired Mechanical Keyboard Red Switch",
        )
        missing_material = assess_product_variant(
            "Ajazz AK820 Aluminum Mechanical Keyboard",
            "Ajazz AK820 Mechanical Keyboard",
        )

        self.assertEqual(wrong_category["status"], "mismatch")
        self.assertIn("product_category_mismatch", wrong_category["reason"])
        self.assertEqual(wrong_brand["status"], "mismatch")
        self.assertIn("brand_mismatch", wrong_brand["reason"])
        self.assertEqual(missing_layout["status"], "unverified")
        self.assertIn("layout_75", missing_layout["reason"])
        self.assertEqual(missing_hot_swap["status"], "unverified")
        self.assertIn("hot_swap", missing_hot_swap["reason"])
        self.assertEqual(missing_material["status"], "unverified")
        self.assertIn("aluminum", missing_material["reason"])

    def test_wrong_category_price_is_excluded_from_benchmark(self):
        target = "Ajazz AK820 75% Wired Mechanical Keyboard Red Switch"
        fake_result = {
            "status": "analyzed",
            "product_query": target,
            "invoice_unit_price": 2600,
            "invoice_currency": "BDT",
            "sources": [{
                "source_name": "mouse-shop.example",
                "title": "Ajazz AK820 Wired Gaming Mouse Red Switch",
                "url": "https://mouse-shop.example/ak820",
                "price": 11000,
                "currency": "BDT",
                "price_source": "page_html",
                "availability": "listed",
            }],
            "search_diagnostics": {},
        }

        with patch.object(
            market_research,
            "_ORIGINAL_ANALYZE_MARKET_PRICE_V29",
            return_value=fake_result,
        ):
            result = market_research.analyze_market_price(
                "Vendor",
                target,
                2600,
                "BDT",
            )

        self.assertEqual(result["sources"], [])
        self.assertIsNone(result["market_statistics"]["average"])
        self.assertFalse(result["usable_for_risk_calculation"])
        self.assertEqual(result["excluded_sources"][0]["price"], 11000)
        self.assertIn(
            "product_category_mismatch",
            result["excluded_sources"][0]["exclusion_reason"],
        )

    def test_snippet_only_and_out_of_stock_prices_are_not_eligible(self):
        base = {"price": 2600, "currency": "BDT", "price_source": "page_html", "availability": "listed"}
        self.assertEqual(classify_price_observation(base), (True, None))
        snippet = {**base, "price_source": "search_result_fallback"}
        self.assertEqual(classify_price_observation(snippet)[1], "search_snippet_only_not_page_verified")
        out = {**base, "availability": "out_of_stock"}
        self.assertEqual(classify_price_observation(out)[1], "out_of_stock")

    def test_extreme_price_outlier_filter_only_runs_with_five_or_more_sources(self):
        prices = [2500, 2600, 2700, 2800, 2900]
        self.assertFalse(is_statistical_price_outlier(prices[:4], 100000))
        self.assertTrue(is_statistical_price_outlier(prices, 100000))

    def test_local_ai_waits_for_five_similar_real_invoices(self):
        invoice = {
            "invoice_id": "current",
            "extracted_data": {
                "vendor_name": "TECH DIVERSITY LTD",
                "product_description": "Ajazz AK820 Mechanical Keyboard",
                "unit_price": 2600,
                "quantity": 1,
                "total_amount": 2600,
            },
        }
        history = [
            {
                "invoice_id": f"old-{index}",
                "extracted_data": {
                    "vendor_name": "TECH DIVERSITY LTD",
                    "product_description": "Ajazz AK820 Mechanical Keyboard",
                    "unit_price": 2500 + index * 50,
                    "quantity": 1,
                    "total_amount": 2500 + index * 50,
                },
            }
            for index in range(2)
        ]
        result = run_ml_model(invoice, history)
        self.assertEqual(result["status"], "insufficient_training_data")
        self.assertEqual(result["training_rows"], 2)
        self.assertEqual(result["minimum_training_rows"], 5)
        self.assertIsNone(result["score"])

    def test_final_result_keeps_other_edition_separate_from_target_statistics(self):
        def fake_result(*_args, **_kwargs):
            def source(domain, title, price):
                return {
                    "source_name": domain,
                    "title": title,
                    "url": f"https://{domain}/aj199",
                    "price": price,
                    "currency": "BDT",
                    "price_source": "page_html",
                    "availability": "listed",
                    "source_type": "retailer",
                    "match_confidence": 0.75,
                }

            return {
                "status": "analyzed",
                "message": "old result",
                "product_query": self.TARGET,
                "invoice_unit_price": 2800,
                "invoice_currency": "BDT",
                "sources": [
                    source("store-a.example", "AJAZZ AJ199 Carbon Fiber Tri-mode Mouse PAW3311", 2800),
                    source("store-b.example", "AJAZZ AJ199 Carbon Fiber Tri-mode Gaming Mouse", 3000),
                    source("max-a.example", "AJAZZ AJ199 MAX Carbon Fiber Tri-mode PAW3395 26,000 DPI", 4200),
                    source("max-b.example", "AJAZZ AJ199 MAX Carbon Fiber Tri-mode PAW3395 26,000 DPI", 4400),
                    source("plain.example", "AJAZZ AJ199 Tri-mode Wireless Mouse", 2500),
                    source("dual.example", "AJAZZ AJ199 Carbon Fiber Dual-mode Mouse 2.4G", 2700),
                ],
                "search_diagnostics": {},
            }

        with patch.object(market_research, "_ORIGINAL_ANALYZE_MARKET_PRICE_V29", side_effect=fake_result):
            result = market_research.analyze_market_price(
                "Example Vendor", self.TARGET, 2800, "BDT"
            )

        self.assertEqual(len(result["sources"]), 2)
        self.assertEqual(result["market_statistics"]["lowest"], 2800.0)
        self.assertEqual(result["market_statistics"]["highest"], 3000.0)
        self.assertTrue(result["usable_for_risk_calculation"])
        self.assertIn("Carbon Fiber Tri-mode", result["market_product_label"])
        self.assertEqual(len(result["related_edition_comparisons"]), 1)
        related = result["related_edition_comparisons"][0]
        self.assertFalse(related["included_in_target_benchmark"])
        self.assertEqual(related["source_count"], 2)
        self.assertEqual(related["market_statistics"]["average"], 4300.0)
        self.assertTrue(any("carbon_fiber" in str(item.get("exclusion_reason")) for item in result["excluded_sources"]))
        self.assertTrue(all(source["variant_validation"]["status"] == "verified" for source in result["sources"]))


if __name__ == "__main__":
    unittest.main()

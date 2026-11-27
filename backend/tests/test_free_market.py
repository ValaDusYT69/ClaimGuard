import io
import json
import unittest
from urllib.error import HTTPError
from unittest.mock import Mock, patch

from invoice.market.query_builder import build_product_search_queries
from invoice.market_research import build_direct_source_candidates
from invoice.market.providers.searxng import search_searxng
from invoice.market.structured_data import extract_matching_product_offers
from invoice.market_research import extract_page_price


class _FakeHeaders:
    def get_content_type(self):
        return "application/json"


class _FakeResponse:
    status = 200
    headers = _FakeHeaders()

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=-1):
        return self.payload

class FreeMarketResearchTests(unittest.TestCase):
    def test_non_cst_product_does_not_receive_cst_queries(self):
        queries = build_product_search_queries(
            "Example Vendor",
            "Ajazz AK820 75% Mechanical Keyboard",
        )
        self.assertTrue(queries)
        self.assertTrue(any("AK820" in query for query in queries))
        self.assertFalse(any("CST" in query or "C1747" in query for query in queries))
        self.assertEqual(len(queries), 1)
        self.assertIn("Bangladesh", queries[0])

    def test_keyboard_retailer_queries_include_invoice_variant_attributes(self):
        queries = build_product_search_queries(
            "Example Vendor",
            "Ajazz AK820 75% Wired White Light Hot-Swap Black Mechanical Keyboard AS Red Switch",
        )
        self.assertEqual(len(queries), 1)
        focused = queries[0].casefold()
        self.assertIn('"ajazz ak820"', focused)
        self.assertIn('(keyboard or "mechanical keyboard")', focused)
        self.assertNotIn("star tech", focused)
        self.assertNotIn("hot-swap black mechanical keyboard as red switch", focused)
        self.assertLess(len(focused), 140)

    def test_psu_and_case_queries_include_category_and_material_specs(self):
        psu_queries = build_product_search_queries(
            "Example Vendor",
            "Antec B550 550W 80+ Bronze Non-Modular Power Supply",
        )
        self.assertEqual(len(psu_queries), 1)
        psu_retailer_query = psu_queries[0]
        self.assertIn('"antec b550"', psu_retailer_query.casefold())
        self.assertIn('(psu or "power supply")', psu_retailer_query.casefold())
        self.assertIn("550w", psu_retailer_query.casefold())
        self.assertIn("80+ bronze", psu_retailer_query.casefold())
        self.assertIn("non-modular", psu_retailer_query.casefold())
        self.assertNotIn("trusttech", psu_retailer_query.casefold())

        case_queries = build_product_search_queries(
            "Example Vendor",
            "MaxGreen Panora F3 M-ATX Mid-Tower Case",
        )
        self.assertEqual(len(case_queries), 1)
        case_retailer_query = case_queries[0]
        self.assertIn('"maxgreen panora f3"', case_retailer_query.casefold())
        self.assertIn("(case or casing or chassis)", case_retailer_query.casefold())
        self.assertNotIn("mid-tower", case_retailer_query.casefold())
        self.assertLess(len(case_retailer_query), 100)

        ram_queries = build_product_search_queries(
            "Example Vendor",
            "Team Delta RGB DDR4 8GB 3200MHz CL16 Desktop RAM",
        )
        self.assertEqual(len(ram_queries), 1)
        ram_retailer_query = ram_queries[0]
        self.assertIn('"team delta rgb"', ram_retailer_query.casefold())
        self.assertIn("ddr4", ram_retailer_query.casefold())
        self.assertIn("(ram or memory)", ram_retailer_query.casefold())
        for attribute in ("8gb", "ddr4", "3200mhz", "cl16"):
            self.assertIn(attribute, ram_retailer_query.casefold())

    def test_motherboard_query_uses_exact_model_and_short_category_synonyms(self):
        queries = build_product_search_queries(
            "Example Vendor",
            "MSI A520M-A PRO AM4 AMD ATX Motherboard",
        )

        self.assertEqual(len(queries), 1)
        self.assertIn('"msi a520m-a pro"', queries[0].casefold())
        self.assertIn("(motherboard or mainboard)", queries[0].casefold())
        self.assertLess(len(queries[0]), 100)

    def test_known_bangladesh_computer_stores_are_classified_as_retailers(self):
        from invoice.market_research import RETAILER_DOMAINS
        for domain in (
            "startech.com.bd", "techlandbd.com", "ryans.com",
            "ultratech.com.bd", "techmart.com.bd", "applegadgetsbd.com",
            "pcpartsbd.com", "pcbstore.com.bd", "skylandofficialbd.com",
            "skyland.com.bd", "pchouse.com.bd", "trusttechbd.com",
        ):
            self.assertIn(domain, RETAILER_DOMAINS)

    def test_search_ranking_keeps_local_exact_model_retailers(self):
        from invoice import market_research

        results = [
            {
                "title": "MSI A520M-A PRO Motherboard Price",
                "url": "https://www.startech.com.bd/msi-a520m-a-pro",
                "snippet": "BDT 7,300",
            },
            {
                "title": "MSI A520M-A Pro Motherboard Price",
                "url": "https://startech.com.bd/product/msi-a520m-a-pro?ref=search",
                "snippet": "BDT 7,300",
            },
            {
                "title": "MSI A520M-A PRO Motherboard Price",
                "url": "https://www.techlandbd.com/msi-a520m-a-pro",
                "snippet": "BDT 7,400",
            },
            {
                "title": "MSI A520M-A PRO Motherboard Price",
                "url": "https://www.facebook.com/marketplace/msi-a520m-a-pro",
                "snippet": "BDT 7,200",
            },
            {
                "title": "MSI A520M-A PRO Motherboard Price",
                "url": "https://hardware.example.com/msi-a520m-a-pro",
                "snippet": "BDT 7,100",
            },
        ]

        ranked = market_research._rank_market_search_results(
            results,
            "MSI A520M-A PRO Motherboard",
        )

        self.assertEqual(
            [result["domain"] for result in ranked],
            ["startech.com.bd", "techlandbd.com", "hardware.example.com"],
        )

    def test_localized_serper_model_result_on_non_bd_domain_is_not_dropped(self):
        from invoice import market_research

        ranked = market_research._rank_market_search_results(
            [{
                "title": "MSI A520M-A PRO Motherboard",
                "url": "https://independentshop.example/products/msi-a520m-a-pro",
                "snippet": "Product listing",
                "engine": "serper",
            }],
            "MSI A520M-A PRO Motherboard",
        )

        self.assertEqual(len(ranked), 1)
        self.assertTrue(ranked[0]["localized_retailer_candidate"])

    def test_search_ranking_prefers_model_listing_urls_before_category_pages(self):
        from invoice import market_research

        target = "MaxGreen Panora F3 M-ATX Mid-Tower Casing"
        generic_results = [
            {
                "title": "MaxGreen computer case price",
                "url": f"https://shop{index}.com.bd/component/casing/maxgreen-cases",
                "snippet": "Panora F3 mid-tower case",
            }
            for index in range(7)
        ]
        exact_model_results = [
            {
                "title": "MaxGreen Panora F3 M-ATX Mid-Tower Case",
                "url": f"https://retailer{index}.com.bd/maxgreen-panora-f3-case",
                "snippet": "Price in Bangladesh",
            }
            for index in range(3)
        ]

        ranked = market_research._rank_market_search_results(
            generic_results + exact_model_results,
            target,
            limit=6,
        )

        self.assertEqual(len(ranked), 6)
        self.assertEqual(
            [result["url"] for result in ranked[:3]],
            [result["url"] for result in exact_model_results],
        )

    def test_search_ranking_keeps_plausible_local_results_without_model_and_rejects_conflicts(self):
        from invoice import market_research

        target = "MSI A520M-A PRO ATX Motherboard"
        results = [
            {
                "title": "MSI Motherboard price in Bangladesh",
                "url": "https://www.startech.com.bd/motherboard",
                "snippet": "MSI mainboard product listings",
            },
            {
                "title": "MSI A320M-A PRO Motherboard",
                "url": "https://www.techlandbd.com/msi-a320m-a-pro",
                "snippet": "MSI motherboard price",
            },
            {
                "title": "MSI A520M-A PRO Motherboard",
                "url": "https://www.skyland.com.bd/msi-a520m-a-pro",
                "snippet": "MSI motherboard price",
            },
        ]

        ranked = market_research._rank_market_search_results(results, target)

        self.assertEqual(
            [result["url"] for result in ranked],
            [
                "https://www.skyland.com.bd/msi-a520m-a-pro",
                "https://www.startech.com.bd/motherboard",
            ],
        )

    def test_market_search_uses_serper_only(self):
        from invoice import market_research

        market_research._set_market_diagnostics(market_research._new_provider_diagnostics())
        try:
            query = '"MSI A520M-A PRO" price Bangladesh'
            serper_results = [{
                "title": "MSI A520M-A PRO Motherboard",
                "url": "https://startech.com.bd/msi-a520m-a-pro",
                "domain": "startech.com.bd",
                "snippet": "Page preview, not a verified price",
                "engine": "serper",
            }]
            with patch.object(market_research, "SERPER_API_KEY", "unit-test-key"), \
                 patch.object(
                     market_research,
                     "_search_serper_provider",
                     return_value=(
                         serper_results,
                         {
                             "configured": True,
                             "attempted": True,
                             "requests_sent": 1,
                             "status_code": 200,
                             "content_type": "application/json",
                             "result_count": 1,
                             "cache_hit": False,
                         },
                     ),
                 ) as serper, \
                 patch(
                     "invoice.market.providers.searxng.search_searxng"
                 ) as searxng, \
                 patch.object(market_research, "search_google") as google, \
                 patch.object(market_research, "search_duckduckgo") as duckduckgo, \
                 patch.object(market_research, "search_bing") as bing, \
                 patch.object(market_research, "search_bing_rss") as bing_rss:
                results = market_research.search_web(query)

            self.assertEqual(results, serper_results)
            serper.assert_called_once_with(query, api_key="unit-test-key")
            searxng.assert_not_called()
            google.assert_not_called()
            duckduckgo.assert_not_called()
            bing.assert_not_called()
            bing_rss.assert_not_called()
            diagnostics = market_research._current_market_diagnostics()["providers"]
            self.assertEqual(diagnostics["serper"]["query_count"], 1)
            self.assertNotIn("searxng", diagnostics)
        finally:
            market_research._set_market_diagnostics(None)

    def test_serper_http_error_message_is_propagated_to_persisted_diagnostics(self):
        from invoice import market_research

        message = "Invalid query parameter"
        market_research._set_market_diagnostics(market_research._new_provider_diagnostics())
        try:
            with patch.object(
                market_research,
                "_search_serper_provider",
                return_value=([], {
                    "configured": True,
                    "attempted": True,
                    "requests_sent": 1,
                    "status_code": 400,
                    "error_type": "http_error",
                    "error_message": message,
                }),
            ):
                market_research.search_web('"MSI A520M-A PRO" price Bangladesh')

            current = market_research._current_market_diagnostics()
            provider_diagnostics = market_research._new_provider_diagnostics()
            market_research._merge_provider_diagnostics(
                provider_diagnostics,
                current,
            )
            self.assertEqual(
                provider_diagnostics["providers"]["serper"]["error_message"],
                message,
            )
            self.assertEqual(
                provider_diagnostics["providers"]["serper"]["http_errors"],
                1,
            )
        finally:
            market_research._set_market_diagnostics(None)

    def test_cst_direct_urls_are_never_fetched_for_unrelated_products(self):
        self.assertEqual(
            build_direct_source_candidates("Example Vendor", "Ajazz AK820 mechanical keyboard"),
            [],
        )
        cst_candidates = build_direct_source_candidates(
            "Bike Shop",
            "CST Jack Rabbit C1747 27.5x2.10 Coffee tire",
        )
        self.assertTrue(cst_candidates)
        self.assertTrue(all("cst" in item["url"].lower() or "daraz.com.bd" in item["url"].lower() or "bikeshopbd" in item["url"].lower() or "othoba" in item["url"].lower() for item in cst_candidates))

    def test_cst_queries_are_scoped_to_cst_product(self):
        queries = build_product_search_queries(
            "Bike Shop",
            "CST Jack Rabbit C1747 27.5x2.10 Coffee tire",
        )
        self.assertTrue(any("C1747" in query for query in queries))
        self.assertEqual(len(queries), 1)

    def test_google_html_is_not_used_by_default(self):
        from invoice import market_research
        with patch.object(market_research, "SERPER_API_KEY", ""), patch.object(
            market_research, "_search_serper_provider", return_value=([], {
                "configured": False,
                "attempted": False,
                "requests_sent": 0,
                "cache_hit": False,
                "error_type": "missing_api_key",
            })
        ), patch.object(market_research, "search_google") as google:
            market_research.search_web('site:startech.com.bd "Ajazz AK820"')
        google.assert_not_called()

    def test_searxng_adapter_normalizes_json_results(self):
        payload = json.dumps({
            "results": [
                {
                    "title": "Ajazz AK820 Keyboard",
                    "url": "https://shop.example/products/ak820",
                    "content": "Price BDT 2600",
                    "engine": "brave",
                },
                {
                    "title": "Bad URL",
                    "url": "javascript:alert(1)",
                    "content": "Ignore",
                },
            ]
        }).encode("utf-8")
        with patch(
            "invoice.market.providers.searxng.urlopen",
            return_value=_FakeResponse(payload),
        ):
            results, diagnostics = search_searxng(
                "Ajazz AK820 price Bangladesh",
                endpoint="http://127.0.0.1:8080",
            )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["engine"], "searxng")
        self.assertEqual(results[0]["origin_engine"], "brave")
        self.assertEqual(results[0]["domain"], "shop.example")
        self.assertTrue(diagnostics["attempted"])
        self.assertEqual(diagnostics["status_code"], 200)

    def test_searxng_resolves_brave_go_links_and_preserves_direct_retailer_urls(self):
        from invoice.market.providers import searxng

        direct_url = "https://techdiversitybd.com/ajazz-ak820-mechanical-keyboard/"
        payload = json.dumps({
            "results": [
                {
                    "title": "AJAZZ AK820 Mechanical Keyboard Price | Star Tech",
                    "url": "http:///go/v1/opaque-token",
                    "content": "Price BDT 2,600",
                    "engine": "brave",
                },
                {
                    "title": "AJAZZ AK820 75% Wired Price In Bangladesh",
                    "url": direct_url,
                    "content": "Price BDT 2,600",
                    "engine": "google cse",
                },
            ]
        }).encode("utf-8")
        redirect = HTTPError(
            "https://search.brave.com/go/v1/opaque-token",
            302,
            "Found",
            {"Location": "https://www.startech.com.bd/ajazz-ak820-mechanical-keyboard"},
            io.BytesIO(),
        )
        opener = Mock()
        opener.open.side_effect = redirect
        query = "AJAZZ AK820 75% wired red switch Bangladesh"

        with patch(
            "invoice.market.providers.searxng.urlopen",
            return_value=_FakeResponse(payload),
        ), patch(
            "invoice.market.providers.searxng.build_opener",
            return_value=opener,
        ):
            results, diagnostics = search_searxng(
                query,
                endpoint="http://127.0.0.1:8888",
            )

        self.assertEqual(
            [result["url"] for result in results],
            [
                "https://www.startech.com.bd/ajazz-ak820-mechanical-keyboard",
                direct_url,
            ],
        )
        self.assertEqual(diagnostics["redirect_resolution_attempts"], 1)
        self.assertEqual(diagnostics["redirect_resolution_successes"], 1)
        self.assertEqual(diagnostics["requests_sent"], 2)
        self.assertEqual(diagnostics["malformed_result_url_count"], 0)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://search.brave.com/go/v1/opaque-token")
        self.assertEqual(request.get_method(), "HEAD")
        self.assertIn("search.brave.com/search?", request.get_header("Referer"))

    def test_searxng_rejects_unsafe_brave_destinations_and_non_brave_go_paths(self):
        payload = json.dumps({
            "results": [
                {
                    "title": "Brave token with an unsafe destination",
                    "url": "http:///go/v1/opaque-token",
                    "engine": "brave",
                },
                {
                    "title": "Untrusted engine path",
                    "url": "http:///go/v1/other-token",
                    "engine": "google cse",
                },
                {
                    "title": "Direct retailer",
                    "url": "https://techdiversitybd.com/ajazz-ak820-mechanical-keyboard/",
                    "engine": "google cse",
                },
            ]
        }).encode("utf-8")
        redirect = HTTPError(
            "https://search.brave.com/go/v1/opaque-token",
            302,
            "Found",
            {"Location": "https://127.0.0.1/internal"},
            io.BytesIO(),
        )
        opener = Mock()
        opener.open.side_effect = redirect

        with patch(
            "invoice.market.providers.searxng.urlopen",
            return_value=_FakeResponse(payload),
        ), patch(
            "invoice.market.providers.searxng.build_opener",
            return_value=opener,
        ):
            results, diagnostics = search_searxng(
                "AJAZZ AK820 price Bangladesh",
                endpoint="http://127.0.0.1:8888",
            )

        self.assertEqual(
            [result["url"] for result in results],
            ["https://techdiversitybd.com/ajazz-ak820-mechanical-keyboard/"],
        )
        self.assertEqual(diagnostics["redirect_resolution_attempts"], 1)
        self.assertEqual(diagnostics["redirect_resolution_successes"], 0)
        self.assertEqual(diagnostics["redirect_resolution_failures"], 1)
        self.assertEqual(diagnostics["requests_sent"], 2)
        self.assertEqual(diagnostics["malformed_result_url_count"], 2)
        self.assertEqual(opener.open.call_count, 1)

    def test_searxng_is_disabled_when_endpoint_is_not_configured(self):
        with patch.dict("os.environ", {}, clear=True):
            results, diagnostics = search_searxng("test product", endpoint="")
        self.assertEqual(results, [])
        self.assertFalse(diagnostics["configured"])
        self.assertFalse(diagnostics["attempted"])

    def test_candidate_uses_final_retailer_url_after_searxng_redirect(self):
        from invoice import market_research

        product = "Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard Red Switch"
        result = {
            "title": product,
            "snippet": product,
            "url": "http://127.0.0.1:8888/go/v1/opaque-token",
            "domain": "127.0.0.1",
        }
        html = (
            "<html><body>Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard "
            "Red Switch. Price: BDT 2,600. Add to cart.</body></html>"
        )
        with patch.object(
            market_research,
            "_fetch_for_provider",
            return_value=(html.encode("utf-8"), "https://www.startech.com.bd/ak820"),
        ):
            source = market_research._ORIGINAL_ANALYZE_CANDIDATE_V29(result, product)
        self.assertIsNotNone(source)
        assert source is not None
        self.assertEqual(source["url"], "https://www.startech.com.bd/ak820")
        self.assertEqual(source["source_name"], "startech.com.bd")

    def test_schema_product_offers_are_matched_to_requested_product(self):
        html = '''
        <html><script type="application/ld+json">
        {
          "@context":"https://schema.org",
          "@graph":[
            {"@type":"Product","name":"Ajazz AK820 Mechanical Keyboard",
             "brand":{"@type":"Brand","name":"Ajazz"},
             "model":"AK820",
             "offers":{"@type":"Offer","price":"2600","priceCurrency":"BDT","availability":"https://schema.org/InStock"}},
            {"@type":"Product","name":"CST Jack Rabbit C1747 Tire",
             "brand":{"@type":"Brand","name":"CST"},
             "model":"C1747",
             "offers":{"@type":"Offer","price":"1100","priceCurrency":"BDT"}}
          ]
        }
        </script></html>
        '''
        offers = extract_matching_product_offers(
            html,
            "Ajazz AK820 75% Mechanical Keyboard",
        )
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["price"], 2600.0)
        self.assertEqual(offers[0]["currency"], "BDT")
        self.assertEqual(offers[0]["availability"], "in_stock")

    def test_page_price_prefers_identity_matched_jsonld_and_ignores_other_product_prices(self):
        html = '''
        <html><script type="application/ld+json">
        {"@graph":[
          {"@type":"Product","name":"Ajazz AK820 Mechanical Keyboard","model":"AK820",
           "offers":{"@type":"Offer","price":"2600","priceCurrency":"BDT"}},
          {"@type":"Product","name":"CST Jack Rabbit C1747 Tire","model":"C1747",
           "offers":{"@type":"Offer","price":"1100","priceCurrency":"BDT"}}
        ]}</script>
        <body>Related tire ৳1,100, keyboard reference ৳2,600</body></html>
        '''
        prices = extract_page_price(
            html,
            "shop.example",
            product_description="Ajazz AK820 Mechanical Keyboard",
        )
        self.assertEqual(len(prices), 1)
        self.assertEqual(prices[0]["price"], 2600.0)
        self.assertEqual(prices[0]["currency"], "BDT")
        self.assertEqual(prices[0]["product_name"], "Ajazz AK820 Mechanical Keyboard")
        self.assertEqual(prices[0]["model"], "AK820")
        self.assertEqual(prices[0]["product_identifier"], "AK820")
        self.assertEqual(prices[0]["price_source"], "schema_org_product_offer")


if __name__ == "__main__":
    unittest.main()

class InvoiceProductOrchestrationTests(unittest.TestCase):
    def test_product_analyses_run_concurrently_with_a_three_worker_limit(self):
        from invoice import market_research
        import threading
        import time

        lock = threading.Lock()
        active = 0
        maximum_active = 0

        def fake_analysis(*_args, **_kwargs):
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return {
                "status": "no_reliable_comparable",
                "sources": [],
                "search_diagnostics": {},
                "market_statistics": {},
                "usable_for_risk_calculation": False,
            }

        with patch.object(market_research, "analyze_market_price", side_effect=fake_analysis):
            result = market_research.analyze_invoice_market(
                "Vendor",
                None,
                None,
                "BDT",
                [{"product": f"Product {index}"} for index in range(5)],
            )

        self.assertGreater(maximum_active, 1)
        self.assertLessEqual(maximum_active, 3)
        self.assertEqual(
            [item["line_index"] for item in result["product_analyses"]],
            [0, 1, 2, 3, 4],
        )

    def test_same_retailer_is_preserved_for_each_distinct_invoice_line(self):
        from invoice import market_research

        def fake_analysis(vendor_name, product_description, invoice_unit_price, invoice_currency=None):
            return {
                "status": "analyzed",
                "sources": [{
                    "source_name": "Star Tech",
                    "url": "https://www.startech.com.bd/product/example",
                    "price": 2500 if "keyboard" in product_description.lower() else 5000,
                    "currency": "BDT",
                    "price_source": "page_html",
                }],
                "market_statistics": {"currency": "BDT", "lowest": invoice_unit_price, "highest": invoice_unit_price, "average": invoice_unit_price, "median": invoice_unit_price},
                "usable_for_risk_calculation": True,
                "search_diagnostics": {"queries_attempted": 1, "search_results_found": 1, "candidates_checked": 1},
            }

        with patch.object(market_research, "analyze_market_price", side_effect=fake_analysis):
            result = market_research.analyze_invoice_market(
                "Vendor", None, None, "BDT",
                [
                    {"product_name": "Ajazz AK820 Keyboard", "quantity": 1, "unit_price": 2500},
                    {"product_name": "MSI Monitor", "quantity": 1, "unit_price": 5000},
                ],
            )

        self.assertEqual(len(result["product_analyses"]), 2)
        self.assertEqual(len(result["sources"]), 2)
        self.assertEqual({item["invoice_line_index"] for item in result["sources"]}, {0, 1})
        self.assertEqual({item["product_description"] for item in result["sources"]}, {"Ajazz AK820 Keyboard", "MSI Monitor"})
        self.assertIsNone(result["market_statistics"]["average"])

    def test_duplicate_product_lines_remain_separate_invoice_lines(self):
        from invoice import market_research
        with patch.object(market_research, "analyze_market_price", return_value={
            "status": "no_reliable_comparable", "sources": [], "search_diagnostics": {},
            "market_statistics": {}, "usable_for_risk_calculation": False,
        }) as mocked:
            result = market_research.analyze_invoice_market(
                "Vendor", None, None, "BDT",
                [{"product": "Same SKU", "quantity": 1}, {"product": "Same SKU", "quantity": 2}],
            )
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual([item["line_index"] for item in result["product_analyses"]], [0, 1])
        self.assertEqual(result["status"], "no_reliable_comparable")

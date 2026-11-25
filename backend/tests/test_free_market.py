import json
import unittest
from unittest.mock import patch

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
        self.assertTrue(any("startech.com.bd" in query for query in queries))

    def test_known_bangladesh_computer_stores_are_classified_as_retailers(self):
        from invoice.market_research import RETAILER_DOMAINS
        for domain in (
            "startech.com.bd", "techlandbd.com", "ryans.com",
            "ultratech.com.bd", "techmart.com.bd", "applegadgetsbd.com",
            "pcpartsbd.com", "pcbstore.com.bd", "skylandofficialbd.com",
        ):
            self.assertIn(domain, RETAILER_DOMAINS)

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
        self.assertTrue(any("csttires.com.bd" in query for query in queries))

    def test_google_html_is_not_used_by_default(self):
        from invoice import market_research
        with patch.object(market_research, "search_google") as google, patch.object(
            market_research, "search_duckduckgo", return_value=[]
        ), patch.object(market_research, "search_bing", return_value=[]), patch.object(
            market_research, "search_bing_rss", return_value=[]
        ):
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

    def test_searxng_is_disabled_when_endpoint_is_not_configured(self):
        with patch.dict("os.environ", {}, clear=True):
            results, diagnostics = search_searxng("test product", endpoint="")
        self.assertEqual(results, [])
        self.assertFalse(diagnostics["configured"])
        self.assertFalse(diagnostics["attempted"])

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
        self.assertEqual(prices[0]["sku"], "AK820")
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

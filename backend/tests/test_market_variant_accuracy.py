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

    def test_explicit_cpu_tray_package_requires_matching_page_evidence(self):
        target = "AMD Ryzen 7 5700G Processor with Radeon Graphics (Tray Box)"
        missing_package = assess_product_variant(
            target,
            "AMD Ryzen 7 5700G Processor with Radeon Graphics",
        )
        matching_tray = assess_product_variant(
            target,
            "AMD Ryzen 7 5700G OEM/Tray Processor with Radeon Graphics",
        )
        conflicting_box = assess_product_variant(
            target,
            "AMD Ryzen 7 5700G Boxed Processor with Radeon Graphics",
        )

        self.assertEqual(missing_package["status"], "unverified")
        self.assertIn("cpu_tray", missing_package["reason"])
        self.assertEqual(matching_tray["status"], "verified")
        self.assertEqual(conflicting_box["status"], "mismatch")
        self.assertIn("cpu_package_retail_box", conflicting_box["reason"])

    def test_cpu_tray_from_product_features_is_accepted_but_snippet_only_is_not(self):
        target = "AMD Ryzen 7 5700G Processor with Radeon Graphics (Tray Box)"
        title = "AMD Ryzen 7 5700G Processor with Radeon Graphics"

        def product_page(package_text):
            return f"""
            <html><body><main>
              <h1>{title}</h1>
              <script type="application/ld+json">
                {{"@graph":[{{"@type":"Product","@id":"#5700g",
                  "name":"{title}","brand":{{"@type":"Brand","name":"AMD"}},
                  "model":"5700G","offers":{{"@type":"Offer","@id":"#offer",
                    "price":"21599","priceCurrency":"BDT",
                    "availability":"https://schema.org/InStock"}}}}]}}
              </script>
              <div class="module-features-description">
                <ul><li>Model: {package_text}</li><li>Speed: 3.8GHz</li></ul>
              </div>
              <table><tr><th>Frequency</th><td>3.8GHz</td></tr></table>
            </main></body></html>
            """

        tray_prices = market_research.extract_page_price(
            product_page("Ryzen 7 5700G (Tray Box)"),
            "fusiontech.com.bd",
            product_description=target,
        )
        self.assertEqual(len(tray_prices), 1)
        binding = tray_prices[0]["product_entity_binding"]
        self.assertEqual(binding["association_status"], "unambiguous")
        self.assertIn("Tray Box", binding["page_specifications"])
        self.assertIn("Frequency", binding["page_specifications"])
        tray_source = {
            **tray_prices[0],
            "title": title,
            "source_name": "fusiontech.com.bd",
            "retrieval_method": "direct_http",
        }
        accepted, assessment, reason = market_research._validate_market_source(
            tray_source,
            target,
        )
        self.assertTrue(accepted, reason)
        self.assertEqual(assessment["status"], "verified")

        non_tray_prices = market_research.extract_page_price(
            product_page("Ryzen 7 5700G Processor"),
            "fusiontech.com.bd",
            product_description=target,
        )
        self.assertEqual(len(non_tray_prices), 1)
        snippet_only_source = {
            **non_tray_prices[0],
            "title": title,
            "source_name": "fusiontech.com.bd",
            "retrieval_method": "direct_http",
            "search_snippet": "AMD Ryzen 7 5700G (Tray Box)",
        }
        accepted, assessment, reason = market_research._validate_market_source(
            snippet_only_source,
            target,
        )
        self.assertFalse(accepted)
        self.assertIn("cpu_tray", assessment["reason"])
        self.assertEqual(reason, assessment["reason"])

    def test_product_page_price_and_separate_specification_table_share_one_entity(self):
        target = "MSI A520M-A PRO Micro-ATX Motherboard"
        html = """
        <html><body><main>
          <h1>MSI A520M-A PRO Motherboard</h1>
          <div class="current-price">BDT 7,700</div>
          <table><tr><th>Form Factor</th><td>Micro-ATX</td></tr></table>
        </main></body></html>
        """

        binding = market_research.build_page_local_product_binding(
            html,
            target,
            7700,
            page_url="https://shop.example/msi-a520m-a-pro",
        )
        source = {
            "title": "MSI A520M-A PRO Motherboard",
            "source_name": "shop.example",
            "url": "https://shop.example/msi-a520m-a-pro",
            "price": 7700,
            "currency": "BDT",
            "price_source": "page_html",
            "availability": "listed",
            "product_entity_binding": binding,
        }

        accepted, assessment, reason = market_research._validate_market_source(source, target)

        self.assertTrue(accepted, reason)
        self.assertEqual(assessment["status"], "verified")
        self.assertEqual(binding["product_entity_id"], binding["price_entity_id"])
        self.assertIn("Form Factor", binding["page_specifications"])
        self.assertEqual(binding["evidence_sources"]["price"], "unique_product_page_price_element")

    def test_related_card_and_crossed_out_prices_cannot_bind_to_product_page(self):
        target = "MSI A520M-A PRO Micro-ATX Motherboard"
        related_card_html = """
        <html><body><main>
          <h1>MSI A520M-A PRO Motherboard</h1>
          <table><tr><th>Form Factor</th><td>Micro-ATX</td></tr></table>
          <section class="related-products">
            <h2>Other products</h2><span class="price">BDT 7,700</span>
            <table><tr><th>Form Factor</th><td>ATX</td></tr></table>
          </section>
        </main></body></html>
        """
        related_binding = market_research.build_page_local_product_binding(
            related_card_html,
            target,
            7700,
            price_context="MSI A520M-A PRO Motherboard BDT 7,700",
            page_url="https://shop.example/msi-a520m-a-pro",
        )
        self.assertEqual(related_binding["association_status"], "ambiguous")
        self.assertIn("price_not_located_in_unique_product_scope", related_binding["association_reason"])
        self.assertNotIn(
            "Form Factor ATX",
            related_binding.get("page_specifications", ""),
        )
        accepted, _, reason = market_research._validate_market_source(
            {
                "title": "MSI A520M-A PRO Motherboard",
                "source_name": "shop.example",
                "price": 7700,
                "currency": "BDT",
                "price_source": "page_html",
                "product_entity_binding": related_binding,
            },
            target,
        )
        self.assertFalse(accepted)
        self.assertEqual(
            reason,
            "ambiguous_product_entity_association:price_not_located_in_unique_product_scope",
        )

        crossed_out_html = """
        <html><body><main>
          <h1>MSI A520M-A PRO Motherboard</h1>
          <del class="old-price">BDT 7,700</del>
          <div class="current-price">BDT 8,000</div>
          <table><tr><th>Form Factor</th><td>Micro-ATX</td></tr></table>
        </main></body></html>
        """
        crossed_binding = market_research.build_page_local_product_binding(
            crossed_out_html,
            target,
            7700,
            page_url="https://shop.example/msi-a520m-a-pro",
        )
        self.assertEqual(crossed_binding["association_status"], "ambiguous")
        self.assertIn("price_not_located_in_unique_product_scope", crossed_binding["association_reason"])

    def test_unresolved_page_variant_selector_keeps_local_binding_ambiguous(self):
        target = "MSI A520M-A PRO Micro-ATX Motherboard"
        html = """
        <html><body><main>
          <h1>MSI A520M-A PRO Motherboard</h1>
          <div class="current-price">BDT 7,700</div>
          <select name="model">
            <option value="standard">Standard</option>
            <option value="alternate">Alternate</option>
          </select>
          <table><tr><th>Form Factor</th><td>Micro-ATX</td></tr></table>
        </main></body></html>
        """

        binding = market_research.build_page_local_product_binding(html, target, 7700)

        self.assertEqual(binding["association_status"], "ambiguous")
        self.assertIn("variant_selector_unresolved:model", binding["association_reason"])

    def test_jina_reader_retries_same_page_when_direct_html_has_no_price(self):
        target = "MSI A520M-A PRO Micro-ATX Motherboard"
        html = """
        <html><body><main>
          <h1>MSI A520M-A PRO Motherboard</h1>
          <table><tr><th>Form Factor</th><td>Micro-ATX</td></tr></table>
        </main></body></html>
        """
        result = {
            "url": "https://www.startech.com.bd/msi-a520m-a-pro",
            "domain": "startech.com.bd",
            "title": "MSI Motherboard price",
            "snippet": "MSI mainboard listing",
        }
        rendered = (
            "MSI A520M-A PRO Motherboard. Form Factor: Micro-ATX. "
            "Price: BDT 7,700. Add to cart."
        )
        with patch.object(
            market_research,
            "_fetch_for_provider",
            return_value=(html.encode(), result["url"]),
        ) as fetch, patch.object(
            market_research,
            "fetch_url_via_jina",
            return_value=rendered,
        ) as jina:
            source = market_research.analyze_candidate(result, target)

        fetch.assert_called_once()
        jina.assert_called_once_with(result["url"])
        self.assertIsNotNone(source)
        self.assertEqual(source["retrieval_method"], "jina_reader")
        self.assertEqual(source["price"], 7700)
        self.assertEqual(source["product_entity_binding"]["association_status"], "unambiguous")

    def test_jina_reader_cannot_replace_direct_page_identity_with_a_sibling_model(self):
        target = "MSI A520M-A PRO Micro-ATX Motherboard"
        html = """
        <html><body><main>
          <h1>MSI A520M-A PRO Motherboard</h1>
          <table><tr><th>Form Factor</th><td>Micro-ATX</td></tr></table>
        </main></body></html>
        """
        result = {
            "url": "https://www.startech.com.bd/msi-a520m-a-pro",
            "domain": "startech.com.bd",
            "title": "MSI Motherboard price",
            "snippet": "MSI mainboard listing",
        }
        with patch.object(
            market_research,
            "_fetch_for_provider",
            return_value=(html.encode(), result["url"]),
        ), patch.object(
            market_research,
            "fetch_url_via_jina",
            return_value="MSI A320M motherboard price BDT 7,700",
        ):
            source = market_research.analyze_candidate(result, target)

        self.assertIsNone(source)

    def test_out_of_stock_jsonld_and_dom_offers_are_retained_as_observations(self):
        target = "Antec B550 550W 80+ Bronze Non-Modular Power Supply"
        title = "Antec B550 550W 80+ Bronze Non-Modular Power Supply"
        specifications = (
            "Output Capacity: 550W. Efficiency: 80 Plus Bronze. "
            "Modularity: Non-Modular."
        )
        jsonld_html = f"""
        <html><body><main>
          <h1>{title}</h1>
          <script type="application/ld+json">
            {{"@type":"Product","@id":"#b550","name":"{title}",
             "brand":{{"@type":"Brand","name":"Antec"}},"model":"B550",
             "category":"Power Supply","offers":{{"@type":"Offer",
             "price":"6500","priceCurrency":"BDT",
             "availability":"https://schema.org/OutOfStock"}}}}
          </script>
          <table><tr><th>Specifications</th><td>{specifications}</td></tr></table>
        </main></body></html>
        """
        jsonld_prices = market_research.extract_page_price(
            jsonld_html,
            "shop.example",
            product_description=target,
        )
        self.assertEqual(len(jsonld_prices), 1)
        self.assertEqual(jsonld_prices[0]["availability"], "out_of_stock")
        jsonld_source = {
            **jsonld_prices[0],
            "title": title,
            "source_name": "shop.example",
            "url": "https://shop.example/antec-b550",
            "retrieval_method": "direct_http",
        }
        accepted, _, reason = market_research._validate_market_source(jsonld_source, target)
        self.assertTrue(accepted, reason)

        dom_html = f"""
        <html><body><main>
          <article itemscope itemtype="https://schema.org/Product">
            <h1 itemprop="name">{title}</h1>
            <meta itemprop="brand" content="Antec">
            <meta itemprop="model" content="B550">
            <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
              <meta itemprop="price" content="6500">
              <meta itemprop="priceCurrency" content="BDT">
              <link itemprop="availability" href="https://schema.org/OutOfStock">
            </div>
            <table><tr><th>Specifications</th><td>{specifications}</td></tr></table>
          </article>
        </main></body></html>
        """
        dom_prices = market_research.extract_matching_dom_product_offers(dom_html, target)
        self.assertEqual(len(dom_prices), 1)
        self.assertEqual(dom_prices[0]["availability"], "out_of_stock")

    def test_psu_minimum_system_power_does_not_override_rated_output(self):
        target = "Antec B Series B550 550W 80+ Bronze Non-Modular Power Supply"
        page_evidence = (
            "Antec B Series B550 550W 80 Plus Bronze Non Modular Power Supply. "
            "Minimum Power (Approx.) 470W. Maximum Power 550 Watt. "
            "Peak Output Capacity 550W."
        )

        assessment = assess_product_variant(
            target,
            page_evidence,
            category_evidence=page_evidence,
            brand_evidence="Antec",
            specification_evidence=page_evidence,
        )

        self.assertEqual(assessment["status"], "verified")

    def test_structured_brand_is_not_confused_with_motherboard_chipset(self):
        target = "MSI A520M-A PRO ATX Motherboard"
        title = "MSI A520M-A PRO AMD Micro-ATX Motherboard"
        html = f"""
        <html><body><main>
          <h1>{title}</h1>
          <script type="application/ld+json">
            {{"@graph":[{{"@type":"Product","@id":"#a520m-a-pro",
              "name":"{title}","brand":{{"@type":"Brand","name":"MSI"}},
              "model":"A520M-A PRO","category":"Motherboard",
              "offers":{{"@type":"Offer","@id":"#offer","price":"7700",
                "priceCurrency":"BDT",
                "availability":"https://schema.org/InStock"}}}}]}}
          </script>
          <table><tr><th>Chipset</th><td>AMD A520</td></tr>
            <tr><th>Form Factor</th><td>Micro-ATX</td></tr></table>
        </main></body></html>
        """

        prices = market_research.extract_page_price(
            html,
            "shop.example",
            product_description=target,
        )

        self.assertEqual(len(prices), 1)
        binding = prices[0]["product_entity_binding"]
        self.assertEqual(binding["entity_brand"], "MSI")
        source = {
            **prices[0],
            "title": title,
            "source_name": "shop.example",
            "retrieval_method": "direct_http",
        }
        accepted, assessment, reason = market_research._validate_market_source(
            source,
            target,
        )

        self.assertFalse(accepted)
        self.assertEqual(assessment["reason"], "variant_mismatch:motherboard_form_factor_mismatch")
        self.assertEqual(reason, assessment["reason"])

    def test_ryzen_5700g_uses_one_variant_specific_search(self):
        queries = build_product_search_queries(
            "Example Vendor",
            "AMD Ryzen 7 5700G Processor with Radeon Graphics (Tray Box)",
        )
        self.assertEqual(len(queries), 1)
        self.assertIn('"AMD Ryzen 7 5700G" "Tray Box"', queries[0])
        self.assertIn("(processor OR CPU)", queries[0])
        self.assertNotIn("Star Tech", queries[0])

    def test_analysis_uses_one_query_and_caps_candidate_fetches_at_six(self):
        target = "MSI A520M-A PRO Motherboard"
        domains = [
            "startech.com.bd",
            "techlandbd.com",
            "skyland.com.bd",
            "pchouse.com.bd",
            "ryans.com",
            "ultratech.com.bd",
        ]

        def result_for(domain):
            return {
                "title": target,
                "url": f"https://{domain}/products/msi-a520m-a-pro",
                "domain": domain,
                "snippet": "BDT 7,300",
                "engine": "serper",
            }

        def fake_candidate(result, product_description):
            return {
                "url": result["url"],
                "source_name": result["domain"],
                "title": product_description,
                "price": 7300,
                "currency": "BDT",
                "price_source": "structured_product_page",
                "retrieval_method": "direct_http",
                "availability": "in_stock",
                "match_confidence": 0.9,
                "product_entity_binding": {
                    "association_status": "unambiguous",
                    "product_entity_id": "msi-a520m-a-pro",
                    "price_entity_id": "msi-a520m-a-pro",
                    "entity_identity": product_description,
                    "entity_title": product_description,
                    "entity_category": "motherboard",
                },
            }

        with patch.object(
            market_research,
            "search_web",
            return_value=[result_for(domain) for domain in domains],
        ) as search, patch.object(
            market_research,
            "analyze_candidate",
            side_effect=fake_candidate,
        ) as candidate, patch.object(
            market_research,
            "_validate_market_source",
            return_value=(True, {"status": "verified", "confidence": 0.9}, None),
        ):
            result = market_research.analyze_market_price(
                "Example Vendor",
                target,
                7300,
                "BDT",
            )

        self.assertEqual(search.call_count, 1)
        self.assertEqual(candidate.call_count, 6)
        self.assertEqual(result["search_diagnostics"]["queries_attempted"], 1)
        self.assertEqual(result["search_diagnostics"]["candidates_checked"], 6)
        self.assertEqual(result["search_diagnostics"]["independent_source_count"], 6)

    def test_analysis_fetches_at_most_six_distinct_retailers(self):
        target = "MSI A520M-A PRO Motherboard"
        domains = [
            "startech.com.bd",
            "techlandbd.com",
            "skyland.com.bd",
            "pchouse.com.bd",
            "ryans.com",
            "ultratech.com.bd",
            "trusttechbd.com",
        ]
        results = [
            {
                "title": target,
                "url": f"https://{domain}/products/msi-a520m-a-pro",
                "domain": domain,
                "snippet": "BDT 7,300",
                "engine": "serper",
            }
            for domain in domains
        ]

        with patch.object(market_research, "search_web", return_value=results) as search, \
             patch.object(market_research, "analyze_candidate", return_value=None) as candidate:
            result = market_research.analyze_market_price(
                "Example Vendor",
                target,
                7300,
                "BDT",
            )

        self.assertEqual(search.call_count, 1)
        self.assertEqual(candidate.call_count, 6)
        self.assertEqual(result["search_diagnostics"]["queries_attempted"], 1)
        self.assertEqual(result["search_diagnostics"]["search_candidates_selected"], 6)
        self.assertEqual(result["search_diagnostics"]["search_results_not_fetched_due_to_candidate_cap"], 1)

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

    def test_exact_model_search_hit_is_discovery_only_not_offer_verification(self):
        target = "Addlink S70 Lite 256GB M.2 2280 PCIe NVMe SSD"
        self.assertTrue(
            market_research._passes_search_result_identity_prefilter(
                target,
                {"s70"},
            )
        )
        accepted, assessment, reason = market_research._validate_market_source(
            {
                "title": "S70",
                "search_snippet": "S70 256GB BDT 5000",
                "url": "https://shop.example/s70",
                "price": 5000,
                "currency": "BDT",
                "price_source": "page_html",
                "availability": "listed",
            },
            target,
        )
        self.assertFalse(accepted)
        self.assertEqual(assessment["status"], "unverified")
        self.assertEqual(reason, "product_entity_association_missing")

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
        self.assertEqual(len(queries), 1)
        self.assertIn("AJ199 MAX Carbon Fiber Tri-mode", queries[0])

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

    def test_search_snippet_cannot_verify_variant_for_a_page_price(self):
        target = "AJAZZ AK820 75% Wired Hot-Swap Black Mechanical Keyboard AS Red Switch"
        source = {
            "title": target,
            "search_snippet": target,
            "url": "https://shop.example/ak820",
            "price": 2600,
            "currency": "BDT",
            "price_source": "page_html",
            "availability": "listed",
        }

        accepted, assessment, _ = market_research._validate_market_source(
            source,
            target,
        )
        self.assertFalse(accepted)
        self.assertEqual(assessment["status"], "unverified")

        source["variant_evidence"] = (
            "AJAZZ AK820 75% Wired Hot-Swap Black Mechanical Keyboard "
            "AS Red Switch Price ৳2,600"
        )
        accepted, assessment, _ = market_research._validate_market_source(
            source,
            target,
        )
        self.assertFalse(accepted)

        source["product_entity_binding"] = {
            "association_status": "unambiguous",
            "association_method": "test_product_entity",
            "product_entity_id": "AK820-RED",
            "price_entity_id": "AK820-RED",
            "entity_identity": "AJAZZ AK820 75% Wired Hot-Swap Black Mechanical Keyboard AS Red Switch",
            "page_specifications": "",
            "selected_variant": "",
        }
        accepted, assessment, _ = market_research._validate_market_source(
            source,
            target,
        )
        self.assertTrue(accepted)
        self.assertEqual(assessment["status"], "verified")

    def test_jsonld_price_and_separate_product_specifications_share_one_entity(self):
        target = "Antec B550 550W 80+ Bronze Non-Modular Power Supply"
        html = """
        <html><script type="application/ld+json">
        {"@type":"Product","@id":"#antec-b550","name":"Antec B550 Power Supply",
         "brand":{"@type":"Brand","name":"Antec"},"model":"B550","sku":"B550",
         "offers":{"@type":"Offer","@id":"#offer-b550","price":"4999",
                   "priceCurrency":"BDT","availability":"https://schema.org/InStock"}}
        </script><body><main>
          <h1>Antec B550 550W Power Supply</h1>
          <table id="product-specifications">
            <tr><th>Wattage</th><td>550W</td></tr>
            <tr><th>Efficiency</th><td>80+ Bronze</td></tr>
            <tr><th>Modularity</th><td>Non-Modular</td></tr>
          </table>
        </main></body></html>
        """

        prices = market_research.extract_page_price(
            html,
            "shop.example",
            product_description=target,
        )
        self.assertEqual(len(prices), 1)
        source = {
            **prices[0],
            "title": "Antec B550 550W Power Supply",
            "url": "https://shop.example/antec-b550",
        }
        accepted, assessment, reason = market_research._validate_market_source(source, target)

        self.assertTrue(accepted, reason)
        self.assertEqual(assessment["status"], "verified")
        self.assertEqual(prices[0]["product_entity_binding"]["price_entity_id"], "#antec-b550")
        self.assertIn("80+ Bronze", prices[0]["product_entity_binding"]["page_specifications"])

    def test_category_comes_from_product_title_not_mixed_specification_identity(self):
        target = "Antec B550 550W 80+ Bronze Non-Modular Power Supply"
        html = """
        <html><script type="application/ld+json">
        {"@type":"Product","@id":"#antec-b550",
         "name":"Antec B550 550W 80+ Bronze Non-Modular Power Supply",
         "brand":{"@type":"Brand","name":"Antec"},"model":"B550","sku":"B550",
         "additionalProperty":[{"name":"Connectors","value":"CPU 8-pin and RAM power"}],
         "offers":{"@type":"Offer","price":"4999","priceCurrency":"BDT",
                   "availability":"https://schema.org/InStock"}}
        </script><body><main><h1>Antec B550 550W Power Supply</h1>
          <table id="product-specifications">
            <tr><th>Efficiency</th><td>80+ Bronze</td></tr>
            <tr><th>Modularity</th><td>Non-Modular</td></tr>
          </table>
        </main></body></html>
        """

        prices = market_research.extract_page_price(
            html,
            "shop.example",
            product_description=target,
        )
        source = {
            **prices[0],
            "title": prices[0]["product_name"],
            "url": "https://shop.example/antec-b550",
        }

        accepted, assessment, reason = market_research._validate_market_source(source, target)

        self.assertTrue(accepted, reason)
        self.assertEqual(assessment["status"], "verified")
        self.assertEqual(
            prices[0]["product_entity_binding"]["entity_title"],
            "Antec B550 550W 80+ Bronze Non-Modular Power Supply",
        )

    def test_jsonld_offer_from_another_product_card_is_not_used(self):
        target = "Antec B550 550W 80+ Bronze Non-Modular Power Supply"
        html = """
        <html><script type="application/ld+json">
        {"@graph":[
          {"@type":"Product","@id":"#b550","name":"Antec B550 Power Supply",
           "brand":{"@type":"Brand","name":"Antec"},"model":"B550",
           "offers":{"@type":"Offer","price":"4999","priceCurrency":"BDT"}},
          {"@type":"Product","@id":"#b650","name":"Antec B650 650W Gold Power Supply",
           "brand":{"@type":"Brand","name":"Antec"},"model":"B650",
           "offers":{"@type":"Offer","price":"1000","priceCurrency":"BDT"}}
        ]}</script><body><main><h1>Antec B550 550W Power Supply</h1>
          <table><tr><th>Efficiency</th><td>80+ Bronze</td></tr>
          <tr><th>Modularity</th><td>Non-Modular</td></tr></table>
        </main><aside class="related-products">Antec B650 650W Gold</aside></body></html>
        """

        prices = market_research.extract_page_price(
            html,
            "shop.example",
            product_description=target,
        )

        self.assertEqual([(item["price"], item["product_name"]) for item in prices], [(4999.0, "Antec B550 Power Supply")])
        self.assertEqual(
            prices[0]["product_entity_binding"]["product_entity_id"],
            prices[0]["product_entity_binding"]["price_entity_id"],
        )

    def test_wrong_sku_variant_does_not_verify_target_switch(self):
        target = "Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard Red Switch"
        html = """
        <html><script type="application/ld+json">
        {"@type":"Product","@id":"#ak820-brown","name":"Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard",
         "brand":{"@type":"Brand","name":"Ajazz"},"model":"AK820","sku":"AK820-BROWN",
         "additionalProperty":{"@type":"PropertyValue","name":"Switch","value":"Brown"},
         "offers":{"@type":"Offer","price":"2600","priceCurrency":"BDT"}}
        </script><body><main><h1>Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard</h1>
          <table><tr><th>Switch</th><td>Brown</td></tr></table>
        </main></body></html>
        """
        offer = market_research.extract_page_price(
            html,
            "shop.example",
            product_description=target,
        )[0]
        source = {**offer, "title": "Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard"}

        accepted, assessment, reason = market_research._validate_market_source(source, target)

        self.assertFalse(accepted)
        self.assertEqual(assessment["status"], "mismatch")
        self.assertIn("switch_brown", reason or "")

    def test_unrelated_page_text_cannot_supply_required_variant_evidence(self):
        target = "Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard Red Switch"
        html = """
        <html><script type="application/ld+json">
        {"@type":"Product","@id":"#ak820","name":"Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard",
         "brand":{"@type":"Brand","name":"Ajazz"},"model":"AK820",
         "offers":{"@type":"Offer","price":"2600","priceCurrency":"BDT"}}
        </script><body><main><h1>Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard</h1>
          <table><tr><th>Layout</th><td>75%</td></tr></table>
        </main><aside class="related-products">Red Switch hot-swap keyboard</aside>
        <p>Search snippet: Red Switch 75% hot-swap</p></body></html>
        """
        offer = market_research.extract_page_price(
            html,
            "shop.example",
            product_description=target,
        )[0]
        source = {
            **offer,
            "title": "Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard",
            "search_snippet": target,
        }

        accepted, assessment, reason = market_research._validate_market_source(source, target)

        self.assertFalse(accepted)
        self.assertEqual(assessment["status"], "unverified")
        self.assertIn("switch_red", reason or "")

    def test_unresolved_variant_selector_is_rejected_as_ambiguous(self):
        target = "Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard Red Switch"
        html = """
        <html><script type="application/ld+json">
        {"@type":"Product","@id":"#ak820","name":"Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard",
         "brand":{"@type":"Brand","name":"Ajazz"},"model":"AK820",
         "offers":{"@type":"Offer","price":"2600","priceCurrency":"BDT"}}
        </script><body><main><h1>Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard</h1>
          <select name="attribute_switch">
            <option value="red">Red</option><option value="brown">Brown</option>
          </select>
        </main></body></html>
        """
        offer = market_research.extract_page_price(
            html,
            "shop.example",
            product_description=target,
        )[0]
        source = {**offer, "title": "Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard"}

        accepted, assessment, reason = market_research._validate_market_source(source, target)

        self.assertFalse(accepted)
        self.assertEqual(assessment["status"], "unverified")
        self.assertTrue((reason or "").startswith("ambiguous_product_entity_association:"))

    def test_product_group_offer_follows_referenced_selected_variant(self):
        target = "Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard Red Switch"
        html = """
        <html><script type="application/ld+json">
        {"@graph":[
          {"@type":"ProductGroup","@id":"#ak820-group","name":"Ajazz AK820 Keyboard",
           "hasVariant":[{"@id":"#ak820-red"},{"@id":"#ak820-brown"}],
           "offers":{"@id":"#group-offer"}},
          {"@type":"Product","@id":"#ak820-red","name":"Ajazz AK820 75% Wired Hot-Swap Keyboard",
           "brand":{"@type":"Brand","name":"Ajazz"},"model":"AK820","sku":"AK820-RED",
           "additionalProperty":{"@type":"PropertyValue","name":"Switch","value":"Red"}},
          {"@type":"Product","@id":"#ak820-brown","name":"Ajazz AK820 75% Wired Hot-Swap Keyboard",
           "brand":{"@type":"Brand","name":"Ajazz"},"model":"AK820","sku":"AK820-BROWN",
           "additionalProperty":{"@type":"PropertyValue","name":"Switch","value":"Brown"}},
          {"@type":"Offer","@id":"#group-offer","price":"2600","priceCurrency":"BDT"}
        ]}</script><body><main>
          <h1>Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard</h1>
          <select name="attribute_switch">
            <option value="red" selected>Red</option><option value="brown">Brown</option>
          </select>
        </main></body></html>
        """

        prices = market_research.extract_page_price(
            html,
            "shop.example",
            product_description=target,
        )

        self.assertEqual(len(prices), 1)
        self.assertEqual(prices[0]["sku"], "AK820-RED")
        self.assertEqual(
            prices[0]["product_entity_binding"]["product_entity_id"],
            "#ak820-red",
        )
        self.assertEqual(prices[0]["product_entity_binding"]["selected_variant"], "red")
        source = {**prices[0], "title": "Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard"}
        accepted, assessment, reason = market_research._validate_market_source(source, target)
        self.assertTrue(accepted, reason)
        self.assertEqual(assessment["status"], "verified")

    def test_unbound_product_group_offer_is_rejected_when_variants_are_ambiguous(self):
        target = "Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard Red Switch"
        html = """
        <html><script type="application/ld+json">
        {"@graph":[
          {"@type":"ProductGroup","@id":"#ak820-group","name":"Ajazz AK820 Keyboard",
           "model":"AK820","hasVariant":[{"@id":"#ak820-red"},{"@id":"#ak820-brown"}],
           "offers":{"@type":"Offer","price":"2600","priceCurrency":"BDT"}},
          {"@type":"Product","@id":"#ak820-red","name":"Ajazz AK820 Keyboard",
           "brand":{"@type":"Brand","name":"Ajazz"},"model":"AK820","sku":"AK820-RED",
           "color":"Red"},
          {"@type":"Product","@id":"#ak820-brown","name":"Ajazz AK820 Keyboard",
           "brand":{"@type":"Brand","name":"Ajazz"},"model":"AK820","sku":"AK820-BROWN",
           "color":"Brown"}
        ]}</script><body><main>
          <h1>Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard</h1>
          <select name="attribute_switch">
            <option value="red">Red</option><option value="brown">Brown</option>
          </select>
        </main></body></html>
        """
        offer = market_research.extract_page_price(
            html,
            "shop.example",
            product_description=target,
        )[0]
        source = {**offer, "title": "Ajazz AK820 75% Wired Hot-Swap Mechanical Keyboard"}

        accepted, assessment, reason = market_research._validate_market_source(source, target)

        self.assertFalse(accepted)
        self.assertEqual(assessment["status"], "unverified")
        self.assertTrue((reason or "").startswith("ambiguous_product_entity_association:"))

    def test_dom_product_container_binds_separate_specs_to_its_offer(self):
        target = "Antec B550 550W 80+ Bronze Non-Modular Power Supply"
        html = """
        <html><body><main><div itemscope itemtype="https://schema.org/Product" itemid="#b550">
          <h1 itemprop="name">Antec B550 550W Power Supply</h1>
          <meta itemprop="brand" content="Antec"><meta itemprop="model" content="B550">
          <div itemprop="offers" itemscope itemtype="https://schema.org/Offer" itemid="#offer">
            <meta itemprop="price" content="4999"><meta itemprop="priceCurrency" content="BDT">
            <link itemprop="availability" href="https://schema.org/InStock">
          </div>
          <table><tr><th>Efficiency</th><td>80+ Bronze</td></tr>
            <tr><th>Modularity</th><td>Non-Modular</td></tr></table>
        </div></main></body></html>
        """

        prices = market_research.extract_page_price(
            html,
            "shop.example",
            product_description=target,
        )

        self.assertEqual(len(prices), 1)
        binding = prices[0]["product_entity_binding"]
        self.assertEqual(binding["association_method"], "microdata_product_offer")
        self.assertEqual(binding["product_entity_id"], binding["price_entity_id"])
        self.assertIn("80+ Bronze", binding["page_specifications"])
        source = {**prices[0], "title": "Antec B550 550W Power Supply"}
        accepted, assessment, reason = market_research._validate_market_source(source, target)
        self.assertTrue(accepted, reason)
        self.assertEqual(assessment["status"], "verified")


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

    def test_psu_wattage_efficiency_and_modularity_must_match(self):
        target = "Antec B550 550W 80+ Bronze Non-Modular Power Supply"
        verified = assess_product_variant(target, target)
        wrong_wattage = assess_product_variant(
            target,
            "Antec B550 650W 80+ Bronze Non-Modular Power Supply",
        )
        wrong_efficiency = assess_product_variant(
            target,
            "Antec B550 550W 80+ Gold Non-Modular Power Supply",
        )
        wrong_modularity = assess_product_variant(
            target,
            "Antec B550 550W 80+ Bronze Fully Modular Power Supply",
        )
        missing_specs = assess_product_variant(target, "Antec B550 Power Supply")

        self.assertEqual(verified["status"], "verified")
        for result, feature in (
            (wrong_wattage, "wattage"),
            (wrong_efficiency, "efficiency"),
            (wrong_modularity, "modularity"),
        ):
            self.assertEqual(result["status"], "mismatch")
            self.assertIn(feature, result["reason"])
        self.assertEqual(missing_specs["status"], "unverified")
        self.assertIn("wattage_550", missing_specs["reason"])

    def test_computer_case_category_model_and_form_factor_are_checked(self):
        target = "MaxGreen Panora F3 M-ATX Mid-Tower"
        verified = assess_product_variant(target, "MaxGreen Panora F3 M-ATX Mid-Tower Computer Case")
        wrong_category = assess_product_variant(
            target,
            "MaxGreen Panora F3 Gaming Mouse",
        )
        missing_specs = assess_product_variant(
            target,
            "MaxGreen Panora F3 Computer Case",
        )

        self.assertEqual(verified["status"], "verified")
        self.assertEqual(wrong_category["status"], "mismatch")
        self.assertIn("product_category_mismatch", wrong_category["reason"])
        self.assertEqual(missing_specs["status"], "unverified")
        self.assertIn("case_form_factor_matx", missing_specs["reason"])

    def test_motherboard_atx_and_matx_formats_are_not_combined(self):
        target = "MSI A520M-A PRO AM4 AMD ATX Motherboard"
        wrong_size = assess_product_variant(
            target,
            "MSI A520M-A PRO AM4 AMD ATX Motherboard; Form Factor: mATX",
        )
        missing_size = assess_product_variant(
            target,
            "MSI A520M-A PRO AMD Motherboard",
        )
        self.assertEqual(wrong_size["status"], "mismatch")
        self.assertIn("motherboard_form_factor_mismatch", wrong_size["reason"])
        self.assertEqual(missing_size["status"], "unverified")
        self.assertIn("motherboard_form_factor_atx", missing_size["reason"])

    def test_motherboard_title_without_bound_form_factor_spec_is_unverified(self):
        target = "MSI A520M-A PRO AM4 AMD ATX Motherboard"
        binding = {
            "association_status": "unambiguous",
            "product_entity_id": "msi-a520m-a-pro",
            "price_entity_id": "msi-a520m-a-pro",
            "entity_identity": target,
            "entity_title": target,
            "entity_category": "Motherboard",
            "page_specifications": "",
        }

        accepted, assessment, reason = market_research._validate_market_source(
            {
                "title": target,
                "url": "https://shop.example/msi-a520m-a-pro",
                "price": 7500,
                "currency": "BDT",
                "price_source": "schema_org_product_offer",
                "product_entity_binding": binding,
            },
            target,
        )

        self.assertFalse(accepted)
        self.assertEqual(assessment["status"], "unverified")
        self.assertEqual(
            reason,
            "required_specification_evidence_missing:motherboard_form_factor",
        )

    def test_team_delta_memory_family_capacity_speed_rgb_and_latency_are_checked(self):
        target = "Team Delta RGB DDR4 8GB 3200MHz CL16 Desktop RAM"
        verified = assess_product_variant(target, target)
        wrong_family = assess_product_variant(
            target,
            "Team T-Create Classic RGB DDR4 8GB 3200MHz CL16 Desktop RAM",
        )
        wrong_speed = assess_product_variant(
            target,
            "Team Delta RGB DDR4 8GB 3600MHz CL16 Desktop RAM",
        )
        mixed_families = assess_product_variant(
            target,
            "Team Delta RGB DDR4 8GB 3200MHz CL16; nearby listing "
            "Team T-Create Classic DDR4 8GB 3200MHz CL16 Desktop RAM",
        )
        missing_variant = assess_product_variant(
            target,
            "Team Delta DDR4 Desktop RAM",
        )

        self.assertEqual(verified["status"], "verified")
        self.assertEqual(wrong_family["status"], "mismatch")
        self.assertIn("memory_family_mismatch", wrong_family["reason"])
        self.assertEqual(wrong_speed["status"], "mismatch")
        self.assertIn("memory_speed_mismatch", wrong_speed["reason"])
        self.assertEqual(mixed_families["status"], "mismatch")
        self.assertIn("memory_family_mismatch", mixed_families["reason"])
        self.assertEqual(missing_variant["status"], "unverified")
        self.assertIn("rgb", missing_variant["reason"])
        self.assertIn("capacity_8gb", missing_variant["reason"])
        self.assertIn("memory_latency_16", missing_variant["reason"])

    def test_ssd_capacity_must_match(self):
        target = "Addlink S70 Lite 256GB NVMe SSD"
        wrong_capacity = assess_product_variant(
            target,
            "Addlink S70 Lite 512GB NVMe SSD",
        )
        missing_capacity = assess_product_variant(
            target,
            "Addlink S70 Lite NVMe SSD",
        )

        self.assertEqual(wrong_capacity["status"], "mismatch")
        self.assertIn("capacity_mismatch", wrong_capacity["reason"])
        self.assertEqual(missing_capacity["status"], "unverified")
        self.assertIn("capacity_256gb", missing_capacity["reason"])

    def test_ssd_weight_decimal_is_not_misread_as_capacity(self):
        target = "Addlink S70 Lite 256GB M.2 2280 PCIe NVMe SSD"
        same_capacity_with_weight = assess_product_variant(
            target,
            "Addlink S70 Lite 256GB M.2 2280 PCIe NVMe SSD Capacity 256GB Weight 8.2g",
        )

        self.assertEqual(same_capacity_with_weight["status"], "verified")

    def test_conflicting_listing_title_model_cannot_be_overridden_by_page_snippet(self):
        target = "MaxGreen Panora F3 M-ATX Mid-Tower"
        fake_result = {
            "status": "analyzed",
            "product_query": target,
            "invoice_unit_price": 2450,
            "invoice_currency": "BDT",
            "sources": [{
                "source_name": "techlandbd.com",
                "title": "MaxGreen S19001 Mid-Tower M-ATX Gaming Case",
                "search_snippet": "MaxGreen Panora F3 M-ATX Mid-Tower Case",
                "url": "https://techlandbd.com/maxgreen-s19001-case",
                "price": 700,
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
                2450,
                "BDT",
            )

        self.assertEqual(result["sources"], [])
        self.assertEqual(
            result["excluded_sources"][0]["exclusion_reason"],
            "exact_model_not_found",
        )

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
                "product_entity_binding": {
                    "association_status": "unambiguous",
                    "product_entity_id": "wrong-category",
                    "price_entity_id": "wrong-category",
                    "entity_identity": "Ajazz AK820 Wired Gaming Mouse Red Switch",
                },
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
        self.assertEqual(
            result["search_diagnostics"]["exclusion_reason_counts"],
            {"product_category_mismatch:mouse": 1},
        )

    def test_snippet_only_is_rejected_but_out_of_stock_price_is_an_observation(self):
        base = {"price": 2600, "currency": "BDT", "price_source": "page_html", "availability": "listed"}
        self.assertEqual(classify_price_observation(base), (True, None))
        snippet = {**base, "price_source": "search_result_fallback"}
        self.assertEqual(classify_price_observation(snippet)[1], "search_snippet_only_not_page_verified")
        out = {**base, "availability": "out_of_stock"}
        self.assertEqual(classify_price_observation(out), (True, None))

    def test_out_of_stock_observations_are_in_market_statistics_but_not_available(self):
        target = "MSI A520M-A PRO Motherboard"

        def source(domain, price, availability):
            entity_id = f"product:{domain}"
            return {
                "title": target,
                "source_name": domain,
                "url": f"https://{domain}/msi-a520m-a-pro",
                "price": price,
                "currency": "BDT",
                "price_source": "page_html",
                "availability": availability,
                "product_entity_binding": {
                    "association_status": "unambiguous",
                    "product_entity_id": entity_id,
                    "price_entity_id": entity_id,
                    "entity_identity": target,
                    "entity_title": target,
                    "entity_category": "Motherboard",
                    "entity_brand": "MSI",
                    "page_specifications": "",
                    "selected_variant": "",
                },
            }

        fake_result = {
            "sources": [
                source("retailer-a.example", 7000, "out_of_stock"),
                source("retailer-b.example", 8000, "in_stock"),
            ],
            "excluded_sources": [],
            "invoice_currency": "BDT",
            "invoice_unit_price": 7500,
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
                7500,
                "BDT",
            )

        self.assertEqual(len(result["sources"]), 2)
        self.assertEqual(result["market_statistics"]["lowest"], 7000)
        self.assertEqual(result["market_statistics"]["highest"], 8000)
        self.assertEqual(result["market_statistics"]["average"], 7500)
        self.assertEqual(result["market_statistics"]["median"], 7500)
        self.assertEqual(result["sources"][0]["availability"], "out_of_stock")

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
                    "product_entity_binding": {
                        "association_status": "unambiguous",
                        "product_entity_id": domain,
                        "price_entity_id": domain,
                        "entity_identity": title,
                    },
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

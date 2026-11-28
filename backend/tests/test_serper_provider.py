import io
import json
import threading
import time
import unittest

from urllib.error import HTTPError
from unittest.mock import patch

from invoice.market.providers.serper import (
    _normalize_free_account_query,
    clear_serper_cache,
    search_serper,
)


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


class _TrackingBody(io.BytesIO):
    def __init__(self, payload):
        super().__init__(payload)
        self.read_limit = None

    def read(self, limit=-1):
        self.read_limit = limit
        return super().read(limit)


class SerperProviderTests(unittest.TestCase):

    def setUp(self):
        clear_serper_cache()

    def tearDown(self):
        clear_serper_cache()

    def test_free_account_query_normalizer_removes_advanced_syntax(self):
        query = (
            '"MSI A520M-A PRO" '
            '(motherboard OR mainboard) price Bangladesh'
        )

        self.assertEqual(
            _normalize_free_account_query(query),
            "MSI A520M-A PRO motherboard mainboard price Bangladesh",
        )

    def test_posts_plain_keyword_query_and_normalizes_organic_results(self):
        payload = {
            "organic": [
                {
                    "title": f"Retailer result {index}",
                    "link": f"https://shop{index}.com.bd/product",
                    "snippet": f"Preview {index}",
                }
                for index in range(24)
            ] + [{
                "title": "Malformed URL",
                "link": "javascript:alert(1)",
                "snippet": "Not a retailer page",
            }],
        }

        calls = []

        def fake_open(request, timeout):
            calls.append((request, timeout))
            return _FakeResponse(
                json.dumps(payload).encode("utf-8")
            )

        with patch(
            "invoice.market.providers.serper.build_opener"
        ) as build_opener_mock:

            build_opener_mock.return_value.open.side_effect = fake_open

            results, diagnostics = search_serper(
                '"MSI A520M-A PRO" '
                '(motherboard OR mainboard) price Bangladesh',
                api_key="unit-test-key",
            )

        self.assertEqual(len(calls), 1)

        request, timeout = calls[0]

        self.assertEqual(
            request.full_url,
            "https://google.serper.dev/search",
        )

        self.assertEqual(request.get_method(), "POST")

        self.assertEqual(
            request.get_header("X-api-key"),
            "unit-test-key",
        )

        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {
                "q": "MSI A520M-A PRO motherboard mainboard price Bangladesh",
                "gl": "bd",
                "hl": "en",
                "num": 20,
            },
        )

        self.assertEqual(timeout, 10.0)

        self.assertEqual(
            results[0]["title"],
            "Retailer result 0",
        )

        self.assertEqual(
            results[0]["url"],
            "https://shop0.com.bd/product",
        )

        self.assertEqual(
            results[0]["domain"],
            "shop0.com.bd",
        )

        self.assertEqual(
            results[0]["snippet"],
            "Preview 0",
        )

        self.assertEqual(results[0]["engine"], "serper")
        self.assertEqual(len(results), 20)
        self.assertEqual(diagnostics["result_count"], 20)
        self.assertEqual(diagnostics["requests_sent"], 1)
        self.assertTrue(diagnostics["query_normalized"])

        self.assertNotIn(
            "unit-test-key",
            repr(diagnostics),
        )

    def test_reuses_cached_results_for_repeated_product_query(self):
        payload = {
            "organic": [{
                "title": "Star Tech MSI motherboard",
                "link": "https://www.startech.com.bd/msi-a520m-a-pro",
                "snippet": "Unverified search preview",
            }],
        }

        with patch(
            "invoice.market.providers.serper.build_opener"
        ) as build_opener_mock:

            build_opener_mock.return_value.open.return_value = (
                _FakeResponse(
                    json.dumps(payload).encode("utf-8")
                )
            )

            first_results, first_diagnostics = search_serper(
                '"MSI A520M-A PRO" price Bangladesh',
                api_key="unit-test-key",
            )

            second_results, second_diagnostics = search_serper(
                "  MSI A520M-A PRO price Bangladesh ",
                api_key="unit-test-key",
            )

        self.assertEqual(
            build_opener_mock.return_value.open.call_count,
            1,
        )

        self.assertEqual(first_results, second_results)
        self.assertTrue(first_diagnostics["attempted"])
        self.assertTrue(second_diagnostics["cache_hit"])
        self.assertFalse(second_diagnostics["attempted"])

        self.assertEqual(
            second_diagnostics["requests_sent"],
            0,
        )

    def test_coalesces_concurrent_requests_for_the_same_product(self):
        request_started = threading.Event()
        release_request = threading.Event()

        response = _FakeResponse(
            json.dumps({
                "organic": [{
                    "title": "Techland MSI motherboard",
                    "link": "https://www.techlandbd.com/msi-a520m-a-pro",
                    "snippet": "Search preview",
                }],
            }).encode("utf-8")
        )

        def slow_open(_request, timeout):
            request_started.set()
            release_request.wait(timeout=2)
            return response

        results = []

        with patch(
            "invoice.market.providers.serper.build_opener"
        ) as build_opener_mock:

            build_opener_mock.return_value.open.side_effect = slow_open

            first = threading.Thread(
                target=lambda: results.append(
                    search_serper(
                        '"MSI A520M-A PRO" price Bangladesh',
                        api_key="unit-test-key",
                    )
                ),
            )

            second = threading.Thread(
                target=lambda: results.append(
                    search_serper(
                        '"MSI A520M-A PRO" price Bangladesh',
                        api_key="unit-test-key",
                    )
                ),
            )

            first.start()

            self.assertTrue(
                request_started.wait(timeout=1)
            )

            second.start()
            time.sleep(0.05)
            release_request.set()

            first.join(timeout=2)
            second.join(timeout=2)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())

        self.assertEqual(
            build_opener_mock.return_value.open.call_count,
            1,
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][0], results[1][0])

    def test_api_error_is_reported_without_retry(self):
        error = HTTPError(
            "https://google.serper.dev/search",
            429,
            "Rate limited",
            hdrs=None,
            fp=None,
        )

        with patch(
            "invoice.market.providers.serper.build_opener"
        ) as build_opener_mock:

            build_opener_mock.return_value.open.side_effect = error

            results, diagnostics = search_serper(
                '"MaxGreen Panora F3" price Bangladesh',
                api_key="unit-test-key",
            )

        self.assertEqual(results, [])

        self.assertEqual(
            build_opener_mock.return_value.open.call_count,
            1,
        )

        self.assertEqual(diagnostics["status_code"], 429)
        self.assertEqual(diagnostics["error_type"], "http_error")

    def test_http_400_json_message_is_safe_and_bounded(self):
        body = _TrackingBody(
            json.dumps({
                "message": "Invalid API key: unit-test-key",
                "debug": "full response details must not be persisted",
            }).encode("utf-8")
        )

        error = HTTPError(
            "https://google.serper.dev/search",
            400,
            "Bad Request",
            hdrs={"X-API-KEY": "header-secret"},
            fp=body,
        )

        with patch(
            "invoice.market.providers.serper.build_opener"
        ) as build_opener_mock:

            build_opener_mock.return_value.open.side_effect = error

            results, diagnostics = search_serper(
                '"MSI A520M-A PRO" price Bangladesh',
                api_key="unit-test-key",
            )

        self.assertEqual(results, [])
        self.assertEqual(body.read_limit, 4 * 1024)
        self.assertEqual(diagnostics["status_code"], 400)
        self.assertEqual(diagnostics["error_type"], "http_error")

        self.assertEqual(
            diagnostics["error_message"],
            "Invalid API key: [redacted]",
        )

        self.assertNotIn("unit-test-key", repr(diagnostics))
        self.assertNotIn("header-secret", repr(diagnostics))
        self.assertNotIn("full response details", repr(diagnostics))

        self.assertEqual(
            build_opener_mock.return_value.open.call_count,
            1,
        )

    def test_http_400_nested_error_message_is_extracted_and_redacted(self):
        body = _TrackingBody(
            json.dumps({
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": (
                        "Invalid credential supplied: unit-test-key"
                    ),
                },
                "request_id": "safe-test-id",
            }).encode("utf-8")
        )

        error = HTTPError(
            "https://google.serper.dev/search",
            400,
            "Bad Request",
            hdrs=None,
            fp=body,
        )

        with patch(
            "invoice.market.providers.serper.build_opener"
        ) as build_opener_mock:

            build_opener_mock.return_value.open.side_effect = error

            results, diagnostics = search_serper(
                "test query",
                api_key="unit-test-key",
            )

        self.assertEqual(results, [])

        self.assertEqual(
            diagnostics["error_message"],
            "Invalid credential supplied: [redacted]",
        )

        self.assertNotIn(
            "unit-test-key",
            repr(diagnostics),
        )

        self.assertEqual(body.read_limit, 4 * 1024)

    def test_plain_text_http_error_message_is_captured(self):
        error = HTTPError(
            "https://google.serper.dev/search",
            400,
            "Bad Request",
            hdrs=None,
            fp=io.BytesIO(b"Invalid search request"),
        )

        with patch(
            "invoice.market.providers.serper.build_opener"
        ) as build_opener_mock:

            build_opener_mock.return_value.open.side_effect = error

            results, diagnostics = search_serper(
                "test query",
                api_key="unit-test-key",
            )

        self.assertEqual(results, [])

        self.assertEqual(
            diagnostics["error_message"],
            "Invalid search request",
        )

    def test_missing_api_key_does_not_make_a_request(self):
        with patch(
            "invoice.market.providers.serper.build_opener"
        ) as build_opener_mock:

            results, diagnostics = search_serper(
                '"Team Delta RGB 8GB DDR4" price Bangladesh',
                api_key="",
            )

        self.assertEqual(results, [])
        self.assertFalse(diagnostics["attempted"])

        self.assertEqual(
            diagnostics["error_type"],
            "missing_api_key",
        )

        build_opener_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
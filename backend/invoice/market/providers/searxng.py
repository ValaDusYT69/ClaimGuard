"""Small, dependency-free adapter for a configured SearXNG JSON endpoint.

SearXNG is optional. ClaimGuard never silently selects an unknown public
instance: an operator must configure SEARXNG_URL explicitly. The endpoint
must have JSON output enabled in its own settings.yml.
"""

from __future__ import annotations

import json
import os
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

DEFAULT_TIMEOUT_SECONDS = 6.0
DEFAULT_MAX_RESULTS = 12
MAX_RESPONSE_BYTES = 1_500_000


def _safe_endpoint(value: str) -> str:
    endpoint = (value or "").strip().rstrip("/")
    if not endpoint:
        return ""
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password:
        return ""
    return endpoint


def _safe_result_url(value: Any) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password:
        return ""
    return url


def search_searxng(
    query: str,
    *,
    endpoint: str | None = None,
    api_key: str | None = None,
    language: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Search a configured SearXNG endpoint and return normalized candidates.

    The second tuple item is a sanitized diagnostic record. It deliberately
    excludes the query, full URL, response body, headers, and credentials.
    """

    configured_endpoint = _safe_endpoint(
        endpoint if endpoint is not None else os.getenv("SEARXNG_URL", "")
    )
    diagnostics: dict[str, Any] = {
        "configured": bool(configured_endpoint),
        "attempted": False,
        "requests_sent": 0,
        "status_code": None,
        "content_type": None,
        "result_count": 0,
        "timeout": False,
        "connection_error": False,
        "http_error": False,
        "parse_error": False,
        "error_type": None,
    }
    if not configured_endpoint or not str(query or "").strip():
        return [], diagnostics

    parsed_endpoint = urlparse(configured_endpoint)
    path = parsed_endpoint.path.rstrip("/")
    if not path.endswith("/search"):
        path = f"{path}/search" if path else "/search"
    search_url = parsed_endpoint._replace(path=path).geturl()

    params = {
        "q": str(query).strip(),
        "format": "json",
        "language": (language or os.getenv("SEARXNG_LANGUAGE", "en")).strip() or "en",
        "safesearch": "1",
        "pageno": "1",
    }
    request_url = f"{search_url}?{urlencode(params)}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "ClaimGuard-MarketResearch/1.0 (+configured SearXNG client)",
    }
    token = (api_key if api_key is not None else os.getenv("SEARXNG_API_KEY", "")).strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(request_url, headers=headers, method="GET")
    diagnostics["attempted"] = True
    diagnostics["requests_sent"] = 1

    try:
        with urlopen(request, timeout=max(1.0, min(float(timeout), 15.0))) as response:
            diagnostics["status_code"] = getattr(response, "status", None)
            diagnostics["content_type"] = response.headers.get_content_type() if response.headers else None
            payload = response.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES:
            diagnostics["parse_error"] = True
            diagnostics["error_type"] = "response_too_large"
            return [], diagnostics
        data = json.loads(payload.decode("utf-8", errors="strict"))
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            diagnostics["parse_error"] = True
            diagnostics["error_type"] = "unexpected_json_shape"
            return [], diagnostics

        results: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in data["results"]:
            if not isinstance(item, dict):
                continue
            url = _safe_result_url(item.get("url"))
            title = str(item.get("title") or "").strip()
            if not url or not title or url in seen:
                continue
            seen.add(url)
            hostname = (urlparse(url).hostname or "").lower()
            domain = hostname.removeprefix("www.")
            content = str(item.get("content") or item.get("snippet") or "").strip()
            results.append({
                "title": title[:500],
                "snippet": content[:2500],
                "url": url,
                "domain": domain,
                "engine": "searxng",
                "origin_engine": str(item.get("engine") or "")[:80],
            })
            if len(results) >= max(1, min(int(max_results), 30)):
                break

        diagnostics["result_count"] = len(results)
        return results, diagnostics

    except HTTPError as exc:
        diagnostics["status_code"] = int(exc.code)
        diagnostics["http_error"] = True
        diagnostics["error_type"] = "http_error"
    except (TimeoutError, socket.timeout):
        diagnostics["timeout"] = True
        diagnostics["error_type"] = "timeout"
    except URLError as exc:
        reason = getattr(exc, "reason", None)
        diagnostics["connection_error"] = True
        diagnostics["error_type"] = "dns_error" if isinstance(reason, socket.gaierror) else "connection_error"
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        diagnostics["parse_error"] = True
        diagnostics["error_type"] = "invalid_json"
    except Exception as exc:  # defensive boundary around an optional provider
        diagnostics["error_type"] = type(exc).__name__

    return [], diagnostics

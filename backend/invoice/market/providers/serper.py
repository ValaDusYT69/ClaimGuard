"""Serper.dev Google Search API adapter with a bounded query-result cache."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

SERPER_SEARCH_URL = "https://google.serper.dev/search"
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 1_500_000
MAX_ERROR_BODY_BYTES = 4 * 1024
CACHE_TTL_SECONDS = 30 * 60
MAX_CACHE_ENTRIES = 128

_CACHE: OrderedDict[str, tuple[float, list[dict[str, str]], dict[str, Any]]] = OrderedDict()
_INFLIGHT: dict[str, threading.Event] = {}
_CACHE_LOCK = threading.Lock()


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _query_key(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip().casefold()


def _copy_results(results: list[dict[str, str]]) -> list[dict[str, str]]:
    return [dict(result) for result in results]


def _safe_http_error_message(body: bytes, api_key: str) -> str | None:
    try:
        payload = json.loads(body.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("message"), str):
        return None

    message = " ".join(payload["message"].split())
    if api_key:
        message = message.replace(api_key, "[redacted]")
    message = re.sub(
        r"(?i)\b(x-api-key|authorization)\b\s*[:=]\s*\S+",
        r"\1=[redacted]",
        message,
    )
    message = message[:500].strip()
    return message or None


def _cache_read(key: str) -> tuple[list[dict[str, str]], dict[str, Any]] | None:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    expires_at, results, diagnostics = entry
    if expires_at <= time.monotonic():
        del _CACHE[key]
        return None
    _CACHE.move_to_end(key)
    cached_diagnostics = dict(diagnostics)
    cached_diagnostics.update({
        "attempted": False,
        "requests_sent": 0,
        "cache_hit": True,
    })
    return _copy_results(results), cached_diagnostics


def clear_serper_cache() -> None:
    """Clear cached organic results, primarily for tests and credential rotation."""
    with _CACHE_LOCK:
        _CACHE.clear()


def search_serper(
    query: str,
    *,
    api_key: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Return normalized organic results; snippets remain unverified search hints."""
    diagnostics: dict[str, Any] = {
        "configured": bool(str(api_key or "").strip()),
        "attempted": False,
        "requests_sent": 0,
        "status_code": None,
        "content_type": None,
        "result_count": 0,
        "cache_hit": False,
        "error_type": None,
        "error_message": None,
    }
    clean_query = re.sub(r"\s+", " ", str(query or "")).strip()
    token = str(api_key or "").strip()
    if not clean_query:
        diagnostics["error_type"] = "empty_query"
        return [], diagnostics
    if not token:
        diagnostics["error_type"] = "missing_api_key"
        return [], diagnostics

    cache_key = (
        hashlib.sha256(token.encode("utf-8")).hexdigest()
        + ":"
        + _query_key(clean_query)
    )
    with _CACHE_LOCK:
        cached = _cache_read(cache_key)
        if cached is not None:
            results, cached_diagnostics = cached
            return results, cached_diagnostics
        event = _INFLIGHT.get(cache_key)
        is_request_owner = event is None
        if is_request_owner:
            event = threading.Event()
            _INFLIGHT[cache_key] = event

    if not is_request_owner:
        event.wait(max(1.0, min(float(timeout), 30.0)) + 1.0)
        with _CACHE_LOCK:
            cached = _cache_read(cache_key)
            if cached is not None:
                results, cached_diagnostics = cached
                return results, cached_diagnostics
        diagnostics["error_type"] = "shared_request_failed"
        return [], diagnostics

    cache_response = False
    results: list[dict[str, str]] = []
    try:
        request = Request(
            SERPER_SEARCH_URL,
            data=json.dumps(
                {"q": clean_query, "gl": "bd", "hl": "en", "num": 20},
                separators=(",", ":"),
            ).encode("utf-8"),
            headers={
                "X-API-KEY": token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        opener = build_opener(_NoRedirectHandler())
        diagnostics["attempted"] = True
        diagnostics["requests_sent"] = 1
        with opener.open(
            request,
            timeout=max(1.0, min(float(timeout), 30.0)),
        ) as response:
            diagnostics["status_code"] = getattr(response, "status", None)
            diagnostics["content_type"] = (
                response.headers.get_content_type() if response.headers else None
            )
            payload = response.read(MAX_RESPONSE_BYTES + 1)

        if len(payload) > MAX_RESPONSE_BYTES:
            diagnostics["error_type"] = "response_too_large"
            return [], diagnostics
        data = json.loads(payload.decode("utf-8", errors="strict"))
        if not isinstance(data, dict) or not isinstance(data.get("organic"), list):
            diagnostics["error_type"] = "unexpected_json_shape"
            return [], diagnostics

        seen_urls: set[str] = set()
        for item in data["organic"]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            raw_url = str(item.get("link") or "").strip()
            try:
                parsed_url = urlparse(raw_url)
                hostname = parsed_url.hostname
                parsed_url.port
            except ValueError:
                continue
            if (
                not title
                or parsed_url.scheme not in {"http", "https"}
                or not hostname
                or parsed_url.username
                or parsed_url.password
            ):
                continue
            canonical_url = parsed_url._replace(query="", fragment="").geturl().rstrip("/")
            if canonical_url in seen_urls:
                continue
            seen_urls.add(canonical_url)
            results.append({
                "title": title[:500],
                "url": raw_url,
                "domain": hostname.lower().removeprefix("www."),
                "snippet": str(item.get("snippet") or "").strip()[:2500],
                "engine": "serper",
            })
            if len(results) >= 20:
                break

        diagnostics["result_count"] = len(results)
        cache_response = True
        return results, diagnostics
    except HTTPError as exc:
        diagnostics["status_code"] = int(exc.code)
        diagnostics["error_type"] = "http_error"
        try:
            diagnostics["error_message"] = _safe_http_error_message(
                exc.read(MAX_ERROR_BODY_BYTES),
                token,
            )
        except (AttributeError, OSError):
            pass
        finally:
            exc.close()
    except (TimeoutError, OSError, URLError):
        diagnostics["error_type"] = "connection_error"
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        diagnostics["error_type"] = "invalid_response"
    except Exception as exc:
        diagnostics["error_type"] = type(exc).__name__
    finally:
        with _CACHE_LOCK:
            if cache_response:
                _CACHE[cache_key] = (
                    time.monotonic() + CACHE_TTL_SECONDS,
                    _copy_results(results),
                    dict(diagnostics),
                )
                _CACHE.move_to_end(cache_key)
                while len(_CACHE) > MAX_CACHE_ENTRIES:
                    _CACHE.popitem(last=False)
            event = _INFLIGHT.pop(cache_key, None)
            if event is not None:
                event.set()

    return [], diagnostics

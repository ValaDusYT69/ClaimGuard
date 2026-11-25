"""Identity-aware extraction of Schema.org Product/Offer JSON-LD prices."""

from __future__ import annotations

import json
import re
from html import unescape
from typing import Any

_JSON_LD_RE = re.compile(
    r'<script\b[^>]*type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script\s*>',
    re.IGNORECASE | re.DOTALL,
)


def _normal(value: Any) -> str:
    text = unescape(str(value or "")).casefold()
    text = re.sub(r"[^a-z0-9.]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("@id") or "")
    if isinstance(value, list):
        return " ".join(_name(item) for item in value if item)
    return str(value or "")


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _types(node: dict[str, Any]) -> set[str]:
    raw = node.get("@type")
    values = raw if isinstance(raw, list) else [raw]
    return {str(item).rsplit("/", 1)[-1].casefold() for item in values if item}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    match = re.search(r"(?<![\w])([0-9]+(?:\.[0-9]{1,2})?)(?![\w])", text)
    if not match:
        return None
    try:
        number = float(match.group(1))
    except (TypeError, ValueError):
        return None
    return round(number, 2) if number > 0 else None


def _offer_nodes(product_node: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for key in ("offers", "aggregateOffer"):
        value = product_node.get(key)
        if isinstance(value, dict):
            candidates.extend(_walk(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    candidates.extend(_walk(item))
    # Preserve order while de-duplicating object identity.
    output: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in candidates:
        marker = id(item)
        if marker not in seen:
            seen.add(marker)
            output.append(item)
    return output


def _identity_score(target: str, candidate: str) -> tuple[float, bool]:
    target_norm = _normal(target)
    candidate_norm = _normal(candidate)
    if not target_norm or not candidate_norm:
        return 0.0, False

    target_tokens = set(target_norm.split())
    candidate_tokens = set(candidate_norm.split())
    overlap = len(target_tokens & candidate_tokens) / max(1, len(target_tokens))

    target_models = set(re.findall(r"\b[a-z][a-z0-9-]*\d[a-z0-9-]*\b", target_norm))
    candidate_models = set(re.findall(r"\b[a-z][a-z0-9-]*\d[a-z0-9-]*\b", candidate_norm))
    model_match = bool(target_models and target_models & candidate_models)

    # If the invoice identity includes a model token, an Offer without that
    # model evidence is not accepted merely because category words overlap.
    if target_models and not model_match:
        return overlap, False

    brand_tokens = [token for token in target_norm.split()[:2] if len(token) >= 3]
    brand_match = not brand_tokens or any(token in candidate_tokens for token in brand_tokens)
    accepted = (overlap >= 0.28 and brand_match) or (model_match and overlap >= 0.18)
    return overlap + (0.35 if model_match else 0.0), accepted


def _is_product_node(node: dict[str, Any]) -> bool:
    types = _types(node)
    if "product" in types:
        return True
    # Some sites omit @type on Product but still expose a named node with an
    # offers member. Keep this fallback conservative.
    return bool(node.get("name") and ("offers" in node or "aggregateOffer" in node))


def extract_matching_product_offers(html: str, product_description: str) -> list[dict[str, Any]]:
    """Return prices only from JSON-LD product nodes matching the requested item."""

    if not html or not product_description:
        return []

    blocks: list[Any] = []
    for match in _JSON_LD_RE.finditer(html):
        raw = re.sub(r"^\s*<!--|--?>\s*$", "", match.group(1)).strip()
        if not raw:
            continue
        try:
            blocks.append(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue

    accepted: list[dict[str, Any]] = []
    seen: set[tuple[float, str, str]] = set()

    for block in blocks:
        for node in _walk(block):
            if not _is_product_node(node):
                continue

            brand = _name(node.get("brand"))
            identity = " ".join(str(part) for part in (
                node.get("name"), brand, node.get("model"), node.get("sku"),
                node.get("mpn"), node.get("description"),
            ) if part)
            score, matched = _identity_score(product_description, identity)
            if not matched:
                continue

            offers = _offer_nodes(node)
            for offer in offers:
                price = _number(offer.get("price"))
                currency = str(offer.get("priceCurrency") or "").upper().strip() or None
                price_spec = offer.get("priceSpecification")
                if price is None and isinstance(price_spec, dict):
                    price = _number(price_spec.get("price"))
                    currency = str(price_spec.get("priceCurrency") or currency or "").upper().strip() or None
                if price is None or not currency:
                    continue

                availability_raw = str(offer.get("availability") or "").casefold()
                availability = (
                    "out_of_stock" if "outofstock" in availability_raw
                    else "in_stock" if "instock" in availability_raw
                    else "unknown"
                )
                # Out-of-stock offers are not current market observations.
                if availability == "out_of_stock":
                    continue
                seller = _name(offer.get("seller"))
                key = (price, currency, seller.casefold())
                if key in seen:
                    continue
                seen.add(key)
                accepted.append({
                    "price": price,
                    "currency": currency,
                    "product_name": str(node.get("name") or "").strip(),
                    "brand": brand,
                    "sku": str(node.get("sku") or node.get("mpn") or node.get("model") or "").strip(),
                    "seller": seller,
                    "availability": availability,
                    "match_confidence": round(min(score, 1.0), 2),
                    "price_source": "schema_org_product_offer",
                })

    return accepted

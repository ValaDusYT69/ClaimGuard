"""Evidence-gated, product-line market comparison for ClaimGuard.

This module consumes accepted source observations from market_research and
creates a canonical comparison record for each invoice line. It deliberately
never builds an invoice-wide price average across different SKUs.
"""
from __future__ import annotations

from collections import Counter
from math import isfinite
from statistics import mean, median
from typing import Any
from urllib.parse import urlsplit

from invoice.market.variant_validation import classify_price_observation

MIN_INDEPENDENT_DOMAINS = 2
PRICE_DEVIATION_START_PERCENT = 15.0
PRICE_DEVIATION_FULL_PERCENT = 50.0
MAX_PRICE_RISK_POINTS = 30.0
_MULTI_PART_SUFFIXES = {
    "com.bd", "net.bd", "org.bd", "gov.bd", "edu.bd", "ac.bd",
    "co.uk", "org.uk", "ac.uk", "com.au", "net.au", "org.au",
    "co.nz", "com.sg", "com.my", "co.in", "com.pk",
}


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def _domain(source: dict[str, Any]) -> str | None:
    url = str(source.get("url") or "").strip()
    host = ""
    if url:
        try:
            host = (urlsplit(url).hostname or "").lower().strip(".")
        except ValueError:
            host = ""
    if not host:
        host = str(source.get("domain") or source.get("source_name") or "").lower().strip()
        host = host.split("/")[0].split(":")[0].strip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    labels = [label for label in host.split(".") if label]
    if len(labels) < 2:
        return None
    suffix2 = ".".join(labels[-2:])
    if suffix2 in _MULTI_PART_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return suffix2


def _excluded(source: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "source": str(source.get("source_name") or source.get("url") or "Unknown source"),
        "title": source.get("title"),
        "url": source.get("url"),
        "price": source.get("price"),
        "currency": source.get("currency"),
        "availability": source.get("availability"),
        "reason": reason,
    }


def _eligible_sources(
    market: dict[str, Any],
    invoice_currency: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Filter already-accepted market results again before financial math."""
    observations: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    sources = market.get("sources") if isinstance(market.get("sources"), list) else []
    target_currency = str(invoice_currency or market.get("invoice_currency") or "").strip().upper()
    by_domain: dict[str, dict[str, Any]] = {}

    for source in sources:
        if not isinstance(source, dict):
            continue
        eligible, reason = classify_price_observation(source)
        if not eligible:
            excluded.append(_excluded(source, reason or "price_observation_rejected"))
            continue

        currency = str(source.get("currency") or "").strip().upper()
        if target_currency and currency != target_currency:
            excluded.append(_excluded(source, "currency_mismatch"))
            continue

        variant = source.get("variant_validation")
        if isinstance(variant, dict):
            variant_status = str(variant.get("status") or "").lower()
            if variant_status not in {"verified", "exact", "matched"}:
                excluded.append(_excluded(source, "product_variant_not_verified"))
                continue

        # Out-of-stock offers remain useful as historical observations in the
        # market-research evidence, but they must not enter the current-price
        # benchmark used for invoice comparison. Support both Schema.org's
        # OutOfStock value and common retailer status spellings.
        availability_raw = str(source.get("availability") or "").casefold()
        availability_compact = "".join(
            character for character in availability_raw if character.isalnum()
        )
        if availability_compact in {
            "outofstock",
            "soldout",
            "unavailable",
            "notavailable",
            "discontinued",
        } or "outofstock" in availability_compact:
            excluded.append(_excluded(source, "out_of_stock"))
            continue

        domain = _domain(source)
        if not domain:
            excluded.append(_excluded(source, "independent_domain_not_identified"))
            continue

        price = _number(source.get("price"))
        if price is None or price <= 0:
            excluded.append(_excluded(source, "price_missing_or_invalid"))
            continue

        candidate = dict(source)
        candidate["_normalized_domain"] = domain
        candidate["_normalized_price"] = price
        existing = by_domain.get(domain)
        # One retailer contributes one observation. Prefer the source with the
        # strongest explicit identity confidence; ties keep the first listing.
        confidence = _number(candidate.get("match_confidence")) or 0.0
        old_confidence = (_number(existing.get("match_confidence")) or 0.0) if existing else -1.0
        if existing is None or confidence > old_confidence:
            if existing is not None:
                excluded.append(_excluded(existing, "duplicate_retailer_domain"))
            by_domain[domain] = candidate
        else:
            excluded.append(_excluded(candidate, "duplicate_retailer_domain"))

    observations = list(by_domain.values())
    return observations, excluded


def _risk_points(difference_percent: float | None) -> float | None:
    if difference_percent is None:
        return None
    magnitude = abs(difference_percent)
    if magnitude <= PRICE_DEVIATION_START_PERCENT:
        return 0.0
    if magnitude >= PRICE_DEVIATION_FULL_PERCENT:
        return MAX_PRICE_RISK_POINTS
    return round(
        ((magnitude - PRICE_DEVIATION_START_PERCENT) /
         (PRICE_DEVIATION_FULL_PERCENT - PRICE_DEVIATION_START_PERCENT))
        * MAX_PRICE_RISK_POINTS,
        2,
    )


def compare_product_market(
    product_analysis: dict[str, Any],
    invoice_currency: str | None = None,
) -> dict[str, Any]:
    """Build one evidence-gated benchmark for a single invoice product line."""
    market = product_analysis.get("market") if isinstance(product_analysis.get("market"), dict) else product_analysis
    currency = str(invoice_currency or market.get("invoice_currency") or "").strip().upper() or None
    invoice_price = _number(
        product_analysis.get("invoice_unit_price")
        if product_analysis.get("invoice_unit_price") is not None
        else market.get("invoice_unit_price")
    )
    sources, excluded = _eligible_sources(market, currency)
    domains = sorted({str(source.get("_normalized_domain")) for source in sources})
    source_count = len(sources)
    domain_count = len(domains)

    source_currencies = Counter(str(source.get("currency") or "").upper() for source in sources)
    benchmark_currency = currency or (source_currencies.most_common(1)[0][0] if source_currencies else None)
    can_benchmark = domain_count >= MIN_INDEPENDENT_DOMAINS and bool(benchmark_currency)

    stats = {
        "currency": benchmark_currency,
        "lowest": None,
        "highest": None,
        "average": None,
        "median": None,
        "source_count": source_count,
        "independent_domain_count": domain_count,
    }
    difference = difference_percent = alignment = risk_points = None
    direction = "unavailable"

    if can_benchmark:
        prices = [float(source["_normalized_price"]) for source in sources]
        average = mean(prices)
        stats.update({
            "lowest": round(min(prices), 2),
            "highest": round(max(prices), 2),
            "average": round(average, 2),
            "median": round(median(prices), 2),
        })
        if invoice_price is not None and average > 0:
            difference = round(invoice_price - average, 2)
            difference_percent = round((difference / average) * 100.0, 2)
            direction = "above" if difference > 0 else "below" if difference < 0 else "at"
            alignment = round(max(0.0, 100.0 - abs(difference_percent)), 1)
            risk_points = _risk_points(difference_percent)

    confidences: list[float] = []
    for source in sources:
        confidence = _number(source.get("match_confidence"))
        if confidence is not None and 0 <= confidence <= 1:
            confidences.append(confidence)
    match_confidence = round(mean(confidences) * 100.0, 1) if confidences else None

    if source_count == 0:
        status = "no_valid_price_evidence"
        message = "No accepted page-verified price observation is available for this product."
    elif domain_count < MIN_INDEPENDENT_DOMAINS:
        status = "insufficient_independent_sources"
        message = f"Only {domain_count} independent retailer domain(s) passed validation; at least {MIN_INDEPENDENT_DOMAINS} are required for a benchmark."
    elif invoice_price is None:
        status = "invoice_price_missing"
        message = "A market reference is available, but the invoice unit price is missing or invalid."
    else:
        status = "comparable"
        message = "The invoice price was compared with page-verified offers from independent retailer domains."

    # Strip private temporary values from the returned source records.
    public_sources = [
        {key: value for key, value in source.items() if not key.startswith("_")}
        for source in sources
    ]

    line_index = product_analysis.get("line_index")
    return {
        "line_index": line_index,
        "product": product_analysis.get("product") or market.get("product_query"),
        "status": status,
        "is_comparable": status == "comparable",
        "message": message,
        "invoice_unit_price": invoice_price,
        "currency": benchmark_currency or currency,
        "market_statistics": stats,
        "accepted_source_count": source_count,
        "independent_domain_count": domain_count,
        "minimum_independent_domains": MIN_INDEPENDENT_DOMAINS,
        "independent_domains": domains,
        "difference_amount": difference,
        "difference_percent": difference_percent,
        "difference_direction": direction,
        "price_alignment_score": alignment,
        "market_match_confidence": match_confidence,
        "price_risk_points": risk_points,
        "price_risk_level": (
            "unassessed" if risk_points is None else
            "high" if risk_points >= 25 else
            "medium" if risk_points >= 12 else "low"
        ),
        "score_methodology": {
            "price_alignment": "max(0, 100 - absolute invoice-to-market-average percentage difference); only with at least two independent domains.",
            "price_risk_points": "0 at or below 15% absolute deviation; linear to 30 points at 50% deviation; only with a valid two-domain benchmark.",
            "match_confidence": "Mean accepted source product-match confidence; not model accuracy or fraud probability.",
        },
        "accepted_sources": public_sources,
        "excluded_observations": excluded,
    }


def enrich_market_analysis(
    market_analysis: dict[str, Any] | None,
    line_items: list[dict[str, Any]] | None,
    invoice_currency: str | None = None,
) -> dict[str, Any]:
    """Attach canonical comparison records and a non-SKU-averaged summary."""
    result = dict(market_analysis or {})
    raw_analyses = result.get("product_analyses")
    product_analyses = [dict(item) for item in raw_analyses if isinstance(item, dict)] if isinstance(raw_analyses, list) else []
    items: list[dict[str, Any]] = []
    for raw_line in (line_items or []):
        if not isinstance(raw_line, dict):
            continue
        product_name = next((str(raw_line.get(key) or "").strip() for key in
                             ("product", "product_name", "description", "name", "item_description")
                             if str(raw_line.get(key) or "").strip()), "")
        if product_name:
            items.append({**raw_line, "product": product_name})

    # Phase 03 preserves line_index; name-based fallback is only used for older
    # records where line indices are absent. Exact names avoid cross-SKU joins.
    analyses_by_index = {
        int(entry["line_index"]): entry
        for entry in product_analyses
        if entry.get("line_index") is not None and str(entry.get("line_index")).isdigit()
    }
    comparisons: list[dict[str, Any]] = []
    weighted: list[tuple[float, float]] = []
    comparable_value = 0.0
    total_known_value = 0.0
    for line in items:
        line_total_value = _number(line.get("line_amount", line.get("line_total")))
        line_unit_value = _number(line.get("unit_price", line.get("price")))
        line_quantity_value = _number(line.get("quantity"))
        known_value = line_total_value if line_total_value is not None and line_total_value > 0 else (
            line_unit_value * line_quantity_value
            if line_unit_value is not None and line_quantity_value is not None and line_unit_value > 0 and line_quantity_value > 0
            else 0.0
        )
        total_known_value += known_value

    for index, line in enumerate(items):
        analysis = analyses_by_index.get(index)
        if analysis is None:
            product_name = str(line.get("product") or line.get("product_name") or line.get("description") or "").strip()
            analysis = next((entry for entry in product_analyses if str(entry.get("product") or "").strip() == product_name), None)
        if analysis is None:
            continue

        if analysis.get("invoice_unit_price") is None:
            analysis["invoice_unit_price"] = line.get("unit_price", line.get("price"))
        if analysis.get("invoice_line_total") is None:
            analysis["invoice_line_total"] = line.get("line_amount", line.get("line_total"))
        comparison = compare_product_market(analysis, invoice_currency)
        analysis["price_comparison"] = comparison
        market = analysis.get("market")
        if isinstance(market, dict):
            market = dict(market)
            market["price_comparison"] = comparison
            analysis["market"] = market
            # Keep the existing UI fields consistent with the canonical engine.
            market["market_statistics"] = comparison["market_statistics"]
            market["price_difference"] = comparison["difference_amount"]
            market["price_difference_percent"] = comparison["difference_percent"]
            market["price_alignment_score"] = comparison["price_alignment_score"]
            market["market_match_confidence"] = comparison["market_match_confidence"]
            market["usable_for_risk_calculation"] = comparison["is_comparable"]
            market["sources"] = comparison["accepted_sources"]
            existing_excluded = market.get("excluded_sources") if isinstance(market.get("excluded_sources"), list) else []
            merged_excluded = list(existing_excluded)
            seen_excluded = {(str(item.get("url") or ""), str(item.get("exclusion_reason") or item.get("reason") or "")) for item in existing_excluded if isinstance(item, dict)}
            for rejected in comparison["excluded_observations"]:
                rejected_key = (str(rejected.get("url") or ""), str(rejected.get("reason") or ""))
                if rejected_key in seen_excluded:
                    continue
                merged_excluded.append({
                    "title": rejected.get("title") or rejected.get("source") or "Excluded observation",
                    "source_name": rejected.get("source"),
                    "url": rejected.get("url"),
                    "price": rejected.get("price"),
                    "currency": rejected.get("currency"),
                    "availability": rejected.get("availability"),
                    "exclusion_reason": rejected.get("reason"),
                })
                seen_excluded.add(rejected_key)
            market["excluded_sources"] = merged_excluded
            quality = dict(market.get("market_quality") or {})
            quality["accepted_price_observations"] = comparison["accepted_source_count"]
            quality["independent_domains"] = comparison["independent_domain_count"]
            quality["minimum_independent_domains_for_risk"] = MIN_INDEPENDENT_DOMAINS
            market["market_quality"] = quality
            diagnostics = dict(market.get("search_diagnostics") or {})
            diagnostics["independent_source_count"] = comparison["independent_domain_count"]
            diagnostics["unique_source_domains"] = comparison["independent_domain_count"]
            market["search_diagnostics"] = diagnostics
            analysis["source_count"] = comparison["accepted_source_count"]
            analysis["independent_source_count"] = comparison["independent_domain_count"]
        analyses_by_index[index] = analysis
        comparisons.append(comparison)

        line_total = _number(analysis.get("invoice_line_total"))
        unit = _number(analysis.get("invoice_unit_price"))
        quantity = _number(analysis.get("quantity"))
        value = line_total if line_total is not None and line_total > 0 else (
            unit * quantity if unit is not None and quantity is not None and unit > 0 and quantity > 0 else 1.0
        )
        if comparison["is_comparable"]:
            comparable_value += value
            weighted.append((float(comparison["price_risk_points"] or 0.0), value))

    # Persist normalized spend weights on each product comparison.
    comparable_weight_total = sum(weight for _, weight in weighted)
    if comparable_weight_total > 0:
        for comparison in comparisons:
            if comparison.get("is_comparable"):
                matching_entry = next((entry for entry in product_analyses if entry.get("line_index") == comparison.get("line_index")), None)
                line_value = _number(matching_entry.get("invoice_line_total")) if matching_entry else None
                unit_value = _number(matching_entry.get("invoice_unit_price")) if matching_entry else None
                quantity_value = _number(matching_entry.get("quantity")) if matching_entry else None
                value = line_value if line_value is not None and line_value > 0 else (
                    unit_value * quantity_value if unit_value is not None and quantity_value is not None and unit_value > 0 and quantity_value > 0 else 1.0
                )
                comparison["spend_weight"] = round(value / comparable_weight_total, 6)
                if matching_entry and isinstance(matching_entry.get("price_comparison"), dict):
                    matching_entry["price_comparison"]["spend_weight"] = comparison["spend_weight"]
                if matching_entry and isinstance(matching_entry.get("market"), dict) and isinstance(matching_entry["market"].get("price_comparison"), dict):
                    matching_entry["market"]["price_comparison"]["spend_weight"] = comparison["spend_weight"]

    # Persist updated entries in their original sequence.
    for position, entry in enumerate(product_analyses):
        index = entry.get("line_index")
        if index is not None and str(index).isdigit() and int(index) in analyses_by_index:
            product_analyses[position] = analyses_by_index[int(index)]

    aggregate_risk = None
    if weighted:
        total_weight = sum(weight for _, weight in weighted)
        aggregate_risk = round(sum(points * weight for points, weight in weighted) / total_weight, 2) if total_weight > 0 else None

    summary_status = "assessed" if comparisons and any(item["is_comparable"] for item in comparisons) else (
        "insufficient_evidence" if comparisons else "not_available"
    )
    result["product_analyses"] = product_analyses
    result["price_comparison"] = {
        "status": summary_status,
        "total_product_lines": len(items),
        "analyzed_product_lines": len(comparisons),
        "comparable_product_lines": sum(1 for item in comparisons if item["is_comparable"]),
        "insufficient_evidence_product_lines": sum(1 for item in comparisons if not item["is_comparable"]),
        "comparable_value": round(comparable_value, 2),
        "known_line_value": round(total_known_value, 2),
        "value_coverage_percent": round((comparable_value / total_known_value) * 100.0, 2) if total_known_value > 0 else None,
        "weighted_price_risk_points": aggregate_risk,
        "risk_points_cap": MAX_PRICE_RISK_POINTS,
        "weighting_method": "Spend-weighted average of comparable product-line price-risk points. It is not an invoice-wide product-price average.",
        "products": comparisons,
    }
    # Keep legacy single-product flags useful, but do not invent a multi-SKU
    # invoice-wide benchmark.
    if len(comparisons) == 1:
        one = comparisons[0]
        result["market_statistics"] = one["market_statistics"]
        result["price_difference"] = one["difference_amount"]
        result["price_difference_percent"] = one["difference_percent"]
        result["price_alignment_score"] = one["price_alignment_score"]
        result["market_match_confidence"] = one["market_match_confidence"]
        result["usable_for_risk_calculation"] = one["is_comparable"]
    else:
        result["market_statistics"] = {"currency": None, "lowest": None, "highest": None, "average": None, "median": None}
        result["price_difference"] = None
        result["price_difference_percent"] = None
        result["usable_for_risk_calculation"] = False
    return result


__all__ = [
    "MIN_INDEPENDENT_DOMAINS",
    "compare_product_market",
    "enrich_market_analysis",
]

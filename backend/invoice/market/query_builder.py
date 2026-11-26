"""Product-specific query generation for free market discovery."""

from __future__ import annotations

import re


CST_DOMAINS = (
    "daraz.com.bd",
    "bikeshopbd.com.bd",
    "csttires.com.bd",
    "othoba.com",
    "sawaribd.com",
)
GENERAL_BD_RETAILERS = (
    "daraz.com.bd",
    "othoba.com",
)
ELECTRONICS_BD_RETAILERS = (
    "daraz.com.bd",
    "startech.com.bd",
    "ryans.com",
    "techlandbd.com",
    "ultratech.com.bd",
    "techmart.com.bd",
    "applegadgetsbd.com",
    "pcpartsbd.com",
    "pcbstore.com.bd",
    "skylandofficialbd.com",
    "othoba.com",
)


def is_cst_product(product: str) -> bool:
    value = re.sub(r"[^a-z0-9.]+", " ", (product or "").lower())
    return (
        "cst" in value
        or ("jack rabbit" in value and bool(re.search(r"\bc1747n?\b", value)))
    )


def _is_electronics_product(product: str) -> bool:
    value = (product or "").lower()
    keywords = (
        "keyboard", "mouse", "monitor", "laptop", "desktop", "ssd", "hdd",
        "ram", "gpu", "graphics card", "motherboard", "processor", "cpu",
        "phone", "smartphone", "tablet", "headphone", "earphone", "router",
        "switch", "mechanical", "gaming", "charger", "power supply",
    )
    return any(keyword in value for keyword in keywords)


def _model_tokens(product: str) -> list[str]:
    tokens = re.findall(r"\b[a-z0-9][a-z0-9]*(?:[-][a-z0-9]+)*\b", (product or "").lower())
    tokens = [
        token for token in tokens
        if re.search(r"[a-z]", token) and re.search(r"\d", token)
    ]
    seen: set[str] = set()
    result: list[str] = []
    for token in tokens:
        if token not in seen and len(token) >= 3:
            seen.add(token)
            result.append(token)
    return result[:4]


def _keyboard_variant_query(product: str, model_phrase: str) -> str:
    if not model_phrase or not re.search(r"\bkeyboards?\b", product, re.IGNORECASE):
        return ""

    terms = [model_phrase]
    layout = re.search(r"\b(\d{2,3})\s*(?:%|percent)(?!\w)", product, re.IGNORECASE)
    if layout:
        terms.append(f"{layout.group(1)}%")

    connectivity = re.search(r"\b(wired|wireless)\b", product, re.IGNORECASE)
    if connectivity:
        terms.append(connectivity.group(1).lower())

    if re.search(r"\bhot[\s-]*swap\b", product, re.IGNORECASE):
        terms.append("hot-swap")

    switch = re.search(
        r"\b(red|blue|brown|silver|yellow|white)\s+switch(?:es)?\b",
        product,
        re.IGNORECASE,
    )
    if switch:
        terms.extend((switch.group(1).lower(), "switch"))

    return " ".join(terms) if len(terms) > 1 else ""


def _dedupe(values: list[str], limit: int = 12) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for raw in values:
        value = re.sub(r"\s+", " ", str(raw or "")).strip()
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        output.append(value)
        if len(output) >= limit:
            break
    return output


def build_product_search_queries(vendor_name: str | None, product_description: str | None) -> list[str]:
    """Build a bounded query set without leaking one product family's queries into another."""

    vendor = re.sub(r"\s+", " ", str(vendor_name or "")).strip()
    product = re.sub(r"\s+", " ", str(product_description or "")).strip()
    if not product:
        return []

    models = _model_tokens(product)
    product_short = product[:180]
    model_phrase = " ".join(models[:2])
    brand_and_model = " ".join([part for part in (product.split(" ")[0], model_phrase) if part]).strip()
    keyboard_variant_query = _keyboard_variant_query(product, model_phrase)

    queries: list[str] = []
    # Exact product wording is retained for precision; model-focused queries
    # improve recall when retailer titles shorten descriptions from invoices.
    queries.append(f'"{product_short}" price Bangladesh')
    if model_phrase:
        queries.append(f'"{brand_and_model}" price Bangladesh')
        queries.append(f'{brand_and_model} BDT price Bangladesh')

    ryzen_match = re.search(
        r"\bamd\s+ryzen\s+(?P<series>[3579])\s+(?P<sku>\d{4}[a-z]{0,2})\b",
        product,
        re.IGNORECASE,
    )
    if ryzen_match:
        series = ryzen_match.group("series")
        sku = ryzen_match.group("sku").upper()
        queries.extend([
            f"AMD Ryzen {series} {sku} processor Bangladesh price",
            f"Ryzen {series} {sku} 8 Core Radeon Graphics",
            f"AMD {sku} processor price in Bangladesh",
            f"Ryzen {series} {sku} Star Tech",
            f"Ryzen {series} {sku} Ryans",
            f"Ryzen {series} {sku} TechLand",
        ])

    if is_cst_product(product):
        queries.extend([
            f'site:daraz.com.bd "{product_short}" price',
            'site:bikeshopbd.com.bd "CST Jack Rabbit" "C1747" price',
            'site:csttires.com.bd "CST Jack Rabbit" "C1747" price',
            'site:othoba.com "CST Jack Rabbit" "C1747" price',
            'site:sawaribd.com "CST Jack Rabbit" "C1747" price',
        ])
    else:
        retailer_domains = (
            ELECTRONICS_BD_RETAILERS
            if _is_electronics_product(product)
            else GENERAL_BD_RETAILERS
        )
        for domain in retailer_domains:
            phrase = keyboard_variant_query or model_phrase or product_short
            queries.append(f'site:{domain} "{phrase}" price')

    if vendor:
        queries.append(f'"{vendor}" "{product_short}" price')

    # Avoid sending a retailer/vendor string without product identity; that
    # query tends to generate unrelated store pages rather than comparables.
    return _dedupe(queries, limit=12)

"""Product-specific query generation for free market discovery."""

from __future__ import annotations

import re

def is_cst_product(product: str) -> bool:
    value = re.sub(r"[^a-z0-9.]+", " ", (product or "").lower())
    return (
        "cst" in value
        or ("jack rabbit" in value and bool(re.search(r"\bc1747n?\b", value)))
    )


def _is_electronics_product(product: str) -> bool:
    value = (product or "").lower()
    if re.search(r"\b(?:psu|power\s+suppl(?:y|ies))\b", value):
        return True
    if re.search(
        r"\b(?:computer|pc)\s+cases?\b|\bchassis\b|\b(?:full|mid|mini|micro)[\s-]?tower\b",
        value,
    ):
        return True
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


def _power_supply_query_phrase(product: str, brand_and_model: str) -> str:
    if not re.search(r"\b(?:psu|power\s+suppl(?:y|ies))\b", product, re.IGNORECASE):
        return ""
    model_terms = [
        term for term in brand_and_model.split()
        if not re.fullmatch(r"\d{3,4}w", term, re.IGNORECASE)
    ]
    terms = [" ".join(model_terms)]
    wattage = re.search(r"\b\d{3,4}\s*(?:w|watts?)\b", product, re.IGNORECASE)
    if wattage:
        terms.append(re.sub(r"\s+", "", wattage.group(0)).upper())
    efficiency = re.search(
        r"\b80\s*(?:\+\s*|plus\s*)?(?:white|bronze|silver|gold|platinum|titanium)\b",
        product,
        re.IGNORECASE,
    )
    if efficiency:
        terms.append(re.sub(r"\s+", " ", efficiency.group(0)))
    modularity = re.search(r"\b(?:fully|semi|non)[\s-]*modular\b", product, re.IGNORECASE)
    if modularity:
        terms.append(re.sub(r"[\s-]+", "-", modularity.group(0).lower()))
    terms.append("power supply")
    return " ".join(term for term in terms if term)


def _computer_case_query_phrase(product: str) -> str:
    if not re.search(
        r"\b(?:(?:computer|pc)\s+)?cases?\b|\bchassis\b|\b(?:full|mid|mini|micro)[\s-]?tower\b",
        product,
        re.IGNORECASE,
    ):
        return ""
    terms = [product.split()[0]]
    model = re.search(r"\b([a-z][a-z0-9]+)\s+([a-z]?\d+[a-z0-9-]*)\b", product, re.IGNORECASE)
    if model:
        terms.extend((model.group(1), model.group(2)))
    form_factor = re.search(
        r"\b(?:e[\s-]?atx|micro[\s-]?atx|m[\s-]?atx|mini[\s-]?itx|itx|atx)\b",
        product,
        re.IGNORECASE,
    )
    if form_factor:
        terms.append(re.sub(r"[\s-]+", "", form_factor.group(0)).upper())
    tower = re.search(r"\b(?:full|mid|mini|micro)[\s-]?tower\b", product, re.IGNORECASE)
    if tower:
        terms.append(re.sub(r"[\s-]+", " ", tower.group(0)).lower())
    terms.append("computer case")
    return " ".join(terms)


def _memory_query_phrase(product: str) -> str:
    if not re.search(r"\b(?:ram|memory|ddr[345])\b", product, re.IGNORECASE):
        return ""
    return product[:160]


def _is_specification_token(token: str) -> bool:
    value = token.casefold()
    return bool(re.fullmatch(
        r"(?:ddr[345]|(?:\d+(?:\.\d+)?)(?:gb|tb|mb|mhz|ghz|hz|w|wh|mah|dpi|ms|mm|cm|inch|in)|"
        r"cl\d+|am\d+|m[.-]?atx|e[.-]?atx|atx|itx|pcie\d*|nvme|sata|m\.2|"
        r"\d{2,3}%|gen\d+)",
        value,
        re.IGNORECASE,
    ))


def _model_phrase(product: str) -> str:
    tokens = list(re.finditer(r"[A-Za-z0-9]+(?:[-.][A-Za-z0-9]+)*", product))
    model_index = next(
        (
            index
            for index, match in enumerate(tokens)
            if len(match.group(0)) >= 2
            and re.search(r"[a-z]", match.group(0), re.IGNORECASE)
            and re.search(r"\d", match.group(0))
            and not _is_specification_token(match.group(0))
        ),
        None,
    )
    if model_index is None:
        category = re.search(
            r"\b(?:motherboards?|mainboards?|cases?|casing|chassis|"
            r"keyboards?|mice|mouse|monitors?|displays?|ram|memory|"
            r"ssds?|hdds?|storage|processors?|cpus?|power\s+suppl(?:y|ies)|psu)\b",
            product,
            re.IGNORECASE,
        )
        name = product[:category.start()] if category else product
        family_tokens = [
            match.group(0)
            for match in re.finditer(r"[A-Za-z][A-Za-z0-9-]*", name)
            if not _is_specification_token(match.group(0))
        ]
        return " ".join(family_tokens[:3]) or product.split()[0]

    before = [
        match.group(0)
        for match in tokens[:model_index]
        if match.group(0).casefold() not in {"series", "model", "the"}
        and len(match.group(0)) > 1
        and not _is_specification_token(match.group(0))
    ][-2:]
    phrase_tokens = before + [tokens[model_index].group(0)]

    suffix_words = {"pro", "lite", "plus", "max", "mini", "ultra"}
    for match in tokens[model_index + 1:]:
        token = match.group(0)
        if _is_specification_token(token) or token.casefold() in {
            "motherboard", "mainboard", "case", "casing", "chassis", "gaming",
            "keyboard", "mouse", "monitor", "ram", "memory", "ssd", "hdd",
            "processor", "cpu", "power", "supply", "mid", "tower",
        }:
            break
        if token.casefold() in suffix_words or (
            re.search(r"[a-z]", token, re.IGNORECASE)
            and re.search(r"\d", token)
        ):
            phrase_tokens.append(token)
            if len(phrase_tokens) >= len(before) + 3:
                break
        else:
            break

    return " ".join(phrase_tokens)


def _category_synonyms(product: str) -> str:
    categories = (
        (r"\b(?:psu|power\s+suppl(?:y|ies))\b", '(PSU OR "power supply")'),
        (r"\b(?:motherboard|mainboard)\b", "(motherboard OR mainboard)"),
        (r"\b(?:computer|pc)\s+cases?\b|\b(?:casing|chassis)\b|\b(?:full|mid|mini|micro)[\s-]?tower\b",
         "(case OR casing OR chassis)"),
        (r"\b(?:ram|memory|ddr[345])\b", "(RAM OR memory)"),
        (r"\b(?:ssd|hdd|storage|nvme)\b", '(SSD OR "solid state drive")'),
        (r"\b(?:processor|cpu|ryzen)\b", "(processor OR CPU)"),
        (r"\bkeyboard\b", '(keyboard OR "mechanical keyboard")'),
        (r"\bmouse\b", '(mouse OR "gaming mouse")'),
        (r"\b(?:monitor|display)\b", "(monitor OR display)"),
        (r"\b(?:tire|tyre)\b", "(tire OR tyre)"),
    )
    for pattern, phrase in categories:
        if re.search(pattern, product, re.IGNORECASE):
            return phrase
    return ""


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
    """Build one concise model-and-category query for the configured provider."""

    product = re.sub(r"\s+", " ", str(product_description or "")).strip()
    if not product:
        return []

    ryzen_match = re.search(
        r"\bamd\s+ryzen\s+(?P<series>[3579])\s+(?P<sku>\d{4}[a-z]{0,2})\b",
        product,
        re.IGNORECASE,
    )

    if ryzen_match:
        series = ryzen_match.group("series")
        sku = ryzen_match.group("sku").upper()
        model_phrase = f"AMD Ryzen {series} {sku}"
    else:
        model_phrase = _model_phrase(product)

    query_parts = [f'"{model_phrase}"']
    if re.search(r"\b(?:tray|oem)\b", product, re.IGNORECASE):
        query_parts.append('"Tray Box"')
    if re.search(r"\bmemory\b|\bram\b|\bddr[345]\b", product, re.IGNORECASE):
        generation = re.search(r"\bDDR[345]\b", product, re.IGNORECASE)
        if generation:
            query_parts.append(generation.group(0).upper())
    category = _category_synonyms(product)
    if category:
        query_parts.append(category)
    query_parts.extend(("price", "Bangladesh"))

    return [" ".join(query_parts)]

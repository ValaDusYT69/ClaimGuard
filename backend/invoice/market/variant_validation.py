"""Strict product/edition validation for market-price observations.

The AJ199 profile below is a user-confirmed market-only identity for the
current ClaimGuard invoice: standard AJ199 Carbon Fiber Tri-mode edition.
It does not rewrite OCR text or invoice fields. Other editions are retained
as separate comparison context and never enter this edition's benchmark.
"""
from __future__ import annotations

import re
from typing import Any

_MODEL_RE = re.compile(r"\b[a-z0-9][a-z0-9-]*\b", re.I)

# This is deliberately limited to the AJ199 family. Explicit MAX/PRO/Dual-mode
# target descriptions take precedence and do not receive this override.
_USER_CONFIRMED_OVERRIDES: tuple[dict[str, Any], ...] = (
    {
        "brand": "ajazz",
        "model": "aj199",
        "profile": "carbon_fiber_tri_mode",
        "require": {"carbon_fiber", "tri_mode"},
        "label": "AJAZZ AJ199 Carbon Fiber Tri-mode (standard edition)",
        "notice": (
            "Market comparison uses the user-confirmed standard AJ199 Carbon Fiber "
            "Tri-mode edition. AJ199 MAX/PAW3395 and other editions are shown "
            "separately and are not included in this benchmark. The original OCR "
            "description remains unchanged."
        ),
    },
)

_FEATURE_PATTERNS: dict[str, re.Pattern[str]] = {
    "motherboard_form_factor_atx": re.compile(r"(?<![a-z0-9-])atx(?![a-z0-9])", re.I),
    "motherboard_form_factor_matx": re.compile(r"\b(?:micro[\s-]*atx|m[\s.-]*atx)\b", re.I),
    "motherboard_form_factor_itx": re.compile(r"\b(?:mini[\s-]*itx|itx)\b", re.I),
    "cpu_tray": re.compile(r"\b(?:tray|oem)\b", re.I),
    "cpu_retail_box": re.compile(r"\b(?:retail\s+box(?:ed)?|boxed\s+(?:cpu|processor))\b", re.I),
    "tri_mode": re.compile(r"\b(?:tri[\s-]*mode|3[\s-]*mode|three[\s-]*mode)\b", re.I),
    "dual_mode": re.compile(r"\b(?:dual[\s-]*mode|2[\s-]*mode|two[\s-]*mode)\b", re.I),
    "wired": re.compile(r"\bwired\b", re.I),
    "wireless": re.compile(r"\bwireless\b", re.I),
    "rgb": re.compile(r"\brgb\b", re.I),
    "2_4ghz": re.compile(r"\b2\s*[.]?\s*4\s*(?:ghz|g)\b", re.I),
    "bluetooth": re.compile(r"\bbluetooth\b|\bbt\s*(?:4|5|5\.\d)\b", re.I),
    "carbon_fiber": re.compile(r"\bcarbon[\s-]*fiber\b|\bcfrp\b", re.I),
    "aluminum": re.compile(r"\balumini?um\b", re.I),
    "stainless_steel": re.compile(r"\bstainless[\s-]*steel\b", re.I),
    "titanium": re.compile(r"\btitanium\b", re.I),
    "plastic": re.compile(r"\bplastic\b", re.I),
    "leather": re.compile(r"\bleather\b", re.I),
    "wood": re.compile(r"\bwood(?:en)?\b", re.I),
    "ceramic": re.compile(r"\bceramic\b", re.I),
    "glass": re.compile(r"\bglass\b", re.I),
    "sensor_3311": re.compile(r"\b(?:pixart\s*)?paw?\s*3311\b|\b3311\s*(?:sensor)?\b", re.I),
    "sensor_3395": re.compile(r"\b(?:pixart\s*)?paw?\s*3395\b|\b3395\s*(?:sensor)?\b", re.I),
    "dpi_26k": re.compile(r"\b(?:26[, ]?000|26000)\s*dpi\b", re.I),
    "battery_800": re.compile(r"\b800\s*m?ah\b", re.I),
    "battery_500": re.compile(r"\b500\s*m?ah\b", re.I),
    "aj199_max": re.compile(r"\baj\s*199\s*max\b", re.I),
    "aj199_pro": re.compile(r"\baj\s*199\s*pro\b", re.I),
    "switch_red": re.compile(r"\bred\s+switch(?:es)?\b", re.I),
    "switch_blue": re.compile(r"\bblue\s+switch(?:es)?\b", re.I),
    "switch_brown": re.compile(r"\bbrown\s+switch(?:es)?\b", re.I),
    "switch_silver": re.compile(r"\bsilver\s+switch(?:es)?\b", re.I),
    "switch_yellow": re.compile(r"\byellow\s+switch(?:es)?\b", re.I),
    "switch_white": re.compile(r"\bwhite\s+switch(?:es)?\b", re.I),
    "hot_swap": re.compile(r"\bhot[\s-]*swap\b", re.I),
    "layout_75": re.compile(r"\b75\s*%(?!\d)|\b75\s*percent\b", re.I),
    "not_hot_swap": re.compile(r"\bnon[\s-]*hot[\s-]*swap\b|\bnot hot[\s-]*swap\b", re.I),
}

_SWITCH_FEATURES = {
    "switch_red", "switch_blue", "switch_brown", "switch_silver",
    "switch_yellow", "switch_white",
}

_CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("keyboard", re.compile(r"\bkeyboards?\b", re.I)),
    ("mouse", re.compile(r"\b(?:mouse|mice)\b", re.I)),
    ("monitor", re.compile(r"\b(?:monitors?|displays?)\b", re.I)),
    ("power_supply", re.compile(r"\b(?:power\s+suppl(?:y|ies)|psu)\b", re.I)),
    ("computer_case", re.compile(
        r"\b(?:(?:computer|pc)\s+)?cases?\b|\bchassis\b|\b(?:full|mid|mini|micro)[\s-]?tower\b",
        re.I,
    )),
    ("gpu", re.compile(r"\b(?:gpu|graphics cards?|video cards?)\b", re.I)),
    ("cpu", re.compile(r"\b(?:cpu|processors?)\b", re.I)),
    ("storage", re.compile(r"\b(?:ssd|hdd|nvme|storage drives?|flash drives?)\b", re.I)),
    ("memory", re.compile(r"\b(?:ram|memory modules?|ddr[345])\b", re.I)),
    ("motherboard", re.compile(r"\bmotherboards?\b", re.I)),
    ("laptop", re.compile(r"\blaptops?\b", re.I)),
    ("phone", re.compile(r"\b(?:phones?|smartphones?)\b", re.I)),
    ("headphones", re.compile(r"\b(?:headphones?|earphones?|headsets?)\b", re.I)),
    ("router", re.compile(r"\brouters?\b", re.I)),
    ("tire", re.compile(r"\b(?:tires?|tyres?)\b", re.I)),
    ("bicycle", re.compile(r"\b(?:bicycles?|bikes?)\b", re.I)),
)

_KNOWN_BRANDS = (
    "western digital", "teamgroup", "cooler master", "deepcool", "powercolor",
    "viewsonic", "redragon", "kingston", "transcend", "logitech", "gigabyte",
    "corsair", "keychron", "samsung", "razer", "fantech", "redragon", "a4tech",
    "royal kludge", "colorful", "crucial", "seagate", "sandisk", "philips",
    "lenovo", "apple", "asustek", "asus", "acer", "dell", "intel", "amd",
    "ajazz", "aula", "rapoo", "msi", "hp", "lg", "aoc", "sony", "jbl",
    "anker", "benq", "zotac", "sapphire", "lexar", "palit",
    "nvidia", "evga", "wd",
)

_NON_BRAND_PREFIXES = {
    "gaming", "mechanical", "wireless", "wired", "rgb", "backlit", "usb",
    "bluetooth", "portable", "professional", "desktop", "laptop", "computer",
    "keyboard", "mouse", "monitor", "display", "graphics", "card", "processor",
    "cpu", "gpu", "ssd", "hdd", "nvme", "memory", "ram", "headset", "headphone",
    "external", "internal", "smart", "curved", "ultrawide", "led", "ips",
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(
            f"{str(key).replace('_', ' ')} {_text(item)}"
            for key, item in value.items()
            if item is not None and item is not False
        )
    if isinstance(value, (list, tuple, set)):
        return " ".join(_text(item) for item in value)
    return str(value)


def source_evidence_text(source: dict[str, Any] | None) -> str:
    """Build product identity evidence only from fields returned for that source."""
    if not isinstance(source, dict):
        return ""
    fields = (
        "title", "search_title", "search_snippet", "snippet", "description",
        "product_name", "model", "sku", "mpn", "variant", "variant_name",
        "search_result_title", "search_result_snippet", "variant_evidence",
        "specifications", "attributes", "features",
    )
    return " ".join(_text(source.get(key)) for key in fields if source.get(key) is not None)


def _models(text: str) -> set[str]:
    return {
        match.group(0).casefold()
        for match in _MODEL_RE.finditer(text or "")
        if re.search(r"[a-z]", match.group(0), re.I)
        and re.search(r"\d", match.group(0))
    }


def has_conflicting_primary_model(product_description: str | None, candidate_title: str | None) -> bool:
    """Detect an explicit listing-title model that conflicts with the target."""
    target_models = _models(str(product_description or ""))
    title_models = _models(str(candidate_title or ""))
    return bool(target_models and title_models and not (target_models & title_models))


def _ryzen_models(text: str) -> set[str]:
    """Return Ryzen SKU tokens, including numeric-leading SKUs such as 5700G."""
    return {
        match.casefold()
        for match in re.findall(r"\b\d{4}[a-z]{0,2}\b", text or "", re.I)
    }


def _features(text: str) -> set[str]:
    value = text or ""
    features = {name for name, pattern in _FEATURE_PATTERNS.items() if pattern.search(value)}
    for match in re.finditer(r"\b(\d{3,4})\s*(?:w|watts?)\b", value, re.I):
        features.add(f"wattage_{int(match.group(1))}")
    for match in re.finditer(
        r"\b80\s*(?:\+\s*|plus\s*)?(white|bronze|silver|gold|platinum|titanium)\b",
        value,
        re.I,
    ):
        features.add(f"efficiency_80plus_{match.group(1).casefold()}")
    for match in re.finditer(r"\b(?:fully|semi|non)[\s-]*modular\b", value, re.I):
        features.add(f"modularity_{re.sub(r'[\s-]+', '_', match.group(0).casefold())}")
    for match in re.finditer(r"\bddr\s*([345])\b", value, re.I):
        features.add(f"memory_generation_ddr{match.group(1)}")
    for match in re.finditer(r"(?<![\d.])(\d{1,3})\s*(?:gb|g)\b", value, re.I):
        features.add(f"capacity_{int(match.group(1))}gb")
    for match in re.finditer(r"\b(\d{3,5})\s*(?:mhz|mt/s)\b", value, re.I):
        features.add(f"memory_speed_{int(match.group(1))}")
    for match in re.finditer(r"\bcl\s*(\d{1,2})\b", value, re.I):
        features.add(f"memory_latency_{int(match.group(1))}")
    for family, pattern in (
        ("delta", r"\bdelta\b"),
        ("tforce", r"\bt[\s-]*force\b"),
        ("tcreate", r"\bt[\s-]*create\b"),
        ("elite", r"\belite\b"),
        ("vulcan", r"\bvulcan\b"),
        ("dark", r"\bdark\b"),
    ):
        if re.search(pattern, value, re.I):
            features.add(f"memory_family_{family}")

    form_factor = re.search(
        r"\b(e[\s-]?atx|micro[\s-]?atx|m[\s-]?atx|mini[\s-]?itx|itx|atx)\b",
        value,
        re.I,
    )
    if form_factor:
        normalized = re.sub(r"[\s-]+", "", form_factor.group(0).casefold())
        features.add(f"case_form_factor_{normalized}")
    tower = re.search(r"\b(full|mid|mini|micro)[\s-]?tower\b", value, re.I)
    if tower:
        features.add(f"case_tower_{tower.group(1).casefold()}_tower")
    return features


def _category(text: str) -> str | None:
    matches = [name for name, pattern in _CATEGORY_PATTERNS if pattern.search(text or "")]
    return matches[0] if len(set(matches)) == 1 else None


def _known_brand(text: str) -> str | None:
    lower = (text or "").casefold()
    for brand in sorted(set(_KNOWN_BRANDS), key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(brand)}(?![a-z0-9])", lower):
            return brand
    return None


def _brand(text: str) -> str | None:
    known = _known_brand(text)
    if known:
        return known
    lower = (text or "").casefold()
    model_tokens = _models(text or "")
    for match in _MODEL_RE.finditer(text or ""):
        if match.group(0).casefold() not in model_tokens:
            continue
        prefix_tokens = re.findall(r"[a-z][a-z0-9-]*", lower[:match.start()])
        brand_tokens = [
            token for token in prefix_tokens
            if token not in _NON_BRAND_PREFIXES
        ]
        if brand_tokens:
            return brand_tokens[0]
        break
    return None


def _has_explicit_aj199_other_edition(text: str) -> bool:
    return bool(re.search(r"\baj\s*199\s*(?:max|pro)\b", text or "", re.I))


def _override_for(product: str) -> dict[str, Any] | None:
    value = product or ""
    lower = value.casefold()
    models = _models(lower)
    if "aj199" not in models or "ajazz" not in lower:
        return None
    # Do not apply this current-invoice correction to another explicitly named SKU.
    if _has_explicit_aj199_other_edition(lower):
        return None
    features = _features(lower)
    if "dual_mode" in features or re.search(r"\bnon[\s-]*tri[\s-]*mode\b", lower):
        return None
    # The correction is tied to the exact generic invoice line that the user
    # identified as the Carbon Fiber Tri-mode edition, not to every AJ199 SKU.
    normalized = re.sub(r"[^a-z0-9]+", " ", lower).strip()
    if "ajazz aj199 tri mode gaming mouse" not in normalized:
        return None
    for override in _USER_CONFIRMED_OVERRIDES:
        if override["model"] in models and override["brand"] in lower:
            return override
    return None


def market_search_identity(product: str | None) -> str:
    """Apply the user's confirmed Carbon Fiber standard-edition identity for AJ199."""
    value = re.sub(r"\s+", " ", str(product or "")).strip()
    override = _override_for(value)
    if override:
        return "AJAZZ AJ199 Carbon Fiber Tri-mode Gaming Mouse"
    return value


def _separate_aj199_edition(candidate: str, candidate_features: set[str]) -> str | None:
    if _has_explicit_aj199_other_edition(candidate):
        return "AJ199 MAX/PRO Carbon Fiber Tri-mode edition"
    if "sensor_3395" in candidate_features or "dpi_26k" in candidate_features or "battery_800" in candidate_features:
        return "AJ199 PAW3395 / higher-spec edition (likely MAX; confirm model label)"
    return None


def assess_product_variant(
    product: str | None,
    candidate_text: str | None,
    *,
    category_evidence: str | None = None,
    brand_evidence: str | None = None,
    specification_evidence: str | None = None,
) -> dict[str, Any]:
    """Return verified/mismatch/unverified identity with explicit edition rules."""
    target = str(product or "").strip()
    candidate = str(candidate_text or "").strip()
    if not target or not candidate:
        return {"status": "unverified", "reason": "missing_identity_evidence", "confidence": 0.0}

    target_category = _category(target)
    candidate_category = _category(category_evidence) if category_evidence else _category(candidate)
    if target_category and candidate_category and target_category != candidate_category:
        return {
            "status": "mismatch",
            "reason": f"product_category_mismatch:{candidate_category}",
            "expected_category": target_category,
            "observed_category": candidate_category,
            "confidence": 0.0,
        }
    if target_category and not candidate_category:
        override = _override_for(target)
        candidate_features = _features(candidate)
        separate_edition = (
            _separate_aj199_edition(candidate, candidate_features)
            if override
            else None
        )
        if separate_edition:
            return {
                "status": "mismatch",
                "reason": f"separate_edition:{separate_edition}",
                "separate_edition": separate_edition,
                "expected_category": target_category,
                "confidence": 0.0,
            }
        return {
            "status": "unverified",
            "reason": "product_category_evidence_missing",
            "expected_category": target_category,
            "confidence": 0.0,
        }
    if not target_category:
        return {
            "status": "unverified",
            "reason": "invoice_product_category_not_identified",
            "confidence": 0.0,
        }

    target_brand = _brand(target)
    candidate_brand_text = str(brand_evidence or candidate)
    candidate_brand = _known_brand(candidate_brand_text)
    if (
        target_brand
        and candidate_brand is None
        and re.search(
            rf"(?<![a-z0-9]){re.escape(target_brand)}(?![a-z0-9])",
            candidate_brand_text.casefold(),
        )
    ):
        candidate_brand = target_brand
    if target_brand and candidate_brand and target_brand != candidate_brand:
        return {
            "status": "mismatch",
            "reason": f"brand_mismatch:{candidate_brand}",
            "expected_brand": target_brand,
            "observed_brand": candidate_brand,
            "confidence": 0.0,
        }
    if target_brand and not candidate_brand:
        return {
            "status": "unverified",
            "reason": "brand_evidence_missing",
            "expected_brand": target_brand,
            "confidence": 0.0,
        }

    target_models = _models(target)
    candidate_models = _models(candidate)
    if target_models and not (target_models & candidate_models):
        return {"status": "mismatch", "reason": "exact_model_not_found", "confidence": 0.0}

    target_ryzen_models = _ryzen_models(target)
    candidate_ryzen_models = _ryzen_models(candidate)
    if target_ryzen_models:
        target_sku = next(iter(target_ryzen_models))
        target_family = target_sku[:4]
        conflicting_skus = {
            sku for sku in candidate_ryzen_models
            if sku[:4] == target_family and sku != target_sku
        }
        if conflicting_skus:
            return {
                "status": "mismatch",
                "reason": "variant_mismatch:ryzen_sku:" + ",".join(sorted(conflicting_skus)),
                "confidence": 0.0,
            }

    # Existing CST-specific model/size/variant parsing remains authoritative.
    if "cst" in target.casefold() or "jack rabbit" in target.casefold() or "c1747" in target.casefold():
        return {"status": "verified", "reason": "existing_cst_exact_variant_rules", "confidence": 0.95}

    target_features = _features(target)
    candidate_features = _features(candidate)
    override = _override_for(target)

    if target_category == "motherboard" and specification_evidence is not None:
        target_form_factors = {
            feature for feature in target_features
            if feature.startswith("motherboard_form_factor_")
        }
        specification_form_factors = {
            feature for feature in _features(specification_evidence)
            if feature.startswith("motherboard_form_factor_")
        }
        if target_form_factors and not specification_form_factors:
            return {
                "status": "unverified",
                "reason": "required_specification_evidence_missing:motherboard_form_factor",
                "expected_variant": sorted(target_form_factors),
                "confidence": 0.0,
            }

    if (
        "ajazz" in target.casefold()
        and "aj199" in target_models
        and not override
        and not (target_features & {"carbon_fiber", "aj199_max", "aj199_pro"})
    ):
        return {
            "status": "unverified",
            "reason": "aj199_edition_not_explicitly_identified",
            "confidence": 0.0,
            "observed_variant": sorted(candidate_features),
        }

    if override:
        separate_edition = _separate_aj199_edition(candidate, candidate_features)
        if separate_edition:
            return {
                "status": "mismatch",
                "reason": f"separate_edition:{separate_edition}",
                "separate_edition": separate_edition,
                "expected_variant": override["label"],
                "observed_variant": sorted(candidate_features),
                "confidence": 0.0,
            }

        if "dual_mode" in candidate_features:
            return {
                "status": "mismatch",
                "reason": "variant_mismatch:dual_mode_vs_tri_mode",
                "expected_variant": override["label"],
                "observed_variant": sorted(candidate_features),
                "confidence": 0.0,
            }

        missing: list[str] = []
        if "carbon_fiber" not in candidate_features:
            missing.append("carbon_fiber")

        # Explicit Tri-mode is strongest; a page can also prove all three modes
        # directly with wired + 2.4GHz + Bluetooth specifications.
        has_three_modes = (
            "tri_mode" in candidate_features
            or {"wired", "2_4ghz", "bluetooth"}.issubset(candidate_features)
        )
        if not has_three_modes:
            missing.append("tri_mode_connectivity_evidence")

        if missing:
            return {
                "status": "unverified",
                "reason": "required_carbon_fiber_tri_mode_evidence_missing:" + ",".join(missing),
                "expected_variant": override["label"],
                "observed_variant": sorted(candidate_features),
                "confidence": 0.0,
            }

        return {
            "status": "verified",
            "reason": "user_confirmed_standard_aj199_carbon_fiber_tri_mode",
            "expected_variant": override["label"],
            "observed_variant": sorted(candidate_features),
            "confidence": 0.98 if "ajazz" in candidate.casefold() else 0.90,
        }

    # Generic material SKU attributes remain hard requirements.
    critical_features = {
        "tri_mode", "dual_mode", "wired", "wireless", "2_4ghz", "bluetooth", "rgb",
        "carbon_fiber", "sensor_3311", "sensor_3395", "aj199_max", "aj199_pro",
        "hot_swap", "layout_75", "aluminum", "stainless_steel", "titanium",
        "plastic", "leather", "wood", "ceramic", "glass",
    } | _SWITCH_FEATURES
    required = target_features & critical_features
    if target_category == "power_supply":
        required |= {
            feature for feature in target_features
            if feature.startswith(("wattage_", "efficiency_80plus_", "modularity_"))
        }
    elif target_category == "computer_case":
        required |= {
            feature for feature in target_features
            if feature.startswith(("case_form_factor_", "case_tower_"))
        }
    elif target_category == "memory":
        required |= {
            feature for feature in target_features
            if feature.startswith((
                "capacity_", "memory_generation_", "memory_speed_",
                "memory_latency_", "memory_family_",
            ))
        }
    elif target_category == "storage":
        required |= {feature for feature in target_features if feature.startswith("capacity_")}
    elif target_category == "motherboard":
        required |= {
            feature for feature in target_features
            if feature.startswith("motherboard_form_factor_")
        }
    elif target_category == "cpu":
        required |= target_features & {"cpu_tray", "cpu_retail_box"}
    if required:
        conflicts: set[str] = set()
        if "aj199_max" in required and "aj199_max" not in candidate_features:
            conflicts.add("aj199_max_edition_not_confirmed")
        if "aj199_pro" in required and "aj199_pro" not in candidate_features:
            conflicts.add("aj199_pro_edition_not_confirmed")
        if "aj199_max" not in required and "aj199_max" in candidate_features:
            conflicts.add("separate_aj199_max_edition")
        if "aj199_pro" not in required and "aj199_pro" in candidate_features:
            conflicts.add("separate_aj199_pro_edition")
        if "tri_mode" in required and "dual_mode" in candidate_features:
            conflicts.add("dual_mode")
        if "dual_mode" in required and "tri_mode" in candidate_features:
            conflicts.add("tri_mode")
        if "wired" in required and "wireless" in candidate_features:
            conflicts.add("wireless")
        if "wireless" in required and "wired" in candidate_features:
            conflicts.add("wired")
        if "hot_swap" in required and "not_hot_swap" in candidate_features:
            conflicts.add("not_hot_swap")
        if "cpu_tray" in required and "cpu_retail_box" in candidate_features:
            conflicts.add("cpu_package_retail_box")
        if "cpu_retail_box" in required and "cpu_tray" in candidate_features:
            conflicts.add("cpu_package_tray")
        for switch in _SWITCH_FEATURES:
            if switch in required:
                conflicts.update((candidate_features & _SWITCH_FEATURES) - {switch})
        for feature in ("sensor_3311", "sensor_3395"):
            if feature in required and (candidate_features & {"sensor_3311", "sensor_3395"}) - {feature}:
                conflicts.update((candidate_features & {"sensor_3311", "sensor_3395"}) - {feature})
        for prefix, label in (
            ("wattage_", "wattage"),
            ("efficiency_80plus_", "efficiency"),
            ("modularity_", "modularity"),
            ("case_form_factor_", "case_form_factor"),
            ("case_tower_", "case_tower"),
            ("capacity_", "capacity"),
            ("memory_generation_", "memory_generation"),
            ("memory_speed_", "memory_speed"),
            ("memory_latency_", "memory_latency"),
            ("memory_family_", "memory_family"),
            ("motherboard_form_factor_", "motherboard_form_factor"),
        ):
            target_values = {feature for feature in required if feature.startswith(prefix)}
            candidate_values = {feature for feature in candidate_features if feature.startswith(prefix)}
            if target_values and candidate_values - target_values:
                conflicts.add(f"{label}_mismatch")
        if conflicts:
            return {"status": "mismatch", "reason": "variant_mismatch:" + ",".join(sorted(conflicts)), "confidence": 0.0}
        missing_features = required - candidate_features
        if missing_features:
            return {"status": "unverified", "reason": "required_variant_evidence_missing:" + ",".join(sorted(missing_features)), "confidence": 0.0}
    elif candidate_features & {"tri_mode", "dual_mode"}:
        return {"status": "unverified", "reason": "candidate_has_unconfirmed_variant", "confidence": 0.0}

    if not target_models:
        return {
            "status": "unverified",
            "reason": "explicit_model_or_sku_evidence_missing",
            "confidence": 0.0,
        }

    if target_models:
        confidence = 0.85 if target_models & candidate_models else 0.0
    else:
        target_words = {word for word in re.findall(r"[a-z0-9]+", target.casefold()) if len(word) >= 3}
        candidate_words = set(re.findall(r"[a-z0-9]+", candidate.casefold()))
        overlap = len(target_words & candidate_words) / max(1, len(target_words))
        confidence = min(0.85, 0.60 + 0.25 * overlap)

    if "ajazz" in target.casefold() and "ajazz" not in candidate.casefold():
        confidence -= 0.10
    if required:
        confidence = min(0.99, confidence + 0.10)
    if confidence < 0.80:
        return {"status": "unverified", "reason": "identity_confidence_below_threshold", "confidence": round(max(0.0, confidence), 2)}
    return {"status": "verified", "reason": "exact_model_and_variant_evidence", "confidence": round(confidence, 2)}


def market_identity_metadata(product: str | None) -> dict[str, str] | None:
    value = str(product or "").strip()
    override = _override_for(value)
    if not override:
        return None
    return {
        "label": override["label"],
        "notice": override["notice"],
        "override": override["profile"],
    }


def effective_search_query(product: str | None) -> str:
    """Return canonical search identity without mutating original invoice text."""
    return market_search_identity(product)


def classify_price_observation(source: dict[str, Any]) -> tuple[bool, str | None]:
    """Allow only positive, currency-backed, in-stock page-level observations."""
    try:
        price = float(source.get("price"))
    except (TypeError, ValueError):
        return False, "price_missing_or_invalid"
    if not (price > 0 and price < 1_000_000_000):
        return False, "price_out_of_range"
    currency = str(source.get("currency") or "").strip().upper()
    if not currency or len(currency) != 3:
        return False, "currency_missing_or_invalid"
    availability = str(source.get("availability") or "").casefold().replace("-", "_").replace(" ", "_")
    if availability in {"out_of_stock", "sold_out", "unavailable", "not_available"}:
        return False, "out_of_stock"
    price_source = str(source.get("price_source") or "").casefold()
    verified_page_sources = {
        "page_html", "local_product_context", "structured_product_page",
        "schema_org_product_offer", "official_catalog_product_context",
        "official_catalog_product_block", "variant_specific_product_context",
    }
    if price_source not in verified_page_sources:
        return False, "search_snippet_only_not_page_verified" if "search" in price_source or "snippet" in price_source else "price_page_evidence_missing"
    return True, None


def is_statistical_price_outlier(prices: list[float], candidate: float) -> bool:
    """Conservative log-MAD outlier gate; only activates with >=5 observations."""
    import math
    if len(prices) < 5 or candidate <= 0:
        return False
    values = [math.log(value) for value in prices if value > 0]
    if len(values) < 5:
        return False
    median = sorted(values)[len(values) // 2]
    deviations = sorted(abs(value - median) for value in values)
    mad = deviations[len(deviations) // 2]
    if mad <= 1e-9:
        return False
    modified_z = 0.6745 * abs(math.log(candidate) - median) / mad
    return modified_z > 3.5

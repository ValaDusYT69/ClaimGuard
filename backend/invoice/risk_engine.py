"""
ClaimGuard Risk & Anomaly Engine
--------------------------------
Deterministic rules + optional lightweight ML/statistical scoring.

Design goals:
- Never invent evidence or numbers.
- Only use market price evidence when market_analysis explicitly says it is
  usable for risk calculation.
- Keep deterministic anomaly rules explainable.
- Use an optional IsolationForest model when scikit-learn is installed and
  there are enough historical records. Otherwise return a clearly documented
  ML-unavailable/insufficient-data state.
- Return a stable JSON-serializable structure for the FastAPI layer and UI.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from math import isfinite
from statistics import mean, pstdev
from typing import Any
import re


# ============================================================
# CONFIGURATION
# ============================================================

MIN_HISTORICAL_FOR_ML = 5

PRICE_ANOMALY_START_PERCENT = 15.0
PRICE_ANOMALY_FULL_PERCENT = 50.0

QUANTITY_OVERAGE_START_PERCENT = 5.0
QUANTITY_OVERAGE_FULL_PERCENT = 50.0

VENDOR_SIMILARITY_THRESHOLD = 0.88
VENDOR_VARIATION_SCORE = 18.0

DUPLICATE_SCORE = 35.0

MAX_DETERMINISTIC_SCORE = 100.0

try:  # Optional dependency; the engine still works without it.
    from sklearn.ensemble import IsolationForest  # type: ignore
    _SKLEARN_AVAILABLE = True
except Exception:  # pragma: no cover - environment dependent
    IsolationForest = None  # type: ignore
    _SKLEARN_AVAILABLE = False


# ============================================================
# BASIC HELPERS
# ============================================================

def _safe_float(value: Any) -> float | None:
    """Return a finite float or None."""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(number):
        return None
    return number


def _safe_int(value: Any) -> int | None:
    """Return an integer-like value or None."""
    number = _safe_float(value)
    if number is None:
        return None
    return int(round(number))


def _normalize_text(value: Any) -> str:
    """Normalize human-readable text for conservative comparison."""
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _same_key(a: Any, b: Any) -> bool:
    return _normalize_text(a) == _normalize_text(b) and bool(_normalize_text(a))


def _similarity(a: Any, b: Any) -> float:
    left = _normalize_text(a)
    right = _normalize_text(b)
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return round(max(minimum, min(maximum, value)), 2)


def _severity_from_score(score: float) -> str:
    if score >= 25:
        return "high"
    if score >= 12:
        return "medium"
    return "low"


def _linear_score(
    magnitude_percent: float,
    start_percent: float,
    full_percent: float,
    max_score: float,
) -> float:
    if magnitude_percent <= start_percent:
        return 0.0
    span = max(full_percent - start_percent, 1.0)
    normalized = (magnitude_percent - start_percent) / span
    return _clamp(normalized * max_score, 0.0, max_score)


# ============================================================
# DATA EXTRACTION HELPERS
# ============================================================

def _invoice_data(invoice: dict[str, Any]) -> dict[str, Any]:
    data = invoice.get("extracted_data")
    return data if isinstance(data, dict) else {}


def _product_key(invoice: dict[str, Any]) -> str:
    data = _invoice_data(invoice)
    return _normalize_text(
        data.get("product_description")
        or data.get("product")
        or data.get("description")
    )


def _vendor_name(invoice: dict[str, Any]) -> str:
    data = _invoice_data(invoice)
    return str(
        data.get("vendor_name")
        or invoice.get("vendor_name")
        or ""
    ).strip()


def _tax_id(invoice: dict[str, Any]) -> str:
    data = _invoice_data(invoice)
    return str(
        data.get("tax_id")
        or invoice.get("tax_id")
        or ""
    ).strip()


def _invoice_number(invoice: dict[str, Any]) -> str:
    data = _invoice_data(invoice)
    return str(
        data.get("invoice_number")
        or invoice.get("invoice_number")
        or ""
    ).strip()


def _total_amount(invoice: dict[str, Any]) -> float | None:
    data = _invoice_data(invoice)
    return _safe_float(
        data.get("total_amount")
        if data.get("total_amount") is not None
        else data.get("total")
    )


def _quantity(invoice: dict[str, Any]) -> float | None:
    return _safe_float(_invoice_data(invoice).get("quantity"))


def _unit_price(invoice: dict[str, Any]) -> float | None:
    return _safe_float(_invoice_data(invoice).get("unit_price"))


# ============================================================
# HISTORICAL PRICE BASELINE
# ============================================================

def _historical_price_values(
    invoice: dict[str, Any],
    all_invoices: list[dict[str, Any]],
) -> list[float]:
    """Collect unit prices for the same vendor/product from prior invoices."""
    current_vendor = _vendor_name(invoice)
    current_product = _product_key(invoice)

    values: list[float] = []

    for other in all_invoices:
        if other.get("invoice_id") == invoice.get("invoice_id"):
            continue

        if current_vendor and _vendor_name(other):
            if not _same_key(current_vendor, _vendor_name(other)):
                # Permit equivalent vendor identity only when tax IDs agree.
                current_tax = _tax_id(invoice)
                other_tax = _tax_id(other)
                if not (current_tax and other_tax and _same_key(current_tax, other_tax)):
                    continue

        if current_product and _product_key(other):
            if _product_key(other) != current_product:
                similarity = _similarity(current_product, _product_key(other))
                if similarity < 0.90:
                    continue

        value = _unit_price(other)
        if value is not None and value > 0:
            values.append(value)

    return values


def _historical_baseline(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"count": 0, "average": None, "median": None, "stddev": None}

    ordered = sorted(values)
    count = len(ordered)
    if count % 2:
        median = ordered[count // 2]
    else:
        middle = count // 2
        median = (ordered[middle - 1] + ordered[middle]) / 2

    return {
        "count": count,
        "average": round(mean(ordered), 2),
        "median": round(median, 2),
        "stddev": round(pstdev(ordered), 2) if count > 1 else 0.0,
    }


# ============================================================
# DUPLICATE DETECTION
# ============================================================

def _find_possible_duplicate(
    invoice: dict[str, Any],
    all_invoices: list[dict[str, Any]],
) -> dict[str, Any] | None:
    current_number = _invoice_number(invoice)
    current_vendor = _vendor_name(invoice)
    current_total = _total_amount(invoice)

    if not current_number or not current_vendor or current_total is None:
        return None

    for other in all_invoices:
        if other.get("invoice_id") == invoice.get("invoice_id"):
            continue

        other_number = _invoice_number(other)
        other_vendor = _vendor_name(other)
        other_total = _total_amount(other)

        if not other_number or not other_vendor or other_total is None:
            continue

        if not _same_key(current_number, other_number):
            continue
        if not _same_key(current_vendor, other_vendor):
            continue
        if abs(current_total - other_total) > 0.01:
            continue

        return other

    return None


# ============================================================
# QUANTITY CHECK
# ============================================================

def _extract_po_context(
    invoice: dict[str, Any],
    purchase_order: dict[str, Any] | None,
) -> dict[str, Any]:
    """Accept explicit PO input first, then common embedded PO structures."""
    if isinstance(purchase_order, dict):
        return purchase_order

    for key in ("purchase_order", "po", "purchase_order_data"):
        candidate = invoice.get(key)
        if isinstance(candidate, dict):
            return candidate

    data = _invoice_data(invoice)
    for key in ("purchase_order", "po", "purchase_order_data"):
        candidate = data.get(key)
        if isinstance(candidate, dict):
            return candidate

    return {}


# ============================================================
# DETERMINISTIC ENGINE
# ============================================================

def run_deterministic_rules(
    invoice: dict[str, Any],
    all_invoices: list[dict[str, Any]] | None = None,
    market_analysis: dict[str, Any] | None = None,
    purchase_order: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run transparent, evidence-backed anomaly rules."""
    all_invoices = all_invoices or []
    market_analysis = market_analysis or {}

    anomalies: list[dict[str, Any]] = []
    score = 0.0

    evidence: dict[str, Any] = {}

    current_price = _unit_price(invoice)

    # --------------------------------------------------------
    # Market price anomaly
    # --------------------------------------------------------
    market_usable = bool(market_analysis.get("usable_for_risk_calculation"))
    market_average = _safe_float(
        (market_analysis.get("market_statistics") or {}).get("average")
    )

    if market_usable and current_price is not None and market_average and market_average > 0:
        difference_percent = ((current_price - market_average) / market_average) * 100.0
        evidence["market_price_difference_percent"] = round(difference_percent, 2)
        evidence["market_reference_average"] = round(market_average, 2)

        # Flag either direction only when the deviation is materially large.
        market_contribution = _linear_score(
            abs(difference_percent),
            PRICE_ANOMALY_START_PERCENT,
            PRICE_ANOMALY_FULL_PERCENT,
            30.0,
        )

        if market_contribution > 0:
            direction = "above" if difference_percent > 0 else "below"
            anomaly = {
                "anomaly_type": "market_price_anomaly",
                "severity": _severity_from_score(market_contribution),
                "score_contribution": round(market_contribution, 2),
                "message": (
                    f"Invoice unit price is {abs(difference_percent):.2f}% "
                    f"{direction} the observed market average."
                ),
                "evidence": {
                    "invoice_unit_price": round(current_price, 2),
                    "observed_market_average": round(market_average, 2),
                    "difference_percent": round(difference_percent, 2),
                },
            }
            anomalies.append(anomaly)
            score += market_contribution

    # --------------------------------------------------------
    # Historical price anomaly
    # --------------------------------------------------------
    historical_values = _historical_price_values(invoice, all_invoices)
    historical = _historical_baseline(historical_values)

    if current_price is not None and historical["average"]:
        historical_average = float(historical["average"])
        historical_difference = (
            (current_price - historical_average) / historical_average
        ) * 100.0

        evidence["historical_unit_price_count"] = historical["count"]
        evidence["historical_average"] = historical_average
        evidence["historical_difference_percent"] = round(historical_difference, 2)

        historical_contribution = _linear_score(
            abs(historical_difference),
            PRICE_ANOMALY_START_PERCENT,
            PRICE_ANOMALY_FULL_PERCENT,
            25.0,
        )

        # Avoid double-counting a small market deviation and a small historical deviation.
        if historical_contribution > 0:
            direction = "above" if historical_difference > 0 else "below"
            anomaly = {
                "anomaly_type": "historical_price_anomaly",
                "severity": _severity_from_score(historical_contribution),
                "score_contribution": round(historical_contribution, 2),
                "message": (
                    f"Invoice unit price is {abs(historical_difference):.2f}% "
                    f"{direction} the historical vendor/product average."
                ),
                "evidence": {
                    "invoice_unit_price": round(current_price, 2),
                    "historical_average": historical_average,
                    "historical_invoice_count": historical["count"],
                    "difference_percent": round(historical_difference, 2),
                },
            }
            anomalies.append(anomaly)
            score += historical_contribution

    # --------------------------------------------------------
    # Quantity mismatch
    # --------------------------------------------------------
    po = _extract_po_context(invoice, purchase_order)
    po_quantity = _safe_float(
        po.get("quantity")
        if po.get("quantity") is not None
        else po.get("ordered_quantity")
    )
    invoice_quantity = _quantity(invoice)

    if invoice_quantity is not None and po_quantity is not None and po_quantity > 0:
        quantity_difference = invoice_quantity - po_quantity
        quantity_difference_percent = (quantity_difference / po_quantity) * 100.0

        evidence["po_quantity"] = po_quantity
        evidence["invoice_quantity"] = invoice_quantity
        evidence["quantity_difference"] = quantity_difference
        evidence["quantity_difference_percent"] = round(quantity_difference_percent, 2)

        if quantity_difference > 0:
            quantity_contribution = _linear_score(
                quantity_difference_percent,
                QUANTITY_OVERAGE_START_PERCENT,
                QUANTITY_OVERAGE_FULL_PERCENT,
                25.0,
            )

            if quantity_contribution > 0:
                anomaly = {
                    "anomaly_type": "quantity_mismatch",
                    "severity": _severity_from_score(quantity_contribution),
                    "score_contribution": round(quantity_contribution, 2),
                    "message": (
                        f"Invoice quantity exceeds PO quantity by "
                        f"{quantity_difference:.0f} units "
                        f"({quantity_difference_percent:.2f}%)."
                    ),
                    "evidence": {
                        "po_quantity": po_quantity,
                        "invoice_quantity": invoice_quantity,
                        "difference_units": quantity_difference,
                        "difference_percent": round(quantity_difference_percent, 2),
                    },
                }
                anomalies.append(anomaly)
                score += quantity_contribution

    # --------------------------------------------------------
    # Vendor identity variation
    # --------------------------------------------------------
    current_vendor = _vendor_name(invoice)
    current_tax_id = _tax_id(invoice)

    if current_vendor and all_invoices:
        closest_match: tuple[float, dict[str, Any]] | None = None

        for other in all_invoices:
            if other.get("invoice_id") == invoice.get("invoice_id"):
                continue

            similarity = _similarity(current_vendor, _vendor_name(other))
            if similarity <= 0 or similarity >= 1.0:
                continue

            other_tax_id = _tax_id(other)
            same_tax = bool(current_tax_id and other_tax_id and _same_key(current_tax_id, other_tax_id))

            # Strongest signal: same tax ID but different spelling/name.
            if same_tax and similarity < 0.995:
                closest_match = (similarity, other)
                break

            if similarity >= VENDOR_SIMILARITY_THRESHOLD and (
                closest_match is None or similarity > closest_match[0]
            ):
                closest_match = (similarity, other)

        if closest_match:
            similarity, other = closest_match
            other_vendor = _vendor_name(other)
            variation_strength = _clamp((1.0 - similarity) * 100.0)
            contribution = min(
                VENDOR_VARIATION_SCORE,
                max(0.0, variation_strength / 12.0 * VENDOR_VARIATION_SCORE),
            )

            # Only flag meaningful variation.
            if contribution >= 4.0:
                anomaly = {
                    "anomaly_type": "vendor_identity_variation",
                    "severity": _severity_from_score(contribution),
                    "score_contribution": round(contribution, 2),
                    "message": (
                        "Vendor identity differs from a prior invoice record "
                        "for the same/closely matching vendor identity."
                    ),
                    "evidence": {
                        "current_vendor": current_vendor,
                        "historical_vendor": other_vendor,
                        "similarity": round(similarity, 4),
                        "same_tax_id": bool(
                            current_tax_id
                            and _tax_id(other)
                            and _same_key(current_tax_id, _tax_id(other))
                        ),
                    },
                }
                anomalies.append(anomaly)
                score += contribution

    # --------------------------------------------------------
    # Possible duplicate
    # --------------------------------------------------------
    duplicate = _find_possible_duplicate(invoice, all_invoices)
    if duplicate:
        anomaly = {
            "anomaly_type": "possible_duplicate",
            "severity": "high",
            "score_contribution": DUPLICATE_SCORE,
            "message": (
                "Another invoice has the same invoice number, vendor, "
                "and total amount."
            ),
            "evidence": {
                "duplicate_invoice_id": duplicate.get("invoice_id"),
                "invoice_number": _invoice_number(invoice),
                "vendor": _vendor_name(invoice),
                "total_amount": _total_amount(invoice),
            },
        }
        anomalies.append(anomaly)
        score += DUPLICATE_SCORE

    deterministic_score = _clamp(score, 0.0, MAX_DETERMINISTIC_SCORE)

    return {
        "score": deterministic_score,
        "anomalies": anomalies,
        "evidence": evidence,
        "historical_baseline": historical,
        "duplicate_invoice_id": duplicate.get("invoice_id") if duplicate else None,
    }


# ============================================================
# LIGHTWEIGHT ML / STATISTICAL MODEL
# ============================================================
# ============================================================
# LOCAL AI / ML ANOMALY MODEL
# ============================================================
#
# ClaimGuard uses a local unsupervised Isolation Forest model.
# The model learns the normal pattern from similar historical
# invoices and scores the current invoice for unusual behaviour.
#
# Important:
# - No fabricated training data is used.
# - No external AI API or secret key is required.
# - Deterministic evidence remains dominant in the final score.
# - The model is not activated until enough real historical
#   records are available.
# ============================================================

AI_MODEL_NAME = "IsolationForest"
AI_ENGINE_NAME = "ClaimGuard Local AI Anomaly Engine"
AI_ENGINE_VERSION = "1.0"
MIN_HISTORICAL_FOR_ML = 5


def _related_historical_invoices(
    invoice: dict[str, Any],
    all_invoices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Select conservative historical peers.

    Priority:
    1. Same vendor + same/very similar product.
    2. Same vendor when the product field is missing.
    3. Same/very similar product when vendor is missing.

    This avoids training the model on unrelated invoices.
    """
    current_vendor = _vendor_name(invoice)
    current_product = _product_key(invoice)

    peers: list[dict[str, Any]] = []

    for other in all_invoices:
        if other.get("invoice_id") == invoice.get("invoice_id"):
            continue

        other_vendor = _vendor_name(other)
        other_product = _product_key(other)

        vendor_match = (
            bool(current_vendor and other_vendor)
            and _same_key(current_vendor, other_vendor)
        )

        product_match = False
        if current_product and other_product:
            product_match = (
                current_product == other_product
                or _similarity(current_product, other_product) >= 0.90
            )

        if current_vendor and current_product:
            if vendor_match and product_match:
                peers.append(other)
                continue

        elif current_vendor:
            if vendor_match:
                peers.append(other)
                continue

        elif current_product:
            if product_match:
                peers.append(other)

    return peers


def _ml_feature_vector(
    invoice: dict[str, Any],
) -> list[float] | None:
    """
    Build numerically stable features for the local anomaly model.

    Log transformation reduces the effect of large currency/quantity
    scales while retaining ordering and relative differences.
    """
    price = _unit_price(invoice)
    quantity = _quantity(invoice)
    total = _total_amount(invoice)

    if price is None or price <= 0:
        return None

    qty_value = quantity if quantity is not None and quantity >= 0 else 0.0
    total_value = total if total is not None and total >= 0 else price

    total_per_unit = (
        total_value / quantity
        if quantity is not None and quantity > 0
        else price
    )

    return [
        float(__import__("math").log1p(max(price, 0.0))),
        float(__import__("math").log1p(max(qty_value, 0.0))),
        float(__import__("math").log1p(max(total_value, 0.0))),
        float(__import__("math").log1p(max(total_per_unit, 0.0))),
    ]


def _ml_reliability(training_rows: int) -> str:
    if training_rows >= 25:
        return "high"
    if training_rows >= 10:
        return "medium"
    return "limited"


def _ml_interpretation(score: float) -> str:
    if score >= 80:
        return "highly_unusual"
    if score >= 60:
        return "unusual"
    if score >= 40:
        return "slightly_unusual"
    return "within_pattern"


def run_ml_model(
    invoice: dict[str, Any],
    all_invoices: list[dict[str, Any]] | None = None,
    market_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Run ClaimGuard's local AI anomaly model.

    The output is intentionally transparent so the reviewer can see:
    model name, training size, feature set, model score, interpretation
    and reliability. No numbers are generated from unsupported evidence.
    """
    all_invoices = all_invoices or []
    market_analysis = market_analysis or {}

    peers = _related_historical_invoices(
        invoice=invoice,
        all_invoices=all_invoices,
    )

    training_rows: list[list[float]] = []

    for other in peers:
        vector = _ml_feature_vector(other)
        if vector is not None:
            training_rows.append(vector)

    current_vector = _ml_feature_vector(invoice)

    base_result = {
        "available": False,
        "engine": AI_ENGINE_NAME,
        "version": AI_ENGINE_VERSION,
        "model": AI_MODEL_NAME if _SKLEARN_AVAILABLE else None,
        "status": "not_scored",
        "score": 0.0,
        "interpretation": "not_scored",
        "training_rows": len(training_rows),
        "minimum_training_rows": MIN_HISTORICAL_FOR_ML,
        "reliability": _ml_reliability(len(training_rows)),
        "feature_names": [
            "log_unit_price",
            "log_quantity",
            "log_total_amount",
            "log_total_per_unit",
        ],
        "message": "",
    }

    if current_vector is None:
        base_result.update(
            {
                "status": "no_numeric_features",
                "message": (
                    "Local AI scoring was skipped because the invoice "
                    "does not contain a valid numeric unit price."
                ),
            }
        )
        return base_result

    if len(training_rows) < MIN_HISTORICAL_FOR_ML:
        base_result.update(
            {
                "status": "insufficient_training_data",
                "message": (
                    "Local AI is integrated and ready, but it needs at least "
                    f"{MIN_HISTORICAL_FOR_ML} real similar historical invoices. "
                    f"Only {len(training_rows)} matching records are currently available."
                ),
            }
        )
        return base_result

    if not _SKLEARN_AVAILABLE or IsolationForest is None:
        base_result.update(
            {
                "status": "dependency_unavailable",
                "message": (
                    "Local AI scoring requires scikit-learn. "
                    "Install the project requirements and restart the backend."
                ),
            }
        )
        return base_result

    try:
        model = IsolationForest(
            n_estimators=250,
            contamination="auto",
            random_state=42,
        )

        model.fit(training_rows)

        training_decisions = [
            float(
                model.decision_function(
                    [row]
                )[0]
            )
            for row in training_rows
        ]

        current_decision = float(
            model.decision_function(
                [current_vector]
            )[0]
        )

        # Lower IsolationForest decision values are more anomalous.
        # Convert the current value into a two-sided empirical tail score
        # relative to real training observations.
        training_anomaly_values = sorted(
            -value
            for value in training_decisions
        )

        current_anomaly_value = -current_decision

        rank = sum(
            1
            for value in training_anomaly_values
            if value <= current_anomaly_value
        )

        percentile = (
            (rank / len(training_anomaly_values)) * 100.0
            if training_anomaly_values
            else 50.0
        )

        # Both unusually high and unusually low behaviour can be anomalous.
        tail_distance = abs(
            percentile - 50.0
        ) * 2.0

        score = _clamp(
            tail_distance,
            0.0,
            100.0,
        )

        interpretation = _ml_interpretation(
            score
        )

        base_result.update(
            {
                "available": True,
                "status": "scored",
                "score": score,
                "interpretation": interpretation,
                "raw_decision": round(current_decision, 6),
                "empirical_percentile": round(percentile, 2),
                "reliability": _ml_reliability(
                    len(training_rows)
                ),
                "message": (
                    "Local Isolation Forest scoring was computed from "
                    "real similar historical invoices."
                ),
            }
        )

        return base_result

    except Exception as error:
        base_result.update(
            {
                "status": "model_error",
                "message": (
                    "Local AI model execution failed safely: "
                    f"{error}"
                ),
            }
        )
        return base_result


# ============================================================
# RISK LEVEL
# ============================================================

def _risk_level(score: float) -> str:
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


# ============================================================
# GROUNDED EXPLANATION
# ============================================================

def build_grounded_explanation(
    deterministic: dict[str, Any],
    ml_result: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []

    for anomaly in deterministic.get("anomalies", []):
        message = anomaly.get("message")
        if message:
            reasons.append(str(message))

    ml_score = _safe_float(ml_result.get("score")) or 0.0
    if ml_result.get("available") and ml_score >= 60:
        reasons.append(
            "The local AI anomaly model detected an unusual pattern relative to similar historical invoices."
        )
    elif ml_result.get("status") == "insufficient_training_data":
        reasons.append(
            "Local AI anomaly scoring was not activated because the available real historical sample is too small."
        )

    if not reasons:
        reasons.append("No deterministic anomaly rule was triggered by the available evidence.")

    return {
        "summary": reasons[0],
        "reasons": reasons,
        "evidence_based": True,
        "human_review_required": True,
    }


# ============================================================
# PUBLIC API
# ============================================================

def analyze_invoice_risk(
    invoice: dict[str, Any],
    all_invoices: list[dict[str, Any]] | None = None,
    market_analysis: dict[str, Any] | None = None,
    purchase_order: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Main ClaimGuard risk analysis entry point.

    Parameters
    ----------
    invoice:
        Current invoice record.
    all_invoices:
        Prior invoice records used for duplicate/history/ML context.
    market_analysis:
        Output from invoice.market_research.analyze_market_price.
    purchase_order:
        Optional PO dictionary containing at least quantity when available.
    """
    all_invoices = all_invoices or []
    market_analysis = market_analysis or {}

    deterministic = run_deterministic_rules(
        invoice=invoice,
        all_invoices=all_invoices,
        market_analysis=market_analysis,
        purchase_order=purchase_order,
    )

    ml_result = run_ml_model(
        invoice=invoice,
        all_invoices=all_invoices,
        market_analysis=market_analysis,
    )

    # ML is capped at 20 points so deterministic evidence remains dominant.
    ml_contribution = _clamp(
        (float(ml_result.get("score") or 0.0) / 100.0) * 20.0,
        0.0,
        20.0,
    )

    deterministic_score = float(deterministic.get("score") or 0.0)
    final_score = _clamp(deterministic_score + ml_contribution)

    explanation = build_grounded_explanation(
        deterministic=deterministic,
        ml_result=ml_result,
    )

    ai_summary = {
        "engine": ml_result.get("engine", AI_ENGINE_NAME),
        "version": ml_result.get("version", AI_ENGINE_VERSION),
        "model": ml_result.get("model"),
        "status": ml_result.get("status"),
        "available": bool(ml_result.get("available")),
        "score": _safe_float(ml_result.get("score")) or 0.0,
        "interpretation": ml_result.get("interpretation"),
        "training_rows": ml_result.get("training_rows", 0),
        "minimum_training_rows": ml_result.get(
            "minimum_training_rows",
            MIN_HISTORICAL_FOR_ML
        ),
        "reliability": ml_result.get("reliability"),
        "feature_names": ml_result.get("feature_names", []),
        "message": ml_result.get("message"),
    }

    return {
        "status": "scored",
        "risk_score": final_score,
        "risk_level": _risk_level(final_score),
        "anomalies": deterministic.get("anomalies", []),
        "explanation": explanation,
        "ai_analysis": ai_summary,
        "score_breakdown": {
            "deterministic_score": deterministic_score,
            "ml_score": _safe_float(ml_result.get("score")) or 0.0,
            "ml_contribution": ml_contribution,
            "final_score": final_score,
        },
        "deterministic_engine": {
            "rule_count_triggered": len(deterministic.get("anomalies", [])),
            "evidence": deterministic.get("evidence", {}),
            "historical_baseline": deterministic.get("historical_baseline", {}),
            "duplicate_invoice_id": deterministic.get("duplicate_invoice_id"),
        },
        "ml_engine": ml_result,
        "market_context": {
            "usable_for_risk_calculation": bool(
                market_analysis.get("usable_for_risk_calculation")
            ),
            "price_difference": market_analysis.get("price_difference"),
            "price_difference_percent": market_analysis.get("price_difference_percent"),
        },
        "human_review_required": True,
    }


def calculate_risk_score(
    invoice: dict[str, Any],
    all_invoices: list[dict[str, Any]] | None = None,
    market_analysis: dict[str, Any] | None = None,
    purchase_order: dict[str, Any] | None = None,
) -> float:
    """Compatibility helper returning only the final risk score."""
    result = analyze_invoice_risk(
        invoice=invoice,
        all_invoices=all_invoices,
        market_analysis=market_analysis,
        purchase_order=purchase_order,
    )
    return float(result["risk_score"])


__all__ = [
    "analyze_invoice_risk",
    "calculate_risk_score",
    "run_deterministic_rules",
    "run_ml_model",
]

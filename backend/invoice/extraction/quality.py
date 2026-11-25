"""Deterministic quality checks for OCR-extracted invoice data."""
from __future__ import annotations
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from invoice.extraction.identity import normalize_product_identity


def number(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        cleaned = re.sub(r"[^0-9,.()-]", "", str(value)).replace(",", "")
        if not cleaned:
            return None
        if cleaned.startswith("(") and cleaned.endswith(")"):
            cleaned = "-" + cleaned[1:-1]
        result = Decimal(cleaned)
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def normalize_line_items(items: Any) -> list[dict]:
    """Normalize rows without guessing missing product names or prices."""
    if not isinstance(items, list):
        return []
    normalized = []
    for index, row in enumerate(items, 1):
        if not isinstance(row, dict):
            continue
        name_candidates = [
            row.get(key)
            for key in ("product", "product_name", "description", "product_description", "name", "item_description")
            if row.get(key) is not None and str(row.get(key)).strip()
        ]
        name = name_candidates[0] if name_candidates else None
        product_name = next(
            (
                normalized_name
                for candidate in name_candidates
                if (normalized_name := normalize_product_identity(candidate)) is not None
            ),
            None,
        )
        quantity = number(row.get("quantity") or row.get("qty"))
        unit_price = number(row.get("unit_price") or row.get("price"))
        line_total = number(row.get("line_amount") or row.get("line_total") or row.get("amount"))
        if line_total is None and quantity is not None and unit_price is not None:
            line_total = quantity * unit_price
        item = dict(row)
        existing_warnings = row.get("extraction_warnings")
        review_warnings = (
            ["product_identity_requires_review"]
            if isinstance(existing_warnings, list)
            and "product_identity_requires_review" in existing_warnings
            else []
        )
        item.update({
            "line_number": row.get("line_number") or index,
            "product_name": product_name,
            "quantity": float(quantity) if quantity is not None else None,
            "unit_price": float(unit_price) if unit_price is not None else None,
            "line_amount": float(line_total) if line_total is not None else None,
            "extraction_warnings": review_warnings,
        })
        if product_name is None:
            item["extraction_warnings"].append("missing_product_name")
            if (
                name is not None
                and str(name).strip()
                and "product_identity_requires_review" not in item["extraction_warnings"]
            ):
                item["extraction_warnings"].append("product_identity_requires_review")
        for key in ("product", "product_name", "description", "product_description", "name", "item_description"):
            if key in item:
                item[key] = product_name
        if item["quantity"] is None: item["extraction_warnings"].append("missing_quantity")
        if item["unit_price"] is None: item["extraction_warnings"].append("missing_unit_price")
        if item["line_amount"] is None: item["extraction_warnings"].append("missing_line_total")
        normalized.append(item)
    return normalized


def assess_invoice(data: dict) -> dict:
    rows = normalize_line_items(data.get("line_items"))
    total = number(data.get("total_amount") or data.get("grand_total"))
    row_total = sum((number(r.get("line_amount")) or Decimal(0) for r in rows), Decimal(0))
    complete_rows = sum(bool(r.get("product_name") and r.get("unit_price") is not None) for r in rows)
    warnings = []
    if not data.get("vendor_name"): warnings.append("vendor_not_identified")
    if not data.get("invoice_number"): warnings.append("invoice_number_not_identified")
    if not rows: warnings.append("no_product_rows_extracted")
    if any("product_identity_requires_review" in row.get("extraction_warnings", []) for row in rows):
        warnings.append("product_identity_requires_review")
    if rows and complete_rows != len(rows): warnings.append("some_product_rows_are_incomplete")
    reconciliation = "not_available"
    if total is not None and rows:
        tolerance = max(Decimal("1.00"), abs(total) * Decimal("0.001"))
        reconciliation = "matched" if abs(total-row_total) <= tolerance else "mismatch"
        if reconciliation == "mismatch": warnings.append("line_items_do_not_reconcile_to_invoice_total")
    score = round((complete_rows / len(rows) * 100) if rows else 0)
    return {"line_items": rows, "line_items_total": float(row_total) if rows else None,
            "product_line_count": len(rows), "total_reconciliation": reconciliation,
            "extraction_completeness_score": score, "extraction_warnings": warnings}

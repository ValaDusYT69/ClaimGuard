"""Field provenance helpers. Confidence is a heuristic, not ML accuracy."""
from __future__ import annotations


def build_field_provenance(data: dict, raw_text: str = "") -> dict:
    provenance = {}
    text = (raw_text or "").casefold()
    for field, value in data.items():
        if value is None or field in {"raw_text_preview", "ocr_metadata", "field_provenance"}:
            continue
        if field == "line_items":
            provenance[field] = {"source": "ocr_table_extraction", "value_present": bool(value), "confidence": None}
            continue
        value_text = str(value).strip().casefold()
        present = bool(value_text and value_text in text)
        provenance[field] = {"source": "ocr_text_match" if present else "structured_extractor", "value_present": True,
                             "confidence": 0.98 if present else None}
    return provenance

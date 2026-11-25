"""Product identity cleanup and invoice-metadata detection."""
from __future__ import annotations

import re


_METADATA_LABEL = re.compile(
    r"\b(?:"
    r"customer\s*name|buyer\s*name|client\s*name|"
    r"invoice\s*(?:no|number|#)|inv\s*(?:no|number|#)|"
    r"status|order\s*by|approved\s*by|person|"
    r"challan\s*(?:no|number|#)?|order\s*(?:no|number|#|id)|"
    r"sales\s*mode|"
    r"product\s*(?:description|name)|item\s*description"
    r")\b",
    re.IGNORECASE,
)
_TABLE_HEADER = re.compile(
    r"\b(?:product\s*(?:description|name)|item\s*description)\b\s*[:#-]?\s*",
    re.IGNORECASE,
)


def is_invoice_metadata_line(value: str) -> bool:
    """Return whether a line starts with a document field or table heading."""
    return bool(_METADATA_LABEL.match(str(value or "").strip()))


def normalize_product_identity(value: object) -> str | None:
    """Normalize whitespace and remove a recognized product-table heading.

    Metadata-contaminated text without a trustworthy product boundary is
    rejected for review instead of being sent to market search.
    """
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return None

    heading = _TABLE_HEADER.search(text)
    if heading:
        text = text[heading.end():].strip()
    elif _METADATA_LABEL.search(text):
        return None

    if not text or _METADATA_LABEL.search(text):
        return None
    return text

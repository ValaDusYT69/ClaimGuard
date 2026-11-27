from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _register_report_font() -> tuple[str, str]:
    """Register a Unicode font when the host provides one, without bundling it."""
    candidates = [
        Path(r"C:\Windows\Fonts\kalpurush.ttf"),
        Path(r"C:\Windows\Fonts\NotoSansBengali-Regular.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            try:
                pdfmetrics.registerFont(TTFont("ClaimGuardUnicode", str(path)))
                return "ClaimGuardUnicode", "ClaimGuardUnicode"
            except Exception:
                continue
    return "Helvetica", "Helvetica-Bold"


REPORT_FONT, REPORT_FONT_BOLD = _register_report_font()


def _text(
    value: Any,
    default: str = "-"
) -> str:

    if value is None:
        return default

    if isinstance(
        value,
        str
    ):

        cleaned = value.strip()

        return (
            cleaned
            if cleaned
            else default
        )

    return str(
        value
    )


def _safe_number(
    value: Any,
    default: str = "-"
) -> str:

    if value is None or value == "":
        return default

    try:

        number = float(
            value
        )

        if number.is_integer():
            return f"{int(number):,}"

        return f"{number:,.2f}"

    except (
        TypeError,
        ValueError,
    ):

        return _text(
            value,
            default
        )


def _p(
    value: Any,
    style: ParagraphStyle
) -> Paragraph:

    return Paragraph(
        escape(
            _text(
                value
            ),
            {
                "'": "&apos;",
            }
        ).replace(
            "\n",
            "<br/>"
        ),
        style
    )


def _section(
    title: str,
    styles: dict[str, ParagraphStyle]
) -> Paragraph:

    return Paragraph(
        escape(
            title
        ),
        styles["section"]
    )


def _kv_table(
    rows: list[tuple[str, str]],
    styles: dict[str, ParagraphStyle]
) -> Table:

    data = []

    for label, value in rows:

        data.append(
            [
                _p(
                    label,
                    styles["label"]
                ),
                _p(
                    value,
                    styles["value"]
                ),
            ]
        )

    table = Table(
        data,
        colWidths=[
            48 * mm,
            122 * mm,
        ],
        hAlign="LEFT",
    )

    table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.HexColor(
                        "#f8fafc"
                    ),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.6,
                    colors.HexColor(
                        "#dbe3ee"
                    ),
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor(
                        "#e5e7eb"
                    ),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
            ]
        )
    )

    return table


def _two_column_rows(
    rows: list[list[Paragraph]],
    styles: dict[str, ParagraphStyle],
) -> Table:

    table = Table(
        rows,
        colWidths=[
            45 * mm,
            125 * mm,
        ],
        hAlign="LEFT",
    )

    table.setStyle(
        TableStyle(
            [
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.6,
                    colors.HexColor(
                        "#dbe3ee"
                    ),
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor(
                        "#e5e7eb"
                    ),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.HexColor(
                        "#f8fafc"
                    ),
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
            ]
        )
    )

    return table


def _anomaly_table(
    anomalies: list[Any],
    styles: dict[str, ParagraphStyle]
) -> Table:

    if not anomalies:

        return Table(
            [
                [
                    _p(
                        "No deterministic anomaly rule was recorded.",
                        styles["value"]
                    )
                ]
            ],
            colWidths=[
                170 * mm,
            ],
            style=TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, -1),
                        colors.HexColor(
                            "#f8fafc"
                        ),
                    ),
                    (
                        "BOX",
                        (0, 0),
                        (-1, -1),
                        0.6,
                        colors.HexColor(
                            "#dbe3ee"
                        ),
                    ),
                    (
                        "LEFTPADDING",
                        (0, 0),
                        (-1, -1),
                        8,
                    ),
                    (
                        "RIGHTPADDING",
                        (0, 0),
                        (-1, -1),
                        8,
                    ),
                    (
                        "TOPPADDING",
                        (0, 0),
                        (-1, -1),
                        8,
                    ),
                    (
                        "BOTTOMPADDING",
                        (0, 0),
                        (-1, -1),
                        8,
                    ),
                ]
            )
        )

    rows = []

    for index, anomaly in enumerate(
        anomalies,
        start=1
    ):

        if isinstance(
            anomaly,
            dict
        ):

            title = (
                anomaly.get(
                    "anomaly_type"
                )
                or anomaly.get(
                    "type"
                )
                or anomaly.get(
                    "name"
                )
                or f"Anomaly {index}"
            )

            message = (
                anomaly.get(
                    "message"
                )
                or anomaly.get(
                    "description"
                )
                or anomaly.get(
                    "reason"
                )
                or "-"
            )

            severity = anomaly.get(
                "severity"
            )

            evidence = anomaly.get(
                "evidence"
            )

            body_parts = [
                _text(
                    message
                )
            ]

            if severity:
                body_parts.append(
                    f"Severity: {_text(severity)}"
                )

            if isinstance(
                evidence,
                dict
            ) and evidence:

                evidence_parts = []

                for key, value in list(
                    evidence.items()
                )[:6]:

                    evidence_parts.append(
                        f"{key}: {_text(value)}"
                    )

                body_parts.append(
                    "Evidence: "
                    + " | ".join(
                        evidence_parts
                    )
                )

            rows.append(
                [
                    _p(
                        title,
                        styles["label"]
                    ),
                    _p(
                        "\n".join(
                            body_parts
                        ),
                        styles["value"]
                    ),
                ]
            )

        else:

            rows.append(
                [
                    _p(
                        f"Item {index}",
                        styles["label"]
                    ),
                    _p(
                        anomaly,
                        styles["value"]
                    ),
                ]
            )

    return _two_column_rows(
        rows,
        styles
    )


def _audit_table(
    events: list[Any],
    styles: dict[str, ParagraphStyle]
) -> Table:

    rows = []

    for event in events:

        if not isinstance(
            event,
            dict
        ):
            continue

        actor = (
            event.get(
                "actor_name"
            )
            or event.get(
                "actor_email"
            )
            or "System"
        )

        action = (
            event.get(
                "decision"
            )
            or event.get(
                "event_type"
            )
            or "-"
        )

        timestamp = (
            event.get(
                "timestamp"
            )
            or "-"
        )

        note = (
            event.get(
                "note"
            )
            or "-"
        )

        rows.append(
            [
                _p(
                    actor,
                    styles["label"]
                ),
                _p(
                    (
                        f"Action: {action}\n"
                        f"Time: {timestamp}\n"
                        f"Note: {note}"
                    ),
                    styles["value"]
                ),
            ]
        )

    if not rows:

        return Table(
            [
                [
                    _p(
                        "No review audit events have been recorded.",
                        styles["value"]
                    )
                ]
            ],
            colWidths=[
                170 * mm,
            ],
            style=TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, -1),
                        colors.HexColor(
                            "#f8fafc"
                        ),
                    ),
                    (
                        "BOX",
                        (0, 0),
                        (-1, -1),
                        0.6,
                        colors.HexColor(
                            "#dbe3ee"
                        ),
                    ),
                    (
                        "LEFTPADDING",
                        (0, 0),
                        (-1, -1),
                        8,
                    ),
                    (
                        "RIGHTPADDING",
                        (0, 0),
                        (-1, -1),
                        8,
                    ),
                    (
                        "TOPPADDING",
                        (0, 0),
                        (-1, -1),
                        8,
                    ),
                    (
                        "BOTTOMPADDING",
                        (0, 0),
                        (-1, -1),
                        8,
                    ),
                ]
            )
        )

    return _two_column_rows(
        rows,
        styles
    )


def _footer(
    canvas,
    doc
) -> None:

    canvas.saveState()

    canvas.setStrokeColor(
        colors.HexColor(
            "#dbe3ee"
        )
    )

    canvas.line(
        18 * mm,
        14 * mm,
        192 * mm,
        14 * mm,
    )

    canvas.setFont(
        "Helvetica",
        8
    )

    canvas.setFillColor(
        colors.HexColor(
            "#64748b"
        )
    )

    canvas.drawString(
        18 * mm,
        9 * mm,
        "ClaimGuard - Invoice Intelligence"
    )

    canvas.drawRightString(
        192 * mm,
        9 * mm,
        f"Page {doc.page}"
    )

    canvas.restoreState()


# =========================================================
# COMPREHENSIVE REPORT V2
# =========================================================
# Exports persisted invoice, per-product market, separate-edition and review evidence.

import json as _report_json
from urllib.parse import urlsplit as _report_urlsplit


def _report_label(value: Any) -> str:
    return " ".join(
        part.capitalize()
        for part in str(value or "").replace("-", "_").split("_")
        if part
    )


def _report_value(value: Any, limit: int = 12000) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (dict, list, tuple)):
        try:
            value = _report_json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            value = str(value)
    text = str(value).strip() or "-"
    if len(text) > limit:
        return text[:limit] + " … [truncated in PDF for readability]"
    return text


def _report_availability(value: Any) -> str:
    normalized = str(value or "").casefold().replace("-", "_").replace(" ", "_")
    if normalized in {"out_of_stock", "sold_out", "unavailable", "not_available"}:
        return "Out of stock (not currently purchasable)"
    if normalized in {"available", "listed", "in_stock"}:
        return "Listed / available"
    if normalized in {"", "unknown", "not_stated"}:
        return "Availability unknown"
    return _report_value(value or "Availability unknown")


def _report_link(url: Any, style: ParagraphStyle) -> Paragraph:
    value = str(url or "").strip()
    try:
        parsed = _report_urlsplit(value)
    except ValueError:
        parsed = None
    if parsed and parsed.scheme in {"http", "https"} and parsed.netloc:
        safe_url = escape(value, {"\"": "&quot;"})
        return Paragraph(
            f'<link href="{safe_url}" color="#1d4ed8">Open source URL</link>',
            style,
        )
    return _p(value or "-", style)


def _report_source_rows(
    sources: list[Any],
    styles: dict[str, ParagraphStyle],
    empty_text: str,
) -> Table:
    rows: list[list[Paragraph]] = []
    for index, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            continue
        title = source.get("title") or source.get("search_title") or f"Source {index}"
        domain = source.get("source_name") or source.get("domain") or "Unknown domain"
        price = source.get("price")
        currency = source.get("currency") or ""
        availability = _report_availability(source.get("availability"))
        source_type = source.get("source_type") or source.get("source_type_label") or "Not stated"
        price_source = source.get("price_source") or source.get("retrieval_method") or "Not stated"
        confidence = source.get("match_confidence")
        confidence_text = (
            f"{float(confidence) * 100:.0f}%"
            if isinstance(confidence, (int, float))
            else "Not stated"
        )
        validation = source.get("variant_validation") or {}
        validation_text = (
            f"{validation.get('status', 'not stated')}: {validation.get('reason', '-') }"
            if isinstance(validation, dict)
            else _report_value(validation, 1000)
        )
        reason = source.get("exclusion_reason")
        detail_lines = [
            f"Price: {_report_value(price)} {currency}".strip(),
            f"Availability: {availability}",
            f"Source type: {_report_value(source_type)}",
            f"Price evidence: {_report_value(price_source)}",
            f"Match / specification status: {_report_value(source.get('market_comparison_status') or source.get('specification_status'))}",
            f"Comparison group: {_report_value(source.get('comparison_group'))}",
            f"Identity confidence: {confidence_text}",
            f"Variant validation: {validation_text}",
        ]
        if reason:
            detail_lines.append(f"Exclusion reason: {_report_value(reason)}")
        left = Paragraph(
            escape(_report_value(title, 1200))
            + "<br/><font color='#64748b'>"
            + escape(_report_value(domain, 300))
            + "</font>",
            styles["label"],
        )
        right_text = "<br/>".join(escape(line) for line in detail_lines)
        right = [
            Paragraph(right_text, styles["value"]),
            _report_link(source.get("url"), styles["small"]),
        ]
        rows.append([left, right])

    if not rows:
        rows.append([_p(empty_text, styles["value"]), _p("-", styles["value"])])
    return _two_column_rows(rows, styles)


def _report_key_value_rows(data: dict[str, Any], excluded: set[str] | None = None) -> list[tuple[str, str]]:
    excluded = excluded or set()
    rows: list[tuple[str, str]] = []
    for key, value in data.items():
        if key in excluded or value is None:
            continue
        if isinstance(value, (dict, list)) and not value:
            continue
        rows.append((_report_label(key), _report_value(value)))
    return rows


def _report_item_rows(line_items: list[Any], extracted: dict[str, Any], styles: dict[str, ParagraphStyle]) -> Table:
    rows: list[list[Paragraph]] = []
    for index, item in enumerate(line_items, start=1):
        if not isinstance(item, dict):
            continue
        product = item.get("product") or item.get("description") or f"Item {index}"
        unit = _report_value(item.get("unit"))
        quantity_line = f"Quantity: {_report_value(item.get('quantity'))}"
        if unit != "-":
            quantity_line += f" {unit}"
        details = [
            f"SKU / Model: {_report_value(item.get('sku') or item.get('model'))}",
            quantity_line,
            f"Unit price: {_report_value(item.get('unit_price'))}",
            f"Discount: {_report_value(item.get('discount'))}",
            f"Tax: {_report_value(item.get('tax') or item.get('tax_amount'))}",
            f"Line total: {_report_value(item.get('line_amount') or item.get('total') or item.get('amount'))}",
        ]
        details = [value for value in details if not value.endswith(": -")]
        rows.append([
            _p(f"{index}. {product}", styles["label"]),
            _p("\n".join(details), styles["value"]),
        ])

    if not rows:
        fallback = {
            "product": extracted.get("product_description"),
            "quantity": extracted.get("quantity"),
            "unit_price": extracted.get("unit_price"),
            "line_amount": extracted.get("line_amount"),
        }
        if any(value is not None for value in fallback.values()):
            return _report_item_rows([fallback], extracted, styles)
        rows.append([_p("No structured product lines were stored.", styles["value"]), _p("-", styles["value"])])
    return _two_column_rows(rows, styles)


def _report_add_market_product(
    story: list[Any],
    product_label: str,
    invoice_price: Any,
    market: dict[str, Any],
    styles: dict[str, ParagraphStyle],
    index: int,
) -> None:
    stats = market.get("market_statistics") if isinstance(market.get("market_statistics"), dict) else {}
    currency = stats.get("currency") or market.get("invoice_currency") or "BDT"
    sources = market.get("sources") if isinstance(market.get("sources"), list) else []
    model_sources = market.get("model_level_sources") if isinstance(market.get("model_level_sources"), list) else sources
    difference_groups = market.get("specification_difference_groups") if isinstance(market.get("specification_difference_groups"), list) else []
    excluded = market.get("excluded_sources") if isinstance(market.get("excluded_sources"), list) else []
    related = market.get("related_edition_comparisons") if isinstance(market.get("related_edition_comparisons"), list) else []
    all_observations = list(model_sources)
    all_observations.extend(
        source
        for group in difference_groups
        if isinstance(group, dict)
        for source in (group.get("sources") or [])
        if isinstance(source, dict)
    )
    all_observations.extend(
        source
        for edition in related
        if isinstance(edition, dict)
        for source in (edition.get("sources") or [])
        if isinstance(source, dict)
    )
    unique_observations: list[dict[str, Any]] = []
    seen_observations: set[str] = set()
    for source in all_observations:
        key = str(source.get("url") or f"{source.get('source_name')}|{source.get('title')}")
        if key not in seen_observations:
            seen_observations.add(key)
            unique_observations.append(source)
    displayed_sources = unique_observations[:8]
    displayed_related = [
        edition for edition in related if isinstance(edition, dict)
    ]
    hidden_evidence_count = (
        max(0, len(unique_observations) - len(displayed_sources))
        + len(excluded)
    )
    comparison = market.get("price_comparison") if isinstance(market.get("price_comparison"), dict) else {}
    domains = market.get("market_quality", {}).get("independent_domains")
    if domains is None:
        domains = market.get("search_diagnostics", {}).get("independent_source_count", len(sources))

    story.append(_section(f"5.{index} {product_label}", styles))
    story.append(_kv_table([
        ("Market identity", _report_value(market.get("market_product_label") or product_label)),
        ("Variant confirmation", _report_value(market.get("market_variant_override") or "From invoice text / source matching")),
        ("Variant notice", _report_value(market.get("market_variant_notice"))),
        ("Market status", _report_value(market.get("status"))),
        ("Analysis message", _report_value(market.get("message"))),
        ("Invoice unit price", f"{currency} {_safe_number(invoice_price)}"),
        ("Market average", f"{currency} {_safe_number(stats.get('average'))}"),
        ("Lowest observed", f"{currency} {_safe_number(stats.get('lowest'))}"),
        ("Highest observed", f"{currency} {_safe_number(stats.get('highest'))}"),
        ("Median observed", f"{currency} {_safe_number(stats.get('median'))}"),
        ("Accepted offers", str(len(sources))),
        ("Independent domains", _report_value(domains)),
        ("Difference", _report_value(market.get("price_difference"))),
        ("Difference percent", _report_value(comparison.get("difference_percent", market.get("price_difference_percent")))),
        ("Price comparison status", _report_value(comparison.get("status"))),
        ("Comparison independent domains", _report_value(comparison.get("independent_domain_count", domains))),
        ("Price alignment score", _report_value(comparison.get("price_alignment_score", market.get("price_alignment_score")))),
        ("Price risk contribution", (f"{_safe_number(comparison.get('price_risk_points'))} / 30 points" if comparison.get("price_risk_points") is not None else "Not assessed")),
        ("Usable for risk calculation", _report_value(comparison.get("is_comparable", market.get("usable_for_risk_calculation")))),
    ], styles))
    story.append(Paragraph(
        f"Price alignment score: {_report_value(comparison.get('price_alignment_score', market.get('price_alignment_score')))}; "
        f"Market match confidence: {_report_value(market.get('market_match_confidence', market.get('market_match_confidence_score')))}",
        styles["small"],
    ))
    model_stats = market.get("model_level_statistics") if isinstance(market.get("model_level_statistics"), dict) else {}
    model_domains = int(market.get("model_level_independent_domains") or 0)
    model_average = model_stats.get("average") if model_domains >= 2 else None
    story.append(Paragraph(
        f"{'Indicative ' if market.get('model_level_is_indicative') else ''}Model-Level Comparison: "
        f"{len(model_sources)} observations across {model_domains} independent domains; "
        f"average {_safe_number(model_average)}, lowest {_safe_number(model_stats.get('lowest'))}, "
        f"highest {_safe_number(model_stats.get('highest'))}, median {_safe_number(model_stats.get('median'))}. "
        "Different material specifications are shown separately.",
        styles["small"],
    ))

    story.append(_section(f"5.{index}.1 Page-verified market observations ({len(unique_observations)})", styles))
    story.append(_report_source_rows(displayed_sources, styles, "No page-verified price observations were accepted."))

    if related:
        story.append(_section(f"5.{index}.2 Other editions — separate comparison only", styles))
        story.append(Paragraph(
            "Different editions are shown for context only. Their prices are never combined with this invoice edition's average, lowest, highest, median or risk benchmark.",
            styles["note"],
        ))
        for related_index, edition in enumerate(displayed_related, start=1):
            related_stats = edition.get("market_statistics") if isinstance(edition.get("market_statistics"), dict) else {}
            related_currency = related_stats.get("currency") or currency
            story.append(_kv_table([
                ("Separate edition", _report_value(edition.get("edition_label"))),
                ("Status", _report_value(edition.get("status"))),
                ("Average", f"{related_currency} {_safe_number(related_stats.get('average'))}"),
                ("Lowest", f"{related_currency} {_safe_number(related_stats.get('lowest'))}"),
                ("Highest", f"{related_currency} {_safe_number(related_stats.get('highest'))}"),
                ("Median", f"{related_currency} {_safe_number(related_stats.get('median'))}"),
                ("Independent domains", _report_value(edition.get("independent_domains"))),
                ("Included in target benchmark", _report_value(edition.get("included_in_target_benchmark"))),
                ("Message", _report_value(edition.get("message"))),
            ], styles))

    if hidden_evidence_count:
        story.append(Paragraph(
            f"{hidden_evidence_count} additional market listings were not shown.",
            styles["small"],
        ))


def build_invoice_report(invoice: dict[str, Any]) -> bytes:
    """Create a concise, decision-oriented PDF invoice report.

    The report uses persisted invoice and market evidence only. Missing market
    prices are clearly marked as unavailable; they are never replaced with an
    invented average or score.
    """
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, KeepTogether, HRFlowable

    palette = {
        "navy": colors.HexColor("#101A33"),
        "blue": colors.HexColor("#315CEB"),
        "blue_light": colors.HexColor("#EEF3FF"),
        "ink": colors.HexColor("#182238"),
        "muted": colors.HexColor("#64748B"),
        "line": colors.HexColor("#DCE3EF"),
        "surface": colors.HexColor("#F7F9FC"),
        "green": colors.HexColor("#087A56"),
        "green_light": colors.HexColor("#E8F7F1"),
        "amber": colors.HexColor("#9A5B00"),
        "amber_light": colors.HexColor("#FFF5E5"),
        "red": colors.HexColor("#B42335"),
        "red_light": colors.HexColor("#FFF0F1"),
    }

    extracted = invoice.get("extracted_data") if isinstance(invoice.get("extracted_data"), dict) else {}
    verification = invoice.get("verification") if isinstance(invoice.get("verification"), dict) else {}
    risk = invoice.get("risk_analysis") if isinstance(invoice.get("risk_analysis"), dict) else {}
    market = invoice.get("market_analysis") if isinstance(invoice.get("market_analysis"), dict) else {}
    decision = invoice.get("decision") if isinstance(invoice.get("decision"), dict) else {}
    anomalies = invoice.get("anomalies") if isinstance(invoice.get("anomalies"), list) else risk.get("anomalies", [])

    line_items = extracted.get("line_items") if isinstance(extracted.get("line_items"), list) else []
    line_items = [item for item in line_items if isinstance(item, dict)]
    invoice_number = extracted.get("invoice_number") or invoice.get("invoice_number") or invoice.get("invoice_id") or "Not detected"
    vendor = extracted.get("vendor_name") or invoice.get("vendor_name") or "Unknown vendor - manual identification needed"
    issue_date = extracted.get("invoice_date") or invoice.get("invoice_date") or "Not stated"
    purchase_date = extracted.get("purchase_date") or extracted.get("purchase_order_date") or "Not stated"
    promised_date = extracted.get("promised_date") or "Not stated"
    order_number = extracted.get("order_id") or "Not stated"
    buyer = extracted.get("customer_name") or "Not stated"
    payment_terms = extracted.get("payment_terms") or "Not stated"
    currency = str(extracted.get("currency") or invoice.get("currency") or "BDT").upper()
    total = extracted.get("total_amount")
    if total is None:
        total = invoice.get("total_amount")
    risk_score = invoice.get("risk_score") if invoice.get("risk_score") is not None else risk.get("risk_score")
    risk_level = str(invoice.get("risk_level") or risk.get("risk_level") or "Not assessed").replace("_", " " ).title()
    status = str(invoice.get("status") or "pending review").replace("_", " " ).title()
    generated_at = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")

    product_analyses = market.get("product_analyses") if isinstance(market.get("product_analyses"), list) else []

    def _product_key(value: Any) -> str:
        import re
        return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))

    def _product_analysis_for(item: dict[str, Any], index: int) -> dict[str, Any]:
        """Match saved market evidence to the product, never by array position alone.

        Older invoice records may contain one stale aggregate analysis from the
        pre-line-item parser. Attaching that result to the first newly extracted
        product can create a false price comparison, so a named product must
        match before its evidence is displayed.
        """
        item_name = _product_key(item.get("product") or item.get("description"))
        named_entries = [entry for entry in product_analyses if isinstance(entry, dict) and _product_key(entry.get("product"))]
        if item_name and named_entries:
            exact = next((entry for entry in named_entries if _product_key(entry.get("product")) == item_name), None)
            if exact:
                return exact
            # Permit only very close OCR spelling differences. Model identifiers
            # must agree whenever both sides contain a model-like token.
            from difflib import SequenceMatcher
            item_tokens = set(item_name.split())
            best = None
            best_score = 0.0
            for entry in named_entries:
                candidate_key = _product_key(entry.get("product"))
                candidate_tokens = set(candidate_key.split())
                score = SequenceMatcher(None, item_name, candidate_key).ratio()
                union = item_tokens | candidate_tokens
                overlap = len(item_tokens & candidate_tokens) / len(union) if union else 0.0
                model_tokens = {token for token in item_tokens if any(ch.isdigit() for ch in token)}
                candidate_models = {token for token in candidate_tokens if any(ch.isdigit() for ch in token)}
                models_agree = not (model_tokens and candidate_models) or bool(model_tokens & candidate_models)
                combined = max(score, overlap)
                if models_agree and combined >= 0.90 and combined > best_score:
                    best, best_score = entry, combined
            return best or {}
        # An entry without a product label is safe only for a single-product
        # invoice; its identity cannot be confirmed for a multi-product invoice.
        if not named_entries and len(line_items) == 1 and len(product_analyses) == 1:
            return product_analyses[0] if isinstance(product_analyses[0], dict) else {}
        return {}

    # Legacy aggregate market evidence can only be used for a single-product
    # invoice. Never attach one invoice-wide result to the first row of a
    # multi-product invoice.
    legacy_single_product_market = (
        market if len(line_items) == 1 and not product_analyses
        and isinstance(market.get("sources"), list) and market.get("sources")
        else None
    )

    def _independent_domains(item_market: dict[str, Any], sources: list[Any]) -> int:
        quality = item_market.get("market_quality") if isinstance(item_market.get("market_quality"), dict) else {}
        diagnostics = item_market.get("search_diagnostics") if isinstance(item_market.get("search_diagnostics"), dict) else {}
        reported = quality.get("independent_domains")
        if reported is None:
            reported = diagnostics.get("independent_source_count")
        if reported is not None:
            try:
                return int(reported)
            except (TypeError, ValueError):
                pass
        from urllib.parse import urlsplit
        domains = set()
        for source in sources:
            if not isinstance(source, dict):
                continue
            domain = str(source.get("domain") or source.get("source_name") or "").strip().lower()
            if not domain and source.get("url"):
                domain = urlsplit(str(source["url"])).netloc.lower()
            if domain:
                domains.add(domain.removeprefix("www."))
        return len(domains)

    def txt(value: Any, default: str = "Not stated") -> str:
        if value is None:
            return default
        value = str(value).strip()
        return value or default

    def money(value: Any, curr: str = currency) -> str:
        if value is None or value == "":
            return "Not available"
        try:
            n = float(value)
            rendered = f"{int(n):,}" if n.is_integer() else f"{n:,.2f}"
            return f"{curr} {rendered}"
        except (TypeError, ValueError):
            return txt(value)

    def percent(value: Any) -> str:
        if value is None or value == "":
            return "Not scored"
        try:
            n = float(value)
            return f"{n:+.1f}%"
        except (TypeError, ValueError):
            return txt(value)

    def score_percent(value: Any, *, fraction_allowed: bool = False) -> str:
        if value is None or value == "":
            return "Not scored"
        try:
            number = float(value)
            if fraction_allowed and 0 <= number <= 1:
                number *= 100
            number = max(0.0, min(100.0, number))
            return f"{number:.0f}%"
        except (TypeError, ValueError):
            return "Not scored"

    def paragraph(value: Any, style: ParagraphStyle, default: str = "Not stated") -> Paragraph:
        return Paragraph(escape(txt(value, default)).replace("\n", "<br/>"), style)

    def simple_table(data: list[list[Any]], widths: list[float], header: bool = False, padd: int = 6) -> Table:
        table = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
        commands = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), padd),
            ("RIGHTPADDING", (0, 0), (-1, -1), padd),
            ("TOPPADDING", (0, 0), (-1, -1), padd),
            ("BOTTOMPADDING", (0, 0), (-1, -1), padd),
            ("BOX", (0, 0), (-1, -1), 0.6, palette["line"]),
            ("INNERGRID", (0, 0), (-1, -1), 0.35, palette["line"]),
        ]
        if header:
            commands.extend([
                ("BACKGROUND", (0, 0), (-1, 0), palette["navy"]),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ])
        else:
            for row_index in range(len(data)):
                if row_index % 2 == 1:
                    commands.append(("BACKGROUND", (0, row_index), (-1, row_index), palette["surface"]))
        table.setStyle(TableStyle(commands))
        return table

    sample = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle("CGReportTitle", parent=sample["Title"], fontName=REPORT_FONT_BOLD, fontSize=22, leading=26, textColor=palette["navy"], alignment=TA_LEFT, spaceAfter=4),
        "subtitle": ParagraphStyle("CGReportSub", parent=sample["Normal"], fontName=REPORT_FONT, fontSize=8.5, leading=12, textColor=palette["muted"], spaceAfter=10),
        "section": ParagraphStyle("CGReportSection", parent=sample["Heading2"], fontName=REPORT_FONT_BOLD, fontSize=12, leading=15, textColor=palette["navy"], spaceBefore=10, spaceAfter=6, keepWithNext=True),
        "label": ParagraphStyle("CGReportLabel", parent=sample["Normal"], fontName=REPORT_FONT_BOLD, fontSize=7.2, leading=9, textColor=palette["muted"]),
        "value": ParagraphStyle("CGReportValue", parent=sample["Normal"], fontName=REPORT_FONT, fontSize=8.4, leading=11, textColor=palette["ink"], wordWrap="CJK"),
        "small": ParagraphStyle("CGReportSmall", parent=sample["Normal"], fontName=REPORT_FONT, fontSize=7, leading=9, textColor=palette["muted"], wordWrap="CJK"),
        "card_value": ParagraphStyle("CGReportCardValue", parent=sample["Normal"], fontName=REPORT_FONT_BOLD, fontSize=13, leading=16, textColor=palette["navy"]),
        "card_label": ParagraphStyle("CGReportCardLabel", parent=sample["Normal"], fontName=REPORT_FONT_BOLD, fontSize=6.5, leading=8, textColor=palette["muted"]),
        "product": ParagraphStyle("CGReportProduct", parent=sample["Normal"], fontName=REPORT_FONT_BOLD, fontSize=7.2, leading=9, textColor=palette["ink"], wordWrap="CJK"),
        "table": ParagraphStyle("CGReportTable", parent=sample["Normal"], fontName=REPORT_FONT, fontSize=6.8, leading=8.3, textColor=palette["ink"], wordWrap="CJK"),
        "table_head": ParagraphStyle("CGReportTableHead", parent=sample["Normal"], fontName=REPORT_FONT_BOLD, fontSize=6.4, leading=8, textColor=colors.white, wordWrap="CJK"),
        "note": ParagraphStyle("CGReportNote", parent=sample["Normal"], fontName=REPORT_FONT, fontSize=7.8, leading=10.5, textColor=palette["ink"], backColor=palette["blue_light"], borderColor=palette["line"], borderWidth=0.5, borderPadding=7, spaceBefore=3, spaceAfter=5, wordWrap="CJK"),
        "source": ParagraphStyle("CGReportSource", parent=sample["Normal"], fontName=REPORT_FONT, fontSize=7.2, leading=9.5, textColor=palette["blue"], wordWrap="CJK"),
    }

    page_width, _ = A4
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=15 * mm, leftMargin=15 * mm,
        topMargin=21 * mm, bottomMargin=18 * mm,
        title=f"ClaimGuard Invoice Review - {invoice_number}",
        author="ClaimGuard",
    )

    def page_decor(canvas, doc) -> None:
        canvas.saveState()
        canvas.setStrokeColor(palette["line"])
        canvas.setLineWidth(0.6)
        canvas.line(15 * mm, 14 * mm, page_width - 15 * mm, 14 * mm)
        canvas.setFont("Helvetica-Bold", 7)
        canvas.setFillColor(palette["navy"])
        canvas.drawString(15 * mm, 9 * mm, "CLAIMGUARD  |  INVOICE INTELLIGENCE")
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(palette["muted"])
        canvas.drawRightString(page_width - 15 * mm, 9 * mm, f"{doc.page}")
        if doc.page > 1:
            canvas.setFont("Helvetica-Bold", 7)
            canvas.setFillColor(palette["muted"])
            canvas.drawString(15 * mm, A4[1] - 11 * mm, f"INVOICE {invoice_number}")
        canvas.restoreState()

    market_verified_count = 0
    market_covered: list[dict] = []
    matched_product_analyses: dict[int, dict[str, Any]] = {}
    for index, item in enumerate(line_items):
        entry = _product_analysis_for(item, index)
        if entry:
            matched_product_analyses[index] = entry
        item_market = entry.get("market") if isinstance(entry.get("market"), dict) else {}
        sources = item_market.get("sources") if isinstance(item_market.get("sources"), list) else []
        model_sources = item_market.get("model_level_sources") if isinstance(item_market.get("model_level_sources"), list) else []
        difference_groups = item_market.get("specification_difference_groups") if isinstance(item_market.get("specification_difference_groups"), list) else []
        stats = item_market.get("market_statistics") if isinstance(item_market.get("market_statistics"), dict) else {}
        domains = _independent_domains(item_market, sources)
        if sources or model_sources or difference_groups:
            if stats.get("average") is not None and domains >= 2:
                market_verified_count += 1
            # Keep partial model-level and separate-conflict observations visible.
            market_covered.append({"index": index, "item": item, "market": item_market, "sources": sources})

    if legacy_single_product_market and line_items:
        legacy_sources = legacy_single_product_market.get("sources") or []
        legacy_model_sources = legacy_single_product_market.get("model_level_sources") or []
        legacy_difference_groups = legacy_single_product_market.get("specification_difference_groups") or []
        if legacy_sources or legacy_model_sources or legacy_difference_groups:
            legacy_stats = legacy_single_product_market.get("market_statistics") if isinstance(legacy_single_product_market.get("market_statistics"), dict) else {}
            if legacy_stats.get("average") is not None:
                market_verified_count = 1
            market_covered.append({
                "index": 0,
                "item": line_items[0],
                "market": legacy_single_product_market,
                "sources": legacy_sources,
            })

    # Some older/single-product records store sources directly under
    # market_analysis rather than under product_analyses[].market. Preserve
    # those links even when structured line items are unavailable.
    if not market_covered:
        top_level_sources = market.get("sources") if isinstance(market.get("sources"), list) else []
        top_level_model_sources = market.get("model_level_sources") if isinstance(market.get("model_level_sources"), list) else []
        top_level_differences = market.get("specification_difference_groups") if isinstance(market.get("specification_difference_groups"), list) else []
        if top_level_sources or top_level_model_sources or top_level_differences:
            fallback_item = line_items[0] if line_items else {
                "product": extracted.get("product_description") or "Invoice market evidence",
                "unit_price": extracted.get("unit_price"),
            }
            market_covered.append({
                "index": 0,
                "item": fallback_item,
                "market": market,
                "sources": top_level_sources,
            })

    total_units = sum(float(item.get("quantity") or 0) for item in line_items) if line_items else 0
    reconciliation = extracted.get("total_reconciliation")
    line_total = extracted.get("line_items_total")
    if line_total is None and line_items:
        line_total = sum(float(item.get("line_amount") or 0) for item in line_items)
    anomaly_texts = []
    for anomaly in anomalies:
        if isinstance(anomaly, dict):
            message = anomaly.get("message") or anomaly.get("anomaly_type")
            if message:
                anomaly_texts.append(str(message))

    story: list[Any] = []
    brand = Table(
        [[
            Paragraph("<font color='#315CEB'><b>CG</b></font> &nbsp; <b>ClaimGuard</b>", ParagraphStyle("CGBrand", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=palette["navy"])),
            Paragraph(f"<font color='#64748B'>GENERATED {escape(generated_at.upper())}</font>", ParagraphStyle("CGBrandRight", fontName="Helvetica", fontSize=6.5, leading=8, textColor=palette["muted"], alignment=TA_RIGHT)),
        ]],
        colWidths=[95 * mm, 85 * mm],
    )
    brand.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), palette["surface"]),
        ("BOX", (0, 0), (-1, -1), 0.6, palette["line"]),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.extend([brand, Spacer(1, 12), Paragraph("Invoice review report", styles["title"])])
    story.append(Paragraph("A clear summary of the invoice, extracted products, market evidence and review signals.", styles["subtitle"]))

    status_color = palette["amber"] if "review" in status.lower() or "pending" in status.lower() else palette["green"]
    status_bg = palette["amber_light"] if status_color == palette["amber"] else palette["green_light"]
    status_table = Table([[Paragraph(f"<b>STATUS</b> &nbsp; {escape(status.upper())}", ParagraphStyle("CGStatus", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=status_color))]], colWidths=[180 * mm])
    status_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), status_bg),
        ("BOX", (0, 0), (-1, -1), 0.5, palette["line"]),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([status_table, Spacer(1, 9)])

    def metric_card(label: str, value: str, note: str = "") -> Table:
        content = [Paragraph(escape(label.upper()), styles["card_label"]), Spacer(1, 3), Paragraph(escape(value), styles["card_value"])]
        if note:
            content.extend([Spacer(1, 2), Paragraph(escape(note), styles["small"])])
        t = Table([[content]], colWidths=[43.5 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ("BOX", (0, 0), (-1, -1), 0.6, palette["line"]),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return t

    risk_status_key = str(risk.get("status") or "").lower()
    risk_is_assessed = (
        risk_status_key not in {"unassessed", "not_assessed", "pending"}
        and str(risk_level).lower() not in {"unassessed", "not assessed", "not scored"}
    )
    risk_metric = f"{float(risk_score):.0f}/100" if isinstance(risk_score, (int, float)) and risk_is_assessed else "Not assessed"
    metrics = Table([[
        metric_card("Invoice total", money(total)),
        metric_card("Product lines", str(len(line_items)), f"{total_units:g} units"),
        metric_card("Market verified", f"{market_verified_count}/{len(line_items)}", "products with usable sources"),
        metric_card("Risk score", risk_metric, risk_level),
    ]], colWidths=[45 * mm] * 4)
    metrics.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.extend([metrics, Paragraph("Invoice information", styles["section"])])

    vendor_method = str(extracted.get("vendor_identification_method") or "").lower()
    vendor_detection = (
        "Detected from invoice logo/header" if vendor_method in {"logo_ocr", "header_wordmark_ocr"}
        else "Detected from invoice text" if vendor and not str(vendor).lower().startswith("unknown")
        else "Not confidently identified - manual review needed"
    )
    info_rows = [
        [Paragraph("VENDOR", styles["label"]), paragraph(vendor, styles["value"]), Paragraph("INVOICE NUMBER", styles["label"]), paragraph(invoice_number, styles["value"])],
        [Paragraph("VENDOR DETECTION", styles["label"]), paragraph(vendor_detection, styles["value"]), Paragraph("CURRENCY", styles["label"]), paragraph(currency, styles["value"])],
        [Paragraph("ISSUE DATE", styles["label"]), paragraph(issue_date, styles["value"]), Paragraph("ORDER / PO NUMBER", styles["label"]), paragraph(order_number, styles["value"])],
        [Paragraph("PURCHASE / ORDER DATE", styles["label"]), paragraph(purchase_date, styles["value"]), Paragraph("PROMISED DATE", styles["label"]), paragraph(promised_date, styles["value"])],
        [Paragraph("BILL TO", styles["label"]), paragraph(buyer, styles["value"]), Paragraph("PAYMENT TERMS", styles["label"]), paragraph(payment_terms, styles["value"])],
    ]
    info = Table(info_rows, colWidths=[32 * mm, 58 * mm, 34 * mm, 56 * mm])
    info.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), palette["surface"]),
        ("BACKGROUND", (2, 0), (2, -1), palette["surface"]),
        ("BOX", (0, 0), (-1, -1), 0.6, palette["line"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, palette["line"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(info)
    story.append(Paragraph(f"Product purchase / order date: {escape(txt(purchase_date))}", styles["small"]))

    # ---------------------------------------------------------
    # EXTRACTION QUALITY, FIELD PROVENANCE AND FULL LINE DETAIL
    # ---------------------------------------------------------
    # These diagnostics are deterministic parser checks, not OCR/ML accuracy.
    story.append(Paragraph("Extraction quality and completeness", styles["section"]))
    extraction_warnings = extracted.get("extraction_warnings") if isinstance(extracted.get("extraction_warnings"), list) else []
    completeness = extracted.get("extraction_completeness_score")
    try:
        completeness_value = float(completeness) if completeness is not None else None
    except (TypeError, ValueError):
        completeness_value = None
    if completeness_value is not None:
        completeness_text = f"{completeness_value:.0f}/100 — row-completeness heuristic only; not OCR accuracy or model confidence"
    else:
        completeness_text = "Not recorded by the extraction pipeline"
    reconciliation_label = str(reconciliation or extracted.get("total_reconciliation") or "not_available").replace("_", " ").title()
    quality_rows = [
        ("Extraction completeness", completeness_text),
        ("Detected product lines", str(extracted.get("product_line_count") if extracted.get("product_line_count") is not None else len(line_items))),
        ("Sum of extracted line totals", money(line_total)),
        ("Invoice-total reconciliation", reconciliation_label),
    ]
    if extraction_warnings:
        readable_warnings = []
        warning_labels = {
            "vendor_not_identified": "Vendor name was not identified",
            "invoice_number_not_identified": "Invoice number was not identified",
            "no_product_rows_extracted": "No product rows were extracted",
            "some_product_rows_are_incomplete": "One or more product rows have incomplete fields",
            "product_identity_requires_review": "One or more product names require manual review",
            "line_items_do_not_reconcile_to_invoice_total": "Extracted line totals do not reconcile with the invoice total",
        }
        for warning in extraction_warnings:
            key = str(warning)
            readable_warnings.append(warning_labels.get(key, key.replace("_", " ").capitalize()))
        quality_rows.append(("Extraction warnings", "\n".join(readable_warnings)))
    else:
        quality_rows.append(("Extraction warnings", "No deterministic extraction warning was recorded. This does not prove that every printed field was captured."))
    optional_review_fields = {
        "invoice_date": "Invoice date",
        "customer_name": "Bill-to / buyer",
        "order_id": "PO / order number",
        "subtotal": "Subtotal",
        "discount": "Discount",
        "tax_amount": "Tax / VAT",
        "payment_terms": "Payment terms",
        "payment_method": "Payment method",
        "due_date": "Due date",
        "amount_paid": "Amount paid",
        "balance_due": "Balance due",
    }
    not_detected = [label for key, label in optional_review_fields.items() if extracted.get(key) is None or extracted.get(key) == ""]
    if not_detected:
        quality_rows.append((
            "Not detected / not stated",
            ", ".join(not_detected) + ". Check the original invoice; these fields may not appear on the document.",
        ))
    story.append(_kv_table(quality_rows, styles))

    # Include all structured scalar/JSON fields except technical payloads that
    # are intentionally kept out of a human-facing report (raw OCR transcript,
    # internal provenance object, and line items shown separately below).
    hidden_extraction_keys = {
        "line_items", "raw_text_preview", "field_provenance",
        "extraction_warnings", "extraction_completeness_score",
        "product_line_count", "line_items_total", "total_reconciliation",
    }
    extra_field_rows = []
    preferred_field_order = [
        "subtotal", "discount", "discount_amount", "tax", "tax_amount",
        "vat", "vat_amount", "shipping", "shipping_amount",
        "amount_paid", "paid_amount", "balance_due", "due_date",
        "payment_method", "payment_status", "transaction_id",
        "reference_number", "bank_name", "customer_address",
        "vendor_address", "contact_number", "email",
        "extraction_status", "extraction_method", "raw_text_length",
    ]
    included_keys = set()
    for key in preferred_field_order:
        if key in extracted and extracted.get(key) is not None:
            extra_field_rows.append((_report_label(key), _report_value(extracted.get(key), 1800)))
            included_keys.add(key)
    for key, value in extracted.items():
        if key in hidden_extraction_keys or key in included_keys or value is None:
            continue
        if key in {"vendor_name", "invoice_number", "invoice_date", "purchase_order_date", "promised_date", "order_id", "customer_name", "payment_terms", "currency", "total_amount"}:
            continue
        if str(key).startswith("_"):
            continue
        # Do not serialize large text dumps; structured fields remain included.
        if isinstance(value, str) and len(value) > 2500:
            continue
        extra_field_rows.append((_report_label(key), _report_value(value, 1800)))
    if extra_field_rows:
        story.append(Paragraph("Other extracted invoice fields", styles["section"]))
        story.append(_kv_table(extra_field_rows, styles))

    provenance = extracted.get("field_provenance") if isinstance(extracted.get("field_provenance"), dict) else {}
    provenance_rows = []
    for field_name, field_evidence in provenance.items():
        if not isinstance(field_evidence, dict) or field_name in {"raw_text_preview", "ocr_metadata", "field_provenance"}:
            continue
        source_key = str(field_evidence.get("source") or "not_recorded")
        source_name = {
            "ocr_text_match": "OCR text match",
            "structured_extractor": "Structured extractor",
            "ocr_table_extraction": "OCR table extraction",
            "not_recorded": "Not recorded",
        }.get(source_key, source_key.replace("_", " ").capitalize())
        confidence_value = field_evidence.get("confidence")
        if isinstance(confidence_value, (int, float)):
            source_name += f"; heuristic confidence {float(confidence_value) * 100:.0f}% (not ML accuracy)"
        provenance_rows.append((_report_label(field_name), source_name))
    if provenance_rows:
        story.append(Paragraph("Field extraction provenance", styles["section"]))
        story.append(Paragraph("These labels describe the extraction path recorded by the parser. Any confidence value is heuristic and must not be interpreted as OCR accuracy.", styles["small"]))
        story.append(_kv_table(provenance_rows, styles))

    if line_items:
        story.append(Paragraph("Extracted product-line details", styles["section"]))
        item_detail_rows = []
        for item_index, item in enumerate(line_items, start=1):
            product_name = item.get("product") or item.get("product_name") or item.get("description") or f"Item {item_index}"
            quantity_text = _report_value(item.get("quantity"))
            if item.get("unit"):
                quantity_text += f" {_report_value(item.get('unit'))}"
            detail_values = [
                ("SKU / model", item.get("sku") or item.get("model") or item.get("product_code")),
                ("Description", item.get("description") if item.get("description") != product_name else None),
                ("Quantity", quantity_text),
                ("Unit price", money(item.get("unit_price"), currency)),
                ("Discount", money(item.get("discount") or item.get("discount_amount"), currency)),
                ("Tax", money(item.get("tax") or item.get("tax_amount"), currency)),
                ("Line total", money(item.get("line_amount") or item.get("line_total") or item.get("amount"), currency)),
            ]
            known_item_keys = {
                "product", "product_name", "name", "description", "sku", "model",
                "product_code", "quantity", "qty", "unit", "unit_price", "price",
                "discount", "discount_amount", "tax", "tax_amount",
                "line_amount", "line_total", "amount", "extraction_warnings",
                "line_number",
            }
            for item_key, item_value in item.items():
                if item_key in known_item_keys or item_value is None or str(item_key).startswith("_"):
                    continue
                if isinstance(item_value, str) and len(item_value) > 1500:
                    continue
                detail_values.append((_report_label(item_key), _report_value(item_value, 1000)))
            detail_lines = [f"{label}: {_report_value(value)}" for label, value in detail_values if value not in (None, "", "-")]
            row_warnings = item.get("extraction_warnings") if isinstance(item.get("extraction_warnings"), list) else []
            if row_warnings:
                detail_lines.append("Row warnings: " + "; ".join(str(w).replace("_", " ") for w in row_warnings))
            item_detail_rows.append([_p(f"{item_index}. {product_name}", styles["label"]), _p("\n".join(detail_lines) or "No additional line-item fields were stored.", styles["value"])])
        story.append(_two_column_rows(item_detail_rows, styles))

    story.append(Paragraph("What needs attention", styles["section"]))
    summary_rows = []
    if not line_items:
        summary_rows.append([Paragraph("PRODUCT EXTRACTION", styles["label"]), paragraph("No product rows were identified. Review the original invoice image and run extraction again.", styles["value"])])
    else:
        product_line_label = "product line" if len(line_items) == 1 else "product lines"
        product_summary = f"{len(line_items)} {product_line_label} and {total_units:g} units detected."
        if reconciliation == "matched":
            product_summary += f" Item totals reconcile with the invoice total ({money(line_total)})."
        elif reconciliation == "mismatch":
            product_summary += f" Warning: item totals ({money(line_total)}) do not match the invoice total ({money(total)})."
        summary_rows.append([Paragraph("PRODUCT EXTRACTION", styles["label"]), paragraph(product_summary, styles["value"])])

    observed_product_count = len({record.get("index") for record in market_covered})
    scanned_product_count = len(matched_product_analyses)
    market_status = str(market.get("status") or "").lower()
    market_error = str(invoice.get("market_research_error") or market.get("error_message") or "").strip()
    if market_status == "provider_error" or market_error:
        market_text = "OCR and product extraction were saved, but online market research failed. Check the search provider and retry the market check; no price benchmark was calculated."
    elif market_status == "pending":
        market_text = "Invoice details were extracted. Product-by-product market research is still running; download the report again after the analysis finishes."
    elif market_verified_count == len(line_items) and line_items:
        market_text = f"Verified market averages are available for all {len(line_items)} products."
    elif market_verified_count:
        market_text = f"Verified market averages are available for {market_verified_count} of {len(line_items)} products. Other products remain unscored."
    elif observed_product_count:
        market_text = f"Listings were found for {observed_product_count} product(s), but they do not yet meet the evidence threshold for a reliable average. No percentage is calculated."
    elif line_items and not scanned_product_count:
        product_line_label = "product line" if len(line_items) == 1 else "product lines"
        market_text = f"Market research has not been run for these {len(line_items)} {product_line_label} yet. Re-run OCR & Market Check to search each product separately."
    elif line_items:
        market_text = f"Market research ran for {scanned_product_count} of {len(line_items)} products, but no comparable listing passed validation. No average or percentage is shown."
    else:
        market_text = "No structured product lines are available to search. Fix or rerun invoice extraction before market research."
    summary_rows.append([Paragraph("MARKET CHECK", styles["label"]), paragraph(market_text, styles["value"])])

    checks = verification.get("checks") if isinstance(verification.get("checks"), dict) else {}
    checks = dict(checks)
    # Normalize legacy/newer verification aliases so the PDF shows all checks
    # consistently regardless of which endpoint created the record.
    check_aliases = {
        "code_present": ("verification_code_present", "verification_code_found"),
        "format_valid": ("verification_code_format_valid", "code_format_valid"),
        "duplicate_code": ("duplicate_verification_code", "duplicate_code_check"),
        "document_check": ("document_verified", "document_valid"),
        "invoice_number_present": ("invoice_number_found",),
        "vendor_present": ("vendor_identified",),
        "total_amount_present": ("total_found", "total_present"),
    }
    for canonical, aliases in check_aliases.items():
        if canonical not in checks:
            alias = next((name for name in aliases if name in checks), None)
            if alias:
                checks[canonical] = checks[alias]
    if verification.get("status") == "verification_required" or checks.get("code_present") is False:
        verification_text = "No verification code was detected. This means the code-based check is incomplete; it does not by itself prove the invoice is false."
    else:
        verification_text = txt(verification.get("message"), "Document checks are recorded in ClaimGuard.")
    summary_rows.append([Paragraph("DOCUMENT CHECK", styles["label"]), paragraph(verification_text, styles["value"])])

    if anomaly_texts:
        risk_text = "; ".join(anomaly_texts[:2]).rstrip(" .")
        risk_text += ". Human review is recommended; an anomaly is a warning, not proof of fraud."
    else:
        risk_text = f"Risk level: {risk_level}. No deterministic anomaly was recorded."
    summary_rows.append([Paragraph("RISK / REVIEW", styles["label"]), paragraph(risk_text, styles["value"])])
    summary_table = Table(summary_rows, colWidths=[35 * mm, 145 * mm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), palette["surface"]),
        ("BOX", (0, 0), (-1, -1), 0.6, palette["line"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, palette["line"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([summary_table, Spacer(1, 7)])
    ai_analysis = risk.get("ai_analysis") if isinstance(risk.get("ai_analysis"), dict) else {}
    if ai_analysis:
        story.append(Paragraph(
            f"AI risk assessment: {escape(txt(ai_analysis.get('model')))}; status: {escape(txt(ai_analysis.get('status')))}.",
            styles["small"],
        ))
    story.append(Paragraph("How to read the market difference", styles["section"]))
    story.append(Paragraph("Difference % = (invoice unit price - market average) / market average × 100. Positive means above the observed average; negative means below. Product match confidence summarizes accepted source identity scores. Price alignment is a closeness indicator (100 minus the absolute percentage difference), not an ML accuracy or fraud probability. A price benchmark and alignment score require at least two independent same-currency domains; match confidence can summarize the accepted identity evidence available.", styles["note"]))

    story.append(PageBreak())
    story.append(Paragraph("Product-by-product price comparison", styles["title"]))
    story.append(Paragraph("Each product is assessed separately. Prices of different products are never combined into one invoice-wide market average.", styles["subtitle"]))
    story.append(Paragraph("No combined invoice-wide average", styles["note"]))

    headers = ["#", "PRODUCT DESCRIPTION", "QTY", "INVOICE UNIT", "LINE TOTAL", "MARKET AVG.", "DIFF.", "MATCH", "PRICE FIT"]
    table_data: list[list[Any]] = [[Paragraph(escape(value), styles["table_head"]) for value in headers]]
    for index, item in enumerate(line_items, start=1):
        analysis_entry = matched_product_analyses.get(index - 1, {})
        if legacy_single_product_market and len(line_items) == 1 and not analysis_entry:
            analysis_entry = {"product": item.get("product"), "market": legacy_single_product_market}
        item_market = analysis_entry.get("market") if isinstance(analysis_entry.get("market"), dict) else {}
        stats = item_market.get("market_statistics") if isinstance(item_market.get("market_statistics"), dict) else {}
        sources = item_market.get("sources") if isinstance(item_market.get("sources"), list) else []
        independent_domains = _independent_domains(item_market, sources)
        average = stats.get("average") if sources and independent_domains >= 2 else None
        item_currency = stats.get("currency") or currency
        diff_percent = item_market.get("price_difference_percent") if average is not None else None
        invoice_unit = item.get("unit_price")
        if diff_percent is None and average not in (None, 0) and invoice_unit is not None:
            diff_percent = (float(invoice_unit) - float(average)) / float(average) * 100
        entry_status = str(analysis_entry.get("status") or item_market.get("status") or "").lower()
        if average is not None:
            diff_text = percent(diff_percent)
            market_average_text = money(average, item_currency)
        elif entry_status == "provider_error":
            diff_text = "Not scored"
            market_average_text = "Search failed"
        elif entry_status == "pending":
            diff_text = "Pending"
            market_average_text = "Searching"
        elif sources:
            diff_text = "Not scored"
            market_average_text = f"Needs 2 sources ({independent_domains})"
        elif analysis_entry:
            diff_text = "Not scored"
            market_average_text = "No verified match"
        else:
            diff_text = "Not scanned"
            market_average_text = "Not scanned"

        source_confidences = []
        for source in sources:
            try:
                value = float(source.get("match_confidence"))
                if 0 <= value <= 1:
                    source_confidences.append(value)
            except (TypeError, ValueError, AttributeError):
                continue
        match_confidence = item_market.get("market_match_confidence")
        if match_confidence is None and source_confidences:
            match_confidence = sum(source_confidences) / len(source_confidences) * 100
        match_text = score_percent(match_confidence, fraction_allowed=True)

        alignment = item_market.get("price_alignment_score") if average is not None else None
        if alignment is None and average not in (None, 0) and diff_percent is not None:
            try:
                alignment = max(0.0, 100.0 - abs(float(diff_percent)))
            except (TypeError, ValueError):
                alignment = None
        alignment_text = score_percent(alignment) if average is not None and independent_domains >= 2 else "Not scored"

        table_data.append([
            Paragraph(str(index), styles["table"]),
            Paragraph(escape(txt(item.get("product") or item.get("description"), "Product name not identified")), styles["product"]),
            Paragraph(escape(txt(item.get("quantity"), "-")), styles["table"]),
            Paragraph(escape(money(invoice_unit)), styles["table"]),
            Paragraph(escape(money(item.get("line_amount"), currency)), styles["table"]),
            Paragraph(escape(market_average_text), styles["table"]),
            Paragraph(escape(diff_text), styles["table"]),
            Paragraph(escape(match_text), styles["table"]),
            Paragraph(escape(alignment_text), styles["table"]),
        ])

    if not line_items:
        table_data.append([Paragraph("No structured product lines were extracted from this invoice.", styles["table"])] + [Paragraph("-", styles["table"]) for _ in range(8)])

    products_table = Table(table_data, colWidths=[5 * mm, 46 * mm, 10 * mm, 22 * mm, 22 * mm, 24 * mm, 18 * mm, 16 * mm, 17 * mm], repeatRows=1, hAlign="LEFT")
    product_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), palette["navy"]),
        ("BOX", (0, 0), (-1, -1), 0.6, palette["line"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, palette["line"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for row_index in range(1, len(table_data)):
        if row_index % 2 == 0:
            product_commands.append(("BACKGROUND", (0, row_index), (-1, row_index), palette["surface"]))
    products_table.setStyle(TableStyle(product_commands))
    story.append(products_table)
    if len(line_items) > 1:
        story.append(Spacer(1, 4))

    if market_covered:
        story.append(Paragraph("Market price evidence", styles["section"]))
        if not market_verified_count:
            story.append(Paragraph("The following listing observations were retained, but there are not enough independent verified sources to calculate a reliable average.", styles["small"]))
        for record in market_covered:
            item = record["item"]
            item_market = record["market"]
            sources = record["sources"]
            model_sources = (
                item_market.get("model_level_sources")
                if isinstance(item_market.get("model_level_sources"), list)
                else sources
            )
            difference_groups = (
                item_market.get("specification_difference_groups")
                if isinstance(item_market.get("specification_difference_groups"), list)
                else []
            )
            evidence_sources: list[dict[str, Any]] = []
            seen_evidence_urls: set[str] = set()
            grouped_observations = list(model_sources)
            grouped_observations.extend(
                source
                for group in difference_groups
                if isinstance(group, dict)
                for source in (group.get("sources") or [])
                if isinstance(source, dict)
            )
            grouped_observations.extend(
                source
                for edition in (item_market.get("related_edition_comparisons") or [])
                if isinstance(edition, dict)
                for source in (edition.get("sources") or [])
                if isinstance(source, dict)
            )
            grouped_observations.extend(
                source for source in (item_market.get("excluded_sources") or [])
                if isinstance(source, dict)
            )
            for source in grouped_observations:
                source_key = str(source.get("url") or f"{source.get('source_name')}|{source.get('title')}")
                if source_key in seen_evidence_urls:
                    continue
                seen_evidence_urls.add(source_key)
                evidence_sources.append(source)
            displayed_sources = evidence_sources[:8]
            item_search_diagnostics = (
                item_market.get("search_diagnostics")
                if isinstance(item_market.get("search_diagnostics"), dict)
                else {}
            )
            hidden_evidence_count = (
                len(evidence_sources) - len(displayed_sources)
                + int(item_search_diagnostics.get("search_results_excluded_by_relevance") or 0)
                + int(item_search_diagnostics.get("search_results_not_fetched_due_to_candidate_cap") or 0)
            )
            product_name = txt(item.get("product"), "Product")
            story.append(Paragraph(escape(product_name), styles["product"]))
            market_label = item_market.get("market_product_label")
            if market_label and str(market_label) != product_name:
                story.append(Paragraph(escape(str(market_label)), styles["small"]))
            for edition in item_market.get("related_edition_comparisons") or []:
                if isinstance(edition, dict) and edition.get("edition_label"):
                    story.append(Paragraph(escape(str(edition["edition_label"])), styles["small"]))
            stats = item_market.get("market_statistics") if isinstance(item_market.get("market_statistics"), dict) else {}
            item_currency = stats.get("currency") or currency
            invoice_unit = item.get("unit_price")
            independent_domains = _independent_domains(item_market, sources)
            benchmark_average = stats.get("average") if independent_domains >= 2 else None
            difference_percent = item_market.get("price_difference_percent") if benchmark_average is not None else None
            if difference_percent is None and benchmark_average not in (None, 0) and invoice_unit is not None:
                difference_percent = (float(invoice_unit) - float(benchmark_average)) / float(benchmark_average) * 100
            source_confidences = []
            for source in sources:
                try:
                    confidence = float(source.get("match_confidence"))
                    if 0 <= confidence <= 1:
                        source_confidences.append(confidence)
                except (TypeError, ValueError, AttributeError):
                    continue
            match_confidence = (sum(source_confidences) / len(source_confidences) * 100) if source_confidences else None
            price_alignment = max(0.0, 100.0 - abs(float(difference_percent))) if difference_percent is not None else None
            difference_amount = item_market.get("price_difference")
            if difference_amount is None and stats.get("average") is not None and invoice_unit is not None:
                difference_amount = float(invoice_unit) - float(stats["average"])
            market_metrics = [[
                Paragraph("INVOICE UNIT", styles["card_label"]),
                Paragraph("LOWEST", styles["card_label"]),
                Paragraph("MARKET AVG.", styles["card_label"]),
                Paragraph("MEDIAN", styles["card_label"]),
                Paragraph("HIGHEST", styles["card_label"]),
                Paragraph("DIFFERENCE", styles["card_label"]),
                Paragraph("MATCH CONF.", styles["card_label"]),
                Paragraph("PRICE ALIGN.", styles["card_label"]),
            ], [
                Paragraph(escape(money(invoice_unit, item_currency)), styles["table"]),
                Paragraph(escape(money(stats.get("lowest") if independent_domains >= 2 else None, item_currency)), styles["table"]),
                Paragraph(escape(money(benchmark_average, item_currency)), styles["table"]),
                Paragraph(escape(money(stats.get("median") if independent_domains >= 2 else None, item_currency)), styles["table"]),
                Paragraph(escape(money(stats.get("highest") if independent_domains >= 2 else None, item_currency)), styles["table"]),
                Paragraph(escape(percent(difference_percent) + (f" ({money(difference_amount, item_currency)})" if difference_amount is not None and difference_percent is not None else "")), styles["table"]),
                Paragraph(escape("Not scored" if match_confidence is None else f"{match_confidence:.0f}%"), styles["table"]),
                Paragraph(escape("Not scored" if price_alignment is None else f"{price_alignment:.0f}%"), styles["table"]),
            ]]
            metric_table = Table(market_metrics, colWidths=[22.5 * mm] * 8)
            metric_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), palette["surface"]),
                ("BOX", (0, 0), (-1, -1), 0.5, palette["line"]),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, palette["line"]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.extend([metric_table, Spacer(1, 3)])
            model_stats = item_market.get("model_level_statistics") if isinstance(item_market.get("model_level_statistics"), dict) else {}
            model_domain_value = item_market.get("model_level_independent_domains")
            if model_domain_value is None:
                model_domain_value = (item_market.get("market_quality") or {}).get("model_level_independent_domains")
            if model_domain_value is None:
                model_domain_value = _independent_domains(item_market, model_sources)
            model_domains = int(model_domain_value or 0)
            model_currency = model_stats.get("currency") or item_currency
            model_average = model_stats.get("average") if model_domains >= 2 else None
            model_label = (
                "Indicative Model-Level Comparison"
                if item_market.get("model_level_is_indicative")
                else "Model-Level Comparison"
            )
            story.append(Paragraph(
                f"{model_label}: {len(model_sources)} page-verified observation(s) across {model_domains} independent retailer domain(s). "
                f"Average: {money(model_average, model_currency)}; "
                f"lowest: {money(model_stats.get('lowest'), model_currency)}; "
                f"highest: {money(model_stats.get('highest'), model_currency)}; "
                f"median: {money(model_stats.get('median'), model_currency)}. "
                "Unknown optional specifications are labeled and excluded from the exact-variant benchmark; explicit conflicts are shown separately.",
                styles["small"],
            ))
            comparison_counts = item_market.get("comparison_counts") if isinstance(item_market.get("comparison_counts"), dict) else {}
            story.append(Paragraph(
                f"Results found: {comparison_counts.get('candidate_results_found', 0)}; "
                f"page-verified prices: {comparison_counts.get('page_verified_prices', len(evidence_sources))}; "
                f"incomplete specifications: {comparison_counts.get('incomplete_specifications', 0)}; "
                f"out of stock: {comparison_counts.get('out_of_stock_prices', 0)}; "
                f"availability unknown: {comparison_counts.get('unknown_availability_prices', 0)}.",
                styles["small"],
            ))
            confidence_value = item_market.get("market_match_confidence")
            if confidence_value is None:
                confidence_value = item_market.get("market_match_confidence_score")
            try:
                confidence_display = f"{float(confidence_value):.0f}/100"
            except (TypeError, ValueError):
                confidence_display = "Not scored"
            story.append(Paragraph(
                f"Price alignment score: {_report_value(item_market.get('price_alignment_score'))}; "
                f"Market match confidence: {confidence_display}",
                styles["small"],
            ))
            comparison = item_market.get("price_comparison") if isinstance(item_market.get("price_comparison"), dict) else {}
            if comparison:
                risk_points = comparison.get("price_risk_points")
                risk_text = f"{float(risk_points):.1f} / 30 points" if isinstance(risk_points, (int, float)) else "Not assessed"
                comparison_note = (
                    f"Comparison status: {txt(comparison.get('status'), 'Not assessed')}. "
                    f"Independent retailer domains: {txt(comparison.get('independent_domain_count'), '0')} "
                    f"(minimum {txt(comparison.get('minimum_independent_domains'), '2')}). "
                    f"Price-risk contribution: {risk_text}. This is a rule-based price-deviation signal, not a fraud probability."
                )
                story.append(Paragraph(escape(comparison_note), styles["small"]))
            story.append(Spacer(1, 5))
            related_editions = item_market.get("related_edition_comparisons") if isinstance(item_market.get("related_edition_comparisons"), list) else []
            if related_editions:
                story.append(Paragraph("Different editions are shown for context only. Similar but different product editions are excluded from this product's average and are not used for the price difference.", styles["small"]))
            source_rows = [[
                Paragraph("SOURCE", styles["table_head"]),
                Paragraph("PRICE / EVIDENCE", styles["table_head"]),
                Paragraph("AVAILABILITY", styles["table_head"]),
                Paragraph("MATCH / SPECS", styles["table_head"]),
                Paragraph("LINK", styles["table_head"]),
            ]]
            for source in displayed_sources:
                if not isinstance(source, dict):
                    continue
                url = str(source.get("url") or "").strip()
                domain = source.get("source_name") or source.get("domain") or (_report_urlsplit(url).netloc if url else "Source")
                source_link = Paragraph("<link href=\"%s\" color=\"#315CEB\">Open listing</link>" % escape(url, {"\"": "&quot;"}), styles["source"]) if url.startswith(("http://", "https://")) else Paragraph("-", styles["table"])
                raw_match_status = str(source.get("market_comparison_status") or source.get("specification_status") or "")
                match_status = {
                    "exact_variant_confirmed": "Exact variant confirmed",
                    "optional_specifications_unknown": "Specifications not confirmed",
                    "specification_difference": "Specification difference",
                }.get(raw_match_status, raw_match_status.replace("_", " ") or "Not stated")
                group_label = str(source.get("comparison_group") or "")
                match_detail = escape(match_status.replace("_", " "))
                if group_label:
                    match_detail += f"<br/>{escape(group_label)}"
                if source.get("exclusion_reason"):
                    match_detail += f"<br/>{escape(str(source['exclusion_reason']))}"
                source_rows.append([
                    Paragraph(escape(str(domain)) + "<br/>" + escape(str(source.get("title") or "")[:180]), styles["table"]),
                    Paragraph(escape(money(source.get("price"), str(source.get("currency") or currency))) + "<br/>" + escape(str(source.get("price_source") or source.get("retrieval_method") or "Not stated")[:100]), styles["table"]),
                    Paragraph(escape(_report_availability(source.get("availability"))), styles["table"]),
                    Paragraph(match_detail, styles["table"]),
                    source_link,
                ])
            source_table = Table(source_rows, colWidths=[38 * mm, 40 * mm, 34 * mm, 42 * mm, 26 * mm], repeatRows=1)
            source_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), palette["blue"]),
                ("BOX", (0, 0), (-1, -1), 0.5, palette["line"]),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, palette["line"]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.extend([source_table, Spacer(1, 6)])
            if hidden_evidence_count:
                story.append(Paragraph(
                    f"{hidden_evidence_count} additional market listings were not shown.",
                    styles["small"],
                ))
    else:
        story.append(Spacer(1, 9))
        if line_items and not matched_product_analyses:
            note_text = "Market research has not been run for these products yet. Use the Re-run OCR & Market Check action in the invoice details page. The PDF does not reuse an old market result unless its product identity matches."
        else:
            note_text = "No comparable web price passed the current product, model, variant, currency and page-price checks. Stock status is reported separately. ClaimGuard has deliberately left the market average and percentage blank rather than compare a different or unverified product."
        story.append(Paragraph(escape(note_text), styles["note"]))

    # Keep reviewer and validation information concise and understandable.
    story.append(Paragraph("Verification and review", styles["section"]))
    check_rows = []
    if checks:
        human_labels = {
            "code_present": "Verification code found",
            "format_valid": "Verification code format",
            "duplicate_code": "Duplicate verification code",
            "document_check": "Document check",
            "invoice_number_present": "Invoice number found",
            "vendor_present": "Vendor identified",
            "total_amount_present": "Invoice total found",
        }
        for key, label in human_labels.items():
            if key not in checks:
                continue
            value = checks.get(key)
            if key == "duplicate_code":
                result = "No duplicate found" if value is False else ("Duplicate found" if value else "Not checked")
            elif key == "code_present":
                result = "Found" if value is True else ("Not found" if value is False else "Not checked")
            elif key == "format_valid" and checks.get("code_present") is False:
                result = "Not checked - no code found"
            elif key == "format_valid":
                result = "Valid" if value is True else ("Invalid" if value is False else "Not checked")
            elif key == "document_check":
                result = "Passed" if value is True else ("Not verified" if value is False else "Not checked")
            elif key == "invoice_number_present":
                result = "Found" if value is True else ("Missing" if value is False else "Not checked")
            elif key == "vendor_present":
                result = "Identified" if value is True else ("Not identified" if value is False else "Not checked")
            elif key == "total_amount_present":
                result = "Found" if value is True else ("Missing" if value is False else "Not checked")
            else:
                result = "Passed" if value is True else ("Not passed" if value is False else "Not checked")
            check_rows.append([Paragraph(escape(label), styles["table"]), Paragraph(escape(result), styles["table"])])
    if not check_rows:
        check_rows.append([Paragraph("Document verification", styles["table"]), paragraph(verification.get("status"), styles["table"])])
    review_rows = [[Paragraph("CHECK", styles["table_head"]), Paragraph("RESULT", styles["table_head"])]] + check_rows
    review_table = Table(review_rows, colWidths=[85 * mm, 95 * mm], repeatRows=1)
    review_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), palette["navy"]),
        ("BOX", (0, 0), (-1, -1), 0.5, palette["line"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, palette["line"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(review_table)

    if decision and (decision.get("decision") or decision.get("reviewer_name")):
        story.append(Paragraph("Reviewer decision", styles["section"]))
        story.append(Paragraph(escape(f"{txt(decision.get('decision'))} - {txt(decision.get('reviewer_name'))}"), styles["value"]))
        if decision.get("note"):
            story.append(Paragraph(escape(str(decision.get("note"))), styles["small"]))
    audit_trail = invoice.get("review_audit_trail") if isinstance(invoice.get("review_audit_trail"), list) else []
    for audit_event in audit_trail:
        if isinstance(audit_event, dict) and audit_event.get("actor_name"):
            story.append(Paragraph(
                f"Review audit: {escape(str(audit_event['actor_name']))} - {escape(txt(audit_event.get('event_type')))}",
                styles["small"],
            ))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Important: A missing market match means that no sufficiently comparable public price was verified at report time. It does not mean the product is unavailable or that the invoice price is wrong. A risk alert is a review signal, not proof of fraud.", styles["small"]))

    document.build(story, onFirstPage=page_decor, onLaterPages=page_decor)
    return buffer.getvalue()

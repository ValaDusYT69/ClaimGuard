from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


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


def build_invoice_report(
    invoice: dict[str, Any]
) -> bytes:

    buffer = BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=19 * mm,
        title="ClaimGuard Invoice Review Report",
        author="ClaimGuard",
    )

    sample = getSampleStyleSheet()

    styles = {

        "title":
            ParagraphStyle(
                "ClaimGuardTitle",
                parent=sample["Title"],
                fontName="Helvetica-Bold",
                fontSize=20,
                leading=25,
                alignment=TA_LEFT,
                textColor=colors.HexColor(
                    "#0f172a"
                ),
                spaceAfter=5,
            ),

        "subtitle":
            ParagraphStyle(
                "ClaimGuardSubtitle",
                parent=sample["Normal"],
                fontName="Helvetica",
                fontSize=9,
                leading=13,
                textColor=colors.HexColor(
                    "#64748b"
                ),
                spaceAfter=10,
            ),

        "section":
            ParagraphStyle(
                "ClaimGuardSection",
                parent=sample["Heading2"],
                fontName="Helvetica-Bold",
                fontSize=11,
                leading=15,
                textColor=colors.HexColor(
                    "#1d4ed8"
                ),
                spaceBefore=12,
                spaceAfter=7,
            ),

        "label":
            ParagraphStyle(
                "ClaimGuardLabel",
                parent=sample["Normal"],
                fontName="Helvetica-Bold",
                fontSize=8.5,
                leading=12,
                textColor=colors.HexColor(
                    "#475569"
                ),
            ),

        "value":
            ParagraphStyle(
                "ClaimGuardValue",
                parent=sample["Normal"],
                fontName="Helvetica",
                fontSize=8.5,
                leading=12,
                textColor=colors.HexColor(
                    "#0f172a"
                ),
            ),

        "small":
            ParagraphStyle(
                "ClaimGuardSmall",
                parent=sample["Normal"],
                fontName="Helvetica",
                fontSize=7.8,
                leading=11,
                textColor=colors.HexColor(
                    "#64748b"
                ),
                spaceBefore=6,
            ),

        "note":
            ParagraphStyle(
                "ClaimGuardNote",
                parent=sample["Normal"],
                fontName="Helvetica",
                fontSize=8.5,
                leading=12.5,
                textColor=colors.HexColor(
                    "#334155"
                ),
                backColor=colors.HexColor(
                    "#f8fafc"
                ),
                borderColor=colors.HexColor(
                    "#dbe3ee"
                ),
                borderWidth=0.6,
                borderPadding=7,
                spaceBefore=5,
                spaceAfter=7,
            ),
    }

    extracted = invoice.get(
        "extracted_data"
    )

    if not isinstance(
        extracted,
        dict
    ):
        extracted = {}

    verification = invoice.get(
        "verification"
    )

    if not isinstance(
        verification,
        dict
    ):
        verification = {}

    risk_analysis = invoice.get(
        "risk_analysis"
    )

    if not isinstance(
        risk_analysis,
        dict
    ):
        risk_analysis = {}

    market = invoice.get(
        "market_analysis"
    )

    if not isinstance(
        market,
        dict
    ):
        market = {}

    decision = invoice.get(
        "decision"
    )

    if not isinstance(
        decision,
        dict
    ):
        decision = {}

    ai = risk_analysis.get(
        "ai_analysis"
    )

    if not isinstance(
        ai,
        dict
    ):
        ai = {}

    anomalies = invoice.get(
        "anomalies"
    )

    if not isinstance(
        anomalies,
        list
    ):
        anomalies = []

    audit = invoice.get(
        "review_audit_trail"
    )

    if not isinstance(
        audit,
        list
    ):
        audit = []

    verification_submission = invoice.get(
        "verification_submission"
    )

    if not isinstance(
        verification_submission,
        dict
    ):
        verification_submission = {}

    generated_at = datetime.now(
        timezone.utc
    ).isoformat()

    invoice_number = (
        extracted.get(
            "invoice_number"
        )
        or invoice.get(
            "invoice_number"
        )
        or invoice.get(
            "invoice_id"
        )
        or "-"
    )

    vendor_name = (
        extracted.get(
            "vendor_name"
        )
        or invoice.get(
            "vendor_name"
        )
        or "Unknown vendor"
    )

    amount = (
        extracted.get(
            "total"
        )
        if extracted.get(
            "total"
        ) is not None
        else extracted.get(
            "grand_total"
        )
    )

    currency = (
        extracted.get(
            "currency"
        )
        or "BDT"
    )

    risk_score = invoice.get(
        "risk_score"
    )

    if risk_score is None:
        risk_score = risk_analysis.get(
            "risk_score"
        )

    risk_level = (
        invoice.get(
            "risk_level"
        )
        or risk_analysis.get(
            "risk_level"
        )
        or "-"
    )

    story = []

    story.append(
        Paragraph(
            "ClaimGuard Invoice Review Report",
            styles["title"]
        )
    )

    story.append(
        Paragraph(
            (
                "Explainable invoice verification, anomaly analysis, "
                "market evidence and Finance/Reviewer decision record."
            ),
            styles["subtitle"]
        )
    )

    story.append(
        _kv_table(
            [
                (
                    "Invoice Number",
                    _text(
                        invoice_number
                    )
                ),
                (
                    "Invoice ID",
                    _text(
                        invoice.get(
                            "invoice_id"
                        )
                    )
                ),
                (
                    "Vendor",
                    _text(
                        vendor_name
                    )
                ),
                (
                    "Current Status",
                    _text(
                        invoice.get(
                            "status"
                        )
                    )
                ),
                (
                    "Risk Score",
                    (
                        f"{float(risk_score):.0f}/100"
                        if isinstance(
                            risk_score,
                            (int, float)
                        )
                        else _text(
                            risk_score
                        )
                    )
                ),
                (
                    "Risk Level",
                    _text(
                        risk_level
                    )
                ),
                (
                    "Report Generated",
                    generated_at
                ),
            ],
            styles
        )
    )

    story.append(
        _section(
            "1. Invoice Information",
            styles
        )
    )

    story.append(
        _kv_table(
            [
                (
                    "Invoice Date",
                    _text(
                        extracted.get(
                            "date"
                        )
                        or extracted.get(
                            "invoice_date"
                        )
                    )
                ),
                (
                    "Vendor",
                    _text(
                        vendor_name
                    )
                ),
                (
                    "Quantity",
                    _safe_number(
                        extracted.get(
                            "quantity"
                        )
                    )
                ),
                (
                    "Unit Price",
                    _safe_number(
                        extracted.get(
                            "unit_price"
                        )
                    )
                ),
                (
                    "Subtotal",
                    _safe_number(
                        extracted.get(
                            "subtotal"
                        )
                    )
                ),
                (
                    "Tax / VAT",
                    _safe_number(
                        extracted.get(
                            "tax"
                        )
                        if extracted.get(
                            "tax"
                        ) is not None
                        else extracted.get(
                            "tax_amount"
                        )
                    )
                ),
                (
                    "Total Amount",
                    f"{currency} {_safe_number(amount)}"
                ),
                (
                    "Purchase Order",
                    _text(
                        extracted.get(
                            "po_number"
                        )
                        or extracted.get(
                            "order_id"
                        )
                    )
                ),
                (
                    "Extraction Method",
                    _text(
                        extracted.get(
                            "extraction_method"
                        )
                    )
                ),
            ],
            styles
        )
    )

    story.append(
        _section(
            "2. Verification Result",
            styles
        )
    )

    verification_status = (
        verification.get(
            "status"
        )
        or verification.get(
            "result"
        )
        or invoice.get(
            "status"
        )
    )

    story.append(
        _kv_table(
            [
                (
                    "Verification Status",
                    _text(
                        verification_status
                    )
                ),
                (
                    "Verification Code",
                    _text(
                        extracted.get(
                            "verification_code"
                        )
                        or invoice.get(
                            "verification_code"
                        )
                    )
                ),
                (
                    "Verification Message",
                    _text(
                        verification.get(
                            "message"
                        )
                    )
                ),
                (
                    "Vendor Check",
                    _text(
                        verification.get(
                            "vendor_check"
                        )
                    )
                ),
                (
                    "Calculation / Field Check",
                    _text(
                        verification.get(
                            "calculation_check"
                        )
                    )
                ),
            ],
            styles
        )
    )

    story.append(
        _section(
            "3. Risk & Anomaly Analysis",
            styles
        )
    )

    ai_status = (
        ai.get(
            "status"
        )
        or "-"
    )

    ai_score = ai.get(
        "ai_score"
    )

    ai_model = (
        ai.get(
            "model_name"
        )
        or ai.get(
            "model"
        )
        or "-"
    )

    story.append(
        _kv_table(
            [
                (
                    "Risk Score",
                    (
                        f"{float(risk_score):.0f}/100"
                        if isinstance(
                            risk_score,
                            (int, float)
                        )
                        else _text(
                            risk_score
                        )
                    )
                ),
                (
                    "Risk Level",
                    _text(
                        risk_level
                    )
                ),
                (
                    "AI / ML Status",
                    _text(
                        ai_status
                    )
                ),
                (
                    "AI Score",
                    (
                        f"{float(ai_score):.0f}/100"
                        if isinstance(
                            ai_score,
                            (int, float)
                        )
                        else _text(
                            ai_score
                        )
                    )
                ),
                (
                    "AI Model",
                    _text(
                        ai_model
                    )
                ),
                (
                    "Human Review Required",
                    _text(
                        risk_analysis.get(
                            "human_review_required"
                        )
                    )
                ),
            ],
            styles
        )
    )

    story.append(
        Spacer(
            1,
            5
        )
    )

    story.append(
        _anomaly_table(
            anomalies,
            styles
        )
    )

    story.append(
        _section(
            "4. Why the Invoice Was Flagged",
            styles
        )
    )

    explanation = (
        risk_analysis.get(
            "explanation"
        )
        or risk_analysis.get(
            "summary"
        )
        or risk_analysis.get(
            "reason"
        )
        or "No additional explanation was recorded."
    )

    story.append(
        Paragraph(
            escape(
                _text(
                    explanation
                )
            ).replace(
                "\n",
                "<br/>"
            ),
            styles["note"]
        )
    )

    story.append(
        _section(
            "5. Market Price Evidence",
            styles
        )
    )

    story.append(
        _kv_table(
            [
                (
                    "Analysis Status",
                    _text(
                        market.get(
                            "status"
                        )
                    )
                ),
                (
                    "Invoice Unit Price",
                    _text(
                        market.get(
                            "invoice_unit_price"
                        )
                    )
                ),
                (
                    "Lowest Observed Price",
                    _text(
                        market.get(
                            "lowest_price"
                        )
                    )
                ),
                (
                    "Highest Observed Price",
                    _text(
                        market.get(
                            "highest_price"
                        )
                    )
                ),
                (
                    "Average Price",
                    _text(
                        market.get(
                            "average_price"
                        )
                    )
                ),
                (
                    "Median Price",
                    _text(
                        market.get(
                            "median_price"
                        )
                    )
                ),
                (
                    "Difference %",
                    _text(
                        market.get(
                            "difference_percent"
                        )
                    )
                ),
            ],
            styles
        )
    )

    sources = market.get(
        "sources"
    )

    if not isinstance(
        sources,
        list
    ):
        sources = []

    source_rows = []

    for index, source in enumerate(
        sources,
        start=1
    ):

        if not isinstance(
            source,
            dict
        ):
            continue

        source_name = (
            source.get(
                "source"
            )
            or source.get(
                "name"
            )
            or f"Source {index}"
        )

        source_price = (
            source.get(
                "price"
            )
            if source.get(
                "price"
            ) is not None
            else source.get(
                "current_price"
            )
        )

        source_url = (
            source.get(
                "url"
            )
            or "-"
        )

        source_rows.append(
            [
                _p(
                    source_name,
                    styles["label"]
                ),
                _p(
                    (
                        f"Price: {_text(source_price)}\n"
                        f"URL: {_text(source_url)}"
                    ),
                    styles["value"]
                ),
            ]
        )

    if source_rows:

        story.append(
            Spacer(
                1,
                6
            )
        )

        story.append(
            _two_column_rows(
                source_rows,
                styles
            )
        )

    story.append(
        _section(
            "6. Finance / Reviewer Decision",
            styles
        )
    )

    story.append(
        _kv_table(
            [
                (
                    "Decision",
                    _text(
                        decision.get(
                            "decision"
                        )
                    )
                ),
                (
                    "Reviewer",
                    _text(
                        decision.get(
                            "reviewer_name"
                        )
                        or decision.get(
                            "reviewer_email"
                        )
                    )
                ),
                (
                    "Reviewer Role",
                    _text(
                        decision.get(
                            "reviewer_role"
                        )
                    )
                ),
                (
                    "Decision Time",
                    _text(
                        decision.get(
                            "decided_at"
                        )
                    )
                ),
                (
                    "Reviewer Note",
                    _text(
                        decision.get(
                            "note"
                        )
                    )
                ),
            ],
            styles
        )
    )

    story.append(
        _section(
            "7. Verification Submission",
            styles
        )
    )

    story.append(
        _kv_table(
            [
                (
                    "Submission Status",
                    _text(
                        verification_submission.get(
                            "status"
                        )
                    )
                ),
                (
                    "Submitted By",
                    _text(
                        verification_submission.get(
                            "submitter_name"
                        )
                        or verification_submission.get(
                            "submitter_email"
                        )
                    )
                ),
                (
                    "Submitted At",
                    _text(
                        verification_submission.get(
                            "submitted_at"
                        )
                    )
                ),
                (
                    "Submitted Information",
                    _text(
                        verification_submission.get(
                            "note"
                        )
                    )
                ),
            ],
            styles
        )
    )

    story.append(
        _section(
            "8. Review Audit Trail",
            styles
        )
    )

    story.append(
        _audit_table(
            audit,
            styles
        )
    )

    story.append(
        Spacer(
            1,
            8
        )
    )

    story.append(
        Paragraph(
            (
                "ClaimGuard report note: A risk score or anomaly is a "
                "verification signal, not definitive proof of fraud. "
                "Final financial decisions remain with the authorized "
                "Finance/Reviewer process."
            ),
            styles["small"]
        )
    )

    document.build(
        story,
        onFirstPage=_footer,
        onLaterPages=_footer,
    )

    return buffer.getvalue()

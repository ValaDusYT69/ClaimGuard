from invoice.extraction import assess_invoice, normalize_line_items


def test_multiple_product_rows_and_totals():
    result = assess_invoice({"total_amount": 100, "line_items": [
        {"description": "Keyboard", "quantity": 2, "unit_price": 20, "amount": 40},
        {"product_name": "Mouse", "qty": 3, "price": 20, "line_total": 60},
    ]})
    assert result["product_line_count"] == 2
    assert result["line_items_total"] == 100
    assert result["total_reconciliation"] == "matched"
    assert result["extraction_completeness_score"] == 100


def test_missing_fields_are_not_guessed():
    rows = normalize_line_items([{"description": "Unknown item", "quantity": 1}])
    assert rows[0]["product_name"] == "Unknown item"
    assert rows[0]["unit_price"] is None
    assert "missing_unit_price" in rows[0]["extraction_warnings"]

def test_product_identity_uses_table_boundary_and_flags_unresolved_metadata():
    rows = normalize_line_items([
        {
            "product": "Customer Name Tazim Invoice No INV-2026 "
            "Product Description AJAZZ AK820 75% Wired Mechanical Keyboard",
            "quantity": 1,
        },
        {
            "product": "Customer Name Tazim Invoice No INV-2026 "
            "Status Approved AJAZZ AK820 Mechanical Keyboard",
            "quantity": 1,
        },
    ])

    assert rows[0]["product"] == "AJAZZ AK820 75% Wired Mechanical Keyboard"
    assert rows[0]["product_name"] == rows[0]["product"]
    assert rows[1]["product"] is None
    assert "product_identity_requires_review" in rows[1]["extraction_warnings"]


def test_mismatch_is_flagged():
    result = assess_invoice({"total_amount": 500, "line_items": [
        {"description": "SSD", "quantity": 1, "unit_price": 400}
    ]})
    assert result["total_reconciliation"] == "mismatch"
    assert "line_items_do_not_reconcile_to_invoice_total" in result["extraction_warnings"]


def test_empty_invoice_has_warning():
    result = assess_invoice({"line_items": []})
    assert result["product_line_count"] == 0
    assert "no_product_rows_extracted" in result["extraction_warnings"]

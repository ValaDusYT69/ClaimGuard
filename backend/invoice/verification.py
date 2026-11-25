import re
from typing import Any


# =========================================================
# VERIFICATION CODE FORMAT
# =========================================================

VERIFICATION_CODE_PATTERN = re.compile(
    r"^[A-Z0-9][A-Z0-9_-]{3,30}$",
    re.IGNORECASE,
)


# =========================================================
# NORMALIZE CODE
# =========================================================

def normalize_verification_code(
    code: Any,
) -> str | None:

    if code is None:
        return None

    code = str(code).strip()

    if not code:
        return None

    return code.upper()


# =========================================================
# CHECK CODE FORMAT
# =========================================================

def is_valid_verification_code_format(
    code: str | None,
) -> bool:

    code = normalize_verification_code(
        code
    )

    if not code:
        return False

    return bool(
        VERIFICATION_CODE_PATTERN.fullmatch(
            code
        )
    )


# =========================================================
# CHECK DUPLICATE VERIFICATION CODE
# =========================================================

def find_duplicate_verification_code(
    invoices: list[dict[str, Any]],
    verification_code: str,
    current_invoice_id: str | None = None,
) -> dict[str, Any] | None:

    normalized_code = (
        normalize_verification_code(
            verification_code
        )
    )


    if not normalized_code:
        return None


    for invoice in invoices:

        invoice_id = invoice.get(
            "invoice_id"
        )


        # Do not compare the invoice with itself
        if (
            current_invoice_id
            and invoice_id == current_invoice_id
        ):

            continue


        existing_code = (
            invoice.get(
                "verification_code"
            )
        )


        if not existing_code:

            extracted_data = (
                invoice.get(
                    "extracted_data"
                )
                or {}
            )


            existing_code = (
                extracted_data.get(
                    "verification_code"
                )
            )


        existing_code = (
            normalize_verification_code(
                existing_code
            )
        )


        if (
            existing_code
            and existing_code == normalized_code
        ):

            return invoice


    return None


# =========================================================
# VERIFY INVOICE CODE
# =========================================================

def verify_invoice_code(
    invoice: dict[str, Any],
    all_invoices: list[dict[str, Any]],
) -> dict[str, Any]:

    invoice_id = invoice.get(
        "invoice_id"
    )


    extracted_data = (
        invoice.get(
            "extracted_data"
        )
        or {}
    )


    verification_code = (
        invoice.get(
            "verification_code"
        )
    )


    # -----------------------------------------------------
    # Fallback to extracted data
    # -----------------------------------------------------

    if not verification_code:

        verification_code = (
            extracted_data.get(
                "verification_code"
            )
        )


    verification_code = (
        normalize_verification_code(
            verification_code
        )
    )


    # =====================================================
    # 1. CODE MISSING
    # =====================================================

    if not verification_code:

        return {

            "status":
                "verification_required",

            "is_valid":
                False,

            "verification_code":
                None,

            "checks": {

                "code_present":
                    False,

                "format_valid":
                    False,

                "duplicate_code":
                    False,

                "document_check":
                    False,

            },

            "message":
                (
                    "No verification code was found "
                    "in the invoice document."
                ),

            "source":
                "invoice_document",

        }


    # =====================================================
    # 2. FORMAT CHECK
    # =====================================================

    format_valid = (
        is_valid_verification_code_format(
            verification_code
        )
    )


    if not format_valid:

        return {

            "status":
                "verification_failed",

            "is_valid":
                False,

            "verification_code":
                verification_code,

            "checks": {

                "code_present":
                    True,

                "format_valid":
                    False,

                "duplicate_code":
                    False,

                "document_check":
                    False,

            },

            "message":
                (
                    "The verification code format "
                    "is invalid."
                ),

            "source":
                "invoice_document",

        }


    # =====================================================
    # 3. DUPLICATE CODE CHECK
    # =====================================================

    duplicate_invoice = (
        find_duplicate_verification_code(
            invoices=all_invoices,
            verification_code=verification_code,
            current_invoice_id=invoice_id,
        )
    )


    if duplicate_invoice:

        duplicate_invoice_id = (
            duplicate_invoice.get(
                "invoice_id"
            )
        )


        return {

            "status":
                "possible_duplicate",

            "is_valid":
                False,

            "verification_code":
                verification_code,

            "checks": {

                "code_present":
                    True,

                "format_valid":
                    True,

                "duplicate_code":
                    True,

                "document_check":
                    False,

            },

            "message":
                (
                    "This verification code has already "
                    "been used by another invoice."
                ),

            "duplicate_invoice_id":
                duplicate_invoice_id,

            "source":
                "internal_invoice_records",

        }


    # =====================================================
    # 4. BASIC DOCUMENT CHECK PASSED
    # =====================================================

    return {

        "status":
            "document_check_passed",

        "is_valid":
            True,

        "verification_code":
            verification_code,

        "checks": {

            "code_present":
                True,

            "format_valid":
                True,

            "duplicate_code":
                False,

            "document_check":
                True,

        },

        "message":
            (
                "The verification code is present, "
                "properly formatted, and has not been "
                "previously used in ClaimGuard records."
            ),

        "source":
            "internal_invoice_records",

    }


# =========================================================
# FULL INVOICE VERIFICATION
# =========================================================

def verify_invoice(
    invoice: dict[str, Any],
    all_invoices: list[dict[str, Any]],
) -> dict[str, Any]:

    verification = verify_invoice_code(
        invoice=invoice,
        all_invoices=all_invoices,
    )


    # -----------------------------------------------------
    # Additional basic document consistency checks
    # -----------------------------------------------------

    extracted_data = (
        invoice.get(
            "extracted_data"
        )
        or {}
    )


    checks = (
        verification.get(
            "checks"
        )
        or {}
    )


    # -----------------------------------------------------
    # Invoice number present?
    # -----------------------------------------------------

    invoice_number_present = bool(
        extracted_data.get(
            "invoice_number"
        )
    )


    # -----------------------------------------------------
    # Vendor present?
    # -----------------------------------------------------

    vendor_present = bool(
        extracted_data.get(
            "vendor_name"
        )
    )


    # -----------------------------------------------------
    # Amount present?
    # -----------------------------------------------------

    total_amount_present = (
        extracted_data.get(
            "total_amount"
        ) is not None
    )


    # -----------------------------------------------------
    # Add document completeness checks
    # -----------------------------------------------------

    checks[
        "invoice_number_present"
    ] = invoice_number_present


    checks[
        "vendor_present"
    ] = vendor_present


    checks[
        "total_amount_present"
    ] = total_amount_present


    # =====================================================
    # FINAL STATUS
    # =====================================================

    if verification.get(
        "status"
    ) in {
        "verification_failed",
        "possible_duplicate",
        "verification_required",
    }:

        final_status = verification.get(
            "status"
        )

        final_is_valid = False


    elif not invoice_number_present:

        final_status = (
            "verification_required"
        )

        final_is_valid = False


    elif not vendor_present:

        final_status = (
            "verification_required"
        )

        final_is_valid = False


    elif not total_amount_present:

        final_status = (
            "verification_required"
        )

        final_is_valid = False


    else:

        final_status = (
            "verified_document"
        )

        final_is_valid = True


    # =====================================================
    # MESSAGE
    # =====================================================

    if final_status == (
        "verified_document"
    ):

        message = (
            "Invoice document checks passed. "
            "The verification code is valid in format, "
            "has not been duplicated in existing ClaimGuard "
            "records, and the required invoice fields were found."
        )

    elif final_status == (
        "possible_duplicate"
    ):

        message = (
            verification.get(
                "message"
            )
            or
            "Possible duplicate invoice detected."
        )

    elif final_status == (
        "verification_failed"
    ):

        message = (
            verification.get(
                "message"
            )
            or
            "Invoice verification failed."
        )

    else:

        message = (
            "Additional verification is required "
            "before the invoice can be considered verified."
        )


    return {

        "status":
            final_status,

        "is_valid":
            final_is_valid,

        "verification_code":
            verification.get(
                "verification_code"
            ),

        "checks":
            checks,

        "message":
            message,

        "source":
            verification.get(
                "source",
                "invoice_document"
            ),

        "duplicate_invoice_id":
            verification.get(
                "duplicate_invoice_id"
            ),

    }
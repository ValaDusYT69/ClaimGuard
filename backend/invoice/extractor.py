from pathlib import Path
import re
import logging

from config import OCR_LANG, TESSDATA_PREFIX, TESSERACT_CMD
from invoice.extraction.identity import (
    is_invoice_metadata_line,
    normalize_product_identity,
)


logger = logging.getLogger(__name__)


# =========================================================
# OCR CONFIGURATION
# =========================================================

def configure_tesseract():

    try:

        import pytesseract

    except ImportError:

        raise RuntimeError(
            "pytesseract is not installed. "
            "Run: pip install pytesseract"
        )


    if TESSDATA_PREFIX:
        pytesseract.pytesseract.tessdata_dir_config = (
            f'--tessdata-dir "{TESSDATA_PREFIX}"'
        )


    # -----------------------------------------------------
    # Common Windows installation paths
    # -----------------------------------------------------

    possible_paths = [
        Path(TESSERACT_CMD) if TESSERACT_CMD else None,
        None,

        Path(
            r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        ),

        Path(
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
        ),

    ]


    for path in possible_paths:

        if path is not None and not path.exists():
            continue

        if path is not None:
            pytesseract.pytesseract.tesseract_cmd = str(path)

        try:
            pytesseract.get_tesseract_version()
            languages = set(pytesseract.get_languages(config=""))
        except Exception:
            continue

        missing = {"ben", "eng"} - languages
        if missing:
            raise RuntimeError(
                "Tesseract is installed but required language models are "
                f"missing: {', '.join(sorted(missing))}."
            )

        return pytesseract


    raise RuntimeError(
        "Tesseract OCR could not be found. "
        "Install Tesseract OCR on Windows."
    )


# =========================================================
# PDF TEXT EXTRACTION
# =========================================================

def extract_pdf_text(
    file_path: Path,
) -> str:

    from pypdf import PdfReader


    reader = PdfReader(
        str(file_path)
    )


    pages = []


    for page in reader.pages:

        try:

            page_text = (
                page.extract_text()
                or ""
            )

        except Exception:

            page_text = ""


        if page_text.strip():

            pages.append(
                page_text
            )


    return "\n".join(
        pages
    )


# =========================================================
# PDF OCR FALLBACK
# =========================================================

def _render_pdf_pages(file_path: Path) -> list[bytes]:
    try:
        import fitz
    except ImportError as error:
        raise RuntimeError(
            "PyMuPDF is missing for robust PDF OCR. "
            "Run: pip install pymupdf"
        ) from error

    document = fitz.open(
        str(file_path)
    )

    try:
        rendered_pages = []
        for page in document:
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(
                    4,
                    4,
                ),
                alpha=False,
            )
            rendered_pages.append(pixmap.tobytes("png"))
        return rendered_pages
    finally:
        document.close()


def extract_pdf_with_ocr(
    file_path: Path,
    rendered_pages: list[bytes] | None = None,
) -> str:

    try:
        import cv2
        import numpy as np

    except ImportError as error:
        raise RuntimeError(
            "OpenCV, NumPy or PyMuPDF is missing for robust PDF OCR. "
            "Run: pip install opencv-python numpy pymupdf"
        ) from error

    pytesseract = configure_tesseract()
    page_images = _render_pdf_pages(file_path) if rendered_pages is None else rendered_pages
    pages = []

    for rendered_page in page_images:
            image = cv2.imdecode(
                np.frombuffer(
                    rendered_page,
                    dtype=np.uint8,
                ),
                cv2.IMREAD_GRAYSCALE,
            )

            if image is None:
                continue

            # Mild preprocessing only. Heavy thresholding can destroy
            # thin invoice text and digits.
            content_rect = _detect_document_content_rect(
                image
            )

            if content_rect:
                x1, y1, x2, y2 = content_rect
                ocr_image = image[y1:y2, x1:x2]
            else:
                ocr_image = image

            attempts = []
            try:
                data = pytesseract.image_to_data(
                    ocr_image,
                    lang=OCR_LANG,
                    config="--oem 3 --psm 11",
                    output_type=pytesseract.Output.DICT,
                )
                line_words: dict[tuple[str, str, str], list[str]] = {}
                confidences = []
                for index, raw_word in enumerate(data.get("text", [])):
                    word = str(raw_word or "").strip()
                    if not word:
                        continue
                    try:
                        confidence = float(data["conf"][index])
                    except (KeyError, IndexError, TypeError, ValueError):
                        confidence = -1
                    if confidence >= 0:
                        confidences.append(confidence)
                    line_key = tuple(
                        str(data[field][index])
                        if index < len(data.get(field, []))
                        else ""
                        for field in ("block_num", "par_num", "line_num")
                    )
                    line_words.setdefault(line_key, []).append(word)
                primary_text = "\n".join(
                    " ".join(words) for words in line_words.values()
                ).strip()
                average_confidence = (
                    sum(confidences) / len(confidences)
                    if confidences
                    else 0
                )
                if primary_text and len(line_words) >= 2 and average_confidence >= 45:
                    attempts.append(primary_text)
            except Exception:
                primary_text = ""
                average_confidence = 0

            if not attempts or average_confidence < 45:
                try:
                    fallback_text = pytesseract.image_to_string(
                        ocr_image,
                        lang=OCR_LANG,
                        config="--oem 3 --psm 6",
                    )
                except Exception:
                    fallback_text = ""
                if fallback_text.strip():
                    attempts.append(fallback_text)

            if attempts:
                pages.append(_select_best_ocr_attempt(attempts))

    if not pages:
        return ""

    return "\n\n".join(
        page_text.strip()
        for page_text in pages
        if page_text.strip()
    )


def _select_best_ocr_attempt(attempts: list[str]) -> str:
    """Choose one OCR configuration for a page without dropping other pages."""

    return max(
        attempts,
        key=lambda value: (
            sum(bool(line.strip()) for line in value.splitlines()),
            len(value.strip()),
        ),
    )




# =========================================================
# DOCUMENT CONTENT DETECTION
# =========================================================

def _detect_document_content_rect(
    image,
):

    """Find the dominant non-white document/photo region."""

    try:
        import cv2

    except ImportError:
        return None

    gray = image

    if len(gray.shape) == 3:
        gray = cv2.cvtColor(
            gray,
            cv2.COLOR_BGR2GRAY,
        )

    _, binary = cv2.threshold(
        gray,
        245,
        255,
        cv2.THRESH_BINARY_INV,
    )

    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (25, 25),
    )

    binary = cv2.morphologyEx(
        binary,
        cv2.MORPH_CLOSE,
        kernel,
    )

    contours, _ = cv2.findContours(
        binary,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    if not contours:
        return None

    image_height, image_width = gray.shape[:2]

    candidates = []

    for contour in contours:

        x, y, w, h = cv2.boundingRect(
            contour
        )

        area = w * h

        if area < image_width * image_height * 0.20:
            continue

        if w < image_width * 0.60:
            continue

        if h < image_height * 0.60:
            continue

        candidates.append(
            (
                area,
                x,
                y,
                w,
                h,
            )
        )

    if not candidates:
        return None

    candidates.sort(
        reverse=True
    )

    _, x, y, w, h = candidates[0]

    padding = 20

    x1 = max(
        0,
        x - padding,
    )

    y1 = max(
        0,
        y - padding,
    )

    x2 = min(
        image_width,
        x + w + padding,
    )

    y2 = min(
        image_height,
        y + h + padding,
    )

    return x1, y1, x2, y2


# =========================================================
# ROBUST STRUCTURED OCR FOR PHOTO INVOICES
# =========================================================

def _detect_table_geometry(
    image,
):

    """Detect the main invoice table rectangle."""

    try:
        import cv2

    except ImportError:
        return None

    gray = image

    if len(gray.shape) == 3:
        gray = cv2.cvtColor(
            gray,
            cv2.COLOR_BGR2GRAY,
        )

    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        15,
    )

    vertical_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (1, max(40, gray.shape[0] // 55)),
    )

    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (max(40, gray.shape[1] // 35), 1),
    )

    vertical = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        vertical_kernel,
    )

    horizontal = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        horizontal_kernel,
    )

    combined = cv2.bitwise_or(
        vertical,
        horizontal,
    )

    contours, _ = cv2.findContours(
        combined,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    image_height, image_width = gray.shape[:2]

    candidates = []

    for contour in contours:

        x, y, w, h = cv2.boundingRect(
            contour
        )

        if w < image_width * 0.30:
            continue

        if h < image_height * 0.08:
            continue

        if h > image_height * 0.35:
            continue

        page_position = (
            y / max(image_height, 1)
        )

        if page_position < 0.20:
            continue

        if page_position > 0.80:
            continue

        aspect = w / max(h, 1)

        if aspect < 1.4:
            continue

        candidates.append(
            (
                w * h,
                x,
                y,
                w,
                h,
            )
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    _, x, y, w, h = candidates[0]

    return x, y, w, h


def _vertical_table_boundaries(
    table,
):

    try:
        import cv2

    except ImportError:
        return []

    gray = table

    if len(gray.shape) == 3:
        gray = cv2.cvtColor(
            gray,
            cv2.COLOR_BGR2GRAY,
        )

    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        15,
    )

    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (1, max(25, gray.shape[0] // 12)),
    )

    vertical = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        kernel,
    )

    strength = (
        vertical > 0
    ).sum(axis=0)

    threshold = max(
        gray.shape[0] * 0.25,
        70,
    )

    raw = [
        index
        for index, value in enumerate(strength)
        if value >= threshold
    ]

    if not raw:
        return []

    groups = []

    for position in raw:

        if (
            not groups
            or position - groups[-1][-1] > 6
        ):
            groups.append([position])
        else:
            groups[-1].append(position)

    centers = [
        int(sum(group) / len(group))
        for group in groups
    ]

    return centers


def _ocr_table_data(
    table,
):

    try:
        import pytesseract

    except ImportError:
        return {}

    try:
        data = pytesseract.image_to_data(
            table,
            lang=OCR_LANG,
            config="--oem 3 --psm 11",
            output_type=pytesseract.Output.DICT,
        )
    except Exception:
        return {}

    rows = []

    for index, value in enumerate(
        data.get("text", [])
    ):

        value = (value or "").strip()

        if not value:
            continue

        try:
            confidence = float(
                data["conf"][index]
            )
        except Exception:
            confidence = 0.0

        if confidence < 20:
            continue

        rows.append(
            {
                "text": value,
                "confidence": confidence,
                "left": int(data["left"][index]),
                "top": int(data["top"][index]),
                "width": int(data["width"][index]),
                "height": int(data["height"][index]),
            }
        )

    return rows


def _numeric_token(
    value: str,
) -> float | int | None:

    match = re.search(
        r"(?<![A-Za-z])([0-9][0-9,]*(?:\.[0-9]+)?)",
        value,
    )

    if not match:
        return None

    return clean_number(
        match.group(1)
    )


def _best_column_number(
    tokens,
    left: int,
    right: int,
    y_min: int = 30,
    y_max: int = 180,
):

    candidates = []

    for token in tokens:

        center_x = (
            token["left"]
            + token["width"] / 2
        )

        center_y = (
            token["top"]
            + token["height"] / 2
        )

        if not (
            left <= center_x <= right
            and y_min <= center_y <= y_max
        ):
            continue

        number = _numeric_token(
            token["text"]
        )

        if number is None:
            continue

        candidates.append(
            (
                token["confidence"],
                number,
            )
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    return candidates[0][1]


def _description_from_tokens(
    tokens,
    left: int,
    right: int,
):

    candidates = []

    for token in tokens:

        center_x = (
            token["left"]
            + token["width"] / 2
        )

        center_y = (
            token["top"]
            + token["height"] / 2
        )

        if not (
            left <= center_x <= right
            and 30 <= center_y <= 180
        ):
            continue

        if _numeric_token(
            token["text"]
        ) is not None:
            continue

        if re.fullmatch(
            r"description|item|product|service",
            token["text"],
            re.IGNORECASE,
        ):
            continue

        candidates.append(
            token
        )

    if not candidates:
        return None

    # The first line of the description column is the first item row.
    candidates.sort(
        key=lambda item: (
            item["top"],
            item["left"],
        )
    )

    first_y = candidates[0]["top"]

    same_line = [
        token
        for token in candidates
        if abs(token["top"] - first_y) <= 12
    ]

    same_line.sort(
        key=lambda item: item["left"]
    )

    text = " ".join(
        token["text"]
        for token in same_line
    )

    return clean_value(
        text
    )


def extract_structured_ocr_fields(
    file_path: Path,
    rendered_pages: list[bytes] | None = None,
) -> dict:

    """Extract fields directly from the geometry of a photographed PDF invoice."""

    try:
        import cv2
        import numpy as np

    except ImportError:
        return {}

    page_images = _render_pdf_pages(file_path) if rendered_pages is None else rendered_pages
    try:
        for rendered_page in page_images:
            image = cv2.imdecode(
                np.frombuffer(
                    rendered_page,
                    dtype=np.uint8,
                ),
                cv2.IMREAD_GRAYSCALE,
            )

            if image is None:
                continue

            # Header OCR
            header_crop = image[
                int(image.shape[0] * 0.14):
                int(image.shape[0] * 0.37),
                int(image.shape[1] * 0.15):
                int(image.shape[1] * 0.90),
            ]

            header_tokens = _ocr_table_data(
                header_crop
            )

            # For header text parsing, OCR the crop directly.
            try:
                import pytesseract

                header_text = pytesseract.image_to_string(
                    header_crop,
                    lang=OCR_LANG,
                    config="--oem 3 --psm 6",
                )

            except Exception:
                header_text = ""

            result = {}

            order_id = first_match(
                header_text,
                [
                    r"(?:order\s*(?:id|no|number))\s*[:;\-]?\s*([A-Z0-9][A-Z0-9\/_-]{2,})",
                ],
            )

            if order_id:
                result["order_id"] = clean_value(
                    order_id
                )
                result["invoice_number"] = clean_value(
                    order_id
                )

            invoice_date = first_match(
                header_text,
                [
                    r"(?:invoice\s*date|date)\s*[:;\-]?\s*([0-9]{1,2}[\/\-.][0-9]{1,2}[\/\-.][0-9]{2,4})",
                    r"(?:invoice\s*date|date)\s*[:;\-]?\s*([0-9]{1,2}[- ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[- ][0-9]{2,4})",
                    r"(?:invoice\s*date|date)\s*[:;\-]?\s*([0-9]{1,2}[- ](?:January|February|March|April|May|June|July|August|September|October|November|December)[a-z]*[- ][0-9]{2,4})",
                ],
            )

            if invoice_date:
                result["invoice_date"] = clean_value(
                    invoice_date
                )

            # Company name from the header.
            header_lines = [
                clean_value(line)
                for line in header_text.splitlines()
                if line.strip()
            ]

            company_candidates = []

            for line in header_lines:

                lower = line.lower()

                if re.search(
                    r"\b(limited|ltd\.?|pvt\.?|inc\.?|corporation|company|traders|enterprise)\b",
                    lower,
                ):

                    if re.search(
                        r"head office|dhaka office|phone|fax|bangladesh",
                        lower,
                    ):
                        continue

                    company_candidates.append(
                        line
                    )

            if company_candidates:

                company_candidates.sort(
                    key=lambda value: (
                        "international" in value.lower(),
                        -len(value),
                    ),
                    reverse=True,
                )

                selected = company_candidates[0]
                upper = selected.upper()

                # Remove common OCR duplication before the final company name.
                repeated = list(
                    re.finditer(
                        r"\bINTERNATIONAL\b",
                        upper,
                    )
                )

                if len(repeated) >= 2:

                    start = repeated[-1].start()
                    before = upper[:start].strip()
                    words = before.split()

                    if words:
                        selected = (
                            words[-1]
                            + " INTERNATIONAL"
                            + upper[
                                start + len("INTERNATIONAL"):
                            ]
                        )

                result["vendor_name"] = clean_value(
                    selected
                )

            # -------------------------------------------------
            # Table geometry
            # -------------------------------------------------

            table_rect = _detect_table_geometry(
                image
            )

            if table_rect:

                tx, ty, tw, th = table_rect

                table = image[
                    ty:ty + th,
                    tx:tx + tw,
                ]

                boundaries = sorted(
                    set(
                        _vertical_table_boundaries(
                            table
                        )
                    )
                )

                if boundaries:

                    if boundaries[0] > 20:
                        boundaries.insert(
                            0,
                            0,
                        )

                    if boundaries[-1] < tw - 20:
                        boundaries.append(
                            tw,
                        )

                if len(boundaries) >= 5:

                    # For the common five-column invoice:
                    # serial | description | unit price | quantity | total
                    desc_left = boundaries[-5]
                    desc_right = boundaries[-4]
                    unit_left = boundaries[-4]
                    unit_right = boundaries[-3]
                    qty_left = boundaries[-3]
                    qty_right = boundaries[-2]
                    total_left = boundaries[-2]
                    total_right = boundaries[-1]

                    tokens = _ocr_table_data(
                        table
                    )

                    # Direct OCR of the first data-row cell preserves model/spec numbers
                    # such as 27.5 and 2.10 better than token filtering.
                    description_crop = table[
                        25:min(150, th),
                        max(0, desc_left + 5):max(
                            desc_left + 6,
                            desc_right - 5,
                        ),
                    ]

                    try:
                        import pytesseract

                        description_crop = cv2.resize(
                            description_crop,
                            None,
                            fx=3,
                            fy=3,
                            interpolation=cv2.INTER_CUBIC,
                        )

                        direct_description = pytesseract.image_to_string(
                            description_crop,
                            lang=OCR_LANG,
                            config="--oem 3 --psm 6",
                        ).strip()
                    except Exception:
                        direct_description = ""

                    description = None

                    for candidate_line in direct_description.splitlines():

                        candidate_line = re.sub(
                            r"\s+",
                            " ",
                            candidate_line,
                        ).strip(
                            " -_=|~`'\""
                        )

                        if not candidate_line:
                            continue

                        if re.fullmatch(
                            r"description|item|product|service",
                            candidate_line,
                            re.IGNORECASE,
                        ):
                            continue

                        if re.search(
                            r"head office|dhaka office|phone|fax|bangladesh|grand total|taka only",
                            candidate_line,
                            re.IGNORECASE,
                        ):
                            continue

                        description = candidate_line
                        break

                    if not description:
                        description = _description_from_tokens(
                            tokens,
                            desc_left + 5,
                            desc_right - 5,
                        )

                    if description:
                        result["product_description"] = description

                    unit_price = _best_column_number(
                        tokens,
                        unit_left + 5,
                        unit_right - 5,
                    )

                    quantity = _best_column_number(
                        tokens,
                        qty_left + 5,
                        qty_right - 5,
                    )

                    line_amount = _best_column_number(
                        tokens,
                        total_left + 5,
                        total_right - 5,
                    )

                    if unit_price is not None:
                        result["unit_price"] = unit_price

                    if quantity is not None:
                        result["quantity"] = quantity

                    if line_amount is not None:
                        result["line_amount"] = line_amount

                    # Quantity is frequently missed in photographed invoices.
                    # Recover it from amount / unit price when the relationship is exact.
                    if (
                        result.get("quantity") is None
                        and result.get("line_amount") is not None
                        and result.get("unit_price") is not None
                    ):

                        try:

                            derived_quantity = (
                                float(result["line_amount"])
                                / float(result["unit_price"])
                            )

                            if (
                                derived_quantity > 0
                                and abs(
                                    derived_quantity
                                    - round(derived_quantity)
                                ) < 0.02
                            ):

                                result["quantity"] = int(
                                    round(derived_quantity)
                                )

                        except Exception:
                            pass

            # Currency from invoice wording.
            if re.search(
                r"\btaka\b|\bBDT\b|\bTk\.?\b|৳",
                header_text,
                re.IGNORECASE,
            ):
                result["currency"] = "BDT"

            # We only need the first page containing a plausible invoice table.
            if result:
                return result
    except Exception:
        raise

    return {}


# =========================================================
# IMAGE OCR
# =========================================================

def extract_image_text(
    file_path: Path,
) -> str:

    try:

        from PIL import Image, ImageOps

    except ImportError:

        raise RuntimeError(
            "Pillow is not installed. "
            "Run: pip install pillow"
        )


    pytesseract = configure_tesseract()


    try:

        image = ImageOps.exif_transpose(
            Image.open(file_path)
        ).convert("RGB")

    except Exception as error:

        raise RuntimeError(
            f"Unable to open image: {error}"
        )


    candidates = []

    # Keep the original pixels as a candidate.  The other candidates are
    # working copies so the uploaded document is never modified.
    for degrees in (0, 90, 180, 270):
        rotated = image.rotate(degrees, expand=True)
        for psm in (6, 11):
            try:
                text = pytesseract.image_to_string(
                    rotated,
                    lang=OCR_LANG,
                    config=f"--oem 3 --psm {psm}",
                )
            except Exception:
                continue

            if text.strip():
                candidates.append(
                    {
                        "degrees": degrees,
                        "variant": "original",
                        "psm": psm,
                        "text": text,
                        "confidence": 0.0,
                        "score": _ocr_quality_score(text, {}),
                    }
                )

    if not candidates:
        raise RuntimeError("Image OCR produced no text.")

    best_orientation = max(
        {candidate["degrees"] for candidate in candidates},
        key=lambda degrees: max(
            candidate["score"]
            for candidate in candidates
            if candidate["degrees"] == degrees
        ),
    )
    orientation_candidates = [
        candidate
        for candidate in candidates
        if candidate["degrees"] == best_orientation
    ]
    orientation_candidates.sort(
        key=lambda candidate: candidate["score"],
        reverse=True,
    )
    selected = orientation_candidates[0]

    try:
        selected_data = pytesseract.image_to_data(
            image.rotate(best_orientation, expand=True),
            lang=OCR_LANG,
            config=f"--oem 3 --psm {selected['psm']}",
            output_type=pytesseract.Output.DICT,
        )
        selected["confidence"] = _ocr_confidence(selected_data)
    except Exception:
        pass

    # A sparse layout pass often reads the header accurately while the
    # uniform-block pass reads table totals more reliably.  Keep both only
    # when they are complementary; this avoids blindly choosing the longest
    # OCR output as the winner.
    selected_text = "\n\n".join(
        candidate["text"].strip()
        for candidate in orientation_candidates
        if candidate["text"].strip()
    )

    # The header is small relative to the photographed page.  A dedicated
    # crop improves company, invoice-number, and date recognition without
    # discarding the full-page table OCR.
    if best_orientation in (90, 270):
        rotated = image.rotate(best_orientation, expand=True)
        header_height = int(rotated.height * 0.28)
        header = rotated.crop((0, 0, rotated.width, header_height)).resize(
            (rotated.width * 2, header_height * 2)
        )
        try:
            header_text = pytesseract.image_to_string(
                header,
                lang=OCR_LANG,
                config="--oem 3 --psm 11",
            ).strip()
        except Exception:
            header_text = ""
        if header_text:
            selected_text = header_text + "\n\n" + selected_text

    return selected_text


def _ocr_confidence(data: dict) -> float:
    values = []
    for value in data.get("conf", []):
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            continue
        if confidence >= 0:
            values.append(confidence)
    return sum(values) / len(values) if values else 0.0


def _ocr_quality_score(text: str, data: dict) -> float:
    lower = text.lower()
    meaningful_patterns = (
        r"\binvoice\b", r"\bdate\b", r"\b(?:qty|quantity)\b",
        r"\b(?:price|amount|total)\b", r"\b(?:bdt|taka|tk)\b",
        r"\b(?:product|customer|vendor|supplier)\b",
    )
    pattern_hits = sum(bool(re.search(pattern, lower)) for pattern in meaningful_patterns)
    numeric_groups = len(re.findall(r"\d[\d,.]*", text))
    return (pattern_hits * 100.0) + min(numeric_groups, 20) * 3.0 + _ocr_confidence(data)


def extract_structured_image_header_fields(file_path: Path) -> dict:
    """Read compact header regions separately to avoid mixing vendor and buyer text.

    This is a deterministic OCR aid, not a trained vendor-classification model.
    Known logo text is accepted only when both brand tokens are independently
    supported by the logo crop. Unknown logos remain unknown instead of being
    filled with nearby order or customer text.
    """
    try:
        from PIL import Image, ImageOps
        from difflib import SequenceMatcher
        import pytesseract
    except ImportError:
        return {}

    try:
        image = ImageOps.exif_transpose(Image.open(file_path)).convert("RGB")
    except Exception:
        return {}

    best: dict = {}
    best_score = -1
    for degrees in (0, 180, 90, 270):
        rotated = image.rotate(degrees, expand=True) if degrees else image
        width, height = rotated.size
        if width < 300 or height < 300:
            continue

        def crop_text(box: tuple[float, float, float, float], psm: int = 6) -> str:
            x1, y1, x2, y2 = box
            crop = rotated.crop((
                max(0, int(width * x1)),
                max(0, int(height * y1)),
                min(width, int(width * x2)),
                min(height, int(height * y2)),
            ))
            if crop.width < 10 or crop.height < 10:
                return ""
            crop = crop.resize((crop.width * 4, crop.height * 4))
            try:
                return pytesseract.image_to_string(
                    crop,
                    lang="eng",
                    config=f"--oem 3 --psm {psm}",
                ).strip()
            except Exception:
                return ""

        # Upper-left company logo; invoice number and sold-to block;
        # right-side order / date / promised-date block.
        logo_text = crop_text((0.02, 0.015, 0.25, 0.105), psm=11)
        # Some vendors use a full-width wordmark rather than a compact logo.
        banner_text = crop_text((0.02, 0.015, 0.98, 0.11), psm=11)
        left_text = crop_text((0.02, 0.135, 0.54, 0.275), psm=6)
        right_text = crop_text((0.50, 0.135, 0.98, 0.305), psm=6)

        invoice_match = re.search(
            r"\bINV[-_][A-Z0-9][A-Z0-9-]{5,}\b",
            left_text.upper(),
        )
        invoice_number = invoice_match.group(0).replace("_", "-") if invoice_match else None

        # STAR is frequently read as STKA / STMR2 by OCR. The additional TECH
        # token and a conservative similarity threshold prevent guessing from
        # unrelated invoice text.
        logo_words = re.findall(r"[A-Z0-9]+", logo_text.upper())
        has_tech = any(
            word == "TECH" or SequenceMatcher(None, word, "TECH").ratio() >= 0.82
            for word in logo_words
        )
        has_star = any(
            SequenceMatcher(None, word, "STAR").ratio() >= 0.64
            for word in logo_words
        )
        vendor_name = "Star Tech" if has_star and has_tech else None
        vendor_method = "logo_ocr" if vendor_name else None

        # Generic full-width wordmark fallback for unfamiliar vendors. Only
        # accept a short, name-like first header line; never use address,
        # hotline, office, or invoice metadata as the vendor name.
        if not vendor_name:
            blocked_header_terms = {
                "INVOICE", "HOTLINE", "COMPLAIN", "WARRANTY", "OFFICE",
                "CORPORATE", "HEAD", "FLAGSHIP", "STORE", "ADDRESS",
            }
            for banner_line in banner_text.splitlines():
                candidate_line = re.sub(r"[^A-Za-z&.' -]", " ", banner_line).strip(" -.'")
                candidate_words = re.findall(r"[A-Za-z][A-Za-z&.'-]*", candidate_line)
                if not candidate_words:
                    continue
                upper_words = [word.upper() for word in candidate_words]
                if any(word in blocked_header_terms for word in upper_words):
                    continue
                alpha_count = sum(len(re.sub(r"[^A-Za-z]", "", word)) for word in candidate_words)
                # Single-word logotypes are accepted only when sufficiently
                # clear. Multiword names need at least two meaningful tokens.
                if len(candidate_words) >= 2 and alpha_count >= 8:
                    candidate_name = " ".join(upper_words)
                elif len(candidate_words) == 1 and len(candidate_words[0]) >= 6 and upper_words[0] not in {"STKE", "STKA", "STMR2"}:
                    candidate_name = upper_words[0].title()
                else:
                    continue
                if candidate_name.upper().endswith(" LT"):
                    candidate_name += "D"
                if candidate_name.upper().endswith(" LTD"):
                    candidate_name = candidate_name[:-3] + "LTD"
                vendor_name = clean_value(candidate_name)
                vendor_method = "header_wordmark_ocr"
                break

        order_match = re.search(
            r"\bSO[-_][A-Z0-9][A-Z0-9 _-]{5,}\d{4,}\b",
            right_text.upper(),
        )
        order_id = re.sub(r"\s+", " ", order_match.group(0)).strip() if order_match else None

        date_match = re.search(
            r"\bDATE\s*[:;]?\s*([0-9]{1,2}[- ](?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*[- ][0-9]{2,4})",
            right_text.upper(),
        )
        promised_match = re.search(
            r"PROMISED\s*DATE\s*[:;]?\s*([0-9]{1,2}[- ](?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*[- ][0-9]{2,4})",
            right_text.upper(),
        )

        # Buyer and payment terms live in different header columns. Capture
        # them explicitly so they are not mixed into the vendor name.
        left_lines = [line.strip(" :\t") for line in left_text.splitlines() if line.strip(" :\t")]
        customer_name = None
        buyer_label_index = next((i for i, line in enumerate(left_lines) if re.search(r"\b(?:sold\s*to|customer\s*name|buyer|bill\s*to)\b", line, re.IGNORECASE)), None)
        if buyer_label_index is not None:
            buyer_label = left_lines[buyer_label_index]
            buyer_value = re.sub(r"^.*?\b(?:sold\s*to|customer\s*name|buyer|bill\s*to)\b\s*[:;]?\s*", "", buyer_label, flags=re.IGNORECASE).strip()
            if len(re.sub(r"[^A-Za-z]", "", buyer_value)) >= 4 and not re.search(r"\bINV[-_]", buyer_value, re.IGNORECASE):
                customer_name = clean_value(buyer_value)
            elif buyer_label_index + 1 < len(left_lines):
                next_line = left_lines[buyer_label_index + 1]
                if not re.search(r"^(address|phone|remarks|invoice)\b", next_line, re.IGNORECASE):
                    customer_name = clean_value(next_line)

        if customer_name:
            customer_name = re.sub(r"\s+(?:St|Stock(?:\s+Location)?)$", "", customer_name, flags=re.IGNORECASE).strip()

        payment_match = re.search(
            r"PAYMENT\s*TERMS\s*[:;]?\s*([A-Z][A-Z /_-]{2,30})",
            right_text.upper(),
        )
        payment_terms = clean_value(payment_match.group(1).title()) if payment_match else None

        score = (10 if invoice_number else 0) + (4 if "INVOICE" in left_text.upper() else 0) + (3 if vendor_name else 0) + (2 if order_id else 0)
        candidate = {
            key: value
            for key, value in {
                "invoice_number": invoice_number,
                "vendor_name": vendor_name,
                "customer_name": customer_name,
                "payment_terms": payment_terms,
                "order_id": order_id,
                "invoice_date": date_match.group(1).title() if date_match else None,
                "promised_date": promised_match.group(1).title() if promised_match else None,
                "vendor_identification_method": vendor_method,
            }.items()
            if value is not None
        }
        if score > best_score:
            best, best_score = candidate, score
        if score >= 15:
            break

    return best


# =========================================================
# EXCEL EXTRACTION
# =========================================================

def extract_excel_text(
    file_path: Path,
    extension: str,
) -> str:

    if extension == ".xls":

        raise RuntimeError(
            "Legacy .xls extraction is not enabled yet. "
            "Please convert the file to .xlsx."
        )


    try:

        from openpyxl import load_workbook

    except ImportError:

        raise RuntimeError(
            "openpyxl is not installed. "
            "Run: pip install openpyxl"
        )


    workbook = load_workbook(
        filename=str(file_path),
        read_only=True,
        data_only=True,
    )


    lines = []


    try:

        for worksheet in workbook.worksheets:

            lines.append(
                f"[Sheet: {worksheet.title}]"
            )


            for row in worksheet.iter_rows(
                values_only=True
            ):

                values = []


                for value in row:

                    if value is None:

                        continue


                    value_text = str(
                        value
                    ).strip()


                    if value_text:

                        values.append(
                            value_text
                        )


                if values:

                    lines.append(
                        " | ".join(
                            values
                        )
                    )

    finally:

        workbook.close()


    return "\n".join(
        lines
    )


# =========================================================
# MAIN FILE TEXT EXTRACTION
# =========================================================

def extract_file_text(
    file_path: Path,
    extension: str,
    rendered_pages: list[bytes] | None = None,
) -> tuple[str, str]:

    extension = extension.lower()


    # -----------------------------------------------------
    # PDF
    # -----------------------------------------------------

    if extension == ".pdf":

        try:

            pdf_text = extract_pdf_text(
                file_path
            )

        except Exception:

            pdf_text = ""


        # Normal PDF text extraction
        if len(
            pdf_text.strip()
        ) >= 20:

            return (
                pdf_text,
                "pdf_text",
            )


        # OCR fallback
        page_images = _render_pdf_pages(file_path)
        if rendered_pages is not None:
            rendered_pages.extend(page_images)
        ocr_text = extract_pdf_with_ocr(file_path, page_images)


        if ocr_text.strip():

            return (
                ocr_text,
                "pdf_ocr",
            )


        return (
            "",
            "pdf_no_text",
        )


    # -----------------------------------------------------
    # EXCEL
    # -----------------------------------------------------

    if extension in {
        ".xls",
        ".xlsx",
    }:

        text = extract_excel_text(
            file_path,
            extension
        )


        return (
            text,
            "excel_cells",
        )


    # -----------------------------------------------------
    # IMAGE
    # -----------------------------------------------------

    if extension in {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
    }:

        text = extract_image_text(
            file_path
        )


        return (
            text,
            "image_ocr",
        )


    raise RuntimeError(
        f"Unsupported file type: {extension}"
    )


# =========================================================
# TEXT NORMALIZATION
# =========================================================

def normalize_text(
    text: str,
) -> str:

    text = text.replace(
        "\r\n",
        "\n"
    )


    text = text.replace(
        "\r",
        "\n"
    )


    # Collapse spaces but preserve line breaks.
    text = re.sub(
        r"[ \t]+",
        " ",
        text
    )


    # Remove excessive blank lines.
    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text
    )


    return text.strip()


# =========================================================
# REGEX HELPERS
# =========================================================

def first_match(
    text: str,
    patterns: list[str],
    flags: int = re.IGNORECASE,
):

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags
        )


        if match:

            value = (
                match.group(1)
                .strip()
            )


            if value:

                return value


    return None


def _next_value_after_label(
    lines: list[str],
    label_pattern: str,
) -> str | None:
    """Read a value that OCR placed on the label's following line."""

    for index, line in enumerate(lines):
        match = re.search(label_pattern, line, re.IGNORECASE)
        if not match:
            continue

        remainder = line[match.end():].strip(" :;.-")
        if remainder:
            return remainder

        for next_line in lines[index + 1: index + 4]:
            if next_line.strip():
                return next_line.strip()

    return None


def _extract_date_value(value: str | None) -> str | None:
    """Return a date-shaped value and reject unrelated OCR labels."""

    if not value:
        return None

    if re.search(r"\b(?:contact|phone|mobile|hotline|invoice|order|code)\b", value, re.IGNORECASE):
        return None

    match = re.search(
        r"\b(?:[0-9]{1,4}[\/.\-][0-9]{1,2}[\/.\-][0-9]{1,4}|"
        r"[0-9]{1,2}[- ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"[a-z]*[- ][0-9]{2,4})\b",
        value,
        re.IGNORECASE,
    )
    return match.group(0) if match else None


def _invoice_date_from_lines(lines: list[str]) -> str | None:
    """Find a date near its label without accepting the next metadata label."""

    for index, line in enumerate(lines):
        if not re.search(r"(?:invoice\s*)?date\b", line, re.IGNORECASE):
            continue

        for candidate in [line, *lines[index + 1:index + 6]]:
            date_value = _extract_date_value(candidate)
            if date_value:
                return date_value

    return None


def _clean_ocr_identifier(value: str | None) -> str | None:
    """Normalize harmless OCR spacing around invoice identifiers."""

    if not value:
        return None

    value = re.sub(r"\s+", "", value)
    value = value.replace("~", "-")
    return clean_value(value)


def _invoice_identifier_from_text(
    text: str,
    lines: list[str],
) -> str | None:
    """Prefer a complete INV token over OCR's intervening metadata labels."""

    matches = re.findall(
        r"\bINV[-_][A-Z0-9][A-Z0-9_-]{5,}\b",
        text,
        re.IGNORECASE,
    )
    for index, line in enumerate(lines):
        if not re.search(r"\bINV[-_]", line, re.IGNORECASE):
            continue
        nearby = line
        for next_line in lines[index + 1: index + 3]:
            if re.search(r"\d", next_line) and not re.search(r"\b(?:date|code|status)\b", next_line, re.IGNORECASE):
                nearby += next_line
        joined = re.search(r"\b(INV[-_][A-Z0-9][A-Z0-9_-]{5,})\b", re.sub(r"\s+", "", nearby), re.IGNORECASE)
        if joined:
            matches.append(joined.group(1))
    if matches:
        return _clean_ocr_identifier(max(matches, key=len))

    for index, line in enumerate(lines):
        if not re.search(r"invoice\s*(?:no|number|#)\.?", line, re.IGNORECASE):
            continue
        nearby = " ".join(lines[index + 1: index + 8])
        match = re.search(
            r"\b(INV[-_][A-Z0-9][A-Z0-9_\- ]{5,})\b",
            nearby,
            re.IGNORECASE,
        )
        if match:
            return _clean_ocr_identifier(match.group(1))
    return None


def clean_value(
    value: str | None,
):

    if value is None:

        return None


    value = re.sub(
        r"\s+",
        " ",
        value
    ).strip()


    value = value.strip(
        " :|-"
    )


    return (
        value
        or None
    )


def clean_number(
    value: str | None,
):

    if not value:

        return None


    value = (
        value
        .replace(",", "")
        .strip()
    )


    try:

        number = float(
            value
        )

    except ValueError:

        return value


    if number.is_integer():

        return int(
            number
        )


    return number


# =========================================================
# VENDOR EXTRACTION
# =========================================================

def extract_vendor_name(
    text: str,
) -> str | None:

    # -----------------------------------------------------
    # Explicit vendor label
    # -----------------------------------------------------

    labelled_vendor = first_match(
        text,
        [

            r"(?:vendor\s*name|vendor|supplier\s*name|supplier|seller\s*name|seller)\s*[:\-]\s*([^\n]+)",

        ]
    )


    if labelled_vendor:

        return clean_value(
            labelled_vendor
        )


    # -----------------------------------------------------
    # Format:
    #
    # INVOICE
    # ABC Traders Ltd.
    # Invoice No: ...
    # -----------------------------------------------------

    lines = [

        line.strip()

        for line in text.split("\n")

        if line.strip()

    ]


    for index, line in enumerate(
        lines
    ):

        if re.fullmatch(
            r"invoice",
            line,
            re.IGNORECASE
        ):

            skip_next_customer_value = False
            for next_line in lines[
                index + 1:
                index + 6
            ]:

                if re.search(
                    r"\binvoice\s*(?:no|number|#)\b",
                    next_line,
                    re.IGNORECASE
                ):

                    break


                if re.search(
                    r"^\s*date\b",
                    next_line,
                    re.IGNORECASE
                ):

                    continue


                if re.search(
                    r"^(description|quantity|qty|unit\s*price|amount)$",
                    next_line,
                    re.IGNORECASE
                ):

                    continue


                # Never treat a neighbouring invoice number, order reference,
                # buyer, location, or contact line as the issuing vendor. If a
                # buyer label appears, also skip its following value line.
                if skip_next_customer_value:
                    skip_next_customer_value = False
                    continue
                if re.search(r"\b(?:customer\s*name|sold\s*to|buyer|bill\s*to)\b", next_line, re.IGNORECASE):
                    skip_next_customer_value = True
                    continue
                if re.search(
                    r"\bINV[-_]|\bSO[-_]|order\s*(?:no|number|id)|stock\s*location|address|phone|remarks|payment\s*terms|contact\s*no|challan\s*no",
                    next_line,
                    re.IGNORECASE,
                ):
                    continue

                alpha_count = len(re.findall(r"[A-Za-z]", next_line))
                digit_count = len(re.findall(r"\d", next_line))
                if alpha_count >= 4 and len(next_line) >= 4 and digit_count <= alpha_count:
                    return clean_value(next_line)


    return None


# =========================================================
# TABLE VALUE EXTRACTION
# =========================================================

def extract_table_values(
    text: str,
) -> tuple[
    float | int | None,
    float | int | None,
    float | int | None
]:

    """
    Extract:

        quantity
        unit price
        line amount

    Supports both:

    1. Horizontal:

       Description Quantity Unit Price Amount
       Product / Service 10 5,000 50,000

    2. Vertical PDF text extraction:

       Description
       Quantity
       Unit Price
       Amount
       Product / Service
       10
       5,000
       50,000
    """


    lines = [

        line.strip()

        for line in text.split("\n")

        if line.strip()

    ]


    header_index = None


    # =====================================================
    # FORMAT 1: ALL HEADERS ON ONE LINE
    # =====================================================

    for index, line in enumerate(
        lines
    ):

        has_description = re.search(
            r"\bdescription\b",
            line,
            re.IGNORECASE
        )


        has_quantity = re.search(
            r"\bquantity\b|\bqty\b",
            line,
            re.IGNORECASE
        )


        has_unit_price = re.search(
            r"\bunit\s*price\b",
            line,
            re.IGNORECASE
        )


        has_amount = re.search(
            r"\bamount\b",
            line,
            re.IGNORECASE
        )


        if (
            has_description
            and has_quantity
            and has_unit_price
            and has_amount
        ):

            header_index = index

            break


    # =====================================================
    # FORMAT 2: HEADERS ON SEPARATE LINES
    # =====================================================

    if header_index is None:

        for index in range(
            len(lines) - 3
        ):

            line_1 = lines[
                index
            ].lower()

            line_2 = lines[
                index + 1
            ].lower()

            line_3 = lines[
                index + 2
            ].lower()

            line_4 = lines[
                index + 3
            ].lower()


            if (

                re.fullmatch(
                    r"description",
                    line_1,
                    re.IGNORECASE
                )

                and

                re.fullmatch(
                    r"quantity|qty",
                    line_2,
                    re.IGNORECASE
                )

                and

                re.fullmatch(
                    r"unit\s*price",
                    line_3,
                    re.IGNORECASE
                )

                and

                re.fullmatch(
                    r"amount",
                    line_4,
                    re.IGNORECASE
                )

            ):

                header_index = index

                break


    if header_index is None:

        return (
            None,
            None,
            None
        )


    # =====================================================
    # READ DATA AFTER HEADER
    # =====================================================

    numeric_values = []


    for line in lines[
        header_index + 1:
    ]:

        # -------------------------------------------------
        # Stop when financial summary starts.
        # -------------------------------------------------

        if re.match(
            r"^(subtotal|sub\s*total|vat|tax|total|grand\s*total|amount\s*due|verification\s*code)\b",
            line,
            re.IGNORECASE
        ):

            break


        numbers = re.findall(
            r"\d[\d,]*(?:\.\d+)?",
            line
        )


        for number in numbers:

            value = clean_number(
                number
            )


            if value is not None:

                numeric_values.append(
                    value
                )


    # -----------------------------------------------------
    # We need at least:
    #
    # quantity
    # unit price
    # amount
    # -----------------------------------------------------

    if len(
        numeric_values
    ) < 3:

        return (
            None,
            None,
            None
        )


    # The last three values before the summary are
    # quantity, unit price and line amount.

    quantity = numeric_values[
        -3
    ]


    unit_price = numeric_values[
        -2
    ]


    line_amount = numeric_values[
        -1
    ]


    return (
        quantity,
        unit_price,
        line_amount
    )


# =========================================================
# SUMMARY VALUE EXTRACTION
# =========================================================

def extract_summary_value(
    lines: list[str],
    label_pattern: str,
) -> float | int | None:

    """
    Supports both:

        Total: 57,500

    and:

        Total
        57,500
    """


    for index, line in enumerate(
        lines
    ):

        # -------------------------------------------------
        # Label + number on same line
        # -------------------------------------------------

        same_line = re.match(
            rf"^\s*{label_pattern}\s*[:\-]?\s*(?:[$€£₹৳]|Tk\.?|BDT)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*$",
            line,
            re.IGNORECASE
        )


        if same_line:

            return clean_number(
                same_line.group(1)
            )


        # -------------------------------------------------
        # Label only, number on next line
        # -------------------------------------------------

        if re.fullmatch(
            label_pattern,
            line,
            re.IGNORECASE
        ):

            for next_index in range(
                index + 1,
                min(
                    index + 3,
                    len(lines)
                )
            ):

                next_line = lines[
                    next_index
                ]


                number_match = re.fullmatch(
                    r"(?:[$€£₹৳]|Tk\.?|BDT)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
                    next_line,
                    re.IGNORECASE
                )


                if number_match:

                    return clean_number(
                        number_match.group(1)
                    )


    return None


def _extract_header_vendor(lines: list[str]) -> str | None:
    """Find a company-like heading before the invoice metadata block."""

    for line in lines:
        if re.search(r"^product\s*name$", line, re.IGNORECASE):
            break
        if re.search(r"\b(invoice|hotline|complain|warranty|flagship|store)\b", line, re.IGNORECASE):
            continue
        if re.search(r"\d{3,}", line):
            continue
        words = re.findall(r"[A-Za-z][A-Za-z&.'-]*", line)
        uppercase_words = [word for word in words if word.isupper() and len(word) >= 1]
        if len(uppercase_words) >= 2:
            value = " ".join(uppercase_words)
            value = re.sub(r"\bL\s*T\s*D\b|\bLT\s+D\b", "LTD", value, flags=re.IGNORECASE)
            parts = value.split()
            if len(parts) >= 2 and parts[-1].upper() == "LT":
                parts[-1] = "LTD"
            elif len(parts) >= 3 and parts[-2].upper().startswith("LT") and len(parts[-1]) == 1:
                parts[-2:] = ["LTD"]
            value = " ".join(parts)
            return clean_value(value)
    return None


def _extract_photo_table_values(
    lines: list[str],
    full_text: str | None = None,
) -> tuple[float | int | None, float | int | None, float | int | None, list[dict]]:
    """Extract item rows from photographed invoices where OCR flattens columns.

    Supports both row-oriented OCR (description + warranty days + qty + two
    currency amounts on one line) and OCR that emits header labels separately.
    It deliberately requires two money values for a row so footer numbers,
    serial numbers and warranty text are not mistaken for product prices.
    """
    source_text = full_text or "\n".join(lines)
    normalized_lines = [str(line or "").strip() for line in lines if str(line or "").strip()]
    if not normalized_lines:
        return None, None, None, []

    # A photographed table may not OCR its header correctly. The stable signal
    # is a row containing both unit price and line total before the Grand Total.
    table_header_indices = [
        index for index, line in enumerate(normalized_lines)
        if re.search(r"product\s*description|description|product\s*name", line, re.IGNORECASE)
    ]
    header_index = table_header_indices[0] if table_header_indices else -1
    invoice_heading_index = next(
        (
            index for index, line in enumerate(normalized_lines)
            if re.fullmatch(r"(?:tax\s+)?invoice", line, re.IGNORECASE)
        ),
        -1,
    )
    # Keep scanning from the invoice heading because OCR may append a later
    # table pass; description collection below uses the nearest preceding
    # product-table header to avoid pulling in the invoice metadata block.
    start_index = (
        invoice_heading_index + 1
        if invoice_heading_index >= 0
        else max(0, header_index + 1)
    )

    # Plain text/PDF extraction commonly flattens a simple table into one
    # line per row, e.g. ``Keyboard K2 1 2500 2500``. The photo-oriented
    # parser below intentionally requires decimal money pairs, so handle this
    # integer/header variant explicitly and conservatively here.
    horizontal_header_index = next(
        (
            index for index, line in enumerate(normalized_lines)
            if re.search(r"\b(?:item|description|product)\b", line, re.IGNORECASE)
            and re.search(r"\b(?:qty|quantity)\b", line, re.IGNORECASE)
            and re.search(r"\b(?:rate|unit\s*price|price)\b", line, re.IGNORECASE)
            and re.search(r"\b(?:total|amount)\b", line, re.IGNORECASE)
        ),
        -1,
    )
    if horizontal_header_index >= 0:
        horizontal_rows: list[dict] = []
        row_pattern = re.compile(
            r"^(?P<product>.+?)\s+(?P<quantity>[0-9][0-9,]*(?:\.[0-9]+)?)\s+"
            r"(?P<unit>[0-9][0-9,]*(?:\.[0-9]+)?)\s+"
            r"(?P<total>[0-9][0-9,]*(?:\.[0-9]+)?)$"
        )
        for line in normalized_lines[horizontal_header_index + 1:]:
            if re.match(r"^(?:subtotal|sub\s*total|vat|tax|grand\s*total|total|amount\s*due)\b", line, re.IGNORECASE):
                break
            match = row_pattern.match(line.replace("|", " "))
            if not match:
                continue
            product = clean_value(match.group("product").strip(" |_-"))
            quantity = clean_number(match.group("quantity"))
            unit_price = clean_number(match.group("unit"))
            line_amount = clean_number(match.group("total"))
            if not product or not all(isinstance(value, (int, float)) for value in (quantity, unit_price, line_amount)):
                continue
            if quantity <= 0 or unit_price <= 0 or line_amount <= 0 or quantity > 10000:
                continue
            if abs(float(quantity) * float(unit_price) - float(line_amount)) > max(0.01, float(line_amount) * 0.01):
                continue
            horizontal_rows.append({
                "product": product,
                "quantity": int(quantity) if float(quantity).is_integer() else float(quantity),
                "unit_price": round(float(unit_price), 2),
                "line_amount": round(float(line_amount), 2),
            })
        if horizontal_rows:
            total_quantity = sum(float(row["quantity"]) for row in horizontal_rows)
            total_line_amount = sum(float(row["line_amount"]) for row in horizontal_rows)
            return (
                clean_number(str(total_quantity)),
                horizontal_rows[0]["unit_price"] if len(horizontal_rows) == 1 else None,
                round(total_line_amount, 2),
                horizontal_rows,
            )

    # PDF text extraction can place each table column on its own line. Once a
    # Description/Quantity/Unit Price/Amount header is present, consume only
    # the repeated four-line product groups and stop at financial summaries.
    if header_index >= 0:
        vertical_rows: list[dict] = []
        index = header_index + 1
        numeric_line = re.compile(r"^[|\s]*[0-9][0-9,]*(?:\.[0-9]+)?\s*$")
        while index < len(normalized_lines):
            if re.match(r"^(?:subtotal|sub\s*total|vat|tax|grand\s*total|total|amount\s*due)\b", normalized_lines[index], re.IGNORECASE):
                break
            if index + 3 >= len(normalized_lines) or all(numeric_line.fullmatch(normalized_lines[index + offset]) for offset in (1, 2, 3)) is False:
                index += 1
                continue
            product = clean_value(normalized_lines[index].strip(" |_-"))
            quantity = clean_number(normalized_lines[index + 1])
            unit_price = clean_number(normalized_lines[index + 2])
            line_amount = clean_number(normalized_lines[index + 3])
            if product and not re.search(r"^(?:description|quantity|unit\s*price|amount)$", product, re.IGNORECASE) and all(isinstance(value, (int, float)) for value in (quantity, unit_price, line_amount)):
                if quantity > 0 and unit_price > 0 and line_amount > 0 and abs(float(quantity) * float(unit_price) - float(line_amount)) <= max(0.01, float(line_amount) * 0.01):
                    vertical_rows.append({
                        "product": product,
                        "quantity": int(quantity) if float(quantity).is_integer() else float(quantity),
                        "unit_price": round(float(unit_price), 2),
                        "line_amount": round(float(line_amount), 2),
                    })
                    index += 4
                    continue
            index += 1
        if vertical_rows:
            return (
                clean_number(str(sum(float(row["quantity"]) for row in vertical_rows))),
                vertical_rows[0]["unit_price"] if len(vertical_rows) == 1 else None,
                round(sum(float(row["line_amount"]) for row in vertical_rows), 2),
                vertical_rows,
            )

    money_pattern = re.compile(
        r"(?<![A-Za-z0-9])(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)\.[0-9]{1,2}(?![A-Za-z0-9])"
    )
    number_pattern = re.compile(r"(?<![A-Za-z0-9])([0-9][0-9,]*(?:\.[0-9]+)?)(?![A-Za-z0-9])")

    # Some OCR passes miss the W.Days column label but still read its values
    # (e.g. 2,190 / 1 / 4,900.00 / 4,900.00). Detect it from repeated rows.
    inferred_warranty_days = bool(
        re.search(r"w\.?\s*days|warranty\s*days", source_text, re.IGNORECASE)
    )
    if not inferred_warranty_days:
        evidence_rows = 0
        for line in normalized_lines[start_index:]:
            if re.match(r"^(?:in\s*word|grand\s*total|subtotal)\b", line, re.IGNORECASE):
                break
            matches = list(money_pattern.finditer(line))
            if len(matches) < 2:
                continue
            prefix = line[:matches[-2].start()].rstrip(" |,;:_")
            tail_numbers = list(number_pattern.finditer(prefix))
            if len(tail_numbers) >= 2:
                first = clean_number(tail_numbers[-2].group(1))
                last = clean_number(tail_numbers[-1].group(1))
                if (first == 0 or (isinstance(first, (int, float)) and float(first) >= 365)) and isinstance(last, (int, float)) and 0 < float(last) <= 100:
                    evidence_rows += 1
        inferred_warranty_days = evidence_rows >= 2

    rows: list[dict] = []
    seen: set[tuple[str, float, float]] = set()

    for line in normalized_lines[start_index:]:
        if re.match(
            r"^(?:in\s*word|grand\s*total|subtotal|sub\s*total|amount\s*due)\b",
            line,
            re.IGNORECASE,
        ):
            break

        money_matches = list(money_pattern.finditer(line))
        if len(money_matches) < 2:
            continue

        unit_match, total_match = money_matches[-2], money_matches[-1]
        unit_price = clean_number(unit_match.group(0))
        line_amount = clean_number(total_match.group(0))
        if not isinstance(unit_price, (int, float)) or not isinstance(line_amount, (int, float)):
            continue
        if unit_price <= 0 or line_amount <= 0:
            continue

        prefix = line[:unit_match.start()].strip()
        suffix = line[total_match.end():].strip()

        # Strip the printed serial number at the beginning of the row, but do
        # not strip digits embedded in product models such as MP243L / 5700G.
        prefix = re.sub(r"^\s*[\W_]*[0-9]{1,2}(?:\s*[|.)}:]\s*|\s+)", "", prefix)
        prefix = re.sub(r"^\s*[|_\W]+", "", prefix)

        trailing_numbers = list(number_pattern.finditer(prefix.rstrip(" |,;:_")))
        quantity = None
        if trailing_numbers:
            quantity = clean_number(trailing_numbers[-1].group(1))
            strip_count = 1
            if inferred_warranty_days and len(trailing_numbers) >= 2:
                possible_warranty_days = clean_number(trailing_numbers[-2].group(1))
                # Strip a second numeric token only when it looks like the
                # invoice's W.Days column (0 or >=365) and the final token
                # looks like a plausible quantity. This avoids chopping model
                # data such as 3200MHz / 5700G from the product description.
                if (
                    isinstance(possible_warranty_days, (int, float))
                    and (float(possible_warranty_days) == 0 or float(possible_warranty_days) >= 365)
                    and isinstance(quantity, (int, float))
                    and 0 < float(quantity) <= 100
                ):
                    strip_count = 2
            cut_match = trailing_numbers[-strip_count]
            prefix = prefix[:cut_match.start()].rstrip(" |,;:_-")

        # If a row wraps and OCR places the description after the price, retain
        # that text only when the prefix itself did not yield a product name.
        if not re.search(r"[A-Za-z]{2,}", prefix):
            prefix = suffix
        product = clean_value(prefix)
        if product:
            # Conservative OCR substitutions observed in photographed hardware invoices.
            # Corrections are scoped to nearby brand/model tokens to avoid
            # rewriting unrelated product identifiers.
            product = re.sub(
                r"\bAntec\s+B\s+Series\s+550\s+550[1Il]\)?\b",
                "Antec B Series B550 550W", product, flags=re.IGNORECASE,
            )
            product = re.sub(r"\bBSS0\s+SS0W\b", "B550 550W", product, flags=re.IGNORECASE)
            product = re.sub(r"\b0550\s+SSOW\b", "B550 550W", product, flags=re.IGNORECASE)
            product = re.sub(r"\bMSI\s*A[S5]20M-A\b", "MSI A520M-A", product, flags=re.IGNORECASE)
            product = re.sub(r"\bMSLAS20M-A\b", "MSI A520M-A", product, flags=re.IGNORECASE)
            product = re.sub(r"\bMP243L\s+0?14\b", "MP243L E14", product, flags=re.IGNORECASE)
            product = re.sub(r"(?<![A-Za-z0-9])\$70(?=\s+Lite)", "S70", product, flags=re.IGNORECASE)
            product = re.sub(r"\b25608\b", "256GB", product, flags=re.IGNORECASE)
            product = re.sub(r"\bDDR4\s+(?:01[.]16|CL1)\b", "DDR4 CL16", product, flags=re.IGNORECASE)
            product = re.sub(r"\bDDR4\s+056\b", "DDR4 CL16", product, flags=re.IGNORECASE)
            product = re.sub(r"\bGraphies\b", "Graphics", product, flags=re.IGNORECASE)
            if re.search(r"\bAMD\s+Ryzen\b", product, re.IGNORECASE):
                product = re.sub(r"\b57000\b", "5700G", product, flags=re.IGNORECASE)
                product = re.sub(r"\b5700O\b", "5700G", product, flags=re.IGNORECASE)
            # Warranty policy text sometimes sits on the same OCR row as the
            # product name. Do not include it in product identity matching.
            product = re.sub(r"\s*/\s*Prod[a-z]{1,2}t\s+Lifetime.*$", "", product, flags=re.IGNORECASE)
            product = re.sub(r"\s+Warranty\s+for\s+Fan/Cooler.*$", "", product, flags=re.IGNORECASE)
            product = re.sub(r"(550W)\)(?=\s+80\+)", r"\1", product, flags=re.IGNORECASE)
            product = re.sub(r"\s*\(No\s+Warranty\b[^)]*$", "", product, flags=re.IGNORECASE)
            product = re.sub(r"\s*\(No\s*$", "", product, flags=re.IGNORECASE)
            product = re.sub(r"\s+", " ", product).strip(" -/;,")
        if not product or len(re.sub(r"[^A-Za-z]", "", product)) < 3:
            continue
        if re.search(r"grand\s*total|in\s*word|warranty\s*complain|signature|authorized", product, re.IGNORECASE):
            continue

        # Quantity is cross-checked against line total / unit price. This
        # recovers the RAM row (2 x 7,525 = 15,050) even if OCR misses qty.
        ratio = float(line_amount) / float(unit_price)
        derived_quantity = round(ratio)
        if derived_quantity > 0 and abs(ratio - derived_quantity) < 0.015:
            quantity = int(derived_quantity)
        elif not isinstance(quantity, (int, float)) or quantity <= 0:
            quantity = 1

        # Avoid accidental acceptance of non-row pairs such as warranty hours.
        if float(quantity) > 10000 or float(line_amount) > 1e12:
            continue

        normalized_product = re.sub(r"[^a-z0-9]+", " ", product.lower()).strip()
        signature = (normalized_product, round(float(unit_price), 2), round(float(line_amount), 2))
        if signature in seen:
            continue
        seen.add(signature)

        rows.append({
            "product": product,
            "quantity": int(quantity) if float(quantity).is_integer() else float(quantity),
            "unit_price": round(float(unit_price), 2),
            "line_amount": round(float(line_amount), 2),
        })

    if not rows:
        # Some POS invoices print three columns on separate OCR lines:
        # unit price | discount, followed by the line amount. Recover that
        # layout and associate it with the nearest product description.
        last_row_end = start_index - 1
        for index, line in enumerate(normalized_lines[start_index:], start=start_index):
            if re.match(r"^(?:in\s*word|grand\s*total|subtotal|sub\s*total|amount\s*due)\b", line, re.IGNORECASE):
                break
            matches = list(money_pattern.finditer(line))
            if len(matches) < 2:
                continue
            unit_price = clean_number(matches[-2].group(0))
            discount = clean_number(matches[-1].group(0))
            if not isinstance(unit_price, (int, float)) or unit_price <= 0:
                continue
            if not isinstance(discount, (int, float)) or abs(float(discount)) > 0.01:
                continue

            amount_index = None
            line_amount = None
            for look_index in range(index + 1, min(index + 4, len(normalized_lines))):
                if re.match(r"^(?:in\s*word|grand\s*total|subtotal|sub\s*total|amount\s*due)\b", normalized_lines[look_index], re.IGNORECASE):
                    break
                amount_matches = list(money_pattern.finditer(normalized_lines[look_index]))
                if len(amount_matches) == 1:
                    parsed_amount = clean_number(amount_matches[0].group(0))
                    if isinstance(parsed_amount, (int, float)) and parsed_amount > 0:
                        amount_index, line_amount = look_index, parsed_amount
                        break
            if amount_index is None or line_amount is None:
                continue

            quantity = None
            for qty_index in range(max(start_index, index - 3), index):
                qty_match = re.search(r"^\s*([0-9]+(?:[.,][0-9]+)?)\s*(?:pcs?|pes|units?)\b", normalized_lines[qty_index], re.IGNORECASE)
                if qty_match:
                    quantity = clean_number(qty_match.group(1).replace(",", "."))
            if not isinstance(quantity, (int, float)) or quantity <= 0:
                quantity = 1
            ratio = float(line_amount) / float(unit_price)
            if ratio >= 1 and abs(ratio - round(ratio)) < 0.015:
                quantity = int(round(ratio))

            def normalize_description_candidate(candidate: str) -> str:
                candidate = candidate.strip(" |_:;.-")
                if "|" in candidate:
                    # OCR often places the internal SKU before a pipe and the
                    # actual human-readable product name after it.
                    parts = [part.strip(" |_:;.-") for part in candidate.split("|") if part.strip(" |_:;.-")]
                    if parts:
                        candidate = parts[-1]
                return candidate

            def looks_like_description(candidate: str) -> bool:
                candidate = normalize_description_candidate(candidate)
                if not candidate or len(re.sub(r"[^A-Za-z]", "", candidate)) < 5:
                    return False
                if is_invoice_metadata_line(candidate):
                    return False
                if re.match(r"^\s*(?:price|disc(?:ount)?|amount|product\s*name|qty|quantity)\b", candidate, re.IGNORECASE):
                    return False
                if re.search(r"warranty|\bs/?n\b|serial|grand\s*total|in\s*word|qty|quantity|unit\s*price|amount|discount|contact|address|phone|date", candidate, re.IGNORECASE):
                    return False
                # Reject isolated SKU/serial tokens, not model numbers embedded
                # in readable product names (e.g. AK820 / 5700G).
                if re.fullmatch(r"[A-Z0-9_./-]{12,}", candidate, re.IGNORECASE):
                    return False
                if len(re.findall(r"[0-9]", candidate)) > len(re.findall(r"[A-Za-z]", candidate)):
                    return False
                return True

            def starts_next_product_row(candidate_index: int) -> bool:
                if not looks_like_description(normalized_lines[candidate_index]):
                    return False
                for qty_index in range(candidate_index + 1, min(candidate_index + 6, len(normalized_lines))):
                    if re.match(r"^\s*[0-9][0-9,]*(?:\.[0-9]+)?\s*(?:pcs?|pes|units?)\b", normalized_lines[qty_index], re.IGNORECASE):
                        return any(
                            len(money_pattern.findall(normalized_lines[price_index])) >= 2
                            for price_index in range(qty_index + 1, min(qty_index + 4, len(normalized_lines)))
                        )
                return False

            description_start = max(start_index, last_row_end + 1)
            preceding_table_headers = [
                header + 1
                for header in table_header_indices
                if last_row_end < header < index
            ]
            if preceding_table_headers:
                description_start = max(description_start, max(preceding_table_headers))

            description_candidates = [
                normalize_description_candidate(normalized_lines[prior])
                for prior in range(description_start, index)
                if looks_like_description(normalized_lines[prior])
            ]
            if not description_candidates:
                for after in range(amount_index + 1, min(amount_index + 6, len(normalized_lines))):
                    candidate = normalized_lines[after]
                    if re.match(r"^(?:total\s*qty|grand\s*total|subtotal|in\s*word)\b", candidate, re.IGNORECASE):
                        break
                    if re.search(r"\b[0-9]+(?:\.[0-9]+)?\s*(?:pcs?|pes|units?)\b", candidate, re.IGNORECASE):
                        break
                    if looks_like_description(candidate):
                        description_candidates.append(normalize_description_candidate(candidate))

            # Include wrapped product-name continuation lines after the price
            # block while excluding warranty text and serial numbers. Advance
            # the cursor through the remainder of this row so those trailing
            # description lines are not reused for the next product.
            row_end = amount_index
            continuation_end = min(amount_index + 7, len(normalized_lines))
            for after in range(amount_index + 1, continuation_end):
                candidate = normalized_lines[after]
                if re.match(r"^(?:total\s*qty|grand\s*total|subtotal|in\s*word)\b", candidate, re.IGNORECASE):
                    row_end = after - 1
                    break
                if starts_next_product_row(after):
                    row_end = after - 1
                    break
                if re.search(r"\b[0-9]+(?:\.[0-9]+)?\s*(?:pcs?|pes|units?)\b", candidate, re.IGNORECASE):
                    row_end = after - 1
                    break
                if re.search(money_pattern, candidate):
                    row_end = after - 1
                    break
                row_end = after
                if looks_like_description(candidate):
                    normalized_candidate = normalize_description_candidate(candidate)
                    if normalized_candidate not in description_candidates:
                        description_candidates.append(normalized_candidate)

            if not description_candidates:
                last_row_end = max(last_row_end, row_end)
                continue
            product = clean_value(" ".join(description_candidates))
            product = re.sub(r"\s+Warranty\s+.*$", "", product, flags=re.IGNORECASE)
            product = re.sub(r"\s+", " ", product).strip(" -/;,")
            product = normalize_product_identity(product)
            if product is None:
                logger.warning(
                    "invoice_product_identity_requires_review",
                    extra={"stage": "product_normalization", "line_index": len(rows)},
                )
                rows.append({
                    "product": None,
                    "quantity": int(quantity) if float(quantity).is_integer() else float(quantity),
                    "unit_price": round(float(unit_price), 2),
                    "line_amount": round(float(line_amount), 2),
                    "extraction_warnings": ["product_identity_requires_review"],
                })
                normalized_lines[amount_index] = ""
                last_row_end = max(last_row_end, row_end)
                continue
            signature = (re.sub(r"[^a-z0-9]+", " ", product.lower()).strip(), round(float(unit_price), 2), round(float(line_amount), 2))
            if signature in seen:
                continue
            seen.add(signature)
            rows.append({
                "product": product,
                "quantity": int(quantity) if float(quantity).is_integer() else float(quantity),
                "unit_price": round(float(unit_price), 2),
                "line_amount": round(float(line_amount), 2),
            })
            # Mark the amount as consumed so it cannot be re-read as another row.
            normalized_lines[amount_index] = ""
            last_row_end = max(amount_index, row_end)

    if not rows:
        return None, None, None, []

    total_quantity = sum(float(row["quantity"]) for row in rows)
    total_line_amount = sum(float(row["line_amount"]) for row in rows)
    root_unit_price = rows[0]["unit_price"] if len(rows) == 1 else None
    return (
        clean_number(str(total_quantity)),
        root_unit_price,
        round(total_line_amount, 2),
        rows,
    )


# =========================================================
# FIELD EXTRACTION
# =========================================================

def extract_invoice_fields(
    raw_text: str,
) -> dict:

    text = normalize_text(
        raw_text
    )


    lines = [

        line.strip()

        for line in text.split("\n")

        if line.strip()

    ]


    # =====================================================
    # INVOICE NUMBER
    # =====================================================

    invoice_number = first_match(
        text,
        [

            r"(?:invoice\s*(?:no|number|#))\s*[:\-]?\s*([A-Z0-9][A-Z0-9\/_-]{2,})",

            r"(?:inv\s*(?:no|number|#))\s*[:\-]?\s*([A-Z0-9][A-Z0-9\/_-]{2,})",

        ]
    )

    lines = [
        line.strip()
        for line in text.split("\n")
        if line.strip()
    ]

    detected_invoice_number = _invoice_identifier_from_text(text, lines)
    if detected_invoice_number and (
        not invoice_number
        or len(detected_invoice_number) > len(invoice_number)
        or not re.search(r"\bINV[-_]", invoice_number, re.IGNORECASE)
    ):
        invoice_number = detected_invoice_number
    invoice_number = _clean_ocr_identifier(invoice_number)


    # =====================================================
    # VENDOR
    # =====================================================

    vendor_name = extract_vendor_name(
        text
    )
    if vendor_name in {"Customer Name", "Invoice", "Product Name"}:
        vendor_name = None
    if vendor_name is None:
        vendor_name = _extract_header_vendor(lines)


    # =====================================================
    # DATE
    # =====================================================

    invoice_date = first_match(
        text,
        [

            r"(?:invoice\s*date|date)\s*[:;\-]?\s*([0-9]{1,4}[\/\-\.][0-9]{1,2}[\/\-\.][0-9]{1,4})",
            r"(?:invoice\s*date|date)\s*[:;\-]?\s*([0-9]{1,2}[- ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[- ][0-9]{2,4})",
            r"(?:invoice\s*date|date)\s*[:;\-]?\s*([0-9]{1,2}[- ](?:January|February|March|April|May|June|July|August|September|October|November|December)[a-z]*[- ][0-9]{2,4})",

        ]
    )
    invoice_date = _extract_date_value(invoice_date)
    if invoice_date is None:
        invoice_date = _invoice_date_from_lines(lines)


    # =====================================================
    # PROMISED / PURCHASE / ORDER DATE
    # =====================================================

    promised_date = first_match(
        text,
        [
            r"promised\s*date\s*[:;\-]?\s*([0-9]{1,2}[- ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[- ][0-9]{2,4})",
            r"promised\s*date\s*[:;\-]?\s*([0-9]{1,2}[/.\-][0-9]{1,2}[/.\-][0-9]{2,4})",
        ],
    )
    promised_date = _extract_date_value(promised_date)

    purchase_order_date = first_match(
        text,
        [
            r"(?:purchase\s*date|order\s*date|purchased\s*on)\s*[:;\-]?\s*([0-9]{1,2}[- ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[- ][0-9]{2,4})",
            r"(?:purchase\s*date|order\s*date|purchased\s*on)\s*[:;\-]?\s*([0-9]{1,2}[/.\-][0-9]{1,2}[/.\-][0-9]{2,4})",
            r"(?:purchase\s*date|order\s*date|purchased\s*on)\s*[:;\-]?\s*([0-9]{4}[/.\-][0-9]{1,2}[/.\-][0-9]{1,2})",
        ],
    )
    purchase_order_date = _extract_date_value(purchase_order_date)

    # =====================================================
    # VERIFICATION CODE
    # =====================================================

    verification_code = first_match(
        text,
        [

            r"(?:verification\s*code)\s*[:\-]?\s*([A-Z0-9][A-Z0-9_-]{3,30})",

            r"(?:validation\s*code)\s*[:\-]?\s*([A-Z0-9][A-Z0-9_-]{3,30})",

            r"(?:authentication\s*code)\s*[:\-]?\s*([A-Z0-9][A-Z0-9_-]{3,30})",

            r"(?:auth\s*code)\s*[:\-]?\s*([A-Z0-9][A-Z0-9_-]{3,30})",

        ]
    )


    # =====================================================
    # TAX ID
    # =====================================================

    tax_id = first_match(
        text,
        [

            r"(?:tax\s*id)\s*[:\-]?\s*([A-Z0-9_-]{3,40})",

            r"(?:vat\s*(?:no|number))\s*[:\-]?\s*([A-Z0-9_-]{3,40})",

        ]
    )


    # =====================================================
    # TABLE VALUES
    # =====================================================

    (
        quantity,
        unit_price,
        line_amount,
    ) = extract_table_values(
        text
    )
    # Always attempt product-row extraction. A generic table parser may find a
    # single quantity elsewhere in the page and otherwise suppress all rows.
    photo_quantity, photo_unit_price, photo_line_amount, line_items = _extract_photo_table_values(
        lines,
        full_text=text,
    )
    logger.info(
        "invoice_product_table_boundaries_detected",
        extra={
            "stage": "table_segmentation",
            "product_line_count": len(line_items),
        },
    )
    if line_items:
        quantity = photo_quantity
        unit_price = photo_unit_price
        line_amount = photo_line_amount


    # =====================================================
    # QUANTITY FALLBACK
    # =====================================================

    if quantity is None:

        quantity = clean_number(
            first_match(
                text,
                [

                    r"\b(?:quantity|qty)\b\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)",

                ]
            )
        )


    # =====================================================
    # UNIT PRICE FALLBACK
    # =====================================================

    if unit_price is None:

        unit_price = clean_number(
            first_match(
                text,
                [

                    r"\b(?:unit\s*price|price\s*per\s*unit)\b\s*[:\-]?\s*(?:[$€£₹৳]|Tk\.?|BDT)?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",

                ]
            )
        )


    # =====================================================
    # SUBTOTAL
    # =====================================================

    subtotal = extract_summary_value(
        lines,
        r"(?:subtotal|sub\s*total)"
    )


    # =====================================================
    # TAX / VAT
    # =====================================================

    tax_amount = extract_summary_value(
        lines,
        r"(?:vat|tax)(?:\s*amount)?"
    )


    # =====================================================
    # TOTAL
    # =====================================================

    total_amount = extract_summary_value(
        lines,
        r"(?:grand\s*total|total\s*amount|amount\s*due|total)"
    )

    if subtotal is None and line_items and tax_amount is None:
        derived_subtotal = sum(
            float(item["line_amount"])
            for item in line_items
            if item.get("line_amount") is not None
        )
        if total_amount is None or abs(derived_subtotal - float(total_amount)) < 0.01:
            subtotal = clean_number(str(derived_subtotal))


    # =====================================================
    # EXTRA FALLBACK:
    # CALCULATE TOTAL FROM SUBTOTAL + TAX
    # =====================================================

    if (
        total_amount is None
        and subtotal is not None
        and tax_amount is not None
    ):

        try:

            total_amount = (
                subtotal
                + tax_amount
            )

        except Exception:

            total_amount = None


    # =====================================================
    # LINE AMOUNT FALLBACK
    # =====================================================

    if (
        line_amount is None
        and quantity is not None
        and unit_price is not None
    ):

        try:

            line_amount = (
                quantity
                * unit_price
            )

        except Exception:

            line_amount = None


    # =====================================================
    # CURRENCY
    # =====================================================

    currency = first_match(
        text,
        [

            r"(?:currency)\s*[:\-]?\s*([A-Z]{3})",

        ]
    )


    if not currency:

        upper_text = text.upper()


        if (
            "৳" in text
            or re.search(
                r"\bBDT\b|\bTK\.?\b|\bTAKA\b",
                upper_text
            )
        ):

            currency = "BDT"

        elif "$" in text:

            currency = "USD"

        elif "€" in text:

            currency = "EUR"

        elif "£" in text:

            currency = "GBP"


    # =====================================================
    # RESULT
    # =====================================================

    fields = {

        "invoice_number":
            clean_value(
                invoice_number
            ),

        "order_id":
            clean_value(
                first_match(
                    text,
                    [
                        r"(?:order\s*(?:id|no|number))\s*[:;\-]?\s*([A-Z0-9][A-Z0-9\/_-]{2,})",
                    ]
                )
            ),

        "vendor_name":
            clean_value(
                vendor_name
            ),

        "product_description":
            clean_value(
                line_items[0].get("product")
                if line_items
                else None
            ),

        "invoice_date":
            clean_value(
                invoice_date
            ),

        "purchase_order_date":
            clean_value(
                purchase_order_date
            ),

        # Keep the short public field name used by the API/report consumers,
        # while retaining purchase_order_date for backwards compatibility.
        "purchase_date":
            clean_value(
                purchase_order_date
            ),

        "promised_date":
            clean_value(
                promised_date
            ),

        "verification_code":
            clean_value(
                verification_code
            ),

        "tax_id":
            clean_value(
                tax_id
            ),

        "quantity":
            quantity,

        "unit_price":
            unit_price,

        "line_amount":
            line_amount,

        "subtotal":
            subtotal,

        "tax_amount":
            tax_amount,

        "total_amount":
            total_amount,

        "currency":
            clean_value(
                currency
            ),

        "line_items": line_items,

    }


    return fields


# =========================================================
# MAIN EXTRACTION FUNCTION
# =========================================================

def extract_invoice_data(
    file_path: Path,
    extension: str,
) -> dict:

    rendered_pages: list[bytes] = []
    raw_text, method = extract_file_text(
        file_path=file_path,
        extension=extension,
        rendered_pages=rendered_pages,
    )
    logger.info(
        "invoice_ocr_extraction_completed",
        extra={
            "stage": "ocr_extraction",
            "method": method,
            "text_length": len(raw_text or ""),
        },
    )


    normalized_text = normalize_text(
        raw_text
    )


    fields = extract_invoice_fields(
        normalized_text
    )
    logger.info(
        "invoice_metadata_extracted",
        extra={
            "stage": "metadata_extraction",
            "field_count": sum(value is not None for value in fields.values()),
            "line_item_count": len(fields.get("line_items") or []),
        },
    )

    # Re-read high-value header zones on photographed invoices. Full-page OCR
    # can interleave the logo, invoice number and Order No into one bad vendor.
    if extension.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
        try:
            image_header_fields = extract_structured_image_header_fields(file_path)
        except Exception:
            image_header_fields = {}
        for key, value in image_header_fields.items():
            if value is not None:
                fields[key] = value


    # -----------------------------------------------------
    # STRUCTURED RECOVERY FOR SCANNED / PHOTO PDFs
    # -----------------------------------------------------

    searchable_line_items = fields.get("line_items")
    searchable_confidence = sum(
        bool(fields.get(key))
        for key in (
            "invoice_number",
            "vendor_name",
            "invoice_date",
            "total_amount",
            "product_description",
        )
    )
    searchable_pdf_is_complete = (
        method == "pdf_text"
        and isinstance(searchable_line_items, list)
        and bool(searchable_line_items)
        and searchable_confidence >= 2
    )
    if extension.lower() == ".pdf" and not searchable_pdf_is_complete:

        try:
            structured_fields = extract_structured_ocr_fields(
                file_path,
                rendered_pages=rendered_pages,
            )
        except Exception:
            structured_fields = {}

        # Structured OCR is authoritative for table values and company/date
        # fields when it found a plausible value.
        for key, value in structured_fields.items():

            if value is None:
                continue

            if key in {
                "product_description",
                "quantity",
                "unit_price",
                "line_amount",
                "vendor_name",
                "invoice_date",
                "currency",
            }:
                fields[key] = value

            elif key in {
                "invoice_number",
                "order_id",
            }:
                fields[key] = value

        # Total-only invoices may not print a separate subtotal/tax block.
        if (
            fields.get("total_amount") is None
            and fields.get("line_amount") is not None
        ):
            fields["total_amount"] = fields[
                "line_amount"
            ]

        # Recover line amount from quantity × unit price when needed.
        if (
            fields.get("line_amount") is None
            and fields.get("quantity") is not None
            and fields.get("unit_price") is not None
        ):
            try:
                fields["line_amount"] = round(
                    float(fields["quantity"])
                    * float(fields["unit_price"]),
                    2,
                )
            except Exception:
                pass

        if (
            fields.get("total_amount") is None
            and fields.get("line_amount") is not None
        ):
            fields["total_amount"] = fields[
                "line_amount"
            ]


    line_items = fields.get("line_items") if isinstance(fields.get("line_items"), list) else []
    if line_items:
        line_items_total = round(
            sum(
                float(item.get("line_amount") or 0)
                for item in line_items
                if isinstance(item, dict)
            ),
            2,
        )
        fields["product_line_count"] = len(line_items)
        fields["line_items_total"] = line_items_total
        invoice_total = fields.get("total_amount")
        if invoice_total is not None:
            try:
                fields["total_reconciliation"] = (
                    "matched"
                    if abs(float(invoice_total) - line_items_total) <= max(1.0, abs(float(invoice_total)) * 0.001)
                    else "mismatch"
                )
            except (TypeError, ValueError):
                fields["total_reconciliation"] = "not_checked"
    else:
        fields["product_line_count"] = 0
        fields["line_items_total"] = None
        fields["total_reconciliation"] = "not_available"

    extracted_count = sum(
        1
        for value in fields.values()
        if value is not None
    )


    # =====================================================
    # STATUS
    # =====================================================

    if not normalized_text and extracted_count > 0:

        extraction_status = (
            "extracted"
        )

    elif not normalized_text:

        extraction_status = (
            "no_text_found"
        )

    elif extracted_count == 0:

        extraction_status = (
            "text_extracted_no_known_fields"
        )

    else:

        extraction_status = (
            "extracted"
        )

    ocr_metadata = None
    if method in {"image_ocr", "pdf_ocr"}:
        ocr_metadata = {
            "engine": "tesseract",
            "language": OCR_LANG,
            "page_segmentation_modes": [11, 6],
            "orientation_correction": method == "image_ocr",
        }
        try:
            ocr_metadata["version"] = str(
                configure_tesseract().get_tesseract_version()
            )
        except Exception:
            ocr_metadata["version"] = None


    # Canonical post-extraction validation. Preserve all original OCR/extractor
    # fields while normalizing every detected row and attaching explicit warnings.
    from invoice.extraction import assess_invoice, build_field_provenance
    quality = assess_invoice(fields)
    fields.update(quality)
    fields["field_provenance"] = build_field_provenance(fields, normalized_text)
    logger.info(
        "invoice_product_lines_normalized",
        extra={
            "stage": "product_normalization",
            "line_item_count": len(fields.get("line_items") or []),
            "review_required_count": sum(
                "product_identity_requires_review" in item.get("extraction_warnings", [])
                for item in fields.get("line_items", [])
                if isinstance(item, dict)
            ),
        },
    )

    return {

        **fields,

        "extraction_status":
            extraction_status,

        "extraction_method":
            method,

        "fields_detected":
            extracted_count,

        "raw_text_length":
            len(normalized_text),

        "raw_text_preview":
            normalized_text[:5000],

        "ocr_metadata":
            ocr_metadata,

    }

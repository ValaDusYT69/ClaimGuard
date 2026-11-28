"""Identity-aware extraction of Schema.org Product/Offer JSON-LD prices."""

from __future__ import annotations

import hashlib
import json
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any

_JSON_LD_RE = re.compile(
    r'<script\b[^>]*type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script\s*>',
    re.IGNORECASE | re.DOTALL,
)


def _normal(value: Any) -> str:
    text = unescape(str(value or "")).casefold()
    text = re.sub(r"[^a-z0-9.]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("@id") or "")
    if isinstance(value, list):
        return " ".join(_name(item) for item in value if item)
    return str(value or "")


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _types(node: dict[str, Any]) -> set[str]:
    raw = node.get("@type")
    values = raw if isinstance(raw, list) else [raw]
    return {str(item).rsplit("/", 1)[-1].casefold() for item in values if item}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    match = re.search(r"(?<![\w])([0-9]+(?:\.[0-9]{1,2})?)(?![\w])", text)
    if not match:
        return None
    try:
        number = float(match.group(1))
    except (TypeError, ValueError):
        return None
    return round(number, 2) if number > 0 else None


def _offer_nodes(product_node: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for key in ("offers", "aggregateOffer"):
        value = product_node.get(key)
        if isinstance(value, dict):
            candidates.extend(_walk(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    candidates.extend(_walk(item))

    output: list[dict[str, Any]] = []
    seen: set[int] = set()

    for item in candidates:
        marker = id(item)
        if marker not in seen:
            seen.add(marker)
            output.append(item)

    return output


class _PageNode:
    def __init__(
        self,
        tag: str,
        attrs: dict[str, str],
        parent: "_PageNode | None" = None,
    ):
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[_PageNode | str] = []


class _PageTreeParser(HTMLParser):
    _VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _PageNode("document", {})
        self.stack = [self.root]

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        node = _PageNode(
            tag.casefold(),
            {key.casefold(): value or "" for key, value in attrs},
            self.stack[-1],
        )

        self.stack[-1].children.append(node)

        if node.tag not in self._VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)

        if tag.casefold() not in self._VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()

        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == normalized:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.stack[-1].children.append(data)


_RELATED_SCOPE_RE = re.compile(
    r"(?:related|recommend|upsell|cross.?sell|product.?grid|products.?grid|"
    r"carousel|sidebar|breadcrumb|navigation|site.?footer|widget)",
    re.IGNORECASE,
)

_VARIANT_SELECTOR_RE = re.compile(
    r"(?:variant|switch|color|colour|layout|capacity|memory|storage|edition|model|size)",
    re.IGNORECASE,
)

_VARIANT_CONTAINER_RE = re.compile(
    r"(?:variations|swatches|product.?options|variant.?selector|variation.?selector|attribute.?select)",
    re.IGNORECASE,
)

_SPECIFICATION_LABEL_RE = re.compile(
    r"\b(?:model|sku|mpn|brand|capacity|frequency|speed|latency|wattage|"
    r"certification|form factor|screen size|resolution|panel type|interface|"
    r"chipset|socket|memory type|supported motherboard|output capacity|"
    r"modularity|efficiency|refresh rate|dimension|dimensions|material|"
    r"storage|type|ports|power)\b",
    re.IGNORECASE,
)

_PRODUCT_SPECIFICATION_SECTION_RE = re.compile(
    r"(?:specification|product.?spec|key.?feature|technical.?detail|"
    r"(?:module|product)[\s_-]*features?(?:[\s_-]*(?:description|list))?|"
    r"feature[\s_-]*description)",
    re.IGNORECASE,
)

_FINANCIAL_TABLE_RE = re.compile(
    r"\b(?:installment|monthly|charges|overall cost|emi)\b",
    re.IGNORECASE,
)


def _walk_page(node: _PageNode):
    yield node
    for child in node.children:
        if isinstance(child, _PageNode):
            yield from _walk_page(child)


def _inside_related_scope(node: _PageNode, scope: _PageNode) -> bool:
    current: _PageNode | None = node

    while current is not None and current is not scope:
        marker = " ".join(
            current.attrs.get(key, "")
            for key in ("class", "id", "role")
        )

        if _RELATED_SCOPE_RE.search(marker):
            return True

        current = current.parent

    return False


def _inside_variant_selector_scope(node: _PageNode, scope: _PageNode) -> bool:
    """Return true for option/select containers, not the selected product specs."""
    current: _PageNode | None = node
    while current is not None and current is not scope:
        marker = " ".join(
            current.attrs.get(key, "")
            for key in ("class", "id", "role", "name", "aria-label", "data-attribute_name")
        )
        if current.tag in {"select", "option"} or _VARIANT_CONTAINER_RE.search(marker):
            return True
        current = current.parent
    return False


def _page_text(
    node: _PageNode,
    *,
    in_variant_selector: bool = False,
) -> str:
    parts: list[str] = []

    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
            continue

        if child.tag in {
            "script", "style", "noscript", "nav",
            "footer", "aside", "option",
        }:
            continue

        marker = " ".join(
            child.attrs.get(key, "")
            for key in ("class", "id", "role")
        )

        if _RELATED_SCOPE_RE.search(marker):
            continue

        if _VARIANT_CONTAINER_RE.search(marker):
            continue

        parts.append(_page_text(child))

    return " ".join(part for part in parts if part).strip()


def _page_specification_text(scope: _PageNode) -> str:
    nodes = list(_walk_page(scope))

    tables = [
        node for node in nodes
        if node.tag == "table"
        and not _inside_related_scope(node, scope)
        and not _inside_variant_selector_scope(node, scope)
    ]

    relevant_tables = []

    for node in tables:
        text = _page_text(node)

        if (
            text
            and not _FINANCIAL_TABLE_RE.search(text)
            and _SPECIFICATION_LABEL_RE.search(text)
        ):
            relevant_tables.append(text)

    marked = [
        node for node in nodes
        if not _inside_related_scope(node, scope)
        and not _inside_variant_selector_scope(node, scope)
        and re.search(
            _PRODUCT_SPECIFICATION_SECTION_RE,
            " ".join(
                node.attrs.get(key, "")
                for key in ("class", "id", "role")
            ),
        )
    ]

    smallest = [
        node for node in marked
        if not any(
            other is not node
            and other in list(_walk_page(node))
            for other in marked
        )
    ]

    evidence_blocks = relevant_tables + [
        text for node in smallest
        if (text := _page_text(node))
    ]

    unique_blocks = list(dict.fromkeys(evidence_blocks))

    return " ".join(unique_blocks)[:12000]


def _variant_state(scope: _PageNode) -> tuple[str, list[str]]:
    values: list[str] = []
    ambiguities: list[str] = []
    nodes = list(_walk_page(scope))

    for node in nodes:
        if node.tag != "select" or _inside_related_scope(node, scope):
            continue

        label = " ".join(
            node.attrs.get(key, "")
            for key in (
                "name", "id", "class",
                "aria-label", "data-attribute_name",
            )
        ).strip()

        if not _VARIANT_SELECTOR_RE.search(label):
            continue

        options = [
            item for item in _walk_page(node)
            if item.tag == "option"
            and "disabled" not in item.attrs
        ]

        selected = [
            item for item in options
            if (
                "selected" in item.attrs
                or item.attrs.get("aria-selected", "").casefold() == "true"
                or item.attrs.get("data-selected", "").casefold()
                in {"1", "true", "yes"}
            )
        ]

        if len(selected) == 1:
            values.append(
                selected[0].attrs.get("value")
                or _page_text(selected[0])
            )

        elif len(options) == 1:
            values.append(
                options[0].attrs.get("value")
                or _page_text(options[0])
            )

        elif len(selected) > 1:
            ambiguities.append(
                f"multiple_selected_options:{label or 'unnamed'}"
            )

        elif options:
            ambiguities.append(
                f"variant_selector_unresolved:{label or 'unnamed'}"
            )

    input_groups: dict[str, list[_PageNode]] = {}

    for node in nodes:
        if node.tag != "input" or _inside_related_scope(node, scope):
            continue

        input_type = node.attrs.get("type", "").casefold()

        label = " ".join(
            node.attrs.get(key, "")
            for key in (
                "name", "id", "class",
                "aria-label", "data-attribute_name",
            )
        ).strip()

        if (
            input_type not in {"radio", "checkbox"}
            or not _VARIANT_SELECTOR_RE.search(label)
        ):
            continue

        input_groups.setdefault(
            node.attrs.get("name") or label,
            [],
        ).append(node)

    for label, inputs in input_groups.items():
        checked = [
            item for item in inputs
            if (
                "checked" in item.attrs
                or item.attrs.get("aria-checked", "").casefold() == "true"
                or item.attrs.get("data-selected", "").casefold()
                in {"1", "true", "yes"}
            )
        ]

        if len(checked) == 1:
            values.append(
                checked[0].attrs.get("value") or label
            )

        elif len(checked) > 1:
            ambiguities.append(
                f"multiple_checked_options:{label}"
            )

        elif len(inputs) > 1:
            ambiguities.append(
                f"variant_selector_unresolved:{label}"
            )

    return (
        " ".join(value for value in values if value).strip(),
        ambiguities,
    )


def _primary_page_scope(
    html: str,
    product_description: str,
) -> tuple[_PageNode, str, str, list[str]] | None:
    """Find one page-local scope containing the requested product identity.

    Prefer a unique main/article/body scope with one matching h1. Retailer
    themes frequently omit semantic main/h1 markup, however, so fall back to
    a unique, title-anchored product detail/card container. The fallback never
    searches related/recommended widgets and requires product-specific text.
    """

    parser = _PageTreeParser()

    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return None

    nodes = list(_walk_page(parser.root))

    def matching_headings(
        scope: _PageNode,
        tags: set[str],
    ) -> list[_PageNode]:
        matches: list[_PageNode] = []

        for node in _walk_page(scope):
            if (
                node.tag not in tags
                or _inside_related_scope(node, scope)
            ):
                continue

            heading_text = _page_text(node)

            if not heading_text:
                continue

            _score, matched = _identity_score(
                product_description,
                heading_text,
            )

            if matched:
                matches.append(node)

        return matches

    def make_result(scope: _PageNode, heading: _PageNode):
        visible = _page_text(scope)

        if not visible:
            return None

        _score, scope_matches = _identity_score(
            product_description,
            visible,
        )

        if not scope_matches:
            return None

        selected_variant, ambiguities = _variant_state(scope)

        return scope, visible, selected_variant, ambiguities

    # First preserve the original, strongest semantic-page-scope path.
    semantic_scopes = [
        node for node in nodes if node.tag == "main"
    ]

    if not semantic_scopes:
        semantic_scopes = [
            node for node in nodes if node.tag == "article"
        ]

    if not semantic_scopes:
        semantic_scopes = [
            node for node in nodes if node.tag == "body"
        ]

    if len(semantic_scopes) == 1:
        scope = semantic_scopes[0]

        headings = matching_headings(scope, {"h1"})

        if len(headings) == 1:
            result = make_result(scope, headings[0])

            if result is not None:
                return result

    # Fallback for retailer pages using h2/h3/h4 or product-card titles.
    # Product cards inside recommendation/related sections are excluded.
    scope_marker_re = re.compile(
        r"(?:^|[\s_-])(?:product|single-product|product-single|product-detail|"
        r"product-details|product-info|product-summary|product-main|product-view|"
        r"pdp|entry-summary|product-card|product-content|item-detail)(?:$|[\s_-])",
        re.IGNORECASE,
    )

    price_marker_re = re.compile(
        r"(?:price|selling|sale|amount|current|special|regular-price|price-box|"
        r"price-current|price-final|woocommerce-Price-amount)",
        re.IGNORECASE,
    )

    candidate_scopes: dict[
        int,
        tuple[_PageNode, _PageNode, int],
    ] = {}

    title_nodes: list[_PageNode] = []

    product_title_marker_re = re.compile(
        r"(?:^|[\s_-])(?:product-title|product-name|product-heading|item-title)(?:$|[\s_-])",
        re.IGNORECASE,
    )

    for node in nodes:
        marker = " ".join(
            node.attrs.get(key, "")
            for key in ("class", "id", "role")
        )

        if (
            node.tag not in {"h1", "h2", "h3", "h4"}
            and not product_title_marker_re.search(marker)
        ):
            continue

        if _inside_related_scope(node, parser.root):
            continue

        title_text = _page_text(node)

        if not title_text:
            continue

        _score, matched = _identity_score(
            product_description,
            title_text,
        )

        if matched:
            title_nodes.append(node)

    for heading in title_nodes:
        ancestors: list[_PageNode] = []
        current = heading.parent
        depth = 0

        while (
            current is not None
            and current is not parser.root
            and depth < 8
        ):
            ancestors.append(current)
            current = current.parent
            depth += 1

        marked_candidates: list[tuple[_PageNode, int]] = []
        local_candidates: list[tuple[_PageNode, int]] = []

        for depth, ancestor in enumerate(ancestors, start=1):
            if _inside_related_scope(ancestor, parser.root):
                continue

            visible = _page_text(ancestor)

            if not visible:
                continue

            _score, scope_matches = _identity_score(
                product_description,
                visible,
            )

            if not scope_matches:
                continue

            has_price = bool(
                re.search(
                    r"(?:৳|\b(?:bdt|taka|tk\.?|price|selling price|sale price)\b)",
                    visible,
                    re.IGNORECASE,
                )
            )

            marked = scope_marker_re.search(
                " ".join(
                    ancestor.attrs.get(key, "")
                    for key in ("class", "id", "role", "itemtype")
                )
            )

            marker_price = any(
                price_marker_re.search(
                    " ".join(
                        child.attrs.get(key, "")
                        for key in (
                            "class", "id", "itemprop", "aria-label"
                        )
                    )
                )
                for child in _walk_page(ancestor)
            )

            if marked and (has_price or marker_price):
                marked_candidates.append((ancestor, depth))

            elif has_price or marker_price:
                local_candidates.append((ancestor, depth))

        selected_candidates = (
            marked_candidates or local_candidates
        )

        if not selected_candidates:
            continue

        selected_candidates.sort(
            key=lambda item: item[1]
        )

        scope, depth = selected_candidates[0]

        candidate_scopes[id(scope)] = (
            scope,
            heading,
            depth,
        )

    if len(candidate_scopes) != 1:
        return None

    scope, heading, _depth = next(
        iter(candidate_scopes.values())
    )

    return make_result(scope, heading)


def _price_value_in_text(text: str, price: float) -> bool:
    if not text or not re.search(
        r"(?:৳|\b(?:bdt|taka|tk\.?|price|selling price|our price|sale price)\b)",
        text,
        re.IGNORECASE,
    ):
        return False

    for raw_value in re.findall(
        r"(?<![\w])([0-9][0-9,]*(?:\.[0-9]{1,2})?)(?![\w])",
        text,
    ):
        if _number(raw_value) == price:
            return True

    return False


def _is_struck_through_price(
    scope: _PageNode,
    price: float,
) -> bool:
    struck_tags = {"del", "s", "strike"}

    struck_marker = re.compile(
        r"(?:old|regular|original|was|crossed|list)[\s_-]*price|price[\s_-]*(?:old|regular|original|was)",
        re.IGNORECASE,
    )

    for node in _walk_page(scope):
        if _inside_related_scope(node, scope):
            continue

        marker = " ".join(
            node.attrs.get(key, "")
            for key in ("class", "id", "itemprop")
        )

        if (
            node.tag not in struck_tags
            and not struck_marker.search(marker)
        ):
            continue

        text = _page_text(node)

        if not text:
            text = " ".join(
                node.attrs.get(key, "")
                for key in ("content", "value", "data-price")
            )

        values = re.findall(
            r"(?<![\w])([0-9][0-9,]*(?:\.[0-9]{1,2})?)(?![\w])",
            text,
        )

        if any(_number(value) == price for value in values):
            return True

    return False


def _page_scope_price_matches(
    scope: _PageNode,
    price: float,
) -> bool:
    price_marker = re.compile(
        r"(?:price|selling|sale|amount|current|special|woocommerce-price-amount)",
        re.IGNORECASE,
    )

    for node in _walk_page(scope):
        if _inside_related_scope(node, scope):
            continue

        marker = " ".join(
            node.attrs.get(key, "")
            for key in ("class", "id", "itemprop", "aria-label")
        )

        if not price_marker.search(marker):
            continue

        text = _page_text(node)

        if not text:
            text = " ".join(
                node.attrs.get(key, "")
                for key in ("content", "value", "data-price")
            )

        if _price_value_in_text(f"{text} price", price):
            return True

    # Some retailer themes have no semantic price class. A currency-labelled
    # amount inside the unique product container is still valid local evidence.
    visible = _page_text(scope)

    return _price_value_in_text(visible, price)


def _build_local_product_context_binding(
    product_description: str,
    price: float,
    *,
    price_context: str = "",
    page_url: str = "",
    allow_local_context_fallback: bool = False,
) -> dict[str, Any] | None:
    """Bind a price to extractor-anchored product text when page scope is unavailable.

    This fallback is enabled only when the caller has independently established
    that the context is a local product-card anchor, not a search result snippet.
    """
    if not allow_local_context_fallback:
        return None

    context = " ".join(str(price_context or "").split())
    if not context or not _price_value_in_text(context, price):
        return None

    _score, identity_matches = _identity_score(product_description, context)
    if not identity_matches:
        return None

    target_models = set(
        re.findall(
            r"\b[a-z][a-z0-9-]*\d[a-z0-9-]*\b",
            _normal(product_description),
        )
    )
    context_models = set(
        re.findall(
            r"\b[a-z][a-z0-9-]*\d[a-z0-9-]*\b",
            _normal(context),
        )
    )
    if target_models and not (target_models & context_models):
        return None

    identity_digest = hashlib.sha256(context.encode("utf-8")).hexdigest()[:12]
    entity_id = f"page-local-product-context:{page_url or 'unknown'}:{identity_digest}"
    return {
        "association_status": "unambiguous",
        "association_reason": None,
        "association_method": "page_local_product_context_anchor",
        "product_entity_id": entity_id,
        "price_entity_id": entity_id,
        "entity_identity": context[:1200],
        "entity_title": context[:1200],
        "entity_category": context[:3000],
        "entity_brand": context[:1200],
        "page_specifications": context[:12000],
        "selected_variant": "",
        "evidence_sources": {
            "entity_identity": "same_page_local_product_card_context",
            "entity_title": "same_page_local_product_card_context",
            "entity_category": "same_page_local_product_card_context",
            "entity_brand": "same_page_local_product_card_context",
            "page_specifications": "same_page_local_product_card_context",
            "price": "same_local_product_card_price_context",
            "page_scope": "same_page_local_product_card_context",
        },
        "page_evidence_excerpt": context[:3000],
    }


def build_page_local_product_binding(
    html: str,
    product_description: str,
    price: float,
    *,
    price_context: str = "",
    page_url: str = "",
    allow_reader_context: bool = False,
    allow_local_context_fallback: bool = False,
) -> dict[str, Any]:
    """Bind page-extracted price/specification evidence to one primary product."""

    page_scope = _primary_page_scope(
        html,
        product_description,
    )

    if page_scope is None:
        local_binding = _build_local_product_context_binding(
            product_description,
            price,
            price_context=price_context,
            page_url=page_url,
            allow_local_context_fallback=allow_local_context_fallback,
        )
        if local_binding is not None:
            return local_binding
        return {
            "association_status": "ambiguous",
            "association_reason": "unique_product_page_scope_missing_or_identity_unverified",
            "association_method": "unique_primary_product_page_scope",
            "evidence_sources": {},
        }

    scope, visible, selected_variant, ambiguities = page_scope

    # On card-style retailer listings, the extractor's same-card context and
    # price are a tighter binding than a broad ancestor container. Prefer that
    # anchor only when no unresolved selector or crossed-out-price conflict exists.
    if (
        scope.tag not in {"main", "article", "body"}
        and allow_local_context_fallback
        and not ambiguities
        and not _is_struck_through_price(scope, price)
    ):
        local_binding = _build_local_product_context_binding(
            product_description,
            price,
            price_context=price_context,
            page_url=page_url,
            allow_local_context_fallback=True,
        )
        if local_binding is not None:
            return local_binding

    heading_nodes = []

    product_title_marker_re = re.compile(
        r"(?:^|[\s_-])(?:product-title|product-name|product-heading|item-title)(?:$|[\s_-])",
        re.IGNORECASE,
    )

    for node in _walk_page(scope):
        marker = " ".join(
            node.attrs.get(key, "")
            for key in ("class", "id", "role")
        )

        if (
            node.tag not in {"h1", "h2", "h3", "h4"}
            and not product_title_marker_re.search(marker)
        ):
            continue

        if _RELATED_SCOPE_RE.search(marker):
            continue

        _score, matched_heading = _identity_score(
            product_description,
            _page_text(node),
        )

        if matched_heading:
            heading_nodes.append(node)

    heading = (
        _page_text(heading_nodes[0])
        if heading_nodes
        else ""
    )

    specifications = _page_specification_text(scope)

    identity_id = (
        f"unique-primary-product-page:{page_url or heading}"
    )

    price_context_matches_product = bool(
        price_context
        and _identity_score(product_description, price_context)[1]
        and _price_value_in_text(price_context, price)
        and (
            _price_value_in_text(visible, price)
            or allow_reader_context
        )
    )

    price_matches_scope = _page_scope_price_matches(
        scope,
        price,
    )

    is_struck_through = _is_struck_through_price(scope, price)
    price_is_associated = (
        price_context_matches_product or price_matches_scope
    ) and not is_struck_through

    # A local card anchor may rescue a retailer page whose product identity is
    # visible in extracted text but whose HTML has no trustworthy price element.
    # Do not use it to override unresolved variant selectors or crossed-out prices.
    if (
        not price_is_associated
        and not is_struck_through
        and not ambiguities
        and allow_local_context_fallback
    ):
        local_binding = _build_local_product_context_binding(
            product_description,
            price,
            price_context=price_context,
            page_url=page_url,
            allow_local_context_fallback=True,
        )
        if local_binding is not None:
            return local_binding

    reasons = list(ambiguities)

    if not price_is_associated:
        reasons.append(
            "price_not_located_in_unique_product_scope"
        )

    return {
        "association_status": "ambiguous" if reasons else "unambiguous",
        "association_reason": ";".join(reasons) if reasons else None,
        "association_method": "unique_primary_product_page_scope",
        "product_entity_id": identity_id,
        "price_entity_id": identity_id,
        "entity_identity": heading,
        "entity_title": heading,
        "entity_category": visible[:3000],
        "entity_brand": f"{heading} {specifications}".strip(),
        "page_specifications": specifications,
        "selected_variant": selected_variant,
        "evidence_sources": {
            "entity_identity": "unique_primary_page_heading",
            "entity_title": "unique_primary_page_heading",
            "entity_category": "unique_primary_product_page_scope",
            "entity_brand": (
                "unique_primary_page_heading_and_specifications"
                if specifications
                else "unique_primary_page_heading"
            ),
            "page_specifications": (
                "unique_product_page_specifications"
                if specifications
                else None
            ),
            "selected_variant": (
                "selected_dom_variant" if selected_variant else None
            ),
            "price": (
                "same_url_reader_product_context"
                if allow_reader_context and price_context_matches_product
                else "same_product_local_price_context"
                if price_context_matches_product
                else "unique_product_page_price_element"
                if price_matches_scope
                else None
            ),
            "page_scope": "unique_primary_product_page",
        },
        "page_evidence_excerpt": visible[:3000],
    }


def _page_entity_binding(
    html: str,
    product_description: str,
    product_identity: str,
    entity_id: str,
    entity_title: str = "",
    entity_category: str = "",
    entity_brand: str = "",
) -> dict[str, Any]:

    page_scope = _primary_page_scope(
        html,
        product_description,
    )

    if page_scope is None:
        return {
            "association_status": "unambiguous",
            "association_method": "jsonld_product_offer",
            "product_entity_id": entity_id,
            "price_entity_id": entity_id,
            "entity_identity": product_identity,
            "entity_title": entity_title,
            "entity_category": entity_category,
            "entity_brand": entity_brand,
            "page_specifications": "",
            "selected_variant": "",
            "evidence_sources": {
                "entity_identity": "jsonld_product",
                "entity_title": (
                    "jsonld_product_name" if entity_title else None
                ),
                "entity_category": (
                    "jsonld_product_category" if entity_category else None
                ),
            },
        }

    scope, _, selected_variant, ambiguities = page_scope
    specifications = _page_specification_text(scope)

    status = (
        "ambiguous" if ambiguities else "unambiguous"
    )

    return {
        "association_status": status,
        "association_reason": ";".join(ambiguities) if ambiguities else None,
        "association_method": "jsonld_product_offer+unique_product_page_scope",
        "product_entity_id": entity_id,
        "price_entity_id": entity_id,
        "entity_identity": product_identity,
        "entity_title": entity_title,
        "entity_category": entity_category,
        "entity_brand": entity_brand,
        "page_specifications": specifications,
        "selected_variant": selected_variant,
        "evidence_sources": {
            "entity_identity": "jsonld_product",
            "entity_title": (
                "jsonld_product_name" if entity_title else None
            ),
            "entity_category": (
                "jsonld_product_category" if entity_category else None
            ),
            "page_specifications": (
                "unique_product_page_specifications"
                if specifications else None
            ),
            "selected_variant": (
                "selected_dom_variant" if selected_variant else None
            ),
        },
    }


def _identity_score(
    target: str,
    candidate: str,
) -> tuple[float, bool]:

    target_norm = _normal(target)
    candidate_norm = _normal(candidate)

    if not target_norm or not candidate_norm:
        return 0.0, False

    target_tokens = set(target_norm.split())
    candidate_tokens = set(candidate_norm.split())

    overlap = len(
        target_tokens & candidate_tokens
    ) / max(1, len(target_tokens))

    target_models = set(
        re.findall(
            r"\b[a-z][a-z0-9-]*\d[a-z0-9-]*\b",
            target_norm,
        )
    )

    candidate_models = set(
        re.findall(
            r"\b[a-z][a-z0-9-]*\d[a-z0-9-]*\b",
            candidate_norm,
        )
    )

    model_match = bool(
        target_models and target_models & candidate_models
    )

    if target_models and not model_match:
        return overlap, False

    brand_tokens = [
        token for token in target_norm.split()[:2]
        if len(token) >= 3
    ]

    brand_match = (
        not brand_tokens
        or any(token in candidate_tokens for token in brand_tokens)
    )

    accepted = (
        overlap >= 0.28 and brand_match
    ) or (
        model_match and overlap >= 0.18
    )

    return overlap + (0.35 if model_match else 0.0), accepted


def _is_product_node(node: dict[str, Any]) -> bool:
    types = _types(node)

    if "product" in types:
        return True

    # Some sites omit @type on Product but still expose a named node with an
    # offers member. Keep this fallback conservative.
    return bool(
        node.get("name")
        and ("offers" in node or "aggregateOffer" in node)
    )


def _jsonld_blocks(html: str) -> list[Any]:
    blocks: list[Any] = []

    for match in _JSON_LD_RE.finditer(html):
        raw = re.sub(
            r"^\s*<!--|--?>\s*$",
            "",
            match.group(1),
        ).strip()

        if not raw:
            continue

        try:
            blocks.append(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue

    return blocks


def _identifier(
    node: dict[str, Any],
    fallback: str,
) -> str:

    return str(
        node.get("@id")
        or node.get("sku")
        or node.get("mpn")
        or node.get("model")
        or fallback
    ).strip()


def _offer_records(
    product_node: dict[str, Any],
    index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:

    output: list[dict[str, Any]] = []

    for key in ("offers", "aggregateOffer"):
        raw = product_node.get(key)
        values = raw if isinstance(raw, list) else [raw]

        for value in values:
            if not isinstance(value, dict):
                continue

            if set(value) == {"@id"}:
                value = index.get(str(value["@id"]), {})

            if not isinstance(value, dict):
                continue

            if (
                _types(value) & {"offer", "aggregateoffer"}
                or "price" in value
                or "lowPrice" in value
            ):
                output.append(value)

    return output


def _resolve_entity(
    value: Any,
    index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:

    if not isinstance(value, dict):
        return None

    if set(value) == {"@id"}:
        return index.get(str(value["@id"]))

    return value


def _group_variants(
    group: dict[str, Any],
    index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:

    raw = group.get("hasVariant")
    values = raw if isinstance(raw, list) else [raw]

    return [
        node for value in values
        if (node := _resolve_entity(value, index)) is not None
    ]


def _selected_group_variant(
    group: dict[str, Any],
    variants: list[dict[str, Any]],
    selected_page_variant: str,
    index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:

    explicit = _resolve_entity(
        group.get("selectedVariant"),
        index,
    )

    if explicit is not None:
        return next(
            (
                variant for variant in variants
                if (
                    variant is explicit
                    or variant.get("@id") == explicit.get("@id")
                )
            ),
            None,
        )

    selected = _normal(selected_page_variant)

    if not selected:
        return None

    selected_tokens = set(selected.split())
    matches = []

    for variant in variants:
        _, identity = _product_identity(variant)

        if selected_tokens.issubset(
            set(_normal(identity).split())
        ):
            matches.append(variant)

    return matches[0] if len(matches) == 1 else None


def _same_product_reference(
    left: dict[str, Any],
    right: dict[str, Any],
) -> bool:

    for key in ("@id", "sku", "mpn", "model", "productID"):
        left_value = _normal(left.get(key))
        right_value = _normal(right.get(key))

        if left_value and left_value == right_value:
            return True

    return False


def _offer_price(
    offer: dict[str, Any],
) -> tuple[float | None, str | None]:

    price = _number(
        offer.get("price") or offer.get("lowPrice")
    )

    currency = (
        str(offer.get("priceCurrency") or "")
        .upper()
        .strip()
        or None
    )

    price_spec = offer.get("priceSpecification")

    if price is None and isinstance(price_spec, dict):
        price = _number(price_spec.get("price"))

        currency = (
            str(
                price_spec.get("priceCurrency")
                or currency
                or ""
            ).upper().strip()
            or None
        )

    return price, currency


def _product_identity(
    node: dict[str, Any],
) -> tuple[str, str]:

    brand = _name(node.get("brand"))
    extra: list[str] = []

    for key in ("additionalProperty", "additionalProperties"):
        raw = node.get(key)

        for item in raw if isinstance(raw, list) else [raw]:
            if isinstance(item, dict):
                extra.extend(
                    str(item.get(part) or "")
                    for part in ("name", "value", "valueReference")
                )

    fields = (
        node.get("name"),
        brand,
        node.get("model"),
        node.get("sku"),
        node.get("mpn"),
        node.get("productID"),
        node.get("category"),
        node.get("color"),
        node.get("size"),
        " ".join(extra),
    )

    return brand, " ".join(
        str(part) for part in fields if part
    )


def extract_matching_product_offers(
    html: str,
    product_description: str,
) -> list[dict[str, Any]]:
    """Return offers bound to a matching Product entity and its page-level evidence."""

    if not html or not product_description:
        return []

    blocks = _jsonld_blocks(html)

    index = {
        str(node.get("@id")): node
        for block in blocks
        for node in _walk(block)
        if isinstance(node, dict) and node.get("@id")
    }

    page_scope = _primary_page_scope(
        html,
        product_description,
    )

    selected_page_variant = (
        page_scope[2] if page_scope else ""
    )

    accepted: list[dict[str, Any]] = []
    seen: set[tuple[float, str, str, str, str]] = set()
    seen_products: set[int] = set()

    def append_offer(
        node: dict[str, Any],
        offer: dict[str, Any],
        *,
        ambiguous_reason: str | None = None,
    ) -> None:

        brand, identity = _product_identity(node)

        score, matched = _identity_score(
            product_description,
            identity,
        )

        if not matched:
            return

        price, currency = _offer_price(offer)

        if price is None or not currency:
            return

        availability_raw = str(
            offer.get("availability") or ""
        ).casefold()

        availability = (
            "out_of_stock" if "outofstock" in availability_raw
            else "in_stock" if "instock" in availability_raw
            else "unknown"
        )

        entity_id = _identifier(
            node,
            f"jsonld-product:{id(node)}",
        )

        offer_id = _identifier(
            offer,
            f"{entity_id}#offer:{len(accepted)}",
        )

        seller = _name(offer.get("seller"))

        key = (
            price,
            currency,
            seller.casefold(),
            entity_id,
            offer_id,
        )

        if key in seen:
            return

        seen.add(key)

        binding = _page_entity_binding(
            html,
            product_description,
            identity,
            entity_id,
            str(node.get("name") or ""),
            str(node.get("category") or ""),
            brand,
        )

        if ambiguous_reason:
            binding["association_status"] = "ambiguous"
            binding["association_reason"] = ambiguous_reason
            binding["association_method"] = (
                "product_group_offer_without_unique_variant"
            )

        accepted.append({
            "price": price,
            "currency": currency,
            "product_name": str(
                node.get("name") or ""
            ).strip(),
            "brand": brand,
            "model": str(
                node.get("model") or ""
            ).strip(),
            "sku": str(
                node.get("sku") or ""
            ).strip(),
            "mpn": str(
                node.get("mpn") or ""
            ).strip(),
            "product_identifier": str(
                node.get("sku")
                or node.get("mpn")
                or node.get("model")
                or ""
            ).strip(),
            "category": str(
                node.get("category") or ""
            ).strip(),
            "specifications": identity,
            "seller": seller,
            "availability": availability,
            "match_confidence": round(min(score, 1.0), 2),
            "price_source": "schema_org_product_offer",
            "product_entity_binding": {
                **binding,
                "price_entity_id": entity_id,
                "offer_entity_id": offer_id,
            },
        })

    nodes = [
        node
        for block in blocks
        for node in _walk(block)
        if isinstance(node, dict)
    ]

    for node in nodes:
        if (
            not _is_product_node(node)
            or id(node) in seen_products
        ):
            continue

        seen_products.add(id(node))

        for offer in _offer_records(node, index):
            append_offer(node, offer)

    for group in nodes:
        if "productgroup" not in _types(group):
            continue

        variants = _group_variants(group, index)
        group_offers = _offer_records(group, index)

        if not group_offers:
            continue

        selected_variant = _selected_group_variant(
            group,
            variants,
            selected_page_variant,
            index,
        )

        for offer in group_offers:
            item_offered = _resolve_entity(
                offer.get("itemOffered"),
                index,
            )

            if item_offered is not None:
                matched_variant = next(
                    (
                        variant for variant in variants
                        if (
                            variant is item_offered
                            or _same_product_reference(
                                variant,
                                item_offered,
                            )
                        )
                    ),
                    None,
                )

                if matched_variant is not None:
                    append_offer(matched_variant, offer)

                continue

            if len(variants) == 1:
                append_offer(variants[0], offer)

            elif selected_variant is not None:
                append_offer(selected_variant, offer)

            else:
                append_offer(
                    group,
                    offer,
                    ambiguous_reason=(
                        "product_group_offer_not_bound_to_selected_variant"
                    ),
                )

    return accepted


def _dom_value(node: _PageNode) -> str:
    return str(
        node.attrs.get("content")
        or node.attrs.get("value")
        or node.attrs.get("data-value")
        or _page_text(node)
    ).strip()


def _itemprop_nodes(
    scope: _PageNode,
    name: str,
) -> list[_PageNode]:

    matches = []

    for node in _walk_page(scope):
        if (
            node is not scope
            and "product" in node.attrs.get("itemtype", "").casefold()
        ):
            continue

        props = set(
            node.attrs.get("itemprop", "").casefold().split()
        )

        if name.casefold() in props:
            matches.append(node)

    return matches


def extract_matching_dom_product_offers(
    html: str,
    product_description: str,
) -> list[dict[str, Any]]:
    """Return offers inside one Schema.org Product DOM container."""

    if not html or not product_description:
        return []

    parser = _PageTreeParser()

    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return []

    output: list[dict[str, Any]] = []

    for index, node in enumerate(_walk_page(parser.root)):
        itemtype = node.attrs.get(
            "itemtype", ""
        ).casefold()

        if (
            "schema.org/product" not in itemtype
            and not itemtype.endswith("/product")
        ):
            continue

        def first_value(prop: str) -> str:
            values = _itemprop_nodes(node, prop)
            return _dom_value(values[0]) if values else ""

        brand = first_value("brand")

        identity_fields = {
            "name": first_value("name"),
            "brand": brand,
            "model": first_value("model"),
            "sku": first_value("sku"),
            "mpn": first_value("mpn"),
            "category": first_value("category"),
            "color": first_value("color"),
            "size": first_value("size"),
        }

        description = first_value("description")

        identity = " ".join(
            value
            for value in identity_fields.values()
            if value
        )

        score, matched = _identity_score(
            product_description,
            identity,
        )

        if not matched:
            continue

        offers = [
            item for item in _itemprop_nodes(node, "offers")
            if item is not node
        ]

        if not offers and _itemprop_nodes(node, "price"):
            offers = [node]

        entity_id = (
            node.attrs.get("id")
            or identity_fields["sku"]
            or identity_fields["mpn"]
            or identity_fields["model"]
            or f"microdata-product:{index}"
        )

        for offer_index, offer_node in enumerate(offers):
            price_nodes = _itemprop_nodes(
                offer_node,
                "price",
            )

            currency_nodes = _itemprop_nodes(
                offer_node,
                "pricecurrency",
            )

            if not price_nodes or not currency_nodes:
                continue

            price = _number(
                _dom_value(price_nodes[0])
            )

            currency = _dom_value(
                currency_nodes[0]
            ).upper()

            if price is None or not currency:
                continue

            availability_nodes = _itemprop_nodes(
                offer_node,
                "availability",
            )

            availability_raw = (
                str(
                    availability_nodes[0].attrs.get("href")
                    or _dom_value(availability_nodes[0])
                ).casefold()
                if availability_nodes
                else ""
            )

            availability = (
                "out_of_stock" if "outofstock" in availability_raw
                else "in_stock" if "instock" in availability_raw
                else "unknown"
            )

            page_scope = _primary_page_scope(
                html,
                product_description,
            )

            selected_variant = (
                page_scope[2] if page_scope else ""
            )

            ambiguities = (
                page_scope[3] if page_scope else []
            )

            binding = {
                "association_status": (
                    "ambiguous" if ambiguities else "unambiguous"
                ),
                "association_reason": (
                    ";".join(ambiguities) if ambiguities else None
                ),
                "association_method": "microdata_product_offer",
                "product_entity_id": str(entity_id),
                "price_entity_id": str(entity_id),
                "offer_entity_id": (
                    offer_node.attrs.get("id")
                    or f"{entity_id}#offer:{offer_index}"
                ),
                "entity_identity": identity,
                "entity_title": identity_fields["name"],
                "entity_category": identity_fields["category"],
                "entity_brand": brand,
                "page_specifications": _page_specification_text(node),
                "selected_variant": selected_variant,
                "evidence_sources": {
                    "entity_identity": "dom_product_container",
                    "entity_title": (
                        "dom_product_name"
                        if identity_fields["name"]
                        else None
                    ),
                    "entity_category": (
                        "dom_product_category"
                        if identity_fields["category"]
                        else None
                    ),
                    "page_specifications": (
                        "same_dom_product_page_specifications"
                        if _page_specification_text(node)
                        else None
                    ),
                    "selected_variant": (
                        "selected_dom_variant"
                        if selected_variant
                        else None
                    ),
                },
            }

            output.append({
                **identity_fields,
                "description": description,
                "product_name": identity_fields["name"],
                "product_identifier": (
                    identity_fields["sku"]
                    or identity_fields["mpn"]
                    or identity_fields["model"]
                ),
                "price": price,
                "currency": currency,
                "availability": availability,
                "match_confidence": round(min(score, 1.0), 2),
                "price_source": "schema_org_product_offer",
                "product_entity_binding": binding,
            })

    return output

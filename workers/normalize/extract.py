"""Rule-based eligibility extraction from structured fields and Kordoc blocks.

Per FR-ONT-003: rule-based extraction is prioritized over LLM.
Per FR-ONT-005: LLM results require provenance and confidence.
Per FR-DOC-006: partial parse documents cannot produce confirmed rules.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from workers.normalize.rule_ast import (
    EligibilityField,
    Provenance,
    RuleNode,
    RuleOperator,
    RulePredicate,
)


def _age_from_fields(
    raw: dict[str, Any],
) -> list[RulePredicate]:
    """Extract age conditions from 온통청년 structured fields."""
    preds: list[RulePredicate] = []
    min_age = raw.get("SPRT_TRGT_MIN_AGE", "")
    max_age = raw.get("SPRT_TRGT_MAX_AGE", "")

    if min_age and str(min_age).strip() and str(min_age).strip() != "0":
        try:
            age = int(str(min_age).strip())
            preds.append(
                RulePredicate(
                    field=EligibilityField.AGE,
                    operator=RuleOperator.GREATER_EQUAL,
                    value=age,
                    unit="years",
                    provenance=Provenance(
                        source_type="structured_field",
                        field_name="SPRT_TRGT_MIN_AGE",
                    ),
                )
            )
        except ValueError:
            pass

    if max_age and str(max_age).strip() and str(max_age).strip() != "0":
        try:
            age = int(str(max_age).strip())
            preds.append(
                RulePredicate(
                    field=EligibilityField.AGE,
                    operator=RuleOperator.LESS_EQUAL,
                    value=age,
                    unit="years",
                    provenance=Provenance(
                        source_type="structured_field",
                        field_name="SPRT_TRGT_MAX_AGE",
                    ),
                )
            )
        except ValueError:
            pass

    return preds


def _income_from_fields(
    raw: dict[str, Any],
) -> list[RulePredicate]:
    """Extract income conditions from structured fields."""
    preds: list[RulePredicate] = []
    earn_min = raw.get("EARN_MIN_AMT", "")
    earn_max = raw.get("EARN_MAX_AMT", "")

    if earn_min and str(earn_min).strip() and str(earn_min).strip() != "0":
        try:
            amount = int(str(earn_min).strip())
            preds.append(
                RulePredicate(
                    field=EligibilityField.INCOME,
                    operator=RuleOperator.LESS_EQUAL,
                    value=amount,
                    unit="KRW/year",
                    provenance=Provenance(
                        source_type="structured_field",
                        field_name="EARN_MIN_AMT",
                    ),
                )
            )
        except ValueError:
            pass

    if earn_max and str(earn_max).strip() and str(earn_max).strip() != "0":
        try:
            amount = int(str(earn_max).strip())
            preds.append(
                RulePredicate(
                    field=EligibilityField.INCOME,
                    operator=RuleOperator.LESS_EQUAL,
                    value=amount,
                    unit="KRW/year",
                    provenance=Provenance(
                        source_type="structured_field",
                        field_name="EARN_MAX_AMT",
                    ),
                )
            )
        except ValueError:
            pass

    return preds


def _text_field_predicate(
    raw: dict[str, Any],
    field_key: str,
    eligibility_field: EligibilityField,
    source_field_name: str,
) -> RulePredicate | None:
    """Extract a text-match predicate from a structured field."""
    value = raw.get(field_key, "")
    if not value or not str(value).strip():
        return None
    text = str(value).strip()
    if text == "무관":
        return None  # "No restriction" → no predicate
    return RulePredicate(
        field=eligibility_field,
        operator=RuleOperator.EQUALS,
        value=text,
        provenance=Provenance(
            source_type="structured_field",
            field_name=source_field_name,
        ),
    )


def extract_from_structured_fields(
    raw: dict[str, Any],
) -> list[RulePredicate]:
    """Extract rule-based predicates from adapter structured fields.

    This handles 온통청년's 79-field structure with structured eligibility axes.
    """
    preds: list[RulePredicate] = []
    preds.extend(_age_from_fields(raw))
    preds.extend(_income_from_fields(raw))

    for field_key, elig_field, source_name in [
        ("MRG_STTS_NM", EligibilityField.MARRIAGE, "MRG_STTS_NM"),
        ("QLFC_ACBG_NM", EligibilityField.EDUCATION, "QLFC_ACBG_NM"),
        ("EMPM_STTS_NM", EligibilityField.EMPLOYMENT, "EMPM_STTS_NM"),
        ("STDG_NM", EligibilityField.REGION, "STDG_NM"),
        ("SPCL_FLD_NM", EligibilityField.SPECIAL_TARGET, "SPCL_FLD_NM"),
    ]:
        pred = _text_field_predicate(raw, field_key, elig_field, source_name)
        if pred:
            preds.append(pred)

    return preds


def extract_from_text_patterns(
    text: str,
    block_id: str = "text-0",
    section: str | None = None,
) -> list[RulePredicate]:
    """Extract rule-based predicates from text using regex patterns.

    Used for documents that don't have structured fields.
    """
    preds: list[RulePredicate] = []

    # Age: "만 19세 이상", "19~39세", "만 39세 이하"
    age_patterns = [
        (r"만\s*(\d+)\s*세\s*이상", RuleOperator.GREATER_EQUAL),
        (r"만\s*(\d+)\s*세\s*초과", RuleOperator.GREATER_THAN),
        (r"만\s*(\d+)\s*세\s*이하", RuleOperator.LESS_EQUAL),
        (r"만\s*(\d+)\s*세\s*미만", RuleOperator.LESS_THAN),
    ]
    for pattern, op in age_patterns:
        m = re.search(pattern, text)
        if m:
            preds.append(
                RulePredicate(
                    field=EligibilityField.AGE,
                    operator=op,
                    value=int(m.group(1)),
                    unit="years",
                    provenance=Provenance(
                        source_type="document_block",
                        block_id=block_id,
                        section=section,
                    ),
                )
            )
            break

    # Age range: "19~39세" or "19세~39세"
    m = re.search(r"(\d+)\s*세?~(\d+)\s*세", text)
    if m and not preds:
        preds.append(
            RulePredicate(
                field=EligibilityField.AGE,
                operator=RuleOperator.RANGE,
                value=[int(m.group(1)), int(m.group(2))],
                unit="years",
                provenance=Provenance(
                    source_type="document_block",
                    block_id=block_id,
                    section=section,
                ),
            )
        )

    return preds


def build_individual_conditions(
    preds: list[RulePredicate],
) -> RuleNode | None:
    """Combine individual-axis predicates into an AND tree."""
    if not preds:
        return None
    nodes = [RuleNode.leaf(p) for p in preds]
    if len(nodes) == 1:
        return nodes[0]
    return RuleNode.and_(nodes)


def build_exclusions(
    preds: list[RulePredicate],
) -> list[RuleNode]:
    """Wrap exclusion predicates as NOT nodes."""
    return [RuleNode.not_(RuleNode.leaf(p)) for p in preds]


def extract_rules(
    policy_version_id: int,
    raw_fields: dict[str, Any] | None = None,
    document_text: str | None = None,
    document_blocks: list[dict[str, Any]] | None = None,
    document_is_partial: bool = False,
) -> dict[str, Any]:
    """Extract eligibility rules from all available sources.

    Args:
        policy_version_id: DB policy version ID
        raw_fields: Structured fields from adapter (온통청년 79-field format)
        document_text: Markdown text from Kordoc extraction
        document_blocks: IR blocks from Kordoc extraction
        document_is_partial: Whether the document extraction was partial

    Returns:
        Dict with 'individual_conditions', 'business_conditions',
        'exclusions', 'is_partial_safe', and metadata.
    """
    individual_preds: list[RulePredicate] = []
    exclusion_preds: list[RulePredicate] = []

    # 1. Structured fields (rule-based, confidence=1.0)
    if raw_fields:
        individual_preds.extend(extract_from_structured_fields(raw_fields))

    # 2. Document text patterns (rule-based, confidence=1.0)
    if document_text:
        individual_preds.extend(extract_from_text_patterns(document_text, "full-text"))

    # 3. Document blocks (rule-based, confidence=1.0)
    if document_blocks:
        for block in document_blocks:
            block_text = block.get("text", "")
            block_id = block.get("id", f"block-{block.get('chunk_index', 0)}")
            section = block.get("section")
            individual_preds.extend(extract_from_text_patterns(block_text, block_id, section))

    # Per FR-DOC-006: partial parse documents cannot produce confirmed rules
    is_partial_safe = not document_is_partial

    # If partial, downgrade all document-derived predicates confidence
    if document_is_partial:
        for p in individual_preds:
            if p.provenance.source_type == "document_block":
                p.confidence = 0.3  # Below 0.5 threshold

    individual_tree = build_individual_conditions(individual_preds)
    exclusions = build_exclusions(exclusion_preds)

    return {
        "policy_version_id": policy_version_id,
        "individual_conditions": individual_tree,
        "business_conditions": None,  # Business rules extracted in future LLM step
        "exclusions": exclusions,
        "is_partial_safe": is_partial_safe,
        "total_predicates": len(individual_preds),
        "llm_predicates": 0,
        "extraction_metadata": {
            "sources": [],
            "extracted_at": datetime.now(UTC).isoformat(),
        },
    }

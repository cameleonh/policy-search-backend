"""Tests for eligibility rule AST and extraction pipeline (Issue #15)."""

from __future__ import annotations

from typing import Any

from workers.normalize.extract import (
    extract_from_structured_fields,
    extract_from_text_patterns,
    extract_rules,
)
from workers.normalize.rule_ast import (
    EligibilityField,
    ExtractMethod,
    LogicalOp,
    Provenance,
    RuleNode,
    RuleOperator,
    RulePredicate,
)

# ── Rule AST construction ──


class TestRuleAST:
    def test_predicate_node(self) -> None:
        p = RulePredicate(
            field=EligibilityField.AGE,
            operator=RuleOperator.GREATER_EQUAL,
            value=19,
            unit="years",
            provenance=Provenance(source_type="structured_field", field_name="MIN_AGE"),
        )
        node = RuleNode.leaf(p)
        assert node.node_type == "predicate"
        assert node.predicate is not None
        assert node.predicate.value == 19

    def test_and_node(self) -> None:
        children = [
            RuleNode.leaf(
                RulePredicate(
                    field=EligibilityField.AGE,
                    operator=RuleOperator.GREATER_EQUAL,
                    value=19,
                    unit="years",
                    provenance=Provenance(source_type="structured_field"),
                )
            ),
            RuleNode.leaf(
                RulePredicate(
                    field=EligibilityField.REGION,
                    operator=RuleOperator.EQUALS,
                    value="서울",
                    provenance=Provenance(source_type="structured_field"),
                )
            ),
        ]
        node = RuleNode.and_(children)
        assert node.node_type == "and"
        assert node.op == LogicalOp.AND
        assert len(node.children) == 2

    def test_not_node(self) -> None:
        child = RuleNode.leaf(
            RulePredicate(
                field=EligibilityField.MARRIAGE,
                operator=RuleOperator.EQUALS,
                value="기혼",
                provenance=Provenance(source_type="structured_field"),
            )
        )
        node = RuleNode.not_(child)
        assert node.node_type == "not"
        assert node.op == LogicalOp.NOT
        assert len(node.children) == 1


# ── Structured field extraction ──


class TestStructuredExtraction:
    def test_extracts_age_min(self) -> None:
        raw: dict[str, Any] = {"SPRT_TRGT_MIN_AGE": "19", "SPRT_TRGT_MAX_AGE": "0"}
        preds = extract_from_structured_fields(raw)
        age_preds = [p for p in preds if p.field == EligibilityField.AGE]
        assert len(age_preds) == 1
        assert age_preds[0].operator == RuleOperator.GREATER_EQUAL
        assert age_preds[0].value == 19

    def test_extracts_age_range(self) -> None:
        raw: dict[str, Any] = {"SPRT_TRGT_MIN_AGE": "19", "SPRT_TRGT_MAX_AGE": "39"}
        preds = extract_from_structured_fields(raw)
        age_preds = [p for p in preds if p.field == EligibilityField.AGE]
        assert len(age_preds) == 2
        ops = {p.operator for p in age_preds}
        assert RuleOperator.GREATER_EQUAL in ops
        assert RuleOperator.LESS_EQUAL in ops

    def test_zero_age_ignored(self) -> None:
        raw: dict[str, Any] = {"SPRT_TRGT_MIN_AGE": "0", "SPRT_TRGT_MAX_AGE": "0"}
        preds = extract_from_structured_fields(raw)
        age_preds = [p for p in preds if p.field == EligibilityField.AGE]
        assert len(age_preds) == 0

    def test_extracts_income(self) -> None:
        raw: dict[str, Any] = {"EARN_MAX_AMT": "50000000", "EARN_MIN_AMT": "0"}
        preds = extract_from_structured_fields(raw)
        income_preds = [p for p in preds if p.field == EligibilityField.INCOME]
        assert len(income_preds) == 1
        assert income_preds[0].value == 50000000

    def test_muyeon_ignored(self) -> None:
        """무관 (no restriction) should not produce a predicate."""
        raw: dict[str, Any] = {"MRG_STTS_NM": "무관", "QLFC_ACBG_NM": "무관"}
        preds = extract_from_structured_fields(raw)
        marriage_preds = [p for p in preds if p.field == EligibilityField.MARRIAGE]
        edu_preds = [p for p in preds if p.field == EligibilityField.EDUCATION]
        assert len(marriage_preds) == 0
        assert len(edu_preds) == 0

    def test_provenance_preserved(self) -> None:
        raw: dict[str, Any] = {"SPRT_TRGT_MIN_AGE": "19"}
        preds = extract_from_structured_fields(raw)
        assert preds[0].provenance.field_name == "SPRT_TRGT_MIN_AGE"
        assert preds[0].provenance.source_type == "structured_field"

    def test_confidence_is_1_for_rule_based(self) -> None:
        raw: dict[str, Any] = {"SPRT_TRGT_MIN_AGE": "19"}
        preds = extract_from_structured_fields(raw)
        assert preds[0].confidence == 1.0
        assert preds[0].extract_method == ExtractMethod.RULE_BASED


# ── Text pattern extraction ──


class TestTextExtraction:
    def test_extracts_age_ge(self) -> None:
        preds = extract_from_text_patterns("지원 대상은 만 19세 이상입니다.")
        assert len(preds) == 1
        assert preds[0].value == 19
        assert preds[0].operator == RuleOperator.GREATER_EQUAL

    def test_extracts_age_le(self) -> None:
        preds = extract_from_text_patterns("만 39세 이하 청년")
        assert len(preds) == 1
        assert preds[0].value == 39
        assert preds[0].operator == RuleOperator.LESS_EQUAL

    def test_extracts_age_range(self) -> None:
        preds = extract_from_text_patterns("19~39세 청년 대상")
        assert len(preds) == 1
        assert preds[0].operator == RuleOperator.RANGE
        assert preds[0].value == [19, 39]

    def test_text_provenance_is_document_block(self) -> None:
        preds = extract_from_text_patterns("만 25세 이상", block_id="block-5")
        assert preds[0].provenance.source_type == "document_block"
        assert preds[0].provenance.block_id == "block-5"

    def test_no_age_in_text(self) -> None:
        preds = extract_from_text_patterns("지원 내용은 창업 자금입니다.")
        assert len(preds) == 0


# ── Rule set safety ──


class TestRuleSetSafety:
    def test_partial_document_downgrades_confidence(self) -> None:
        result = extract_rules(
            policy_version_id=1,
            document_text="만 19세 이상",
            document_is_partial=True,
        )
        assert result["is_partial_safe"] is False
        preds = result["individual_conditions"]
        if preds and preds.predicate:
            assert preds.predicate.confidence < 0.5

    def test_non_partial_keeps_confidence(self) -> None:
        result = extract_rules(
            policy_version_id=1,
            document_text="만 19세 이상",
            document_is_partial=False,
        )
        assert result["is_partial_safe"] is True

    def test_empty_input_no_crash(self) -> None:
        result = extract_rules(policy_version_id=1)
        assert result["individual_conditions"] is None
        assert result["total_predicates"] == 0

    def test_structured_fields_override_not_needed(self) -> None:
        """Structured fields and text patterns can coexist."""
        result = extract_rules(
            policy_version_id=1,
            raw_fields={"SPRT_TRGT_MIN_AGE": "19"},
            document_text="만 19세 이상",
        )
        assert result["total_predicates"] >= 1


# ── Deterministic output ──


class TestDeterministic:
    def test_same_input_same_output(self) -> None:
        raw: dict[str, Any] = {"SPRT_TRGT_MIN_AGE": "19", "SPRT_TRGT_MAX_AGE": "39"}
        preds1 = extract_from_structured_fields(raw)
        preds2 = extract_from_structured_fields(dict(raw))
        assert len(preds1) == len(preds2)
        for p1, p2 in zip(preds1, preds2, strict=True):
            assert p1.field == p2.field
            assert p1.value == p2.value
            assert p1.operator == p2.operator

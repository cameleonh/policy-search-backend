"""Tests for the 3-valued logic eligibility engine (Issue #16)."""

from __future__ import annotations

import pytest

from packages.matching.engine import (
    TriState,
    UserProfile,
    evaluate_predicate,
    evaluate_rule_tree,
    kleene_and,
    kleene_not,
    kleene_or,
    match_policy,
)
from workers.normalize.rule_ast import (
    EligibilityField,
    RuleNode,
    RuleOperator,
    RulePredicate,
)


def _pred(
    field: EligibilityField,
    op: RuleOperator,
    value: object,
) -> RulePredicate:
    from workers.normalize.rule_ast import Provenance

    return RulePredicate(
        field=field,
        operator=op,
        value=value,
        provenance=Provenance(source_type="test"),
    )


# ── Kleene operators ──


class TestKleene:
    def test_and_false_wins(self) -> None:
        assert kleene_and([TriState.TRUE, TriState.FALSE, TriState.UNKNOWN]) == TriState.FALSE

    def test_and_unknown_if_no_false(self) -> None:
        assert kleene_and([TriState.TRUE, TriState.UNKNOWN]) == TriState.UNKNOWN

    def test_and_all_true(self) -> None:
        assert kleene_and([TriState.TRUE, TriState.TRUE]) == TriState.TRUE

    def test_or_true_wins(self) -> None:
        assert kleene_or([TriState.FALSE, TriState.TRUE, TriState.UNKNOWN]) == TriState.TRUE

    def test_or_unknown_if_no_true(self) -> None:
        assert kleene_or([TriState.FALSE, TriState.UNKNOWN]) == TriState.UNKNOWN

    def test_or_all_false(self) -> None:
        assert kleene_or([TriState.FALSE, TriState.FALSE]) == TriState.FALSE

    def test_not_true(self) -> None:
        assert kleene_not(TriState.TRUE) == TriState.FALSE

    def test_not_false(self) -> None:
        assert kleene_not(TriState.FALSE) == TriState.TRUE

    def test_not_unknown(self) -> None:
        assert kleene_not(TriState.UNKNOWN) == TriState.UNKNOWN


# ── Predicate evaluation ──


class TestPredicateEvaluation:
    def test_age_ge_pass(self) -> None:
        result = evaluate_predicate(
            _pred(EligibilityField.AGE, RuleOperator.GREATER_EQUAL, 19),
            UserProfile(age=25),
        )
        assert result.tri_state == TriState.TRUE

    def test_age_ge_fail(self) -> None:
        result = evaluate_predicate(
            _pred(EligibilityField.AGE, RuleOperator.GREATER_EQUAL, 19),
            UserProfile(age=15),
        )
        assert result.tri_state == TriState.FALSE

    def test_missing_input_is_unknown(self) -> None:
        result = evaluate_predicate(
            _pred(EligibilityField.AGE, RuleOperator.GREATER_EQUAL, 19),
            UserProfile(),
        )
        assert result.tri_state == TriState.UNKNOWN

    def test_range_pass(self) -> None:
        result = evaluate_predicate(
            _pred(EligibilityField.AGE, RuleOperator.RANGE, [19, 39]),
            UserProfile(age=30),
        )
        assert result.tri_state == TriState.TRUE

    def test_range_fail(self) -> None:
        result = evaluate_predicate(
            _pred(EligibilityField.AGE, RuleOperator.RANGE, [19, 39]),
            UserProfile(age=45),
        )
        assert result.tri_state == TriState.FALSE

    def test_equals_pass(self) -> None:
        result = evaluate_predicate(
            _pred(EligibilityField.REGION, RuleOperator.EQUALS, "서울특별시"),
            UserProfile(region="서울특별시"),
        )
        assert result.tri_state == TriState.TRUE

    def test_equals_fail(self) -> None:
        result = evaluate_predicate(
            _pred(EligibilityField.REGION, RuleOperator.EQUALS, "서울특별시"),
            UserProfile(region="부산광역시"),
        )
        assert result.tri_state == TriState.FALSE


# ── Rule tree evaluation ──


class TestRuleTreeEvaluation:
    def test_and_tree_all_pass(self) -> None:
        tree = RuleNode.and_(
            [
                RuleNode.leaf(_pred(EligibilityField.AGE, RuleOperator.GREATER_EQUAL, 19)),
                RuleNode.leaf(_pred(EligibilityField.REGION, RuleOperator.EQUALS, "서울특별시")),
            ]
        )
        state, _ = evaluate_rule_tree(tree, UserProfile(age=25, region="서울특별시"))
        assert state == TriState.TRUE

    def test_and_tree_one_fail(self) -> None:
        tree = RuleNode.and_(
            [
                RuleNode.leaf(_pred(EligibilityField.AGE, RuleOperator.GREATER_EQUAL, 19)),
                RuleNode.leaf(_pred(EligibilityField.REGION, RuleOperator.EQUALS, "서울특별시")),
            ]
        )
        state, _ = evaluate_rule_tree(tree, UserProfile(age=25, region="부산광역시"))
        assert state == TriState.FALSE

    def test_and_tree_one_unknown(self) -> None:
        tree = RuleNode.and_(
            [
                RuleNode.leaf(_pred(EligibilityField.AGE, RuleOperator.GREATER_EQUAL, 19)),
                RuleNode.leaf(_pred(EligibilityField.REGION, RuleOperator.EQUALS, "서울특별시")),
            ]
        )
        state, _ = evaluate_rule_tree(tree, UserProfile(age=25))
        assert state == TriState.UNKNOWN

    def test_not_tree(self) -> None:
        tree = RuleNode.not_(
            RuleNode.leaf(_pred(EligibilityField.MARRIAGE, RuleOperator.EQUALS, "기혼")),
        )
        state, _ = evaluate_rule_tree(tree, UserProfile(marriage="미혼"))
        assert state == TriState.TRUE

    def test_or_tree(self) -> None:
        tree = RuleNode.or_(
            [
                RuleNode.leaf(_pred(EligibilityField.REGION, RuleOperator.EQUALS, "서울특별시")),
                RuleNode.leaf(_pred(EligibilityField.REGION, RuleOperator.EQUALS, "부산광역시")),
            ]
        )
        state, _ = evaluate_rule_tree(tree, UserProfile(region="부산광역시"))
        assert state == TriState.TRUE


# ── Policy matching ──


class TestPolicyMatching:
    def test_eligible_all_pass(self) -> None:
        tree = RuleNode.and_(
            [
                RuleNode.leaf(_pred(EligibilityField.AGE, RuleOperator.GREATER_EQUAL, 19)),
                RuleNode.leaf(_pred(EligibilityField.AGE, RuleOperator.LESS_EQUAL, 39)),
            ]
        )
        result = match_policy(tree, UserProfile(age=30))
        assert result.is_eligible
        assert len(result.matched_rules) == 2

    def test_ineligible_one_fail(self) -> None:
        tree = RuleNode.and_(
            [
                RuleNode.leaf(_pred(EligibilityField.AGE, RuleOperator.GREATER_EQUAL, 19)),
                RuleNode.leaf(_pred(EligibilityField.AGE, RuleOperator.LESS_EQUAL, 39)),
            ]
        )
        result = match_policy(tree, UserProfile(age=45))
        assert result.is_ineligible
        assert len(result.failed_rules) == 1

    def test_possible_missing_input(self) -> None:
        tree = RuleNode.and_(
            [
                RuleNode.leaf(_pred(EligibilityField.AGE, RuleOperator.GREATER_EQUAL, 19)),
                RuleNode.leaf(_pred(EligibilityField.REGION, RuleOperator.EQUALS, "서울특별시")),
            ]
        )
        result = match_policy(tree, UserProfile(age=25))
        assert result.is_possible
        assert "region" in result.missing_inputs

    def test_no_rules_means_eligible(self) -> None:
        result = match_policy(None, UserProfile(age=25))
        assert result.is_eligible

    def test_exclusion_blocks_eligible(self) -> None:
        """A NOT condition that fails should block eligibility."""
        # "NOT married" + age >= 19
        tree = RuleNode.and_(
            [
                RuleNode.not_(
                    RuleNode.leaf(_pred(EligibilityField.MARRIAGE, RuleOperator.EQUALS, "기혼")),
                ),
                RuleNode.leaf(_pred(EligibilityField.AGE, RuleOperator.GREATER_EQUAL, 19)),
            ]
        )
        result = match_policy(tree, UserProfile(age=25, marriage="기혼"))
        assert result.is_ineligible

    def test_deterministic_output(self) -> None:
        """Same profile + same rules → same result."""
        tree = RuleNode.and_(
            [
                RuleNode.leaf(_pred(EligibilityField.AGE, RuleOperator.GREATER_EQUAL, 19)),
                RuleNode.leaf(_pred(EligibilityField.REGION, RuleOperator.EQUALS, "서울특별시")),
            ]
        )
        profile = UserProfile(age=25, region="서울특별시")
        r1 = match_policy(tree, profile)
        r2 = match_policy(tree, profile)
        assert r1.tri_state == r2.tri_state
        assert len(r1.matched_rules) == len(r2.matched_rules)
        assert r1.missing_inputs == r2.missing_inputs


# ── Boundary value tests ──


class TestBoundaries:
    @pytest.mark.parametrize(
        "age,expected",
        [
            (18, TriState.FALSE),
            (19, TriState.TRUE),
            (20, TriState.TRUE),
        ],
    )
    def test_age_ge_boundary(self, age: int, expected: TriState) -> None:
        result = evaluate_predicate(
            _pred(EligibilityField.AGE, RuleOperator.GREATER_EQUAL, 19),
            UserProfile(age=age),
        )
        assert result.tri_state == expected

    @pytest.mark.parametrize(
        "age,expected",
        [
            (38, TriState.TRUE),
            (39, TriState.TRUE),
            (40, TriState.FALSE),
        ],
    )
    def test_age_le_boundary(self, age: int, expected: TriState) -> None:
        result = evaluate_predicate(
            _pred(EligibilityField.AGE, RuleOperator.LESS_EQUAL, 39),
            UserProfile(age=age),
        )
        assert result.tri_state == expected

    @pytest.mark.parametrize(
        "age,expected",
        [
            (18, TriState.FALSE),
            (19, TriState.TRUE),
            (39, TriState.TRUE),
            (40, TriState.FALSE),
        ],
    )
    def test_range_boundaries(self, age: int, expected: TriState) -> None:
        result = evaluate_predicate(
            _pred(EligibilityField.AGE, RuleOperator.RANGE, [19, 39]),
            UserProfile(age=age),
        )
        assert result.tri_state == expected

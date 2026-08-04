"""Deterministic 3-valued logic eligibility evaluation engine.

Implements the core matching engine that evaluates a user profile
against a policy's eligibility rule tree using Kleene 3-valued logic:
  - True = condition met
  - False = condition explicitly failed
  - Unknown = insufficient information

Overall result:
  - eligible: all rules True (or no rules)
  - possible: no False, at least one Unknown
  - ineligible: at least one False
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from workers.normalize.rule_ast import (
    EligibilityField,
    RuleNode,
    RuleOperator,
    RulePredicate,
)


class TriState(StrEnum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class MatchResult(BaseModel):
    """Result of evaluating a single predicate or rule tree."""

    field: str
    tri_state: TriState
    expected: str = ""
    actual: str = ""
    reason: str = ""


class PolicyMatchResult(BaseModel):
    """Complete result of matching a user profile against a policy."""

    tri_state: TriState
    matched_rules: list[MatchResult] = Field(default_factory=list)
    failed_rules: list[MatchResult] = Field(default_factory=list)
    unknown_rules: list[MatchResult] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)

    @property
    def is_eligible(self) -> bool:
        return self.tri_state == TriState.TRUE

    @property
    def is_possible(self) -> bool:
        return self.tri_state == TriState.UNKNOWN

    @property
    def is_ineligible(self) -> bool:
        return self.tri_state == TriState.FALSE


class UserProfile(BaseModel):
    """Temporary user profile for matching — never persisted."""

    age: int | None = None
    region: str | None = None
    employment: str | None = None
    education: str | None = None
    income: int | None = None
    marriage: str | None = None
    special_target: str | None = None
    business_stage: str | None = None
    business_age: int | None = None
    business_region: str | None = None
    industry: str | None = None
    annual_revenue: int | None = None
    employee_count: int | None = None
    certification: str | None = None


def _get_profile_value(profile: UserProfile, field: EligibilityField) -> Any:
    """Map an EligibilityField to the corresponding UserProfile value."""
    mapping = {
        EligibilityField.AGE: profile.age,
        EligibilityField.REGION: profile.region,
        EligibilityField.EMPLOYMENT: profile.employment,
        EligibilityField.EDUCATION: profile.education,
        EligibilityField.INCOME: profile.income,
        EligibilityField.MARRIAGE: profile.marriage,
        EligibilityField.SPECIAL_TARGET: profile.special_target,
        EligibilityField.BUSINESS_STAGE: profile.business_stage,
        EligibilityField.BUSINESS_AGE: profile.business_age,
        EligibilityField.BUSINESS_REGION: profile.business_region,
        EligibilityField.INDUSTRY: profile.industry,
        EligibilityField.ANNUAL_REVENUE: profile.annual_revenue,
        EligibilityField.EMPLOYEE_COUNT: profile.employee_count,
        EligibilityField.CERTIFICATION: profile.certification,
    }
    return mapping.get(field)


def evaluate_predicate(
    predicate: RulePredicate,
    profile: UserProfile,
) -> MatchResult:
    """Evaluate a single predicate against the user profile."""
    actual = _get_profile_value(profile, predicate.field)
    field_name = predicate.field.value

    # Unknown if profile field is not provided
    if actual is None:
        return MatchResult(
            field=field_name,
            tri_state=TriState.UNKNOWN,
            expected=str(predicate.value),
            reason=f"Missing input for {field_name}",
        )

    expected = predicate.value
    op = predicate.operator

    if op == RuleOperator.EQUALS:
        result = TriState.TRUE if str(actual) == str(expected) else TriState.FALSE
    elif op == RuleOperator.NOT_EQUALS:
        result = TriState.TRUE if str(actual) != str(expected) else TriState.FALSE
    elif op == RuleOperator.GREATER_EQUAL:
        result = _compare_numeric(actual, expected, ">=")
    elif op == RuleOperator.LESS_EQUAL:
        result = _compare_numeric(actual, expected, "<=")
    elif op == RuleOperator.GREATER_THAN:
        result = _compare_numeric(actual, expected, ">")
    elif op == RuleOperator.LESS_THAN:
        result = _compare_numeric(actual, expected, "<")
    elif op == RuleOperator.RANGE:
        result = _in_range(actual, expected)
    elif op == RuleOperator.IN:
        result = TriState.TRUE if actual in expected else TriState.FALSE
    elif op == RuleOperator.NOT_IN:
        result = TriState.FALSE if actual in expected else TriState.TRUE
    elif op == RuleOperator.EXISTS:
        result = TriState.TRUE if actual is not None else TriState.UNKNOWN
    else:
        result = TriState.UNKNOWN

    return MatchResult(
        field=field_name,
        tri_state=result,
        expected=str(expected),
        actual=str(actual),
        reason="" if result == TriState.TRUE else f"{field_name} {op.value} {expected} failed",
    )


def _compare_numeric(actual: Any, expected: Any, op: str) -> TriState:
    """Numeric comparison with type safety."""
    try:
        a = float(actual)
        e = float(expected)
    except (ValueError, TypeError):
        return TriState.UNKNOWN

    if op == ">=":
        return TriState.TRUE if a >= e else TriState.FALSE
    if op == "<=":
        return TriState.TRUE if a <= e else TriState.FALSE
    if op == ">":
        return TriState.TRUE if a > e else TriState.FALSE
    if op == "<":
        return TriState.TRUE if a < e else TriState.FALSE
    return TriState.UNKNOWN


def _in_range(actual: Any, expected: Any) -> TriState:
    """Check if a value is within a [min, max] range."""
    if not isinstance(expected, list) or len(expected) != 2:
        return TriState.UNKNOWN
    try:
        a = float(actual)
        lo, hi = float(expected[0]), float(expected[1])
    except (ValueError, TypeError):
        return TriState.UNKNOWN
    return TriState.TRUE if lo <= a <= hi else TriState.FALSE


# ── 3-valued logic operators (Kleene) ──────────


def kleene_and(values: list[TriState]) -> TriState:
    """AND: False wins, then Unknown, then True."""
    if TriState.FALSE in values:
        return TriState.FALSE
    if TriState.UNKNOWN in values:
        return TriState.UNKNOWN
    return TriState.TRUE


def kleene_or(values: list[TriState]) -> TriState:
    """OR: True wins, then Unknown, then False."""
    if TriState.TRUE in values:
        return TriState.TRUE
    if TriState.UNKNOWN in values:
        return TriState.UNKNOWN
    return TriState.FALSE


def kleene_not(value: TriState) -> TriState:
    """NOT: negate True/False, Unknown stays Unknown."""
    if value == TriState.TRUE:
        return TriState.FALSE
    if value == TriState.FALSE:
        return TriState.TRUE
    return TriState.UNKNOWN


def evaluate_rule_tree(
    node: RuleNode,
    profile: UserProfile,
) -> tuple[TriState, list[MatchResult]]:
    """Recursively evaluate a rule tree and return (TriState, results)."""
    if node.node_type == "predicate" and node.predicate:
        result = evaluate_predicate(node.predicate, profile)
        return result.tri_state, [result]

    if node.node_type == "not":
        child_state, child_results = evaluate_rule_tree(node.children[0], profile)
        return kleene_not(child_state), child_results

    child_states: list[TriState] = []
    all_results: list[MatchResult] = []

    for child in node.children:
        state, results = evaluate_rule_tree(child, profile)
        child_states.append(state)
        all_results.extend(results)

    if node.node_type == "and":
        return kleene_and(child_states), all_results
    if node.node_type == "or":
        return kleene_or(child_states), all_results

    return TriState.UNKNOWN, all_results


def match_policy(
    individual_tree: RuleNode | None,
    profile: UserProfile,
) -> PolicyMatchResult:
    """Evaluate a policy's eligibility rules against a user profile.

    Returns PolicyMatchResult with:
      - tri_state: overall result
      - matched/failed/unknown rules
      - missing_inputs (fields that caused Unknown)
    """
    if individual_tree is None:
        return PolicyMatchResult(tri_state=TriState.TRUE)

    state, results = evaluate_rule_tree(individual_tree, profile)

    matched = [r for r in results if r.tri_state == TriState.TRUE]
    failed = [r for r in results if r.tri_state == TriState.FALSE]
    unknown = [r for r in results if r.tri_state == TriState.UNKNOWN]
    missing = [r.field for r in unknown]

    return PolicyMatchResult(
        tri_state=state,
        matched_rules=matched,
        failed_rules=failed,
        unknown_rules=unknown,
        missing_inputs=missing,
    )

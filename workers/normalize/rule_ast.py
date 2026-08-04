"""Eligibility rule AST — versioned tree structure for policy conditions.

Each rule node is either a logical operator (AND/OR/NOT) or a predicate.
Predicates carry provenance back to the source document or structured field.
Rules are immutable per policy version — new versions get new rule rows.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class LogicalOp(StrEnum):
    AND = "AND"
    OR = "OR"
    NOT = "NOT"


class RuleOperator(StrEnum):
    """Comparison operators for predicates."""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_EQUAL = "greater_equal"
    LESS_EQUAL = "less_equal"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    IN = "in"
    NOT_IN = "not_in"
    EXISTS = "exists"
    BEFORE = "before"
    AFTER = "after"
    RANGE = "range"


class EligibilityField(StrEnum):
    """Standardized eligibility field names.

    Individual axis:
      age, region, employment, education, income, special_target, marriage
    Business axis:
      business_stage, business_age, business_region, industry,
      annual_revenue, employee_count, certification
    Temporal:
      application_period
    """

    AGE = "age"
    REGION = "region"
    EMPLOYMENT = "employment"
    EDUCATION = "education"
    INCOME = "income"
    SPECIAL_TARGET = "special_target"
    MARRIAGE = "marriage"
    BUSINESS_STAGE = "business_stage"
    BUSINESS_AGE = "business_age"
    BUSINESS_REGION = "business_region"
    INDUSTRY = "industry"
    ANNUAL_REVENUE = "annual_revenue"
    EMPLOYEE_COUNT = "employee_count"
    CERTIFICATION = "certification"
    APPLICATION_PERIOD = "application_period"


class ExtractMethod(StrEnum):
    RULE_BASED = "rule_based"
    LLM = "llm"


class Provenance(BaseModel):
    """Where the rule was extracted from — traceable to source."""

    source_type: str = Field(description="'structured_field' or 'document_block'")
    field_name: str | None = Field(default=None, description="Structured field if from adapter")
    block_id: str | None = Field(default=None, description="Kordoc IR block ID if from document")
    section: str | None = None
    page: int | None = None
    table_ref: str | None = None
    row: int | None = None
    col: int | None = None


class RulePredicate(BaseModel):
    """A leaf node — a single eligibility condition."""

    node_type: str = Field(default="predicate")
    field: EligibilityField
    operator: RuleOperator
    value: Any = Field(description="Comparison value")
    unit: str | None = Field(
        default=None,
        description="e.g. 'years', 'KRW', 'months', 'persons'",
    )
    provenance: Provenance
    extract_method: ExtractMethod = ExtractMethod.RULE_BASED
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="1.0 for rule-based, <1.0 for LLM-extracted",
    )


class RuleNode(BaseModel):
    """A rule tree node — either a logical operator or a predicate."""

    node_type: str = Field(description="'and', 'or', 'not', or 'predicate'")
    op: LogicalOp | None = None
    children: list[RuleNode] = Field(default_factory=list)
    predicate: RulePredicate | None = None

    @staticmethod
    def and_(children: list[RuleNode]) -> RuleNode:
        return RuleNode(node_type="and", op=LogicalOp.AND, children=children)

    @staticmethod
    def or_(children: list[RuleNode]) -> RuleNode:
        return RuleNode(node_type="or", op=LogicalOp.OR, children=children)

    @staticmethod
    def not_(child: RuleNode) -> RuleNode:
        return RuleNode(node_type="not", op=LogicalOp.NOT, children=[child])

    @staticmethod
    def leaf(p: RulePredicate) -> RuleNode:
        return RuleNode(node_type="predicate", predicate=p)


# Resolve forward references
RuleNode.model_rebuild()


class EligibilityRuleSet(BaseModel):
    """Complete rule set for a single policy version.

    Contains separate trees for individual and business conditions,
    plus explicit exclusions.
    """

    policy_version_id: int
    individual_conditions: RuleNode | None = None
    business_conditions: RuleNode | None = None
    exclusions: list[RuleNode] = Field(default_factory=list)
    extraction_metadata: dict[str, Any] = Field(default_factory=dict)

    def all_predicates(self) -> list[RulePredicate]:
        """Flatten all leaf predicates across the entire rule set."""

        def walk(node: RuleNode | None) -> list[RulePredicate]:
            if node is None:
                return []
            if node.node_type == "predicate" and node.predicate:
                return [node.predicate]
            preds: list[RulePredicate] = []
            for child in node.children:
                preds.extend(walk(child))
            return preds

        result: list[RulePredicate] = []
        result.extend(walk(self.individual_conditions))
        result.extend(walk(self.business_conditions))
        for excl in self.exclusions:
            result.extend(walk(excl))
        return result

    def llm_predicates(self) -> list[RulePredicate]:
        """Return only LLM-extracted predicates (need review before promotion)."""
        return [p for p in self.all_predicates() if p.extract_method == ExtractMethod.LLM]

    def is_safe_for_matching(self) -> bool:
        """Check if all predicates have provenance and sufficient confidence."""
        for p in self.all_predicates():
            if p.confidence < 0.5:
                return False
            if (
                p.extract_method == ExtractMethod.LLM
                and not p.provenance.block_id
                and not p.provenance.field_name
            ):
                return False
        return True

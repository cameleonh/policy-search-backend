"""Shared enumerations for the policy search schema.

These enums mirror the PostgreSQL CHECK constraints in the migrations.
They are the single source of truth for allowed values — migrations
reference the string values, and the Python contracts reuse them.
"""

from __future__ import annotations

from enum import StrEnum


class ExecutionStatus(StrEnum):
    """Ingestion run / item execution lifecycle."""

    PENDING = "pending"
    RUNNING = "running"
    PARTIAL = "partial"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DocumentStatus(StrEnum):
    """Document extraction pipeline status."""

    PENDING = "pending"
    PARSED = "parsed"
    PARTIAL = "partial"
    ENCRYPTED = "encrypted"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class ExtractMethod(StrEnum):
    """How an eligibility rule was extracted."""

    RULE_BASED = "rule_based"
    LLM = "llm"


class TargetType(StrEnum):
    """Whether a policy targets individuals, businesses, or both."""

    INDIVIDUAL = "individual"
    BUSINESS = "business"
    BOTH = "both"


class RegionLevel(StrEnum):
    """Administrative region hierarchy level."""

    NATIONAL = "national"
    METROPOLITAN = "metropolitan"
    LOCAL = "local"

"""Three-valued logic match result type.

This is the minimal contract for the matching package. Issue #16 implements
the full deterministic eligibility evaluator on top of this.
"""

from __future__ import annotations

from enum import StrEnum


class TriState(StrEnum):
    """Three-valued logic match result."""

    ELIGIBLE = "eligible"
    POSSIBLE = "possible"
    INELIGIBLE = "ineligible"

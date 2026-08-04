"""Exit codes for ingestion adapters.

Compatible with both youth-search and sole-search conventions:
  0 — complete: all expected records collected
  2 — partial/failure: some records collected but not all, or parse failure
  3 — manual escalation: blocked, CAPTCHA, or auth required

Adapters MUST use these constants rather than raw integers.
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    COMPLETE = 0
    PARTIAL = 2
    MANUAL = 3
    FAILED = 1

"""Retryable error classification for ingestion adapters.

Adapters raise these exceptions to signal the nature of a failure.
The ingestion orchestrator uses them to decide whether to retry,
escalate to manual, or fail immediately.
"""

from __future__ import annotations


class AdapterError(Exception):
    """Base class for adapter errors."""


class RetryableError(AdapterError):
    """Transient failure — network timeout, rate limit, temporary 5xx.

    The orchestrator may retry with backoff.
    """


class BlockedError(AdapterError):
    """Access blocked — 401/403, CAPTCHA, IP ban.

    The orchestrator must NOT retry; escalate to manual.
    """


class ParseError(AdapterError):
    """Response structure changed or is unexpected.

    The orchestrator should not retry the same request; the adapter
    or site contract may have changed.
    """


class robotsDisallowedError(AdapterError):
    """The target URL is disallowed by robots.txt or ToS.

    The adapter must not send the request at all.
    """

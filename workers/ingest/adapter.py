"""Source adapter protocol — the contract every site-specific adapter must implement.

Issue #3 defines the interface only; actual network implementations
land in issues #4–#12.  This protocol is what the ingestion orchestrator
calls.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from workers.ingest.collection_report import CollectionReport
from workers.ingest.source_definition import SourceDefinition
from workers.ingest.source_record import AttachmentMeta, SourceRecord


@runtime_checkable
class SourceAdapter(Protocol):
    """Contract for all ingestion source adapters.

    Implementations wrap a specific source (온통청년, 소상공인24, etc.)
    and expose a uniform interface for list, detail, attachments, and
    checkpointing.
    """

    definition: SourceDefinition

    def list_records(
        self,
        *,
        checkpoint: str | None = None,
        max_pages: int | None = None,
    ) -> Iterator[SourceRecord]:
        """Yield normalized listing records.

        Args:
            checkpoint: Opaque value from a previous run to resume.
            max_pages: Safety limit on pagination depth.

        Yields:
            SourceRecord instances (listing-level, may lack body_text).

        Raises:
            RetryableError: Transient network failure.
            BlockedError: Access blocked (401/403, CAPTCHA).
            ParseError: Response structure unexpected.
        """
        ...

    def fetch_detail(self, record: SourceRecord) -> SourceRecord:
        """Enrich a listing record with full body text and metadata.

        Returns a new SourceRecord with body_text and content_hash filled.
        If detail fetch fails, content_hash stays None.

        Raises:
            RetryableError: Transient failure.
            BlockedError: Access blocked.
        """
        ...

    def list_attachments(self, record: SourceRecord) -> list[AttachmentMeta]:
        """Enumerate downloadable attachments for a record.

        Returns attachment metadata without downloading the actual files.
        """
        ...

    def get_checkpoint(self) -> str | None:
        """Return the current checkpoint value for resumable collection.

        None if the adapter does not support checkpointing or has no state.
        """
        ...

    def collect(self) -> CollectionReport:
        """Run a full collection cycle: list → detail → attachments.

        This is the high-level entry point called by the orchestrator.
        It internally calls list_records, fetch_detail, list_attachments,
        and produces a CollectionReport.
        """
        ...

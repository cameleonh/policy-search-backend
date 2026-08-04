"""Ingestion worker — adapter contracts and source registry.

Issue #3 defines the interface; network implementations land in #4–#12.
"""

from workers.ingest.adapter import SourceAdapter
from workers.ingest.collection_report import (
    CollectionOutcome,
    CollectionReport,
    exit_code_from_outcome,
    outcome_from_counts,
)
from workers.ingest.dedup import DuplicateCandidate, find_duplicates
from workers.ingest.errors import (
    AdapterError,
    BlockedError,
    ParseError,
    RetryableError,
    robotsDisallowedError,
)
from workers.ingest.exit_codes import ExitCode
from workers.ingest.source_definition import (
    KNOWN_SOURCES,
    CredentialRequirement,
    ExecutionMode,
    RobotsStatus,
    SourceCategory,
    SourceDefinition,
)
from workers.ingest.source_record import (
    AttachmentMeta,
    RecordStatus,
    RecordType,
    SourceRecord,
)

__all__ = [
    "AdapterError",
    "AttachmentMeta",
    "BlockedError",
    "CollectionOutcome",
    "CollectionReport",
    "CredentialRequirement",
    "DuplicateCandidate",
    "ExecutionMode",
    "ExitCode",
    "KNOWN_SOURCES",
    "ParseError",
    "RecordStatus",
    "RecordType",
    "RetryableError",
    "RobotsStatus",
    "SourceAdapter",
    "SourceCategory",
    "SourceDefinition",
    "SourceRecord",
    "exit_code_from_outcome",
    "find_duplicates",
    "outcome_from_counts",
    "robotsDisallowedError",
]

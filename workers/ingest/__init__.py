"""Ingestion worker — adapter contracts and source registry.

Issue #3 defines the interface; network implementations land in #4–#12.
"""

from workers.ingest.adapter import SourceAdapter
from workers.ingest.bizinfo_adapter import BizinfoAdapter, normalize_bizinfo
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
from workers.ingest.region_util import canon_region
from workers.ingest.sbiz24_adapter import Sbiz24Adapter, normalize_combine, normalize_pbanc
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
from workers.ingest.youthcenter_adapter import (
    YouthcenterAdapter,
    normalize_youthcenter,
)

__all__ = [
    "AdapterError",
    "AttachmentMeta",
    "BlockedError",
    "BizinfoAdapter",
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
    "Sbiz24Adapter",
    "SourceAdapter",
    "SourceCategory",
    "SourceDefinition",
    "SourceRecord",
    "YouthcenterAdapter",
    "canon_region",
    "exit_code_from_outcome",
    "find_duplicates",
    "normalize_bizinfo",
    "normalize_combine",
    "normalize_pbanc",
    "normalize_youthcenter",
    "outcome_from_counts",
    "robotsDisallowedError",
]

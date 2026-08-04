"""Normalized source record — the common output shape from all adapters.

Every adapter, regardless of its source's native format, must produce
SourceRecord instances.  This is the bridge between site-specific
crawlers and the rest of the pipeline (dedup, archive, normalize).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RecordStatus(StrEnum):
    """Application period status of a policy announcement."""

    OPEN = "open"
    CLOSED = "closed"
    ALWAYS_OPEN = "always_open"
    UNKNOWN = "unknown"


class RecordType(StrEnum):
    """Distinguishes policy announcements from reference data.

    Only POLICY records are eligible for eligibility matching.
    REFERENCE records (notices, guides, FAQs) must be kept out of
    the matching pipeline.
    """

    POLICY = "policy"
    REFERENCE = "reference"


class AttachmentMeta(BaseModel):
    """Metadata for a single attachment file, before download."""

    filename: str
    url: str
    mime_type: str | None = None
    byte_size: int | None = None


class SourceRecord(BaseModel):
    """Normalized output from a single source listing.

    This shape unifies the youth-search record (source/id/title/org/...)
    and the sole-search record (source/source_id/canonical_url/agency/...)
    into a single contract.
    """

    source: str = Field(description="Source key matching a SourceDefinition")
    remote_id: str = Field(description="Source-native unique identifier")
    canonical_url: str = Field(description="Stable, human-visitable URL")
    title: str = Field(description="Announcement title")
    agency: str = Field(default="", description="Implementing or supervising agency")
    body_text: str | None = Field(default=None, description="Full body text if fetched")
    status: RecordStatus = Field(default=RecordStatus.UNKNOWN)
    record_type: RecordType = Field(
        default=RecordType.POLICY,
        description="Policy announcement vs reference data",
    )
    apply_start: datetime | None = None
    apply_end: datetime | None = None
    region: str | None = Field(default=None, description="Geographic scope")
    target_category: str | None = Field(
        default=None,
        description="individual, business, or both",
    )
    announce_no: str | None = Field(
        default=None,
        description="Official announcement number, if available",
    )
    tags: list[str] = Field(default_factory=list)
    attachments: list[AttachmentMeta] = Field(default_factory=list)
    attachments_complete: bool = Field(
        default=False,
        description="True only when all attachments were fetched",
    )
    content_hash: str | None = Field(
        default=None,
        description="SHA-256 of body + sorted attachment hashes, or None if incomplete",
    )
    crawled_at: datetime = Field(description="UTC timestamp of collection")
    raw: dict[str, Any] = Field(
        default_factory=dict,
        description="Preserved original fields from the source",
    )

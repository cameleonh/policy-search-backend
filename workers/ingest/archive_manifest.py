"""Archive manifest contract for weekly GitHub Release bundles.

A manifest describes the contents of a single source's archive bundle
within a weekly Release.  Each entry maps a collected original file to
its archive coordinates and integrity hash.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ArchiveAssetStatus(StrEnum):
    """Lifecycle of an archive asset."""

    DRAFT = "draft"
    FINALIZED = "finalized"
    FAILED = "failed"


class ManifestEntry(BaseModel):
    """A single file entry within the archive manifest.

    Maps a collected original to its compressed location and integrity.
    """

    source: str = Field(description="Source key, e.g. 'youthcenter'")
    remote_id: str = Field(description="Source-native identifier")
    source_url: str | None = Field(default=None, description="Original URL")
    collected_at: datetime = Field(description="UTC collection timestamp")
    original_filename: str = Field(description="Filename as fetched from source")
    safe_path: str = Field(description="Sanitized path within the archive bundle")
    mime_type: str | None = Field(default=None)
    byte_size: int = Field(description="Original uncompressed byte count")
    sha256: str = Field(description="SHA-256 of the original file content (pre-compression)")
    archive_asset: str = Field(
        description="Release asset name containing this file, e.g. 'youthcenter.tar.gz'"
    )
    archive_member: str = Field(description="Path within the compressed archive bundle")
    content_hash: str | None = Field(
        default=None,
        description="Normalized content hash from the adapter, if available",
    )


class ArchiveManifest(BaseModel):
    """The complete manifest for a single weekly Release asset.

    One manifest per source per weekly Release.  Stored as `manifest.json`
    inside the compressed bundle and also uploaded as a standalone asset.
    """

    release_tag: str = Field(description="Weekly tag: 'ingest-YYYY-Www'")
    source: str = Field(description="Source key")
    manifest_version: str = Field(default="1.0")
    created_at: datetime = Field(description="UTC manifest creation time")
    status: ArchiveAssetStatus = Field(default=ArchiveAssetStatus.DRAFT)
    entries: list[ManifestEntry] = Field(default_factory=list)
    total_files: int = Field(default=0)
    total_bytes: int = Field(default=0)

    def add_entry(self, entry: ManifestEntry) -> None:
        """Add a file entry and update totals."""
        self.entries.append(entry)
        self.total_files = len(self.entries)
        self.total_bytes += entry.byte_size

    def find_by_sha256(self, sha256: str) -> ManifestEntry | None:
        """Find an existing entry by SHA-256 (for dedup)."""
        return next((e for e in self.entries if e.sha256 == sha256), None)

    def to_json(self) -> str:
        """Serialize to JSON string for embedding in the archive."""
        import json

        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2)


class WeeklyReleaseTag:
    """Utility for weekly Release tag naming and parsing.

    Tags follow the pattern: ingest-YYYY-Www
    e.g. ingest-2026-W31
    """

    PREFIX = "ingest-"
    FORMAT = "ingest-{year}-W{week:02d}"

    @staticmethod
    def format_tag(year: int, week: int) -> str:
        """Build a Release tag from ISO year and week number."""
        return WeeklyReleaseTag.FORMAT.format(year=year, week=week)

    @staticmethod
    def from_date(dt: datetime) -> str:
        """Build a Release tag from a datetime using ISO calendar week."""
        iso_year, iso_week, _ = dt.isocalendar()
        return WeeklyReleaseTag.format_tag(iso_year, iso_week)

    @staticmethod
    def parse_tag(tag: str) -> tuple[int, int] | None:
        """Parse a tag into (year, week). Returns None if not matching."""
        import re

        m = re.fullmatch(r"ingest-(\d{4})-W(\d{2})", tag)
        if not m:
            return None
        return int(m.group(1)), int(m.group(2))


def safe_archive_filename(filename: str) -> str:
    """Sanitize a filename for safe use within an archive bundle.

    Replaces path separators and dangerous characters with underscores.
    Preserves Korean characters (UTF-8).
    """
    import re

    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[*:"<>|?\x00-\x1f]', "_", name)
    name = name.strip(". ")
    return name or "unnamed"


def split_asset_name(source: str, part: int, total_parts: int) -> str:
    """Generate a split asset filename for large bundles.

    GitHub Release assets have a 2GiB limit.  When a bundle exceeds this,
    it is split into parts with deterministic names.
    """
    if total_parts <= 1:
        return f"{source}.tar.gz"
    return f"{source}.part{part:02d}of{total_parts:02d}.tar.gz"

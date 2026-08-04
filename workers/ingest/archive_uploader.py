"""Archive uploader — manages weekly GitHub Release bundles.

Handles the draft → finalize lifecycle for source bundles:
  1. Collect files for a source during a weekly run
  2. Compute SHA-256 for each file (dedup against existing manifests)
  3. Compress into a source bundle with manifest.json
  4. Upload as a Release asset (draft until all sources complete)
  5. Verify by re-downloading and checking SHA-256

Network operations are isolated behind clear interfaces so the contract
and manifest logic can be tested without GitHub API access.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from datetime import UTC, datetime
from pathlib import Path

from workers.ingest.archive_manifest import (
    ArchiveAssetStatus,
    ArchiveManifest,
    ManifestEntry,
    safe_archive_filename,
    split_asset_name,
)

# GitHub Release asset size limit
MAX_ASSET_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB


def compute_sha256(data: bytes) -> str:
    """Compute SHA-256 hex digest of byte data."""
    return hashlib.sha256(data).hexdigest()


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 of a file on disk."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class CollectedFile:
    """A single file collected for archival."""

    def __init__(
        self,
        *,
        source: str,
        remote_id: str,
        filename: str,
        content: bytes,
        source_url: str | None = None,
        mime_type: str | None = None,
        collected_at: datetime | None = None,
        content_hash: str | None = None,
    ) -> None:
        self.source = source
        self.remote_id = remote_id
        self.filename = filename
        self.content = content
        self.source_url = source_url
        self.mime_type = mime_type
        self.collected_at = collected_at or datetime.now(UTC)
        self.content_hash = content_hash
        self.sha256 = compute_sha256(content)
        self.byte_size = len(content)
        self.safe_path = safe_archive_filename(filename)


class SourceBundle:
    """Builds a compressed tar.gz bundle for a single source.

    The bundle contains:
      - manifest.json (file index with SHA-256 hashes)
      - <files> (original files with safe names)

    If the resulting bundle would exceed MAX_ASSET_BYTES, the caller
    must split it — this class reports the size but does not split.
    """

    def __init__(self, source: str, release_tag: str) -> None:
        self.source = source
        self.release_tag = release_tag
        self._files: list[CollectedFile] = []
        self._existing_shas: dict[str, ManifestEntry] = {}

    def add_existing_entry(self, entry: ManifestEntry) -> None:
        """Register an already-archived file for dedup."""
        self._existing_shas[entry.sha256] = entry

    def add_file(self, file: CollectedFile) -> ManifestEntry | None:
        """Add a file. Returns None if deduped (already archived).

        Returns the ManifestEntry if the file is new and will be included
        in this bundle.  Returns None if the SHA-256 matches an existing
        archive entry (dedup — no re-upload needed).
        """
        if file.sha256 in self._existing_shas:
            return None  # Already archived — dedup

        entry = ManifestEntry(
            source=file.source,
            remote_id=file.remote_id,
            source_url=file.source_url,
            collected_at=file.collected_at,
            original_filename=file.filename,
            safe_path=file.safe_path,
            mime_type=file.mime_type,
            byte_size=file.byte_size,
            sha256=file.sha256,
            archive_asset=split_asset_name(self.source, 1, 1),
            archive_member=file.safe_path,
            content_hash=file.content_hash,
        )
        self._files.append(file)
        self._existing_shas[file.sha256] = entry
        return entry

    def build(self) -> tuple[bytes, ArchiveManifest]:
        """Build the tar.gz bundle and manifest.

        Returns (bundle_bytes, manifest).
        """
        manifest = ArchiveManifest(
            release_tag=self.release_tag,
            source=self.source,
            created_at=datetime.now(UTC),
            status=ArchiveAssetStatus.DRAFT,
        )

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for file in self._files:
                info = tarfile.TarInfo(name=file.safe_path)
                info.size = file.byte_size
                info.mtime = int(file.collected_at.timestamp())
                tar.addfile(info, io.BytesIO(file.content))

                manifest.add_entry(self._existing_shas[file.sha256])

            manifest_json = manifest.to_json().encode("utf-8")
            info = tarfile.TarInfo(name="manifest.json")
            info.size = len(manifest_json)
            tar.addfile(info, io.BytesIO(manifest_json))

        bundle = buf.getvalue()
        manifest.status = ArchiveAssetStatus.FINALIZED
        manifest.total_bytes = sum(f.byte_size for f in self._files)

        return bundle, manifest

    def estimated_size(self) -> int:
        """Rough uncompressed size estimate."""
        return sum(f.byte_size for f in self._files)


def needs_splitting(bundle_size: int) -> bool:
    """Check if a bundle exceeds the GitHub Release asset limit."""
    return bundle_size >= MAX_ASSET_BYTES


def verify_manifest_integrity(bundle_bytes: bytes, manifest: ArchiveManifest) -> bool:
    """Verify that every file in the manifest exists in the bundle and
    its SHA-256 matches.

    Returns True if all entries verify, False otherwise.
    """
    buf = io.BytesIO(bundle_bytes)
    try:
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            members = {m.name: m for m in tar.getmembers()}

            for entry in manifest.entries:
                if entry.safe_path not in members:
                    return False
                extracted = tar.extractfile(entry.safe_path)
                if extracted is None:
                    return False
                content = extracted.read()
                if compute_sha256(content) != entry.sha256:
                    return False
            return True
    except (tarfile.TarError, OSError):
        return False


def re_download_verify(downloaded_bytes: bytes, expected_sha256: str) -> bool:
    """Verify a re-downloaded asset matches the expected SHA-256."""
    return compute_sha256(downloaded_bytes) == expected_sha256

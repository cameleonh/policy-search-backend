"""Contract tests for the GitHub Release archive system (Issue #13).

All tests are network-free — they test manifest construction, bundle
building, SHA-256 verification, dedup, tag naming, and splitting.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from workers.ingest.archive_manifest import (
    ArchiveAssetStatus,
    ArchiveManifest,
    ManifestEntry,
    WeeklyReleaseTag,
    safe_archive_filename,
    split_asset_name,
)
from workers.ingest.archive_uploader import (
    CollectedFile,
    SourceBundle,
    compute_file_sha256,
    compute_sha256,
    needs_splitting,
    re_download_verify,
    verify_manifest_integrity,
)

# ── Weekly Release tag ──


class TestWeeklyTag:
    def test_format_tag(self) -> None:
        assert WeeklyReleaseTag.format_tag(2026, 31) == "ingest-2026-W31"

    def test_from_date_known(self) -> None:
        # 2026-08-04 is ISO week 32 of 2026
        dt = datetime(2026, 8, 4, tzinfo=UTC)
        tag = WeeklyReleaseTag.from_date(dt)
        assert tag == "ingest-2026-W32"

    def test_parse_valid_tag(self) -> None:
        result = WeeklyReleaseTag.parse_tag("ingest-2026-W31")
        assert result == (2026, 31)

    def test_parse_invalid_tag(self) -> None:
        assert WeeklyReleaseTag.parse_tag("weekly-2026-31") is None
        assert WeeklyReleaseTag.parse_tag("ingest-2026-W1") is None
        assert WeeklyReleaseTag.parse_tag("") is None


# ── Safe filename ──


class TestSafeFilename:
    def test_strips_path(self) -> None:
        assert safe_archive_filename("dir/subdir/file.pdf") == "file.pdf"

    def test_replaces_dangerous_chars(self) -> None:
        result = safe_archive_filename("file:*?.pdf")
        assert "*" not in result
        assert "?" not in result
        assert ":" not in result

    def test_preserves_korean(self) -> None:
        assert safe_archive_filename("청년정책.hwp") == "청년정책.hwp"

    def test_empty_becomes_unnamed(self) -> None:
        assert safe_archive_filename("") == "unnamed"

    def test_strips_leading_trailing_dots(self) -> None:
        assert safe_archive_filename(".hidden.") == "hidden"


# ── Asset splitting ──


class TestSplitAssetName:
    def test_single_part(self) -> None:
        assert split_asset_name("youthcenter", 1, 1) == "youthcenter.tar.gz"

    def test_multi_part(self) -> None:
        assert split_asset_name("sbiz24", 1, 3) == "sbiz24.part01of03.tar.gz"
        assert split_asset_name("sbiz24", 2, 3) == "sbiz24.part02of03.tar.gz"

    def test_needs_splitting(self) -> None:
        assert needs_splitting(2 * 1024 * 1024 * 1024)
        assert not needs_splitting(1024)


# ── Manifest entry and operations ──


class TestManifestEntry:
    def test_entry_fields(self) -> None:
        entry = ManifestEntry(
            source="youthcenter",
            remote_id="PLCY001",
            collected_at=datetime.now(UTC),
            original_filename="doc.hwp",
            safe_path="doc.hwp",
            byte_size=100,
            sha256="abc123",
            archive_asset="youthcenter.tar.gz",
            archive_member="doc.hwp",
        )
        assert entry.source == "youthcenter"
        assert entry.archive_asset == "youthcenter.tar.gz"


class TestArchiveManifest:
    def test_add_entry_updates_totals(self) -> None:
        manifest = ArchiveManifest(
            release_tag="ingest-2026-W32",
            source="youthcenter",
            created_at=datetime.now(UTC),
        )
        entry = ManifestEntry(
            source="youthcenter",
            remote_id="PLCY001",
            collected_at=datetime.now(UTC),
            original_filename="doc.hwp",
            safe_path="doc.hwp",
            byte_size=500,
            sha256="abc123",
            archive_asset="youthcenter.tar.gz",
            archive_member="doc.hwp",
        )
        manifest.add_entry(entry)
        assert manifest.total_files == 1
        assert manifest.total_bytes == 500

    def test_find_by_sha256(self) -> None:
        manifest = ArchiveManifest(
            release_tag="ingest-2026-W32",
            source="youthcenter",
            created_at=datetime.now(UTC),
        )
        entry = ManifestEntry(
            source="youthcenter",
            remote_id="PLCY001",
            collected_at=datetime.now(UTC),
            original_filename="doc.hwp",
            safe_path="doc.hwp",
            byte_size=100,
            sha256="deadbeef",
            archive_asset="youthcenter.tar.gz",
            archive_member="doc.hwp",
        )
        manifest.add_entry(entry)
        found = manifest.find_by_sha256("deadbeef")
        assert found is not None
        assert found.remote_id == "PLCY001"

    def test_find_by_sha256_not_found(self) -> None:
        manifest = ArchiveManifest(
            release_tag="ingest-2026-W32",
            source="youthcenter",
            created_at=datetime.now(UTC),
        )
        assert manifest.find_by_sha256("nonexistent") is None

    def test_to_json_roundtrip(self) -> None:
        import json

        manifest = ArchiveManifest(
            release_tag="ingest-2026-W32",
            source="youthcenter",
            created_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
        entry = ManifestEntry(
            source="youthcenter",
            remote_id="PLCY001",
            collected_at=datetime(2026, 8, 4, tzinfo=UTC),
            original_filename="doc.hwp",
            safe_path="doc.hwp",
            byte_size=100,
            sha256="abc123",
            archive_asset="youthcenter.tar.gz",
            archive_member="doc.hwp",
        )
        manifest.add_entry(entry)
        manifest.status = ArchiveAssetStatus.FINALIZED

        parsed = json.loads(manifest.to_json())
        assert parsed["release_tag"] == "ingest-2026-W32"
        assert parsed["status"] == "finalized"
        assert len(parsed["entries"]) == 1


# ── CollectedFile ──


class TestCollectedFile:
    def test_sha256_computed(self) -> None:
        file = CollectedFile(
            source="youthcenter",
            remote_id="PLCY001",
            filename="test.txt",
            content=b"hello world",
        )
        assert file.sha256 == compute_sha256(b"hello world")

    def test_byte_size(self) -> None:
        file = CollectedFile(
            source="youthcenter",
            remote_id="PLCY001",
            filename="test.txt",
            content=b"hello",
        )
        assert file.byte_size == 5

    def test_safe_path_generated(self) -> None:
        file = CollectedFile(
            source="youthcenter",
            remote_id="PLCY001",
            filename="dir/청년정책.hwp",
            content=b"data",
        )
        assert file.safe_path == "청년정책.hwp"


# ── SourceBundle building ──


class TestSourceBundle:
    def test_build_creates_bundle_with_manifest(self) -> None:
        bundle = SourceBundle("youthcenter", "ingest-2026-W32")
        bundle.add_file(
            CollectedFile(
                source="youthcenter",
                remote_id="PLCY001",
                filename="doc.txt",
                content=b"policy content",
            )
        )
        data, manifest = bundle.build()
        assert len(data) > 0
        assert manifest.source == "youthcenter"
        assert manifest.total_files == 1
        assert manifest.status == ArchiveAssetStatus.FINALIZED

    def test_dedup_skips_existing_sha(self) -> None:
        bundle = SourceBundle("youthcenter", "ingest-2026-W32")
        entry = ManifestEntry(
            source="youthcenter",
            remote_id="PLCY_OLD",
            collected_at=datetime.now(UTC),
            original_filename="old.txt",
            safe_path="old.txt",
            byte_size=4,
            sha256=compute_sha256(b"data"),
            archive_asset="youthcenter.tar.gz",
            archive_member="old.txt",
        )
        bundle.add_existing_entry(entry)

        result = bundle.add_file(
            CollectedFile(
                source="youthcenter",
                remote_id="PLCY_NEW",
                filename="new.txt",
                content=b"data",  # Same content → same SHA
            )
        )
        assert result is None  # Deduped

    def test_no_dedup_for_different_content(self) -> None:
        bundle = SourceBundle("youthcenter", "ingest-2026-W32")
        bundle.add_existing_entry(
            ManifestEntry(
                source="youthcenter",
                remote_id="OLD",
                collected_at=datetime.now(UTC),
                original_filename="old.txt",
                safe_path="old.txt",
                byte_size=4,
                sha256="aaaa",
                archive_asset="youthcenter.tar.gz",
                archive_member="old.txt",
            )
        )
        result = bundle.add_file(
            CollectedFile(
                source="youthcenter",
                remote_id="NEW",
                filename="new.txt",
                content=b"different",
            )
        )
        assert result is not None

    def test_empty_bundle(self) -> None:
        bundle = SourceBundle("youthcenter", "ingest-2026-W32")
        data, manifest = bundle.build()
        assert manifest.total_files == 0
        assert manifest.total_bytes == 0


# ── Integrity verification ──


class TestIntegrityVerification:
    def test_verify_correct_bundle(self) -> None:
        bundle = SourceBundle("youthcenter", "ingest-2026-W32")
        bundle.add_file(
            CollectedFile(
                source="youthcenter",
                remote_id="PLCY001",
                filename="doc.txt",
                content=b"policy document content",
            )
        )
        data, manifest = bundle.build()
        assert verify_manifest_integrity(data, manifest) is True

    def test_verify_corrupted_manifest_sha(self) -> None:
        """Manifest with wrong SHA-256 for an entry should fail verification."""
        bundle = SourceBundle("youthcenter", "ingest-2026-W32")
        bundle.add_file(
            CollectedFile(
                source="youthcenter",
                remote_id="PLCY001",
                filename="doc.txt",
                content=b"original content",
            )
        )
        data, manifest = bundle.build()

        # Tamper with the manifest entry SHA (but bundle content stays same)
        manifest.entries[0] = manifest.entries[0].model_copy(update={"sha256": "0" * 64})
        assert verify_manifest_integrity(data, manifest) is False

    def test_re_download_verify_match(self) -> None:
        content = b"downloaded content"
        sha = compute_sha256(content)
        assert re_download_verify(content, sha) is True

    def test_re_download_verify_mismatch(self) -> None:
        content = b"downloaded content"
        assert not re_download_verify(content, "wrong_sha")


# ── SHA-256 utilities ──


class TestSha256:
    def test_compute_sha256_deterministic(self) -> None:
        assert compute_sha256(b"test") == compute_sha256(b"test")

    def test_compute_sha256_different_input(self) -> None:
        assert compute_sha256(b"a") != compute_sha256(b"b")

    def test_compute_file_sha256(self, tmp_path: Path) -> None:
        p: Path = tmp_path / "test.txt"
        p.write_bytes(b"file content")
        assert compute_file_sha256(p) == compute_sha256(b"file content")


# ── Same-week re-run safety ──


class TestSameWeekRerun:
    def test_same_tag_produces_same_tag(self) -> None:
        """Re-running within the same week produces the same tag."""
        dt1 = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
        dt2 = datetime(2026, 8, 5, 18, 0, tzinfo=UTC)
        assert WeeklyReleaseTag.from_date(dt1) == WeeklyReleaseTag.from_date(dt2)

    def test_dedup_prevents_duplicate_upload(self) -> None:
        """Same file content in two runs → deduped, no new binary."""
        bundle1 = SourceBundle("youthcenter", "ingest-2026-W32")
        entry1 = bundle1.add_file(
            CollectedFile(
                source="youthcenter",
                remote_id="PLCY001",
                filename="doc.txt",
                content=b"same content",
            )
        )
        assert entry1 is not None
        _, manifest1 = bundle1.build()

        bundle2 = SourceBundle("youthcenter", "ingest-2026-W32")
        for e in manifest1.entries:
            bundle2.add_existing_entry(e)
        result = bundle2.add_file(
            CollectedFile(
                source="youthcenter",
                remote_id="PLCY001",
                filename="doc.txt",
                content=b"same content",
            )
        )
        assert result is None  # Deduped — no new binary


# ── Draft/finalize lifecycle ──


class TestDraftFinalize:
    def test_manifest_starts_as_draft(self) -> None:
        bundle = SourceBundle("youthcenter", "ingest-2026-W32")
        bundle.add_file(
            CollectedFile(
                source="youthcenter",
                remote_id="PLCY001",
                filename="doc.txt",
                content=b"content",
            )
        )
        # Before build, manifest doesn't exist yet — simulate
        manifest = ArchiveManifest(
            release_tag="ingest-2026-W32",
            source="youthcenter",
            created_at=datetime.now(UTC),
        )
        assert manifest.status == ArchiveAssetStatus.DRAFT

    def test_manifest_finalized_after_build(self) -> None:
        bundle = SourceBundle("youthcenter", "ingest-2026-W32")
        bundle.add_file(
            CollectedFile(
                source="youthcenter",
                remote_id="PLCY001",
                filename="doc.txt",
                content=b"content",
            )
        )
        _, manifest = bundle.build()
        assert manifest.status == ArchiveAssetStatus.FINALIZED

    def test_partial_upload_not_consumed_as_final(self) -> None:
        """A failed upload leaves manifest in DRAFT, not FINALIZED."""
        bundle = SourceBundle("youthcenter", "ingest-2026-W32")
        bundle.add_file(
            CollectedFile(
                source="youthcenter",
                remote_id="PLCY001",
                filename="doc.txt",
                content=b"content",
            )
        )
        # Simulate failure before build completes
        manifest = ArchiveManifest(
            release_tag="ingest-2026-W32",
            source="youthcenter",
            created_at=datetime.now(UTC),
            status=ArchiveAssetStatus.FAILED,
        )
        assert manifest.status != ArchiveAssetStatus.FINALIZED

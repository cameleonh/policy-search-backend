"""Tests for the hybrid search layer (Issue #17)."""

from __future__ import annotations

from packages.matching.search import (
    ChunkType,
    LexicalHit,
    SearchChunk,
    VectorHit,
    chunk_document,
    fallback_lexical_only,
    reciprocal_rank_fusion,
)

# ── Chunking ──


class TestChunking:
    def test_basic_chunking(self) -> None:
        blocks = [
            {
                "type": "paragraph",
                "text": "지원 대상은 만 19세 이상입니다.",
                "provenance": {"section": "지원대상", "page": 1},
            },
            {"type": "heading", "text": "신청 방법", "provenance": {"section": "신청방법"}},
        ]
        chunks = chunk_document(1, blocks)
        assert len(chunks) == 2
        assert chunks[0].chunk_type == ChunkType.PARAGRAPH
        assert chunks[1].chunk_type == ChunkType.SECTION

    def test_provenance_preserved(self) -> None:
        blocks = [
            {
                "type": "table_cell",
                "text": "만 19세",
                "provenance": {
                    "section": "지원자격",
                    "page": 2,
                    "tableRef": "table-1",
                    "row": 0,
                    "col": 1,
                },
            },
        ]
        chunks = chunk_document(1, blocks)
        assert chunks[0].table_ref == "table-1"
        assert chunks[0].row == 0
        assert chunks[0].col == 1

    def test_empty_text_skipped(self) -> None:
        blocks = [
            {"type": "paragraph", "text": "", "provenance": {}},
            {"type": "paragraph", "text": "내용 있음", "provenance": {}},
        ]
        chunks = chunk_document(1, blocks)
        assert len(chunks) == 1

    def test_deterministic_hash(self) -> None:
        c1 = SearchChunk(
            policy_version_id=1, chunk_index=0, chunk_type=ChunkType.PARAGRAPH, text="hello"
        )
        c2 = SearchChunk(
            policy_version_id=2, chunk_index=5, chunk_type=ChunkType.TITLE, text="hello"
        )
        assert c1.chunk_hash == c2.chunk_hash

    def test_location_str(self) -> None:
        c = SearchChunk(
            policy_version_id=1,
            chunk_index=0,
            chunk_type=ChunkType.TABLE_CELL,
            text="만 19세",
            section="지원자격",
            page=2,
            table_ref="table-1",
            row=0,
            col=1,
        )
        assert "지원자격" in c.location_str
        assert "p.2" in c.location_str
        assert "table-1" in c.location_str

    def test_same_blocks_same_chunks(self) -> None:
        blocks = [{"type": "paragraph", "text": "test", "provenance": {}}]
        c1 = chunk_document(1, list(blocks))
        c2 = chunk_document(1, list(blocks))
        assert len(c1) == len(c2)
        assert c1[0].text == c2[0].text
        assert c1[0].chunk_hash == c2[0].chunk_hash


# ── Rank fusion ──


class TestRankFusion:
    def test_rrf_combines_scores(self) -> None:
        lexical = [
            LexicalHit(chunk_id=1, policy_version_id=1, text="a", location="s1", score=1.0),
            LexicalHit(chunk_id=2, policy_version_id=1, text="b", location="s2", score=0.5),
        ]
        vector = [
            VectorHit(chunk_id=2, policy_version_id=1, text="b", location="s2", score=0.9),
            VectorHit(chunk_id=3, policy_version_id=1, text="c", location="s3", score=0.8),
        ]
        results = reciprocal_rank_fusion(lexical, vector)
        assert len(results) == 3
        assert results[0].fused_score >= results[1].fused_score

    def test_rrf_deterministic(self) -> None:
        lexical = [
            LexicalHit(chunk_id=1, policy_version_id=1, text="a", location="s", score=1.0),
        ]
        vector = [
            VectorHit(chunk_id=1, policy_version_id=1, text="a", location="s", score=0.9),
        ]
        r1 = reciprocal_rank_fusion(lexical, vector)
        r2 = reciprocal_rank_fusion(lexical, vector)
        assert r1[0].fused_score == r2[0].fused_score

    def test_rrf_empty_lists(self) -> None:
        results = reciprocal_rank_fusion([], [])
        assert len(results) == 0

    def test_fallback_lexical_only(self) -> None:
        lexical = [
            LexicalHit(chunk_id=1, policy_version_id=1, text="a", location="s", score=1.0),
        ]
        results = fallback_lexical_only(lexical)
        assert len(results) == 1
        assert results[0].vector_score == 0.0
        assert results[0].lexical_score > 0.0

    def test_chunk_in_both_lists_gets_higher_score(self) -> None:
        lexical = [
            LexicalHit(chunk_id=1, policy_version_id=1, text="a", location="s", score=1.0),
            LexicalHit(chunk_id=2, policy_version_id=1, text="b", location="s", score=0.5),
        ]
        vector = [
            VectorHit(chunk_id=1, policy_version_id=1, text="a", location="s", score=0.9),
        ]
        results = reciprocal_rank_fusion(lexical, vector)
        # Chunk 1 appears in both → highest fused score
        assert results[0].chunk_id == 1
        assert results[0].fused_score > results[1].fused_score

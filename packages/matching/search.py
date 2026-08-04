"""Search contracts — chunking, embedding interface, and rank fusion.

Issue #17 — defines the search layer that combines PostgreSQL FTS
with pgvector similarity, gated by eligibility matching results.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel

# ── Chunking ──────────────────────────────────


class ChunkType(StrEnum):
    TITLE = "title"
    SECTION = "section"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    TABLE_CELL = "table_cell"


class SearchChunk(BaseModel):
    """A searchable text chunk with provenance."""

    policy_version_id: int
    chunk_index: int
    chunk_type: ChunkType
    text: str
    section: str | None = None
    page: int | None = None
    table_ref: str | None = None
    row: int | None = None
    col: int | None = None

    @property
    def chunk_hash(self) -> str:
        """Deterministic hash for dedup — same text → same hash."""
        return hashlib.sha256(self.text.encode()).hexdigest()[:16]

    @property
    def location_str(self) -> str:
        """Human-readable location for evidence display."""
        parts = [self.section or "본문"]
        if self.page:
            parts.append(f"p.{self.page}")
        if self.table_ref:
            parts.append(self.table_ref)
            if self.row is not None:
                parts.append(f"r{self.row}")
            if self.col is not None:
                parts.append(f"c{self.col}")
        return " / ".join(parts)


def chunk_document(
    policy_version_id: int,
    blocks: list[dict[str, Any]],
) -> list[SearchChunk]:
    """Split Kordoc IR blocks into searchable chunks.

    Each block becomes one chunk with its provenance preserved.
    Same blocks + same options → same chunk boundaries.
    """
    chunks: list[SearchChunk] = []
    for i, block in enumerate(blocks):
        text = block.get("text", "").strip()
        if not text:
            continue

        block_type = block.get("type", "paragraph")
        chunk_type_map = {
            "heading": ChunkType.SECTION,
            "paragraph": ChunkType.PARAGRAPH,
            "table": ChunkType.TABLE,
            "table_cell": ChunkType.TABLE_CELL,
        }
        chunk_type = chunk_type_map.get(block_type, ChunkType.PARAGRAPH)

        prov = block.get("provenance", {})
        chunks.append(
            SearchChunk(
                policy_version_id=policy_version_id,
                chunk_index=i,
                chunk_type=chunk_type,
                text=text,
                section=prov.get("section"),
                page=prov.get("page"),
                table_ref=prov.get("tableRef"),
                row=prov.get("row"),
                col=prov.get("col"),
            )
        )
    return chunks


# ── Embedding interface ───────────────────────


class EmbeddingProvider(Protocol):
    """Interface for embedding models — isolated behind protocol.

    Allows benchmarking different providers without coupling.
    """

    model_name: str
    model_version: str
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def model_hash(self) -> str:
        """Hash of model name + version + dimension for vector isolation."""
        raw = f"{self.model_name}:{self.model_version}:{self.dimension}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Search results ────────────────────────────


class LexicalHit(BaseModel):
    """A single FTS search hit."""

    chunk_id: int
    policy_version_id: int
    text: str
    location: str
    score: float


class VectorHit(BaseModel):
    """A single vector similarity hit."""

    chunk_id: int
    policy_version_id: int
    text: str
    location: str
    score: float


class HybridResult(BaseModel):
    """Fused result from lexical + vector search."""

    chunk_id: int
    policy_version_id: int
    text: str
    location: str
    lexical_score: float = 0.0
    vector_score: float = 0.0
    fused_score: float = 0.0


def reciprocal_rank_fusion(
    lexical_hits: list[LexicalHit],
    vector_hits: list[VectorHit],
    k: int = 60,
) -> list[HybridResult]:
    """Combine lexical and vector rankings using Reciprocal Rank Fusion.

    RRF(score) = sum(1 / (k + rank_i)) for each list i.
    Deterministic — same inputs always produce same ordering.
    """
    fused: dict[int, dict[str, Any]] = {}

    for rank, hit in enumerate(lexical_hits, start=1):
        cid = hit.chunk_id
        if cid not in fused:
            fused[cid] = {
                "chunk_id": cid,
                "policy_version_id": hit.policy_version_id,
                "text": hit.text,
                "location": hit.location,
                "lexical_score": 0.0,
                "vector_score": 0.0,
            }
        fused[cid]["lexical_score"] += 1.0 / (k + rank)

    for rank, v_hit in enumerate(vector_hits, start=1):
        cid = v_hit.chunk_id
        if cid not in fused:
            fused[cid] = {
                "chunk_id": cid,
                "policy_version_id": v_hit.policy_version_id,
                "text": v_hit.text,
                "location": v_hit.location,
                "lexical_score": 0.0,
                "vector_score": 0.0,
            }
        fused[cid]["vector_score"] += 1.0 / (k + rank)

    results: list[HybridResult] = []
    for item in fused.values():
        item["fused_score"] = item["lexical_score"] + item["vector_score"]
        results.append(HybridResult(**item))

    results.sort(key=lambda r: r.fused_score, reverse=True)
    return results


def fallback_lexical_only(
    lexical_hits: list[LexicalHit],
) -> list[HybridResult]:
    """When vector search fails, return lexical-only results.

    Per FR-SRCH: vector failure must not block search.
    """
    return reciprocal_rank_fusion(lexical_hits, [])

/**
 * Document extraction types and contracts.
 *
 * These types define the input/output shape of the Kordoc document
 * extraction pipeline. They mirror the PostgreSQL `document_extractions`
 * table from Issue #2.
 */

// ── Status ────────────────────────────────────

export type ExtractionStatus =
  | "pending"
  | "parsed"
  | "partial"
  | "encrypted"
  | "unsupported"
  | "failed";

// ── Input ─────────────────────────────────────

export interface ExtractionRequest {
  /** Attachment ID from the DB */
  attachmentId: number;
  /** SHA-256 of the file content — part of the cache key */
  fileSha256: string;
  /** Archive locator (release tag + asset path) */
  archiveTag: string;
  archiveAsset: string;
  archiveMember: string;
  /** Original filename for MIME inference */
  filename: string;
  /** MIME type if known */
  mimeType: string | null;
  /** Byte size for resource limiting */
  byteSize: number;
}

// ── Output ────────────────────────────────────

export interface ProvenanceLocation {
  /** Section heading or document part name */
  section: string | null;
  /** Page number (1-indexed, if applicable) */
  page: number | null;
  /** Table reference (e.g. "table-2") */
  tableRef: string | null;
  /** Row index within a table (0-indexed) */
  row: number | null;
  /** Column index within a table (0-indexed) */
  col: number | null;
}

export interface IRBlock {
  /** Block type: paragraph, heading, list_item, table, table_cell */
  type: "paragraph" | "heading" | "list_item" | "table" | "table_cell";
  /** Text content */
  text: string;
  /** Heading level (1-6) for heading blocks */
  level?: number;
  /** Provenance back to the source document */
  provenance: ProvenanceLocation;
}

export interface ExtractionResult {
  /** The extraction status */
  status: ExtractionStatus;
  /** Markdown text of the full document */
  markdown: string | null;
  /** Structured intermediate representation blocks */
  blocks: IRBlock[];
  /** Parser name (always "kordoc") */
  parserName: string;
  /** Parser version (pinned to "4.6.0") */
  parserVersion: string;
  /** Options hash — part of the cache key */
  optionsHash: string;
  /** Error code if status is not "parsed" */
  errorCode: string | null;
  /** Parser warnings (non-fatal issues) */
  warnings: string[];
  /** Content hash for dedup */
  contentHash: string | null;
}

// ── Cache key ─────────────────────────────────

export interface CacheKey {
  fileSha256: string;
  parserName: string;
  parserVersion: string;
  optionsHash: string;
}

export function makeCacheKey(
  fileSha256: string,
  optionsHash: string,
): CacheKey {
  return {
    fileSha256,
    parserName: "kordoc",
    parserVersion: "4.6.0",
    optionsHash,
  };
}

export function cacheKeyToString(key: CacheKey): string {
  return `${key.fileSha256}:${key.parserName}:${key.parserVersion}:${key.optionsHash}`;
}

// ── Resource limits ───────────────────────────

export interface ResourceLimits {
  maxFileSize: number;
  maxUncompressedSize: number;
  maxPages: number;
  cpuLimit: number;
  memoryLimitMb: number;
  wallTimeoutMs: number;
}

export const DEFAULT_LIMITS: ResourceLimits = {
  maxFileSize: 100 * 1024 * 1024,
  maxUncompressedSize: 200 * 1024 * 1024,
  maxPages: 500,
  cpuLimit: 1,
  memoryLimitMb: 512,
  wallTimeoutMs: 60_000,
};

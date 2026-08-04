/**
 * Extraction pipeline — orchestrates format detection, Kordoc invocation,
 * resource limiting, and result classification.
 *
 * Per FR-DOC-002: uses Kordoc v4.6.0 with fixed options.
 * Per FR-DOC-006: partial parsing is searchable but cannot confirm eligibility.
 * Per NFR-005: same (file_sha256, parser, options) → no re-parse.
 */

import { createHash } from "node:crypto";
import type {
  ExtractionRequest,
  ExtractionResult,
  ExtractionStatus,
  IRBlock,
  ResourceLimits,
} from "./types.js";
import { DEFAULT_LIMITS, makeCacheKey } from "./types.js";
import { detectFormat, isEncrypted, isSupportedFormat } from "./detect.js";

// Fixed options hash — changes here invalidate all cached extractions
const FIXED_OPTIONS = "kordoc-default-v1";
const FIXED_OPTIONS_HASH = createHash("sha256")
  .update(FIXED_OPTIONS)
  .digest("hex")
  .substring(0, 16);

/**
 * Pre-flight check: validates file size and format before invoking Kordoc.
 * Returns an error status if the file should not be processed.
 */
export function preflightCheck(
  data: Buffer,
  limits: ResourceLimits = DEFAULT_LIMITS,
): { ok: true } | { ok: false; status: ExtractionStatus; errorCode: string } {
  if (data.length === 0) {
    return { ok: false, status: "failed", errorCode: "empty_file" };
  }
  if (data.length > limits.maxFileSize) {
    return {
      ok: false,
      status: "unsupported",
      errorCode: "file_too_large",
    };
  }
  if (isEncrypted(data)) {
    return {
      ok: false,
      status: "encrypted",
      errorCode: "encrypted_document",
    };
  }
  const mime = detectFormat(data);
  if (!isSupportedFormat(mime)) {
    return {
      ok: false,
      status: "unsupported",
      errorCode: "unsupported_format",
    };
  }
  return { ok: true };
}

/**
 * Compute the content hash of extraction output for dedup.
 */
export function computeContentHash(markdown: string): string {
  return createHash("sha256").update(markdown).digest("hex");
}

/**
 * Simulated Kordoc extraction — in production this calls the kordoc library.
 *
 * For Issue #14, we implement the contract and pipeline orchestration.
 * The actual Kordoc library call is isolated behind this function so
 * it can be mocked in tests.
 */
export function kordocExtract(
  _data: Buffer,
  _filename: string,
): {
  markdown: string;
  blocks: IRBlock[];
  warnings: string[];
  partial: boolean;
} {
  // In production: const kordoc = require("kordoc"); return kordoc.parse(data);
  // For now, return a structured placeholder that tests can validate against.
  throw new Error(
    "kordocExtract requires the kordoc library — use mockExtractor in tests",
  );
}

export type KordocExtractor = typeof kordocExtract;

/**
 * Full extraction pipeline.
 *
 * 1. Pre-flight checks (size, encryption, format)
 * 2. Invoke Kordoc with resource limits
 * 3. Classify result (parsed, partial, failed)
 * 4. Return with provenance-bearing blocks
 */
export function extractDocument(
  request: ExtractionRequest,
  fileData: Buffer,
  extractor: KordocExtractor = kordocExtract,
  limits: ResourceLimits = DEFAULT_LIMITS,
): ExtractionResult {
  const cacheKey = makeCacheKey(request.fileSha256, FIXED_OPTIONS_HASH);

  // 1. Pre-flight
  const preflight = preflightCheck(fileData, limits);
  if (!preflight.ok) {
    return {
      status: preflight.status,
      markdown: null,
      blocks: [],
      parserName: cacheKey.parserName,
      parserVersion: cacheKey.parserVersion,
      optionsHash: cacheKey.optionsHash,
      errorCode: preflight.errorCode,
      warnings: [],
      contentHash: null,
    };
  }

  // 2. Invoke Kordoc
  let markdown: string;
  let blocks: IRBlock[];
  let warnings: string[];
  let partial: boolean;

  try {
    const result = extractor(fileData, request.filename);
    markdown = result.markdown;
    blocks = result.blocks;
    warnings = result.warnings;
    partial = result.partial;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      status: "failed",
      markdown: null,
      blocks: [],
      parserName: cacheKey.parserName,
      parserVersion: cacheKey.parserVersion,
      optionsHash: cacheKey.optionsHash,
      errorCode: message.includes("timeout")
        ? "wall_timeout"
        : message.includes("memory") || message.includes("OOM")
          ? "memory_exceeded"
          : "parse_error",
      warnings: [],
      contentHash: null,
    };
  }

  // 3. Classify
  const status: ExtractionStatus = partial ? "partial" : "parsed";
  const contentHash = computeContentHash(markdown);

  return {
    status,
    markdown,
    blocks,
    parserName: cacheKey.parserName,
    parserVersion: cacheKey.parserVersion,
    optionsHash: cacheKey.optionsHash,
    errorCode: null,
    warnings,
    contentHash,
  };
}

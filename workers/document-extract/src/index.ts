/**
 * Document extraction worker — Kordoc pipeline entrypoint.
 *
 * Issue #14: Converts HWP/HWPX/PDF/Office files to Markdown + IR blocks
 * with provenance. Uses kordoc@4.6.0 with fixed options.
 */

export { extractDocument, preflightCheck, computeContentHash, kordocExtract } from "./extract.js";
export type { KordocExtractor } from "./extract.js";
export { detectFormat, isSupportedFormat, isEncrypted } from "./detect.js";
export type {
  ExtractionRequest,
  ExtractionResult,
  ExtractionStatus,
  IRBlock,
  ProvenanceLocation,
  ResourceLimits,
  CacheKey,
} from "./types.js";
export { makeCacheKey, cacheKeyToString, DEFAULT_LIMITS } from "./types.js";

export function main(): void {
  console.log("document-extract worker ready — kordoc@4.6.0");
}

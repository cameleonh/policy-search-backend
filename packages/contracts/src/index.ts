/**
 * Shared TypeScript contracts consumed by apps/web and workers/document-extract.
 *
 * These types are intentionally minimal for the foundation skeleton.
 * Issue #2 (data schema) and issue #3 (ingestion contracts) will expand them.
 */

/** Three-valued logic match result. */
export type TriState = "eligible" | "possible" | "ineligible";

export interface HealthResponse {
  status: "ok";
  service: string;
}

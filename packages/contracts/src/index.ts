/**
 * Shared TypeScript contracts consumed by apps/web and workers/document-extract.
 *
 * These types mirror the Python Pydantic models and the PostgreSQL schema.
 */

// ── Enums ─────────────────────────────────────

/** Three-valued logic match result. */
export type TriState = "eligible" | "possible" | "ineligible";

export type ExecutionStatus =
  | "pending"
  | "running"
  | "partial"
  | "succeeded"
  | "failed";

export type DocumentStatus =
  | "pending"
  | "parsed"
  | "partial"
  | "encrypted"
  | "unsupported"
  | "failed";

export type TargetType = "individual" | "business" | "both";

export type ExtractMethod = "rule_based" | "llm";

export type RegionLevel = "national" | "metropolitan" | "local";

// ── API health ────────────────────────────────

export interface HealthResponse {
  status: "ok";
  service: string;
}

// ── Policy search contracts ───────────────────

export interface PolicyVersionRef {
  programId: number;
  versionNumber: number;
  title: string;
  summary: string | null;
  targetType: TargetType;
  announcementUrl: string;
}

export interface EligibilityRuleRef {
  policyVersionId: number;
  fieldName: string;
  operator: string;
  value: string | null;
  unit: string | null;
  evidenceRef: string | null;
  extractMethod: ExtractMethod;
  confidence: number | null;
  logicalOp: string | null;
}

export interface SearchProfile {
  // Individual
  birthDate?: string;
  region?: string;
  employmentStatus?: string;
  incomeBracket?: string;
  // Business
  isBusinessOwner?: boolean;
  businessStartDate?: string;
  businessRegion?: string;
  industry?: string;
  annualRevenue?: number;
  employeeCount?: number;
}

export interface SearchResult {
  policyVersion: PolicyVersionRef;
  triState: TriState;
  reasons: string[];
  missingInfo: string[];
  benefits: string[];
  applicationDeadline: string | null;
  announcementUrl: string;
  evidenceRefs: string[];
}

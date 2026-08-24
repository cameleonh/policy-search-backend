/**
 * Shared TypeScript contracts — mirrors the Python wire contracts in
 * `apps/api/contracts/search.py` (Pydantic, snake_case JSON). The Python
 * models are the source of truth; keep these in sync manually.
 */

// ── Enums ─────────────────────────────────────

/** Three-valued verdict shown on result cards. */
export type MatchStatus = "eligible" | "possible";

/** Legacy name kept for Badge tokens; the API never emits "ineligible". */
export type TriState = MatchStatus | "ineligible";

export type PolicyCategory = "individual" | "business" | "both";

// ── API health ────────────────────────────────

export interface HealthResponse {
  status: "ok";
  service: string;
}

// ── Policy search contracts ───────────────────

export interface EvidenceRef {
  evidence_id: string;
  chunk_id: number | null;
  section: string | null;
  location: string;
  text_snippet: string;
}

export interface PolicyResult {
  result_id: string;
  policy_version_id: number;
  policy_title: string;
  category: PolicyCategory;
  status: MatchStatus;
  agency: string;
  reasons: string[];
  missing_info: string[];
  benefits: string[];
  application_deadline: string | null;
  announcement_url: string | null;
  evidence: EvidenceRef[];
  rag_explanation: string | null;
}

export interface SearchProfile {
  // Individual
  birth_date?: string;
  region?: string;
  employment_status?: string;
  income_bracket?: string;
  interest_topics?: string[];
  // Business
  is_business_owner?: boolean;
  business_start_date?: string;
  business_region?: string;
  industry?: string;
  annual_revenue?: number;
  employee_count?: number;
}

export interface SearchResponse {
  data_version: string;
  results: PolicyResult[];
  total: number;
  page: number;
  page_size: number;
  rag_enabled: boolean;
}

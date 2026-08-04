import { describe, it, expect } from "vitest";
import type {
  DocumentStatus,
  ExecutionStatus,
  ExtractMethod,
  HealthResponse,
  RegionLevel,
  SearchResult,
  TargetType,
  TriState,
} from "../src/index.js";

describe("contracts", () => {
  it("TriState accepts all three values", () => {
    const eligible: TriState = "eligible";
    const possible: TriState = "possible";
    const ineligible: TriState = "ineligible";

    expect([eligible, possible, ineligible]).toHaveLength(3);
  });

  it("HealthResponse has ok status", () => {
    const health: HealthResponse = { status: "ok", service: "test" };
    expect(health.status).toBe("ok");
  });

  it("status enums have expected values", () => {
    const exec: ExecutionStatus = "succeeded";
    const doc: DocumentStatus = "parsed";
    const method: ExtractMethod = "rule_based";
    const target: TargetType = "both";
    const level: RegionLevel = "metropolitan";

    expect(exec).toBe("succeeded");
    expect(doc).toBe("parsed");
    expect(method).toBe("rule_based");
    expect(target).toBe("both");
    expect(level).toBe("metropolitan");
  });

  it("SearchResult is well-formed", () => {
    const result: SearchResult = {
      policyVersion: {
        programId: 1,
        versionNumber: 1,
        title: "Test Policy",
        summary: null,
        targetType: "individual",
        announcementUrl: "https://example.com/policy/1",
      },
      triState: "eligible",
      reasons: ["age meets criteria"],
      missingInfo: [],
      benefits: ["50000 KRW/month"],
      applicationDeadline: "2026-12-31",
      announcementUrl: "https://example.com/policy/1",
      evidenceRefs: ["doc-1/chunk-3"],
    };
    expect(result.triState).toBe("eligible");
    expect(result.policyVersion.programId).toBe(1);
  });
});

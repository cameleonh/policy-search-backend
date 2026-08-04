import { describe, it, expect } from "vitest";
import type { HealthResponse, TriState } from "../src/index.js";

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
});

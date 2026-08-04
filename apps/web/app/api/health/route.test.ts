import { describe, it, expect } from "vitest";
import { GET } from "./route";

describe("/api/health", () => {
  it("returns ok status", async () => {
    const response = await GET();
    const data = (await response.json()) as { status: string; service: string };

    expect(response.status).toBe(200);
    expect(data.status).toBe("ok");
    expect(data.service).toBe("web");
  });
});

import { describe, it, expect } from "vitest";
import { main } from "../src/index.js";

describe("document-extract worker", () => {
  it("runs without throwing", () => {
    expect(() => main()).not.toThrow();
  });
});

import { describe, expect, it } from "vitest";
import { compareVersions } from "./version.js";

describe("compareVersions", () => {
  it("orders semantic release versions numerically", () => {
    expect(compareVersions("1.0.0", "0.4.9")).toBe(1);
    expect(compareVersions("v0.4.10", "0.4.9")).toBe(1);
    expect(compareVersions("1.0.0", "1.0.1")).toBe(-1);
  });

  it("treats missing components and build suffixes consistently", () => {
    expect(compareVersions("1.0", "1.0.0")).toBe(0);
    expect(compareVersions("1.2.3+portable", "v1.2.3")).toBe(0);
  });
});

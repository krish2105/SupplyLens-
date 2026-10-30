import { describe, expect, it } from "vitest";
import { sharedPrefix } from "@/components/floorplan";

describe("floor plan tile labels", () => {
  it("drops a prefix every code shares, up to its last separator", () => {
    expect(sharedPrefix(["DEMO-SKU-001", "DEMO-SKU-005", "DEMO-SKU-013"])).toBe("DEMO-SKU-");
  });
  it("keeps codes that share no separated prefix", () => {
    expect(sharedPrefix(["85099B", "85123A", "20725"])).toBe("");
    expect(sharedPrefix(["SYN001", "SYN009"])).toBe("");
    expect(sharedPrefix(["DEMO-SKU-001"])).toBe("");
  });
  it("never leaves a label empty", () => {
    expect(sharedPrefix(["A-1", "A-"])).toBe("");
  });
});

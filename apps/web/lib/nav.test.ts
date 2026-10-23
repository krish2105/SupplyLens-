import { describe, expect, it } from "vitest";
import { safeNext } from "./nav";

describe("return path after sign-in (P3-FE-09)", () => {
  it("keeps a path on this site", () => {
    expect(safeNext("/approvals?ws=demo&action=1")).toBe("/approvals?ws=demo&action=1");
  });
  it.each([null, "", "https://evil.example/", "//evil.example/x", "/\\evil.example", "javascript:alert(1)", "/login?next=/x"])(
    "refuses %s", (v) => expect(safeNext(v)).toBe("/"));
});

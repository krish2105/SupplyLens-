import { describe, expect, it } from "vitest";
import { isStaleBuild } from "@/components/crash";

describe("stale build detection", () => {
  it("recognises a chunk from an older deploy", () => {
    expect(isStaleBuild({ name: "ChunkLoadError", message: "Failed to load chunk /_next/static/chunks/x.js" })).toBe(true);
    expect(isStaleBuild({ name: "TypeError", message: "Failed to fetch dynamically imported module: /x.js" })).toBe(true);
    expect(isStaleBuild({ name: "Error", message: "Loading chunk 123 failed." })).toBe(true);
  });
  it("leaves real render errors alone", () => {
    expect(isStaleBuild({ name: "TypeError", message: "Cannot read properties of undefined (reading 'map')" })).toBe(false);
  });
});

// Phase 8 WP-ART: every illustration the app can show is a published, optimised file, and the Phase 8 pieces appear only on
// the screen they were briefed for (A17 Extracted terms, A18 status assistant).
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import manifest from "@/lib/illustrations.json";
import { FILE } from "./illustration";

type Entry = { id: string; published: boolean; path?: string; rendered?: boolean };
const assets = manifest.assets as Entry[];
const WEB = process.cwd();

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    if (statSync(p).isDirectory()) return n === "node_modules" ? [] : sources(p);
    return /\.tsx?$/.test(n) && !/\.test\.tsx?$/.test(n) ? [p] : [];
  });
}

describe("illustration registry (Phase 8 WP-ART)", () => {
  it("every art id points at a published WebP that exists", () => {
    for (const [art, name] of Object.entries(FILE)) {
      const path = `/illustrations/supplylens/${name}.webp`;
      expect(assets.some((a) => a.published && a.path === path), `${art}: ${path} published in lib/illustrations.json`).toBe(true);
      expect(existsSync(join(WEB, "public", path)), `${art}: public${path} exists`).toBe(true);
    }
  });

  it("nothing is held back, and A17 and A18 appear only on their briefed screens", () => {
    expect(assets.filter((a) => a.rendered === false).map((a) => a.id)).toEqual([]);
    const files = [...sources(join(WEB, "app")), ...sources(join(WEB, "components"))];
    const using = (art: string) => files.filter((p) => readFileSync(p, "utf8").includes(`art="${art}"`)).map((p) => p.slice(WEB.length + 1)).sort();
    expect(using("empty-extraction")).toEqual(["components/extracted-terms.tsx"]);
    expect(using("assistant-ready")).toEqual(["components/status-assistant.tsx"]);
  });
});

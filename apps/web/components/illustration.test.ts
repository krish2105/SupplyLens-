// Phase 8 WP-ART: every illustration the app can show is a published, optimised file; pieces prepared for screens that
// do not exist yet (A17 Extracted terms, A18 status assistant) are rendered nowhere until those screens are built.
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

  it("reserved pieces are not rendered anywhere in the app yet", () => {
    const reserved = assets.filter((a) => a.rendered === false).map((a) => a.id).sort();
    expect(reserved).toEqual(["A17", "A18"]);
    const code = [...sources(join(WEB, "app")), ...sources(join(WEB, "components"))].map((p) => readFileSync(p, "utf8")).join("\n");
    for (const art of ["empty-extraction", "assistant-ready"]) expect(code).not.toContain(`art="${art}"`);
  });
});

import { test as base } from "@playwright/test";
import { mkdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

/**
 * The Demo reference case (DEMO-REF-SKU, 30 units needed) is shared by every test that drafts, approves or reconciles an
 * order there. An order one test has reconciled covers the need until that test releases it, so another test's
 * investigation run finds nothing to order (P2-QA-01: an order-dependent failure under parallel workers). Tests that use
 * the reference case take this cross-process lock first; it is held until the test ends, so they run one at a time while
 * every other test stays parallel. The lock is a directory (atomic to create); one older than STALE_MS is from a crashed
 * runner and is broken.
 */
const LOCK = join(tmpdir(), `supplylens-e2e-reference-${(process.env.SUPPLYLENS_WEB_URL ?? "local").replace(/\W+/g, "_")}.lock`);
const STALE_MS = 5 * 60_000;
let held = false;

export async function lockReferenceCase(timeoutMs = 180_000): Promise<void> {
  if (held) return;
  const until = Date.now() + timeoutMs;
  for (;;) {
    try {
      mkdirSync(LOCK);
      writeFileSync(join(LOCK, "owner"), `${process.pid}`);
      held = true;
      return;
    } catch {
      try { if (Date.now() - statSync(LOCK).mtimeMs > STALE_MS) rmSync(LOCK, { recursive: true, force: true }); } catch { /* gone */ }
      if (Date.now() > until) throw new Error(`reference-case lock ${LOCK} not acquired in ${timeoutMs} ms`);
      await new Promise((r) => setTimeout(r, 100));       // polling a lock, not waiting for the app
    }
  }
}

function release() {
  if (!held) return;
  rmSync(LOCK, { recursive: true, force: true });
  held = false;
}

export const test = base.extend<{ referenceLock: void }>({
  // Automatic for every test: releases the lock (if this test took it) when the test ends, pass or fail.
  referenceLock: [async ({}, use) => { await use(); release(); }, { auto: true }],
});
export { expect } from "@playwright/test";

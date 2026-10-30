"use client";
import { RotateCcw } from "lucide-react";
import { useEffect } from "react";

/**
 * What a screen shows when it fails to render (P2-FE-04): a plain statement, the reference Next.js gives the error (so it
 * can be matched in the server or browser log), and two ways on — render the screen again, or go to the overview. Nothing
 * the user typed in other screens is lost: drafts live in session storage.
 */
/** A code file from an older deploy (or build) that no longer exists: the tab predates the current version. */
export function isStaleBuild(error: { name?: string; message?: string }): boolean {
  return error.name === "ChunkLoadError" || /Failed to load chunk|Loading chunk [\w-]+ failed|Importing a module script failed|Failed to fetch dynamically imported module/i.test(error.message ?? "");
}

const RELOADED = "supplylens-stale-build-reload";

export function Crash({ error, reset, inShell }: { error: Error & { digest?: string }; reset: () => void; inShell?: boolean }) {
  const stale = isStaleBuild(error);
  useEffect(() => {
    console.error(error);
    // A tab opened before a deploy asks for files the new version no longer has. Reload once to pick up the new version;
    // the session-storage mark stops a reload loop if the error persists for another reason.
    if (!stale) return;
    try {
      if (sessionStorage.getItem(RELOADED) === window.location.href) return;
      sessionStorage.setItem(RELOADED, window.location.href);
    } catch { /* storage blocked: still reload once */ }
    window.location.reload();
  }, [error, stale]);
  if (stale) return (
    <div role="status" data-testid="render-error" className={inShell ? "space-y-3 py-6" : "mx-auto max-w-xl space-y-3 p-8"}>
      <h1 className="display text-2xl font-semibold">A new version of SupplyLens is available</h1>
      <p className="text-sm text-muted">Loading it now. If this page stays, reload it.</p>
      <button onClick={() => window.location.reload()}
        className="inline-flex h-10 items-center gap-2 rounded-lg bg-accent px-4 text-sm font-medium text-accent-ink hover:brightness-110">
        <RotateCcw className="size-4" aria-hidden /> Reload</button>
    </div>
  );
  return (
    <div role="alert" data-testid="render-error" className={inShell ? "space-y-4 py-6" : "mx-auto max-w-xl space-y-4 p-8"}>
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">Something went wrong</p>
      <h1 className="display text-2xl font-semibold">This screen could not be displayed</h1>
      <p className="text-sm text-muted">
        An unexpected error stopped this screen from rendering. Your drafts and inputs elsewhere are kept. Try showing it again;
        if it keeps happening, quote the reference below when you report it.
      </p>
      {error.digest && <p className="num text-xs text-muted">Reference {error.digest}</p>}
      <div className="flex flex-wrap gap-3">
        <button onClick={reset}
          className="inline-flex h-10 items-center gap-2 rounded-lg bg-accent px-4 text-sm font-medium text-accent-ink hover:brightness-110">
          <RotateCcw className="size-4" aria-hidden /> Show it again</button>
        {/* a full navigation, not a client transition: it leaves whatever state broke this screen behind */}
        {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
        <a href="/" className="inline-flex h-10 items-center rounded-lg border border-line-strong bg-surface px-4 text-sm font-medium hover:bg-surface-2">
          Go to the overview</a>
      </div>
    </div>
  );
}

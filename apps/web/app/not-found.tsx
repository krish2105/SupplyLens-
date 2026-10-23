import Link from "next/link";

export const metadata = { title: "Page not found · SupplyLens" };

// An unknown address says so and offers the way back, instead of the framework's bare 404 (P2-FE-04).
export default function NotFound() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-bg p-4">
      <div className="max-w-xl space-y-4" data-testid="not-found">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">404</p>
        <h1 className="display text-2xl font-semibold">There is no page at this address</h1>
        <p className="text-sm text-muted">The link may be mistyped or out of date. Your workspaces and drafts are unaffected.</p>
        <Link href="/" className="inline-flex h-10 items-center rounded-lg bg-accent px-4 text-sm font-medium text-accent-ink hover:brightness-110">
          Go to the overview</Link>
      </div>
    </main>
  );
}

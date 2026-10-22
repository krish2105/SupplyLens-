"use client";
// Signature element: the two clocks of every decision.
// "Known by" = knowledge cutoff (what had been received). "In force on" = effective date.
// Policy documents are plotted where they became known (hollow) and where they take effect (solid).
import { useMemo } from "react";
import { History, RotateCcw } from "lucide-react";
import { usePlanningContext } from "@/lib/state";
import { useApi } from "@/lib/queries";
import { day } from "@/lib/format";


const DAY = 86_400_000;

export function useDecisionClock() {
  const [ctx] = usePlanningContext();
  const overview = useApi(["overview"], "/api/v1/overview");
  const base = overview.data?.settings?.operational_as_of ?? null;
  const known = ctx.known ?? base;
  const eff = ctx.eff ?? (known ? known.slice(0, 10) : null);
  return { known, eff, base, replay: !!ctx.known && ctx.known !== base, loading: overview.isLoading };
}

export function ClockRail() {
  const [, setCtx] = usePlanningContext();
  const { known, eff, base, replay } = useDecisionClock();
  const docs = useApi(["documents"], "/api/v1/documents");

  const range = useMemo(() => {
    if (!base) return null;
    const pts = [Date.parse(base)];
    for (const d of docs.data ?? []) pts.push(Date.parse(d.known_at), Date.parse(d.valid_from + "T00:00:00Z"));
    if (known) pts.push(Date.parse(known));
    if (eff) pts.push(Date.parse(eff + "T00:00:00Z"));
    const lo = Math.min(...pts) - 10 * DAY, hi = Math.max(...pts) + 10 * DAY;
    return { lo, hi };
  }, [base, docs.data, known, eff]);

  const pos = (t: number) => (range ? `${(((t - range.lo) / (range.hi - range.lo)) * 100).toFixed(2)}%` : "0%");
  const knownLocal = known ? known.slice(0, 16) : "";

  return (
    <div className="border-b border-line bg-surface" role="region" aria-label="Decision time">
      <div className="flex flex-col items-start gap-y-2 px-4 py-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-6 md:px-6">
        <label className="flex items-center gap-2 text-xs">
          <span className="inline-flex size-5 items-center justify-center rounded-full border-2 border-forecast text-[10px] font-bold text-forecast" aria-hidden>K</span>
          <span className="text-muted">Known by</span>
          <input type="datetime-local" className="num w-[11.5rem] rounded-md border border-line bg-surface px-2 py-1 text-xs"
            value={knownLocal} aria-label="Knowledge cutoff (UTC)"
            onChange={(e) => e.target.value && setCtx({ known: new Date(e.target.value + ":00Z").toISOString() })} />
        </label>
        <label className="flex items-center gap-2 text-xs">
          <span className="inline-flex size-5 items-center justify-center rounded-full bg-accent text-[10px] font-bold text-accent-ink" aria-hidden>E</span>
          <span className="text-muted">In force on</span>
          <input type="date" className="num w-[8.5rem] rounded-md border border-line bg-surface px-2 py-1 text-xs"
            value={eff ?? ""} aria-label="Effective date"
            onChange={(e) => e.target.value && setCtx({ eff: e.target.value })} />
        </label>
        {replay ? (
          <span className="inline-flex items-center gap-1.5 rounded-md bg-risk-soft px-2 py-1 text-[11px] font-semibold text-risk">
            <History className="size-3.5" aria-hidden /> Historical replay — not the workspace&apos;s current as-of
          </span>
        ) : (
          // Always rendered (with a placeholder until the overview arrives) so the row wraps the same way before and after load.
          <span className="text-[11px] text-muted">Workspace as-of <span className="num">{base ? day(base) : "—"}</span> (UTC)</span>
        )}
        {(replay || (eff && known && eff !== known.slice(0, 10))) && (
          <button className="inline-flex items-center gap-1 text-xs text-accent underline-offset-2 hover:underline"
            onClick={() => setCtx({ known: null, eff: null })}>
            <RotateCcw className="size-3.5" aria-hidden /> Reset to workspace as-of
          </button>
        )}
      </div>
      {/* The strip's height is reserved from the first paint so data arriving later never pushes the page down (CLS). */}
      <div className="relative mx-4 mb-2 h-6 md:mx-6" aria-hidden>
        {range && (<>
          <div className="absolute inset-x-0 top-3 h-px bg-line-strong" />
          {(docs.data ?? []).map((d) => (
            <div key={d.version_id}>
              <span title={`${d.title} ${d.version_label} known ${day(d.known_at)}`}
                className="absolute top-[7px] size-2.5 -translate-x-1/2 rounded-full border-2 border-muted bg-surface"
                style={{ left: pos(Date.parse(d.known_at)) }} />
              <span title={`${d.title} ${d.version_label} in force ${day(d.valid_from)}`}
                className="absolute top-[8px] h-2 w-[3px] -translate-x-1/2 rounded bg-muted"
                style={{ left: pos(Date.parse(d.valid_from + "T00:00:00Z")) }} />
            </div>
          ))}
          {known && <span className="absolute top-0 h-6 w-[2px] -translate-x-1/2 bg-forecast" style={{ left: pos(Date.parse(known)) }} />}
          {eff && <span className="absolute top-1 h-4 w-[6px] -translate-x-1/2 rounded-sm bg-accent" style={{ left: pos(Date.parse(eff + "T00:00:00Z")) }} />}
        </>)}
      </div>
    </div>
  );
}

"use client";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { ArrowRight, CalendarClock, FileWarning } from "lucide-react";
import { useDecisionClock } from "@/components/clock-rail";
import { FloorPlan } from "@/components/floorplan";
import { Card, Empty, ErrorState, Eyebrow, Provenance, Skeleton, Stat, Status } from "@/components/ui";
import { webglAvailable } from "@/components/warehouse3d";
import { useTenantQuery, useWs, type InventoryItem, type Overview } from "@/lib/queries";
import { usePlanningContext } from "@/lib/state";
import { day, int, money, short } from "@/lib/format";

const Warehouse3D = dynamic(() => import("@/components/warehouse3d"), { ssr: false, loading: () => <Skeleton className="h-[460px]" /> });

type Doc = { version_id: string; title: string; version_label: string; known_at: string; valid_from: string; supplier_id: string | null; doc_type: string };
type Run = { id: string; status: string; mode: string; created_at: string; created_by: string; actions: number };

export default function OverviewPage() {
  const ws = useWs();
  const [ctx, setCtx] = usePlanningContext();
  const { known, eff } = useDecisionClock();
  const reduce = useReducedMotion();
  const ov = useTenantQuery<Overview>(["overview"], "/api/v1/overview");
  const inv = useTenantQuery<{ effective_date: string; items: InventoryItem[] }>(["inventory", eff], eff ? `/api/v1/inventory?effective_date=${eff}` : null);
  const docs = useTenantQuery<Doc[]>(["documents"], "/api/v1/documents");
  const runs = useTenantQuery<Run[]>(["runs"], "/api/v1/agent-runs");
  const [gl, setGl] = useState<boolean | null>(null);
  // Constrained devices default to the 2D floor plan (UX-005); WebGL failure always does.
  useEffect(() => setGl(webglAvailable() && window.innerWidth >= 768), []);

  if (ov.error) return <ErrorState error={ov.error} retry={() => ov.refetch()} />;
  const items = inv.data?.items ?? [];
  const risk = items.filter((i) => i.health === "shortage_risk");
  const excess = items.filter((i) => i.health === "excess");
  const o = ov.data;
  const currency = o?.settings?.currency ?? "GBP";
  const upcoming = (docs.data ?? []).filter((d) => known && eff && d.known_at <= known && d.valid_from > eff);
  const pending = o?.actions_by_status?.PENDING_APPROVAL ?? 0;

  return (
    <div className="space-y-6">
      <section aria-labelledby="hero" className="grid gap-6 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div className="flex flex-col justify-between gap-6 py-2">
          <div>
            <Eyebrow>{o?.dataset ? "UCI Online Retail II · one online retailer" : "Fictional demo workspace"}</Eyebrow>
            {inv.isLoading || !o ? <Skeleton className="mt-3 h-36" /> : (
              <motion.h1 id="hero" className="display mt-2 text-[clamp(2.1rem,4.2vw,3.6rem)] font-semibold leading-[1.02]"
                initial={reduce ? false : { opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease: [0.2, 0.7, 0.2, 1] }}>
                {risk.length > 0 ? (
                  <><span className="text-danger">{risk.length}</span> of {items.length} stocked products have under a week of cover on {day(eff)}.</>
                ) : items.length ? (
                  <>No stocked product is under a week of cover on {day(eff)}.</>
                ) : <>No stock positions are recorded at {day(eff)}.</>}
              </motion.h1>
            )}
            <p className="mt-4 max-w-xl text-[15px] text-muted">
              Cover is available stock divided by the last 28 days of recorded unit sales. Stock levels here are{" "}
              <Provenance kind={o?.dataset ? "simulated" : "synthetic"} /> because the source data contains sales only.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 xl:grid-cols-2 2xl:grid-cols-4">
            <Stat label="At risk" value={int(risk.length)} sub="under 7 days" kind="derived" />
            <Stat label="Excess" value={int(excess.length)} sub="over 90 days" kind="derived" />
            <Stat label="Awaiting approval" value={int(pending)} sub="purchase-order drafts" />
            <Stat label="Policy changes ahead" value={int(upcoming.length)} sub="known, not yet in force" />
          </div>
          <div className="flex flex-wrap gap-3">
            <Link href={{ pathname: "/runs", query: { ws } }} className="inline-flex h-11 items-center gap-2 rounded-lg bg-accent px-5 text-sm font-semibold text-accent-ink hover:brightness-110">
              Investigate exceptions <ArrowRight className="size-4" aria-hidden />
            </Link>
            <Link href={{ pathname: "/approvals", query: { ws } }} className="inline-flex h-11 items-center gap-2 rounded-lg border border-line-strong bg-surface px-5 text-sm font-semibold hover:bg-surface-2">
              Review approvals
            </Link>
          </div>
        </div>
        <Card className="overflow-hidden p-0">
          {inv.error ? <div className="p-4"><ErrorState error={inv.error} /></div> :
            gl === false ? (
              <div className="p-4">
                <p className="mb-3 text-sm text-muted">Showing the 2D floor plan (small screen or WebGL unavailable). It shows the same records as the 3D view.</p>
                <FloorPlan items={items} selected={ctx.sku} onSelect={(s) => setCtx({ sku: s })} />
              </div>
            ) : gl === null || inv.isLoading ? <Skeleton className="h-[460px]" /> : items.length ? (
              <Warehouse3D items={items} selected={ctx.sku} onSelect={(s) => setCtx({ sku: s })} />
            ) : <div className="p-6"><Empty title="No stock positions at this date">Move “In force on” to a date with a recorded snapshot.</Empty></div>}
          {ctx.sku && (() => {
            const it = items.find((i) => i.sku_id === ctx.sku);
            return it ? (
              <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-line px-4 py-3 text-sm">
                <span className="num font-semibold">{it.sku_id}</span>
                <span className="min-w-0 flex-1 truncate text-muted">{it.description}</span>
                <span className="num">{int(it.available)} available</span>
                <Status value={it.health} />
                <Link className="text-accent underline-offset-2 hover:underline" href={{ pathname: "/inventory", query: { ws, sku: it.sku_id } }}>Open in inventory</Link>
              </div>
            ) : null;
          })()}
        </Card>
      </section>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="p-5">
          <Eyebrow>Admitted data</Eyebrow>
          {o?.dataset ? (
            <div className="mt-3 space-y-3">
              <p className="font-semibold">{o.dataset.name} <span className="text-muted">· {o.dataset.license}</span></p>
              <div className="grid grid-cols-3 gap-3">
                <Stat label="Accepted" value={int(o.dataset.totals.accepted)} kind="observed" />
                <Stat label="Returns" value={int(o.dataset.totals.returned)} />
                <Stat label="Quarantined" value={int(o.dataset.totals.quarantined)} />
              </div>
              <p className="text-xs text-muted">{int(o.dataset.totals.input_rows)} source rows, {day(o.dataset.date_span[0])} to {day(o.dataset.date_span[1])}. SHA-256 <span className="num">{short(o.dataset.sha256, 12)}</span>.</p>
              <Link href={{ pathname: "/data", query: { ws } }} className="text-sm text-accent underline-offset-2 hover:underline">See reconciliation</Link>
            </div>
          ) : <p className="mt-3 text-sm text-muted">No sales dataset in this workspace. It uses the execution pack&apos;s fictional fixtures, so forecasting is unavailable here.</p>}
        </Card>

        <Card className="p-5">
          <Eyebrow>What this data can answer</Eyebrow>
          <ul className="mt-3 space-y-2">
            {(o?.capabilities ?? []).map((c) => (
              <li key={c.capability} className="flex items-start justify-between gap-3 text-sm">
                <span><span className="font-medium">{c.capability}</span><span className="block text-xs text-muted">{c.note}</span></span>
                <Status value={c.status} />
              </li>
            ))}
          </ul>
        </Card>

        <Card className="p-5">
          <Eyebrow>Policy changes on the horizon</Eyebrow>
          {upcoming.length ? (
            <ul className="mt-3 space-y-3">
              {upcoming.map((d) => (
                <li key={d.version_id} className="flex gap-3 text-sm">
                  <FileWarning className="mt-0.5 size-4 shrink-0 text-risk" aria-hidden />
                  <span>
                    <span className="font-medium">{d.title}</span> — {d.version_label}
                    <span className="block text-xs text-muted">Known {day(d.known_at)} · in force {day(d.valid_from)}</span>
                  </span>
                </li>
              ))}
            </ul>
          ) : <p className="mt-3 text-sm text-muted">No document known by the cutoff takes effect after {day(eff)}.</p>}
          <Link href={{ pathname: "/policies", query: { ws } }} className="mt-4 inline-block text-sm text-accent underline-offset-2 hover:underline">Open policies</Link>
        </Card>
      </div>

      <Card className="p-5">
        <div className="flex items-center justify-between">
          <Eyebrow>Recent investigations</Eyebrow>
          <Link href={{ pathname: "/runs", query: { ws } }} className="text-sm text-accent underline-offset-2 hover:underline">All runs</Link>
        </div>
        {runs.data?.length ? (
          <ul className="mt-3 divide-y divide-line">
            {runs.data.slice(0, 5).map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-4 py-2.5 text-sm">
                <CalendarClock className="size-4 text-muted" aria-hidden />
                <Link className="num font-semibold text-accent" href={{ pathname: "/runs", query: { ws, run: r.id } }}>{short(r.id)}</Link>
                <span className="text-muted">{r.mode} · {r.created_by}</span>
                <span className="text-muted">{day(r.created_at)}</span>
                <span className="ml-auto flex items-center gap-3"><span className="text-muted">{r.actions} draft(s)</span><Status value={r.status} /></span>
              </li>
            ))}
          </ul>
        ) : <p className="mt-3 text-sm text-muted">No investigations yet. Start one to forecast, plan and prepare drafts with cited evidence.</p>}
        {o?.assumption_set && (
          <p className="mt-4 border-t border-line pt-3 text-xs text-muted">
            Simulated inputs come from assumption set <span className="num">{o.assumption_set.name} v{o.assumption_set.version}</span>. Budget {money(Number(o.settings?.planning?.weekly_budget_minor ?? 0), currency)} per run <Provenance kind="assumed" />.
          </p>
        )}
      </Card>
    </div>
  );
}

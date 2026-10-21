"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import clsx from "clsx";
import { AlertOctagon, CalendarClock, FileWarning, PackageX, Warehouse } from "lucide-react";
import { useDecisionClock } from "@/components/clock-rail";
import { Card, Empty, ErrorState, Loading, PageHeader, Provenance } from "@/components/ui";
import { useTenantQuery, useWs } from "@/lib/queries";
import { day, money } from "@/lib/format";

type Item = { kind: string; basis: string; sku_id: string | null; action_id?: string; title: string; detail: string; severity: string;
  materiality_minor: number | null; materiality_basis: string | null; deadline: string | null; value_kind: string };
type Resp = { effective_date: string | null; currency: string; items: Item[]; counts: Record<string, number>; message?: string };

const KIND: Record<string, { label: string; icon: typeof AlertOctagon }> = {
  shortage_risk: { label: "Shortage risk", icon: PackageX }, excess: { label: "Excess stock", icon: Warehouse },
  policy_change: { label: "Policy change ahead", icon: FileWarning }, action_pending_approval: { label: "Awaiting approval", icon: CalendarClock },
  action_unknown_outcome: { label: "Unknown outcome", icon: AlertOctagon }, action_stale: { label: "Stale draft", icon: AlertOctagon },
  action_failed: { label: "Dispatch failed", icon: AlertOctagon },
};

export default function ExceptionsPage() {
  const ws = useWs();
  const { eff } = useDecisionClock();
  const q = useTenantQuery<Resp>(["exceptions", eff], eff ? `/api/v1/exceptions?effective_date=${eff}` : "/api/v1/exceptions", { refetchInterval: 10000 });
  const [kind, setKind] = useState<string>("all");
  const items = useMemo(() => (q.data?.items ?? []).filter((i) => kind === "all" || i.kind === kind), [q.data, kind]);
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Exceptions" title="What needs a decision, ranked by severity and value">
        Predicted exceptions come from recent sales and stock; policy changes come from documents known by the cutoff; action
        exceptions come from the system&apos;s own state. Each one says which.
      </PageHeader>
      {q.error && <ErrorState error={q.error} retry={() => q.refetch()} />}
      {q.data?.message && <Empty title="No operational exceptions here">{q.data.message}</Empty>}
      <div role="tablist" aria-label="Exception type" className="flex flex-wrap gap-1">
        {["all", ...Object.keys(q.data?.counts ?? {})].map((k) => (
          <button key={k} role="tab" aria-selected={kind === k} onClick={() => setKind(k)}
            className={clsx("rounded-lg px-3 py-1.5 text-sm", kind === k ? "bg-ink text-bg" : "text-muted hover:bg-surface-2")}>
            {k === "all" ? `All (${q.data?.items.length ?? 0})` : `${KIND[k]?.label ?? k} (${q.data?.counts[k]})`}
          </button>
        ))}
      </div>
      {q.isLoading ? <Loading /> : (
        <ul className="grid gap-3 lg:grid-cols-2">
          {items.map((i, n) => {
            const K = KIND[i.kind] ?? KIND.action_failed!;
            return (
              <li key={n}>
                <Card as="article" className="flex h-full gap-4 p-4">
                  <span className={clsx("mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg",
                    i.severity === "high" ? "bg-danger-soft text-danger" : i.severity === "medium" ? "bg-risk-soft text-risk" : "bg-surface-2 text-muted")}>
                    <K.icon className="size-4" aria-hidden />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="font-semibold">{i.title}</h2>
                      <span className="text-xs text-muted">{K.label} · {i.basis}</span><Provenance kind={i.value_kind} />
                    </div>
                    <p className="mt-1 text-sm text-muted">{i.detail}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
                      {i.materiality_minor != null && <span title={i.materiality_basis ?? undefined}><span className="num font-semibold text-ink">{money(i.materiality_minor, q.data?.currency)}</span> <span className="text-muted">{i.materiality_basis}</span></span>}
                      {i.deadline && <span className="text-muted">Decide by <span className="num text-ink">{day(i.deadline)}</span></span>}
                      <span className={clsx("rounded-md px-2 py-0.5 font-semibold capitalize",
                        i.severity === "high" ? "bg-danger-soft text-danger" : i.severity === "medium" ? "bg-risk-soft text-risk" : "bg-surface-2 text-muted")}>
                        {i.severity} severity</span>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-3 text-sm">
                      {i.sku_id && <Link className="text-accent hover:underline" href={{ pathname: "/inventory", query: { ws, sku: i.sku_id } }}>Inspect {i.sku_id}</Link>}
                      {i.sku_id && i.kind === "shortage_risk" && <Link className="text-accent hover:underline" href={{ pathname: "/runs", query: { ws, sku: i.sku_id } }}>Investigate</Link>}
                      {i.kind === "policy_change" && <Link className="text-accent hover:underline" href={{ pathname: "/policies", query: { ws, sku: i.sku_id } }}>Compare versions</Link>}
                      {i.action_id && <Link className="text-accent hover:underline" href={{ pathname: "/approvals", query: { ws, action: i.action_id } }}>Open draft</Link>}
                    </div>
                  </div>
                </Card>
              </li>
            );
          })}
        </ul>
      )}
      {!q.isLoading && !items.length && !q.data?.message && <Empty title="No exceptions match this filter" />}
    </div>
  );
}

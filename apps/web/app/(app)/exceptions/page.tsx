"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import clsx from "clsx";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertOctagon, BellRing, CalendarClock, FileWarning, PackageX, Warehouse } from "lucide-react";
import { useDecisionClock } from "@/components/clock-rail";
import { Button, Card, Empty, ErrorState, Eyebrow, Loading, Mono, PageHeader, Provenance, Status, TabList, TabPanel } from "@/components/ui";
import { EmptyState } from "@/components/illustration";
import { apiPost } from "@/lib/api";
import { useApi, useMe, useWs } from "@/lib/queries";
import { usePlanningContext } from "@/lib/state";
import { dateTime, day, money } from "@/lib/format";


const KIND: Record<string, { label: string; icon: typeof AlertOctagon }> = {
  shortage_risk: { label: "Shortage risk", icon: PackageX }, excess: { label: "Excess stock", icon: Warehouse },
  policy_change: { label: "Policy change ahead", icon: FileWarning }, action_pending_approval: { label: "Awaiting approval", icon: CalendarClock },
  action_unknown_outcome: { label: "Unknown outcome", icon: AlertOctagon }, action_stale: { label: "Stale draft", icon: AlertOctagon },
  action_failed: { label: "Dispatch failed", icon: AlertOctagon },
};

export default function ExceptionsPage() {
  const ws = useWs();
  const [ctx] = usePlanningContext();
  const { eff } = useDecisionClock();
  // Without a replayed date the API uses the workspace as-of itself, so the first request does not wait for (and is not
  // repeated after) the overview that the clock derives its date from.
  const effQ = ctx.known || ctx.eff ? eff ?? undefined : undefined;
  const q = useApi(["exceptions", effQ ?? "workspace"], "/api/v1/exceptions", { query: { effective_date: effQ }, refetchInterval: 10000 });
  const [kind, setKind] = useState<string>("all");
  const items = useMemo(() => (q.data?.items ?? []).filter((i) => kind === "all" || i.kind === kind), [q.data, kind]);
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Exceptions" title="What needs a decision, ranked by severity and value">
        Predicted exceptions come from recent sales and stock; policy changes come from documents known by the cutoff; action
        exceptions come from the system&apos;s own state. Each one says which.
      </PageHeader>
      <AlertQueue />
      {q.error && <ErrorState error={q.error} retry={() => q.refetch()} />}
      {q.data?.message && <Empty title="No operational exceptions here">{q.data.message}</Empty>}
      <TabList id="exc" label="Exception type" value={kind} onChange={setKind} className="flex flex-wrap gap-1"
        tabClassName={(on) => clsx("rounded-lg px-3 py-1.5 text-sm", on ? "bg-ink text-bg" : "text-muted hover:bg-surface-2")}
        tabs={["all", ...Object.keys(q.data?.counts ?? {})].map((k) => ({ key: k,
          label: k === "all" ? `All (${q.data?.items.length ?? 0})` : `${KIND[k]?.label ?? k} (${q.data?.counts[k]})` }))} />
      <TabPanel id="exc" value={kind} className="space-y-3">
      {q.isLoading ? <Loading /> : (
        <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2">
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
                      {i.materiality_minor == null && i.materiality_basis && <span className="text-muted">{i.materiality_basis}</span>}
                      {i.materiality_minor != null && <span title={i.materiality_basis ?? undefined}><span className="num font-semibold text-ink">{money(i.materiality_minor, q.data?.currency ?? undefined)}</span> <span className="text-muted">{i.materiality_basis}</span></span>}
                      {i.deadline && <span className="text-muted">Decide by <span className="num text-ink">{day(i.deadline)}</span></span>}
                      <span className={clsx("rounded-md px-2 py-0.5 font-semibold capitalize",
                        i.severity === "high" ? "bg-danger-soft text-danger" : i.severity === "medium" ? "bg-risk-soft text-risk" : "bg-surface-2 text-muted")}>
                        {i.severity} severity</span>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-3 text-sm">
                      {i.sku_id && <Link className="inline-flex min-h-6 items-center text-accent hover:underline" href={{ pathname: "/inventory", query: { ws, sku: i.sku_id } }}>Inspect {i.sku_id}</Link>}
                      {i.sku_id && i.kind === "shortage_risk" && <Link className="inline-flex min-h-6 items-center text-accent hover:underline" href={{ pathname: "/runs", query: { ws, sku: i.sku_id } }}>Investigate</Link>}
                      {i.kind === "policy_change" && <Link className="inline-flex min-h-6 items-center text-accent hover:underline" href={{ pathname: "/policies", query: { ws, sku: i.sku_id } }}>Compare versions</Link>}
                      {i.action_id && <Link className="inline-flex min-h-6 items-center text-accent hover:underline" href={{ pathname: "/approvals", query: { ws, action: i.action_id } }}>Open draft</Link>}
                    </div>
                  </div>
                </Card>
              </li>
            );
          })}
        </ul>
      )}
      {!q.isLoading && !q.error && !items.length && !q.data?.message && (kind === "all"
        ? <EmptyState variant="no_pending" title="No exceptions in this view" compact>Nothing is predicted or recorded for this workspace at these clocks. This is not a statement about overall system health.</EmptyState>
        : <EmptyState variant="empty_filtered" title="No exceptions of this type" compact>Choose “All” to see every exception at these clocks.</EmptyState>)}
      </TabPanel>
    </div>
  );
}

const ALERT_LABEL: Record<string, string> = {
  stale_data: "Stale data", failed_reconciliation: "Failed reconciliation", budget_exhausted: "Budget exhausted", model_unavailable: "Model unavailable", job_failed: "Background job failed",
  erp_connector: "ERP connector", erp_sync: "ERP synchronisation", overdue_receipt: "Overdue receipt",
};

/** The operational queue: stale data, failed reconciliation, exhausted budgets and unavailable models. */
function AlertQueue() {
  const ws = useWs();
  const qc = useQueryClient();
  const me = useMe();
  const role = me.data?.memberships.find((m) => m.slug === ws)?.role;
  const q = useApi(["alerts"], "/api/v1/alerts", { refetchInterval: 8000 });
  const ack = useMutation({
    mutationFn: (id: string) => apiPost("/api/v1/alerts/{alert_id}/acknowledge", { path: { alert_id: id }, body: {} }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [ws, "alerts"] }),
  });
  const live = (q.data?.alerts ?? []).filter((a) => a.status !== "RESOLVED");
  const canAck = ["planner", "approver", "tenant_admin"].includes(role ?? "");
  return (
    <Card className="p-5" aria-labelledby="alerts-title">
      <div className="flex items-center gap-2"><BellRing className="size-4 text-muted" aria-hidden /><h2 id="alerts-title"><Eyebrow>Operational alerts</Eyebrow></h2></div>
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : live.length ? (
        <ul className="mt-3 divide-y divide-line" aria-live="polite">
          {live.map((a) => (
            <li key={a.id} className="flex flex-wrap items-start gap-3 py-3">
              <Status value={a.status} />
              <div className="min-w-0 flex-1">
                <p className="font-medium">{a.title}</p>
                <p className="text-xs text-muted">{ALERT_LABEL[a.kind] ?? a.kind} · {a.severity} · first {dateTime(a.first_seen)} · seen {a.occurrences}×
                  {a.delivery_status !== "NONE" && <> · webhook <Mono>{a.delivery_status.toLowerCase()}</Mono></>}</p>
              </div>
              {canAck && a.status === "OPEN" && <Button size="sm" variant="outline" onClick={() => ack.mutate(a.id)} busy={ack.isPending && ack.variables === a.id}>Acknowledge</Button>}
            </li>
          ))}
        </ul>
      ) : <p className="mt-3 text-sm text-muted">No open alerts. Alerts open when data goes stale, an order cannot be reconciled, a run exhausts its budget, or a model becomes unavailable.</p>}
      {ack.error && <div className="mt-3"><ErrorState error={ack.error} /></div>}
    </Card>
  );
}

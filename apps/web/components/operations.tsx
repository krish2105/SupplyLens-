"use client";
// Operational health and order reconciliation (Phase 6): what is broken now, which approved orders lack a known outcome,
// and the service levels the runbook defines. Read-only except "Test connection", which never sends an order.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, Card, ErrorState, Eyebrow, Loading, Mono, QueryError, Status } from "@/components/ui";
import { apiPost } from "@/lib/api";
import { useApi, useWs } from "@/lib/queries";
import { dateTime, int, money } from "@/lib/format";

type Row = Record<string, unknown>;
const secs = (v: unknown) => (typeof v === "number" ? (v < 120 ? `${v.toFixed(0)} s` : `${(v / 60).toFixed(1)} min`) : "—");

export function OperationsHealth({ locked }: { locked: boolean }) {
  const ws = useWs();
  const qc = useQueryClient();
  const health = useApi(["ops-health"], "/api/v1/ops/health", { refetchInterval: 15000 });
  const test = useMutation({
    mutationFn: () => apiPost("/api/v1/ops/connector/test", {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: [ws, "ops-health"] }),
  });
  const h = health.data;
  const conn = (h?.connector ?? {}) as Row;
  const jobs = (h?.jobs ?? {}) as Row;
  const outbox = (h?.outbox ?? {}) as Row;
  const imports = (h?.imports ?? {}) as Row;
  const workers = (h?.workers ?? {}) as Row;
  return (
    <Card className="min-w-0 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2"><Eyebrow>Service health</Eyebrow>{h && <Status value={h.status} />}</div>
      {health.error ? <QueryError q={health} what="service health" /> : !h ? <Loading /> : <>
        {h.problems.length > 0
          ? <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-danger" aria-label="Problems">{h.problems.map((p) => <li key={p}>{p}</li>)}</ul>
          : <p className="mt-3 text-sm text-muted">No problem detected at {dateTime(h.checked_at)}.</p>}
        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3">
          <div><dt className="text-xs text-muted">Workers</dt><dd><Status value={String(workers.status)} /> <span className="text-xs text-muted">{workers.mode === "inline" ? "inline (serverless)" : `${int(Number(workers.live ?? 0))} live`}</span></dd></div>
          <div><dt className="text-xs text-muted">Database</dt><dd className="num">{String((h.database as Row).latency_ms)} ms</dd></div>
          <div><dt className="text-xs text-muted">ERP connector</dt><dd><Status value={String(conn.status ?? "unknown")} /> <span className="text-xs text-muted">{String(conn.adapter ?? "")}</span></dd></div>
          <div><dt className="text-xs text-muted">Jobs queued / failed 24 h</dt><dd className="num">{int(Number(jobs.queued ?? 0))} / {int(Number(jobs.failed_24h ?? 0))}</dd></div>
          <div><dt className="text-xs text-muted">Oldest approved order waiting</dt><dd className="num">{secs(outbox.oldest_pending_s)}</dd></div>
          <div><dt className="text-xs text-muted">Imports rejected 7 d / quarantined rows</dt><dd className="num">{int(Number(imports.rejected_7d ?? 0))} / {int(Number(imports.quarantined_rows_7d ?? 0))}</dd></div>
        </dl>
        {conn.last_error != null && conn.status !== "OK" && <p className="mt-3 text-xs text-muted">Last connector error: <Mono>{String(conn.last_error)}</Mono></p>}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button size="sm" variant="outline" disabled={locked} title={locked ? "Disabled in the public demo" : undefined} busy={test.isPending}
            onClick={() => test.mutate()}>Test ERP connection</Button>
          {test.data && <span className="text-xs text-muted" role="status">Connector {test.data.status}{test.data.error ? `: ${test.data.error}` : ""}</span>}
        </div>
        {test.error && <div className="mt-2"><ErrorState error={test.error} /></div>}
        {(jobs.recent_failures as Row[] | undefined)?.length ? (
          <details className="mt-3 text-xs text-muted"><summary className="cursor-pointer">Recent failed jobs</summary>
            <ul className="mt-1 space-y-1">{(jobs.recent_failures as Row[]).map((j) => <li key={String(j.id)}><Mono>{String(j.kind)}</Mono> attempt {String(j.attempts)}/{String(j.max_attempts)}: {String(j.error ?? "no error recorded")}</li>)}</ul></details>) : null}
      </>}
    </Card>
  );
}

export function OrderReconciliation() {
  const rec = useApi(["ops-reconciliation"], "/api/v1/ops/reconciliation", { refetchInterval: 15000 });
  const r = rec.data;
  const sl = (r?.service_levels ?? {}) as Row;
  const ledger = (r?.ledger ?? {}) as Row;
  const sync = (r?.sync ?? {}) as Row;
  return (
    <Card className="min-w-0 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2"><Eyebrow>Order reconciliation</Eyebrow>
        {r && <span className="text-xs text-muted">adapter <Mono>{r.adapter}</Mono></span>}</div>
      {rec.error ? <QueryError q={rec} what="order reconciliation" /> : !r ? <Loading /> : <>
        <p className="mt-2 text-sm">{r.unaccounted_orders === 0
          ? "Every approved order has a known outcome."
          : <span className="text-danger">{int(r.unaccounted_orders)} order(s) without a confirmed, matching outcome.</span>}</p>
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-4">
          <div><dt className="text-xs text-muted">Approved → reconciled, p95 ({String(sl.window_days)} d)</dt><dd className="num">{secs(sl.p95_s)}</dd></div>
          <div><dt className="text-xs text-muted">Within 5 minutes</dt><dd className="num">{typeof sl.approved_to_reconciled_within_5_min === "number" ? `${(sl.approved_to_reconciled_within_5_min * 100).toFixed(1)}%` : "—"}</dd></div>
          <div><dt className="text-xs text-muted">Open units / overdue lines</dt><dd className="num">{int(Number(ledger.open_units ?? 0))} / {int(Number(ledger.overdue_lines ?? 0))}</dd></div>
          <div><dt className="text-xs text-muted">Last receipt sync</dt><dd className="text-xs">{sync.last_receipt_sync_at ? dateTime(String(sync.last_receipt_sync_at)) : "never"}</dd></div>
        </dl>
        <div className="mt-3 flex flex-wrap gap-2">{Object.entries(r.actions_by_status).map(([k, n]) => (
          <span key={k} className="inline-flex items-center gap-1.5 text-xs"><Status value={k} /><span className="num">{int(n)}</span></span>))}</div>
        {r.needs_attention.length > 0 && (
          <div className="mt-4 max-w-full overflow-x-auto"><table className="w-full text-sm"><caption className="sr-only">Orders that need a person</caption>
            <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Order</th><th className="font-medium">Status</th><th className="font-medium">Value</th><th className="font-medium">Next step</th></tr></thead>
            <tbody>{r.needs_attention.map((x) => (
              <tr key={String(x.action_id)} className="border-b border-line/60 align-top">
                <td className="py-2"><Mono>{String(x.supplier_id)}</Mono><span className="block text-xs text-muted">{x.external_ref ? String(x.external_ref) : "not placed"}{x.failure_kind ? ` · ${String(x.failure_kind)}` : ""}</span></td>
                <td><Status value={String(x.status)} /></td>
                <td className="num">{money(Number(x.total_minor), String(x.currency))}</td>
                <td className="text-xs text-muted">{String(x.next_step)}</td></tr>))}</tbody></table></div>)}
        {r.sync_alerts.length > 0 && (
          <ul className="mt-4 space-y-1 text-sm" aria-label="Synchronisation exceptions">{r.sync_alerts.map((a) => (
            <li key={String(a.dedupe_key)} className="flex flex-wrap items-center gap-2"><Status value={String(a.severity) === "high" ? "OPEN" : "ACKNOWLEDGED"} />{String(a.title)}</li>))}</ul>)}
      </>}
    </Card>
  );
}

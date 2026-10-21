"use client";
import { useState } from "react";
import { Card, Empty, ErrorState, Eyebrow, KV, Loading, Mono, PageHeader, Provenance, Stat, Status } from "@/components/ui";
import { useTenantQuery } from "@/lib/queries";
import { dateTime, day, int, money } from "@/lib/format";

type Dataset = {
  id: string; name: string; source_kind: string; license: string; source_url: string | null; file_name: string; sha256: string;
  bytes: number; schema_version: string; status: string; created_at: string;
  report: { totals: Record<string, number>; sheets: Record<string, { input_rows: number; accepted: number; returned: number; quarantined: number; quarantine_reasons: Record<string, number> }>;
    date_span: [string, string]; distinct_skus_accepted: number; distinct_customers: number; missing_customer_id_rows: number; notes: string[]; doi?: string };
};
type Quarantine = { summary: { reason: string; n: number }[]; rows: { id: number; source_sheet: string; source_row: number; reason: string; raw: Record<string, unknown> }[]; next_cursor: number | null };

const REASON_COPY: Record<string, string> = {
  cross_sheet_overlap: "Invoice already present in the earlier sheet (1–9 Dec 2010 appears in both); counted once.",
  exact_duplicate_line: "Identical line repeated on the same invoice; first occurrence kept.",
  non_merchandise_code: "Postage, fees, discounts and manual adjustments are not products.",
  zero_price: "Positive quantity at zero price: stock adjustment or free item, not a sale.",
  negative_price_adjustment: "Bad-debt adjustment with negative price.",
  invalid_invoice_date: "Date could not be parsed.",
  zero_quantity: "Quantity of zero.",
};

export default function DataPage() {
  const ds = useTenantQuery<Dataset[]>(["datasets"], "/api/v1/datasets");
  const d = ds.data?.[0];
  const [reason, setReason] = useState<string | null>(null);
  const q = useTenantQuery<Quarantine>(["quarantine", d?.id, reason], d ? `/api/v1/datasets/${d.id}/quarantine?limit=25${reason ? `&reason=${reason}` : ""}` : null);

  if (ds.isLoading) return <Loading label="Loading datasets" />;
  if (ds.error) return <ErrorState error={ds.error} retry={() => ds.refetch()} />;
  if (!d) return (
    <>
      <PageHeader eyebrow="Data admission" title="No dataset admitted in this workspace" />
      <Empty title="This workspace uses fictional fixtures only">
        Switch to <b>UCI Research</b> to inspect the real dataset, or run <Mono>python scripts/download_datasets.py --dataset online_retail_ii</Mono> and <Mono>uv run python -m supplylens.bootstrap</Mono>.
      </Empty>
    </>
  );
  const t = d.report.totals;
  const parts = [
    { k: "accepted", label: "Accepted sales", v: t.accepted!, cls: "bg-accent" },
    { k: "returned", label: "Returns & cancellations", v: t.returned!, cls: "bg-forecast" },
    { k: "quarantined", label: "Quarantined", v: t.quarantined!, cls: "bg-risk" },
  ];
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Data admission" title={d.name}>
        Every source row ends in exactly one place. The raw file is never modified; its hash is checked after ingestion.
      </PageHeader>

      <Card className="p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <Eyebrow>Row reconciliation</Eyebrow>
          <span className="num text-sm">{int(t.accepted)} + {int(t.returned)} + {int(t.quarantined)} = {int(t.input_rows)} source rows
            {t.accepted! + t.returned! + t.quarantined! === t.input_rows ? <span className="ml-2 text-accent">✓ reconciles</span> : <span className="ml-2 text-danger">✗ does not reconcile</span>}</span>
        </div>
        <div className="mt-3 flex h-4 overflow-hidden rounded-full" role="img"
          aria-label={parts.map((p) => `${p.label} ${int(p.v)}`).join(", ")}>
          {parts.map((p) => <div key={p.k} className={p.cls} style={{ width: `${(p.v / t.input_rows!) * 100}%` }} />)}
        </div>
        <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4">
          {parts.map((p) => <Stat key={p.k} label={p.label} value={int(p.v)} sub={`${((p.v / t.input_rows!) * 100).toFixed(2)}% of rows`} />)}
          <Stat label="Accepted value" value={money(t.accepted_value_minor_gbp, "GBP")} sub="selling price × units, not purchase cost" kind="observed" />
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-5">
          <Eyebrow>Provenance and rights</Eyebrow>
          <div className="mt-3">
            <KV items={[
              ["Source", d.source_url ? <a className="text-accent underline-offset-2 hover:underline" href={d.source_url} target="_blank" rel="noreferrer">UCI Machine Learning Repository</a> : "—"],
              ["DOI", d.report.doi ?? "—"],
              ["Licence", <span key="l">{d.license} <span className="text-muted">— attribution required; redistribution allowed with credit</span></span>],
              ["File", <Mono key="f">{d.file_name}</Mono>],
              ["SHA-256", <Mono key="h" className="break-all">{d.sha256}</Mono>],
              ["Size", `${int(d.bytes)} bytes`],
              ["Transform", <Mono key="t">{d.schema_version}</Mono>],
              ["Ingested", dateTime(d.created_at)],
              ["Coverage", `${day(d.report.date_span[0])} – ${day(d.report.date_span[1])}`],
              ["Products", int(d.report.distinct_skus_accepted)],
              ["Status", <Status key="s" value={d.status} />],
            ]} />
          </div>
        </Card>
        <Card className="p-5">
          <Eyebrow>What the target means</Eyebrow>
          <ul className="mt-3 list-disc space-y-2 pl-5 text-sm">
            {d.report.notes.map((n) => <li key={n}>{n}</li>)}
            <li>{int(d.report.missing_customer_id_rows)} accepted rows have no customer ID; they are still sales.</li>
            <li>9 Dec 2011 is a partial trading day, so the workspace as-of is 8 Dec 2011.</li>
          </ul>
          <div className="mt-4 flex flex-wrap gap-2"><Provenance kind="observed" /><span className="text-xs text-muted">Sales history</span>
            <Provenance kind="simulated" /><span className="text-xs text-muted">Stock, suppliers, costs, lead times</span></div>
        </Card>
      </div>

      <Card className="p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Eyebrow>Quarantine — why rows were excluded</Eyebrow>
          {reason && <button className="text-sm text-accent hover:underline" onClick={() => setReason(null)}>Show all reasons</button>}
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {q.data?.summary.map((s) => (
            <button key={s.reason} onClick={() => setReason(s.reason)} aria-pressed={reason === s.reason}
              className={`rounded-xl border p-3 text-left text-sm ${reason === s.reason ? "border-accent bg-accent-soft" : "border-line hover:bg-surface-2"}`}>
              <span className="flex items-center justify-between gap-3"><Mono className="font-semibold">{s.reason}</Mono><span className="num">{int(s.n)}</span></span>
              <span className="mt-1 block text-xs text-muted">{REASON_COPY[s.reason] ?? ""}</span>
            </button>
          ))}
        </div>
        {q.isLoading ? <Loading /> : q.data && (
          <div className="mt-4 overflow-x-auto" tabIndex={0} role="region" aria-label="Quarantined rows, scrollable">
            <table className="w-full text-sm">
              <caption className="sr-only">Sample of quarantined source rows</caption>
              <thead><tr className="border-b border-line text-left text-xs text-muted">
                <th className="py-2 pr-4 font-medium">Sheet / row</th><th className="pr-4 font-medium">Reason</th><th className="font-medium">Original values</th></tr></thead>
              <tbody>
                {q.data.rows.map((r) => (
                  <tr key={r.id} className="border-b border-line/60 align-top">
                    <td className="num py-2 pr-4 text-xs">{r.source_sheet} · {r.source_row}</td>
                    <td className="pr-4"><Mono>{r.reason}</Mono></td>
                    <td className="num py-2 text-xs text-muted">{Object.keys(r.raw).length ? Object.entries(r.raw).map(([k, v]) => `${k}=${v ?? "∅"}`).join("  ") : "see earlier sheet"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

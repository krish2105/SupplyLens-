"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { baseOption, Chart, token } from "@/components/chart";
import { useDecisionClock } from "@/components/clock-rail";
import { Button, Card, Empty, ErrorState, Eyebrow, Mono, PageHeader, Provenance, Status } from "@/components/ui";
import { post } from "@/lib/api";
import { useMe, useTenantQuery, useWs, type Overview } from "@/lib/queries";
import { dateTime, int, money, num } from "@/lib/format";

type Inputs = { demand_multiplier: number; supplier_delay_days: number; budget_minor: number; safety_days: number; coverage_days: number };
type Result = {
  scenario_id: string; name: string; inputs: Record<string, any>; forecast_run_id: string;
  plan: { status: string; lines: any[]; explanation?: string[]; total_minor?: number; shortfall?: Record<string, number> };
  metrics: { skus_assessed: number; skus_needing_order: number; units_ordered: number; spend_minor: number; shortfall_units: number; projected_q50_coverage: number | null; metric_note: string };
  terms: { applicable: number; ignored: unknown[]; conflicts: string[][] };
};

const CONTROLS: { k: keyof Inputs; label: string; unit: string; min: number; max: number; step: number; scale?: number }[] = [
  { k: "demand_multiplier", label: "Demand multiplier", unit: "× forecast median", min: 0.5, max: 2, step: 0.05 },
  { k: "supplier_delay_days", label: "Supplier delay", unit: "days added to every lead time", min: 0, max: 30, step: 1 },
  { k: "budget_minor", label: "Purchasing budget", unit: "per run", min: 0, max: 10_000_000, step: 50_000, scale: 100 },
  { k: "safety_days", label: "Safety buffer", unit: "days of mean forecast demand", min: 0, max: 30, step: 1 },
  { k: "coverage_days", label: "Coverage window", unit: "days", min: 7, max: 60, step: 1 },
];

export default function ScenariosPage() {
  const ws = useWs();
  const qc = useQueryClient();
  const me = useMe();
  const role = me.data?.memberships.find((m) => m.slug === ws)?.role;
  const { known, eff } = useDecisionClock();
  const ov = useTenantQuery<Overview>(["overview"], "/api/v1/overview");
  const saved = useTenantQuery<any[]>(["scenarios"], "/api/v1/scenarios");
  const planning = (ov.data?.settings?.planning ?? {}) as Record<string, number>;
  const currency = ov.data?.settings?.currency ?? "GBP";
  const baseline: Inputs = { demand_multiplier: 1, supplier_delay_days: 0, budget_minor: planning.weekly_budget_minor ?? 0,
    safety_days: planning.safety_days ?? 5, coverage_days: planning.coverage_days ?? 21 };
  const [draft, setDraft] = useState<Inputs | null>(null);
  const d = draft ?? baseline;
  const [results, setResults] = useState<{ base?: Result; draft?: Result; draftInputs?: Inputs }>({});

  const compute = useMutation({
    mutationFn: async (which: "base" | "draft") => {
      const inp = which === "base" ? baseline : d;
      const r = await post<Result>("/api/v1/scenarios", { name: which === "base" ? "Baseline" : "Draft", knowledge_cutoff: known, effective_date: eff, ...inp });
      return { which, r, inp };
    },
    onSuccess: ({ which, r, inp }) => {
      setResults((s) => (which === "base" ? { ...s, base: r } : { ...s, draft: r, draftInputs: inp }));
      qc.invalidateQueries({ queryKey: [ws, "scenarios"] });
    },
  });
  const stale = results.draft && results.draftInputs && JSON.stringify(results.draftInputs) !== JSON.stringify(d);
  const canRun = role === "planner";

  if (ov.data && !ov.data.dataset) return (
    <><PageHeader eyebrow="Scenario studio" title="Scenarios need a sales history" />
      <Empty title="This workspace has no sales dataset">Switch to UCI Research to compare forecast-driven scenarios.</Empty></>
  );

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Scenario studio" title="Compare a draft scenario against the baseline">
        Both run the same forecast, stock snapshot, supplier terms and optimiser. Only the inputs you change differ. Results are simulated.
      </PageHeader>
      {compute.error && <ErrorState error={compute.error} />}
      <div className="grid gap-6 xl:grid-cols-[minmax(0,4fr)_minmax(0,8fr)]">
        <Card className="space-y-5 p-5">
          <Eyebrow>Draft inputs</Eyebrow>
          {CONTROLS.map((c) => {
            const v = d[c.k];
            const shown = c.scale ? v / c.scale : v;
            return (
              <div key={c.k}>
                <div className="flex items-baseline justify-between gap-2">
                  <label htmlFor={c.k} className="text-sm font-medium">{c.label}</label>
                  <span className="num text-sm">{c.k === "budget_minor" ? money(v, currency) : num(shown, c.step < 1 ? 2 : 0)}</span>
                </div>
                <input id={c.k} type="range" min={c.min} max={c.max} step={c.step} value={v} className="mt-1 w-full accent-[var(--accent)]"
                  aria-describedby={`${c.k}-help`} onChange={(e) => setDraft({ ...d, [c.k]: Number(e.target.value) })} />
                <p id={`${c.k}-help`} className="flex flex-wrap items-center gap-2 text-xs text-muted">
                  {c.unit} · baseline {c.k === "budget_minor" ? money(baseline[c.k], currency) : baseline[c.k]} · range {c.k === "budget_minor" ? `${money(c.min, currency)}–${money(c.max, currency)}` : `${c.min}–${c.max}`} <Provenance kind="assumed" />
                </p>
              </div>
            );
          })}
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => compute.mutate("base")} busy={compute.isPending && compute.variables === "base"} disabled={!canRun}>Compute baseline</Button>
            <Button onClick={() => compute.mutate("draft")} busy={compute.isPending && compute.variables === "draft"} disabled={!canRun}>Compute draft</Button>
            <Button variant="ghost" onClick={() => setDraft(null)}>Reset inputs</Button>
          </div>
          {!canRun && <p className="text-xs text-muted">Only planners can compute scenarios. You can view saved scenarios below.</p>}
        </Card>
        <div className="space-y-6">
          {stale && (
            <div role="status" className="flex items-center gap-2 rounded-xl bg-risk-soft p-3 text-sm text-risk">
              <AlertTriangle className="size-4" aria-hidden /> Inputs changed after the draft was computed. The draft result below is stale until you compute it again.
            </div>
          )}
          <Compare base={results.base} draft={results.draft} currency={currency} stale={!!stale} />
          {results.draft && <Lines result={results.draft} currency={currency} />}
        </div>
      </div>
      <Card className="p-5">
        <Eyebrow>Saved scenario runs</Eyebrow>
        <table className="mt-3 w-full text-sm">
          <caption className="sr-only">Previously computed scenarios</caption>
          <thead><tr className="border-b border-line text-left text-xs text-muted">
            <th className="py-2 font-medium">Name</th><th className="font-medium">Computed</th><th className="font-medium">Status</th><th className="font-medium">Spend</th><th className="font-medium">Shortfall</th></tr></thead>
          <tbody>
            {(saved.data ?? []).slice(0, 12).map((s) => (
              <tr key={s.id} className="border-b border-line/60"><td className="py-2">{s.name}</td><td className="text-xs text-muted">{dateTime(s.created_at)}</td>
                <td><Status value={s.status} /></td><td className="num">{money(s.metrics?.spend_minor, currency)}</td><td className="num">{int(s.metrics?.shortfall_units)}</td></tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function Compare({ base, draft, currency, stale }: { base?: Result; draft?: Result; currency: string; stale: boolean }) {
  const rows: [string, (r: Result) => number | null, (n: number | null) => string][] = [
    ["Products needing an order", (r) => r.metrics.skus_needing_order, (n) => int(n)],
    ["Units ordered", (r) => r.metrics.units_ordered, (n) => int(n)],
    ["Spend", (r) => r.metrics.spend_minor, (n) => money(n, currency)],
    ["Shortfall (units not covered)", (r) => r.metrics.shortfall_units, (n) => int(n)],
    ["Projected q50 coverage", (r) => r.metrics.projected_q50_coverage, (n) => (n == null ? "—" : `${num(n * 100, 1)}%`)],
  ];
  const option = useMemo(() => {
    if (!base || !draft) return null;
    const b = baseOption();
    return { ...b, legend: { ...(b.legend as object), data: ["Baseline", "Draft"] },
      xAxis: { ...(b.xAxis as object), type: "category", data: ["Spend (k)", "Shortfall units (k)", "Units ordered (k)"] },
      yAxis: { ...(b.yAxis as object), type: "value" },
      series: [
        { type: "bar", name: "Baseline", itemStyle: { color: token("--muted") }, data: [base.metrics.spend_minor / 100_000, base.metrics.shortfall_units / 1000, base.metrics.units_ordered / 1000] },
        { type: "bar", name: "Draft", itemStyle: { color: token("--accent") }, data: [draft.metrics.spend_minor / 100_000, draft.metrics.shortfall_units / 1000, draft.metrics.units_ordered / 1000] },
      ] };
  }, [base, draft]);
  if (!base && !draft) return <Card className="p-5"><Empty title="Nothing computed yet">Compute the baseline, then a draft with changed inputs to compare them.</Empty></Card>;
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between"><Eyebrow>Baseline vs draft</Eyebrow><Provenance kind="simulated" /></div>
      <table className="mt-3 w-full text-sm">
        <caption className="sr-only">Scenario metrics compared</caption>
        <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Measure</th><th className="font-medium">Baseline</th><th className="font-medium">Draft</th><th className="font-medium">Change</th></tr></thead>
        <tbody>
          {rows.map(([label, get, fmt]) => {
            const bv = base ? get(base) : null, dv = draft ? get(draft) : null;
            return (
              <tr key={label} className="border-b border-line/60">
                <td className="py-2">{label}</td><td className="num">{base ? fmt(bv) : "—"}</td>
                <td className={`num ${stale ? "text-muted line-through" : ""}`}>{draft ? fmt(dv) : "—"}</td>
                <td className="num text-muted">{bv != null && dv != null ? (dv - bv >= 0 ? "+" : "") + fmt(dv - bv) : "—"}</td>
              </tr>
            );
          })}
          <tr><td className="py-2">Plan status</td><td>{base && <Status value={base.plan.status} />}</td><td>{draft && <Status value={draft.plan.status} />}</td><td /></tr>
        </tbody>
      </table>
      {option && <div className="mt-4"><Chart option={option} height={220} label="Bar chart comparing baseline and draft spend, shortfall and units ordered" /></div>}
      <p className="mt-2 text-xs text-muted">{(draft ?? base)!.metrics.metric_note} A lower simulated cost is not a realised saving.</p>
    </Card>
  );
}

function Lines({ result, currency }: { result: Result; currency: string }) {
  return (
    <Card className="p-5">
      <Eyebrow>Draft plan lines (not sent anywhere)</Eyebrow>
      {result.plan.explanation?.length ? <ul className="mt-2 list-disc pl-5 text-sm text-risk">{result.plan.explanation.map((e) => <li key={e}>{e}</li>)}</ul> : null}
      <div className="mt-3 max-h-80 overflow-auto" tabIndex={0} role="region" aria-label="Draft plan lines, scrollable">
        <table className="w-full text-sm">
          <caption className="sr-only">Proposed order lines for the draft scenario</caption>
          <thead className="sticky top-0 bg-surface"><tr className="border-b border-line text-left text-xs text-muted">
            <th className="py-2 font-medium">Product</th><th className="font-medium">Supplier</th><th className="font-medium">Qty</th><th className="font-medium">Line value</th><th className="font-medium">Arrives</th></tr></thead>
          <tbody>
            {result.plan.lines.map((l) => (
              <tr key={l.term_id} className="border-b border-line/60"><td className="py-1.5"><Mono>{l.sku_id}</Mono></td><td className="text-xs">{l.supplier_id}</td>
                <td className="num">{int(l.quantity)}</td><td className="num">{money(l.line_minor, currency)}</td><td className="num text-xs">{l.arrival_date}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

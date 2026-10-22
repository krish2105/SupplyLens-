"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { baseOption, Chart, token } from "@/components/chart";
import { useDecisionClock } from "@/components/clock-rail";
import { Button, Card, Empty, ErrorState, Eyebrow, Mono, PageHeader, Provenance, Status } from "@/components/ui";
import { EmptyState } from "@/components/illustration";
import { apiPost, intentKey } from "@/lib/api";
import type { Schemas } from "@/lib/contract";
import { useApi, useMe, useWs } from "@/lib/queries";
import { dateTime, int, money, num } from "@/lib/format";

type Basis = "leadtime_demand" | "q90_sum" | "q50_plus_safety";
type Inputs = { demand_multiplier: number; supplier_delay_days: number; budget_minor: number; safety_days: number;
  coverage_days: number; service_level: number; replenishment_basis: Basis };
type Result = Schemas["ScenarioResult"];
/** Decision-context fingerprint (audit S15): a result belongs to the workspace, clocks, dataset and basis it was computed in. */
type Fingerprint = { ws: string; known: string | null; eff: string | null; dataset: string | null; basis: Basis };
type Computed = { result: Result; inputs: Inputs; fp: Fingerprint };
const fpKey = (f: Fingerprint) => `${f.ws}|${f.known}|${f.eff}|${f.dataset}|${f.basis}`;

const BASES: { v: Basis; label: string; help: string }[] = [
  { v: "leadtime_demand", label: "Lead-time demand (default)", help: "Order up to a service-level quantile of demand over lead time + coverage." },
  { v: "q90_sum", label: "Summed daily q90", help: "Heuristic: every day at its 90th percentile. Over-covers (study L1)." },
  { v: "q50_plus_safety", label: "Median + safety days", help: "Median path plus a buffer of mean daily demand. Under-covers (study S1)." },
];

type NumKey = Exclude<keyof Inputs, "replenishment_basis">;
const CONTROLS: { k: NumKey; label: string; unit: string; min: number; max: number; step: number; scale?: number; only?: Basis }[] = [
  { k: "demand_multiplier", label: "Demand multiplier", unit: "× forecast", min: 0.5, max: 2, step: 0.05 },
  { k: "supplier_delay_days", label: "Supplier delay", unit: "days added to every lead time", min: 0, max: 30, step: 1 },
  { k: "budget_minor", label: "Purchasing budget", unit: "per run", min: 0, max: 10_000_000, step: 50_000, scale: 100 },
  { k: "service_level", label: "Service level", unit: "probability demand is covered", min: 0.5, max: 0.99, step: 0.01, only: "leadtime_demand" },
  { k: "safety_days", label: "Safety buffer", unit: "days of mean forecast demand", min: 0, max: 30, step: 1, only: "q50_plus_safety" },
  { k: "coverage_days", label: "Coverage window", unit: "days (forecast horizon is 28)", min: 7, max: 28, step: 1 },
];

function body(inp: Inputs) {
  // Only controls that apply to the basis are sent; the API rejects the others (audit F03).
  const { safety_days, service_level, ...rest } = inp;
  return { ...rest, ...(inp.replenishment_basis === "q50_plus_safety" ? { safety_days } : {}),
    ...(inp.replenishment_basis === "leadtime_demand" ? { service_level } : {}) };
}

export default function ScenariosPage() {
  const ws = useWs();
  const qc = useQueryClient();
  const me = useMe();
  const role = me.data?.memberships.find((m) => m.slug === ws)?.role;
  const { known, eff } = useDecisionClock();
  const ov = useApi(["overview"], "/api/v1/overview");
  const saved = useApi(["scenarios"], "/api/v1/scenarios");
  const planning = (ov.data?.settings?.planning ?? {}) as Record<string, number>;
  const currency = ov.data?.settings?.currency ?? "GBP";
  const baseline: Inputs = { demand_multiplier: 1, supplier_delay_days: 0, budget_minor: planning.weekly_budget_minor ?? 0,
    safety_days: planning.safety_days ?? 5, coverage_days: planning.coverage_days ?? 21, service_level: planning.service_level ?? 0.9,
    replenishment_basis: "leadtime_demand" };
  const [draft, setDraft] = useState<Inputs | null>(null);
  const d = draft ?? baseline;
  const [results, setResults] = useState<{ base?: Computed; draft?: Computed }>({});
  const fpNow = (basis: Basis): Fingerprint => ({ ws, known, eff, dataset: ov.data?.dataset?.id ?? null, basis });

  const compute = useMutation({
    mutationFn: async (which: "base" | "draft") => {
      const inp = which === "base" ? { ...baseline, replenishment_basis: d.replenishment_basis } : d;
      const fp = fpNow(inp.replenishment_basis);
      const req = { name: which === "base" ? "Baseline" : "Draft", knowledge_cutoff: known, effective_date: eff, ...body(inp) };
      const intent = intentKey("scenario", { fp, req });
      const r = await apiPost("/api/v1/scenarios", { body: req as never, idempotencyKey: intent.key });
      intent.settle();
      return { which, r, inp, fp };
    },
    onSuccess: ({ which, r, inp, fp }) => {
      // A response that arrives after the context changed is kept but marked incompatible, never shown as current.
      setResults((s) => ({ ...s, [which]: { result: r, inputs: inp, fp } }));
      qc.invalidateQueries({ queryKey: [ws, "scenarios"] });
    },
  });
  const current = fpKey(fpNow(d.replenishment_basis));
  const incompatible = (c?: Computed) => !!c && fpKey(c.fp) !== current;
  const stale = !!results.draft && !incompatible(results.draft) && JSON.stringify(results.draft.inputs) !== JSON.stringify(d);
  const comparable = results.base && results.draft && fpKey(results.base.fp) === fpKey(results.draft.fp);
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
          <fieldset>
            <legend className="text-sm font-medium">Replenishment basis</legend>
            <div className="mt-2 space-y-1.5">
              {BASES.map((b) => (
                <label key={b.v} className="flex cursor-pointer items-start gap-2 rounded-lg p-1.5 text-sm hover:bg-surface-2">
                  <input type="radio" name="basis" value={b.v} checked={d.replenishment_basis === b.v} className="mt-1 accent-[var(--accent)]"
                    onChange={() => setDraft({ ...d, replenishment_basis: b.v })} />
                  <span><span className="font-medium">{b.label}</span><span className="block text-xs text-muted">{b.help}</span></span>
                </label>
              ))}
            </div>
          </fieldset>
          {CONTROLS.map((c) => {
            const v = d[c.k];
            const shown = c.scale ? v / c.scale : v;
            const off = !!c.only && c.only !== d.replenishment_basis;
            const set = (n: number) => Number.isFinite(n) && setDraft({ ...d, [c.k]: Math.min(c.max, Math.max(c.min, n)) });
            return (
              <div key={c.k} data-applicable={!off}>
                <div className="flex items-baseline justify-between gap-2">
                  <label htmlFor={c.k} className="text-sm font-medium">{c.label}</label>
                  <span className="flex items-center gap-1">
                    <input aria-label={`${c.label} exact value${c.scale ? " in major units" : ""}`} type="number" disabled={off}
                      min={c.scale ? c.min / c.scale : c.min} max={c.scale ? c.max / c.scale : c.max} step={c.scale ? c.step / c.scale : c.step}
                      value={shown} onChange={(e) => set(Number(e.target.value) * (c.scale ?? 1))}
                      className="num w-24 rounded-md border border-line bg-surface px-2 py-0.5 text-right text-sm" />
                    {c.k === "budget_minor" && <span className="text-xs text-muted">{currency}</span>}
                  </span>
                </div>
                <input id={c.k} type="range" min={c.min} max={c.max} step={c.step} value={v} disabled={off} className="mt-1 w-full accent-[var(--accent)]"
                  aria-describedby={`${c.k}-help`} onChange={(e) => set(Number(e.target.value))} />
                <p id={`${c.k}-help`} className="flex flex-wrap items-center gap-2 text-xs text-muted">
                  {off ? <>Not applicable under {BASES.find((b) => b.v === d.replenishment_basis)?.label.toLowerCase()}: this control would not change the result.</>
                    : <>{c.unit} · baseline {c.k === "budget_minor" ? money(baseline[c.k], currency) : num(baseline[c.k], c.step < 1 ? 2 : 0)} · range {c.k === "budget_minor" ? `${money(c.min, currency)}–${money(c.max, currency)}` : `${c.min}–${c.max}`} <Provenance kind="assumed" /></>}
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
          {(incompatible(results.base) || incompatible(results.draft)) && (
            <div role="status" className="flex flex-wrap items-center gap-2 rounded-xl bg-risk-soft p-3 text-sm text-risk">
              <AlertTriangle className="size-4" aria-hidden /> The workspace, clocks, dataset or basis changed since a result was computed. It is hidden here; compute again in this context.
              <Button size="sm" variant="outline" onClick={() => setResults({})}>Clear old results</Button>
            </div>
          )}
          {results.base && results.draft && !comparable && !incompatible(results.base) && !incompatible(results.draft) && (
            <p role="status" className="text-sm text-risk">Baseline and draft were computed under different bases; compute the baseline again to compare.</p>
          )}
          <Compare base={incompatible(results.base) ? undefined : results.base?.result}
            draft={incompatible(results.draft) ? undefined : results.draft?.result} currency={currency} stale={stale} />
          {results.draft && !incompatible(results.draft) && <Lines result={results.draft.result} currency={currency} />}
        </div>
      </div>
      <Card className="p-5">
        <Eyebrow>Saved scenario runs</Eyebrow>
        {saved.data && saved.data.length === 0 && (
          <div className="mt-3"><EmptyState variant="first_run" art="empty-scenarios" title="Compare your first planning scenario">
            Compute a baseline and a draft above; every computed scenario is saved here with its inputs.</EmptyState></div>
        )}
        {saved.error && <div className="mt-3"><ErrorState error={saved.error} retry={() => saved.refetch()} /></div>}
        {!!saved.data?.length && <table className="mt-3 w-full text-sm">
          <caption className="sr-only">Previously computed scenarios</caption>
          <thead><tr className="border-b border-line text-left text-xs text-muted">
            <th className="py-2 font-medium">Name</th><th className="font-medium">Computed</th><th className="font-medium">Status</th><th className="font-medium">Spend</th><th className="font-medium">Shortfall</th></tr></thead>
          <tbody>
            {(saved.data ?? []).slice(0, 12).map((s) => (
              <tr key={s.id} className="border-b border-line/60"><td className="py-2">{s.name}</td><td className="text-xs text-muted">{dateTime(s.created_at)}</td>
                <td><Status value={s.status} /></td><td className="num">{money(s.metrics?.spend_minor, currency)}</td><td className="num">{int(s.metrics?.shortfall_units)}</td></tr>
            ))}
          </tbody>
        </table>}
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
      <Controls r={(draft ?? base)!} />
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


/** What the server says it applied: basis, which controls changed the result, capacity caps and SKUs left out. */
function Controls({ r }: { r: Result }) {
  const notAssessed = Object.entries((r.scope?.not_assessed ?? {}) as Record<string, string>);
  return (
    <div className="mt-3 space-y-1 text-xs text-muted">
      <p>Basis: <span className="font-medium text-ink">{r.controls?.replenishment_basis ?? r.inputs.replenishment_basis}</span>
        {Object.entries(r.controls ?? {}).filter(([k]) => k !== "replenishment_basis").map(([k, v]) => <span key={k}> · {k.replaceAll("_", " ")}: {v}</span>)}</p>
      {!!r.metrics.capacity_capped_units && <p className="text-risk">Storage capacity capped {int(r.metrics.capacity_capped_units)} units of demand-driven need; that demand stays unserved.</p>}
      {notAssessed.length > 0 && (
        <details><summary className="cursor-pointer">{notAssessed.length} product(s) not assessed</summary>
          <ul className="mt-1 list-disc pl-5">{notAssessed.slice(0, 20).map(([k, why]) => <li key={k}><Mono>{k}</Mono>: {why}</li>)}</ul></details>
      )}
    </div>
  );
}

"use client";
import type { UseQueryResult } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo } from "react";
import { baseOption, Chart, token, useChartTheme } from "@/components/chart";
import { Card, Eyebrow, Mono, PageHeader, Provenance, QueryError, Skeleton, Status, TableScroll } from "@/components/ui";
import { EmptyState } from "@/components/illustration";
import { useApi, useWs } from "@/lib/queries";
import { int, num } from "@/lib/format";

// Study results are JSON documents whose shape differs per study; the cards read named fields from them.
type Any = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any -- untyped study JSON (see the comment above)
const pct = (v: number | null | undefined, d = 1) => (v == null ? "—" : `${num(v * 100, d)}%`);

function useStudy(id: string) {
  const f1 = useApi(["study", id], id === "F1" ? "/api/v1/research/forecast-study" : null);
  const other = useApi(["study", id], id !== "F1" ? "/api/v1/research/{study}" : null, { path: { study: id.toLowerCase() } });
  // Study metrics are open-ended documents produced by the evaluation scripts; the page reads them as such.
  return (id === "F1" ? f1 : other) as unknown as UseQueryResult<Any>;
}

function bars(categories: string[], series: { name: string; data: number[]; color: string }[], yName: string) {
  const b = baseOption();
  return { ...b, grid: { ...(b.grid as object), top: 52 },  // legend and axis name on separate rows at phone width
    xAxis: { ...(b.xAxis as object), type: "category", data: categories, axisLabel: { ...(b.xAxis as { axisLabel: object }).axisLabel, interval: 0 } },  // label every group, even at phone width
    yAxis: { ...(b.yAxis as object), type: "value", name: yName },
    series: series.map((s) => ({ type: "bar", name: s.name, data: s.data, itemStyle: { color: s.color }, barMaxWidth: 28 })) };
}

/** The headline is the reviewed one from evaluations/study_registry.json, never a string fixed in this page (audit S16).
 *  `fallback` is shown only as the question's topic when no reviewed headline exists. */
function StudyCard({ id, title: fallback, question, children, q, week }: { id: string; title: string; question: string; children: React.ReactNode; q: { isLoading: boolean; data?: Any; error: unknown; refetch: () => unknown }; week?: string }) {
  const review = q.data?.review as { status: string; headline?: string | null; notes?: string | null; superseded?: { experiment_id: string; reason?: string }[] } | undefined;
  return (
    <Card className="min-w-0 p-5">{/* a grid item: without min-w-0 a wide table stretches the card past a phone screen */}
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div><Eyebrow>Study {id}{week && <span className="font-normal"> · course week {week}</span>}</Eyebrow>
          <h2 className="display mt-1 text-xl font-semibold">{review?.headline ?? (q.data?.available ? `${fallback} — headline not yet reviewed` : fallback)}</h2>
          <p className="mt-1 text-sm text-muted">{question}</p></div>
        <div className="flex flex-col items-end gap-1">
          {review && <Status value={review.status.toUpperCase()} />}
          {q.data?.experiment_id && <Mono className="text-muted">{q.data.experiment_id}</Mono>}
        </div>
      </div>
      {review?.notes && <p className="mt-2 text-xs text-muted">{review.notes}</p>}
      <div className="mt-4">{q.isLoading ? <Skeleton className="h-40" /> : q.error ? <QueryError q={q} what="this study" /> : q.data?.available === false ? <EmptyState variant="first_run" art="empty-research" title="No experiment recorded for this study" compact>{q.data?.message}</EmptyState> : children}</div>
      {!!review?.superseded?.length && (
        <details className="mt-3 text-xs text-muted"><summary className="cursor-pointer">{review.superseded.length} superseded run(s) not shown</summary>
          <ul className="mt-1 list-disc pl-5">{review.superseded.map((x) => <li key={x.experiment_id}><Mono>{x.experiment_id}</Mono>: {x.reason}</li>)}</ul></details>
      )}
    </Card>
  );
}

/** A plain results table: first column is the row name, the rest are right-aligned numbers. */
function MetricTable({ label, caption, cols, rows, min, className }: { label: string; caption: string; cols: string[]; rows: React.ReactNode[][]; min: number; className?: string }) {
  return (
    <TableScroll label={label} min={min} className={className}><table className="w-full text-sm"><caption className="sr-only">{caption}</caption>
      <thead><tr className="border-b border-line text-left text-xs text-muted">{cols.map((c, i) => <th key={c} className={i ? "pr-4 text-right font-medium last:pr-0" : "py-2 pr-4 font-medium"}>{c}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i} className="border-b border-line/60">{r.map((v, j) => <td key={j} className={j ? "num pr-4 text-right last:pr-0" : "py-1.5 pr-4"}>{v}</td>)}</tr>)}</tbody>
    </table></TableScroll>
  );
}

const SECTIONS: [string, string][] = [
  ["forecast-studies", "Forecasting and supplier documents"], ["operations-studies", "Operations trade-offs"],
  ["warehouse-studies", "Running the warehouse"], ["transport-studies", "Moving goods"], ["documents-studies", "Documents and answers"],
];
const gbp = (v: number | null | undefined) => (v == null ? "—" : `£${int(Math.round(v))}`);

export default function ResearchPage() {
  const ws = useWs();
  const f1 = useStudy("F1"), s2 = useStudy("S2"), r3 = useStudy("R3"), r1 = useStudy("R1"), r2 = useStudy("R2"), c1 = useStudy("C1"), ib = useStudy("IB"), agt = useStudy("AGT");
  const e1 = useStudy("E1"), fa1 = useStudy("FA1"), g1 = useStudy("G1"), w1 = useStudy("W1"), d1s = useStudy("D1");
  const js1 = useStudy("JS1"), pm1 = useStudy("PM1"), qc1 = useStudy("QC1");
  const fe1 = useStudy("FE1"), w2 = useStudy("W2"), b1 = useStudy("B1"), et1 = useStudy("ET1"), rt1 = useStudy("RT1");
  const x1 = useStudy("X1"), as1 = useStudy("AS1"), red1 = useStudy("RED1");

  const chartTheme = useChartTheme();     // chart colours follow the theme (audit S17)
  const f1Opt = useMemo(() => {
    const d = f1.data;
    if (!d?.summary) return null;
    const fams = ["seasonal_naive", "lightgbm", "tcn"];
    return bars(["MAE", "Pinball (mean)", "MASE ×10"], [
      { name: "Seasonal naive", color: token("--muted"), data: [d.summary.seasonal_naive.mae, d.summary.seasonal_naive.pinball_mean, d.summary.seasonal_naive.mase * 10] },
      { name: "LightGBM", color: token("--accent"), data: [d.summary.lightgbm.mae, d.summary.lightgbm.pinball_mean, d.summary.lightgbm.mase * 10] },
      { name: "TCN", color: token("--forecast"), data: [d.summary.tcn.mae, d.summary.tcn.pinball_mean, d.summary.tcn.mase * 10] },
    ].filter((_, i) => fams[i]), "lower is better");
  }, [f1.data, chartTheme]); // eslint-disable-line react-hooks/exhaustive-deps -- recolour when the theme changes (token() reads CSS variables)

  const s2Opt = useMemo(() => {
    const d = s2.data;
    if (!d?.results) return null;
    const keys = ["product_seasonal_naive", "product_lightgbm", "product_tcn", "simple_base_stock"];
    return bars(["Naive", "LightGBM", "TCN", "Base\nstock"], [
      { name: "No budget limit", color: token("--accent"), data: keys.map((k) => Math.round(d.results.unconstrained[k].total_cost)) },
      { name: "Workspace budget", color: token("--muted"), data: keys.map((k) => Math.round(d.results.workspace_scaled[k].total_cost)) },
    ], "£, 28 days");
  }, [s2.data, chartTheme]); // eslint-disable-line react-hooks/exhaustive-deps -- recolour when the theme changes (token() reads CSS variables)

  const e1Opt = useMemo(() => {
    const d = e1.data;
    if (!d?.exact?.points) return null;
    const req = d.scope.required_units as number;
    const b = baseOption();
    const front = (d.nsga2.per_seed[0]?.front ?? []) as [number, number][];
    return { ...b, grid: { left: 56, right: 20, top: 40, bottom: 76 }, legend: { bottom: 0, textStyle: { color: token("--muted") } },
      tooltip: { trigger: "item", backgroundColor: token("--surface"), borderColor: token("--line"), textStyle: { color: token("--ink") } },
      xAxis: { ...(b.xAxis as object), type: "value", name: "kg CO₂e", nameLocation: "middle", nameGap: 26 },
      yAxis: { ...(b.yAxis as object), type: "value", name: "required units covered", min: 0, max: 1, nameLocation: "middle", nameGap: 40,
        axisLabel: { color: token("--muted"), formatter: (v: number) => `${Math.round(v * 100)}%` } },
      series: [
        { type: "scatter", name: "NSGA-II front (seed 1)", symbolSize: 5, data: front.map(([sh, g]) => [g / 1000, 1 - sh / req]), itemStyle: { color: token("--muted") } },
        { type: "line", name: "Exact (CP-SAT, epsilon-constraint)", data: (d.exact.points as Any[]).map((p) => [p.co2_grams / 1000, 1 - p.shortfall_units / req]),
          lineStyle: { color: token("--accent") }, itemStyle: { color: token("--accent") } },
      ] };
  }, [e1.data, chartTheme]); // eslint-disable-line react-hooks/exhaustive-deps -- recolour when the theme changes (token() reads CSS variables)

  const fa1Opt = useMemo(() => {
    const d = fa1.data;
    if (!d?.baseline?.groups) return null;
    const groups = Object.keys(d.baseline.groups).filter((g) => d.baseline.groups[g].required >= 50);
    const rec = d.recommended?.groups ?? {};
    return bars(groups, [
      { name: "No reweighing", color: token("--muted"), data: groups.map((g) => d.baseline.groups[g].coverage) },
      ...(d.recommended ? [{ name: `Reweighed (alpha ${d.recommended.alpha})`, color: token("--accent"), data: groups.map((g) => rec[g]) }] : []),
      { name: "Full reweighing (alpha 1)", color: token("--risk"), data: groups.map((g) => d.reweighed.groups[g].coverage) },
    ], "coverage");
  }, [fa1.data, chartTheme]); // eslint-disable-line react-hooks/exhaustive-deps -- recolour when the theme changes (token() reads CSS variables)

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Research" title="Measured results, including the ones that didn't go our way">
        Every number here is read from an experiment artifact under <Mono>artifacts/experiments/</Mono>. Simulated outcomes are labelled as such. Nothing is typed in by hand.
      </PageHeader>
      <nav aria-label="On this page" className="flex flex-wrap gap-2 text-sm">
        {SECTIONS.map(([id, label]) => <a key={id} href={`#${id}`} className="inline-flex min-h-9 items-center rounded-full border border-line bg-surface px-3 text-muted hover:text-ink">{label}</a>)}
      </nav>

      <section aria-labelledby="forecast-studies" className="space-y-6">
      <h2 id="forecast-studies" className="display pt-2 text-2xl font-semibold">Forecasting, decisions and supplier documents</h2>
      <StudyCard id="F1" q={f1} week="3" title="Forecasting study"
        question="Do LightGBM and a compact quantile TCN improve 28-day daily unit-sales forecasts on UCI Online Retail II?">
        {f1.data?.summary && (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,4fr)]">
            {f1Opt && <Chart option={f1Opt} height={240} label="Bar chart comparing MAE, pinball and MASE across three models" />}
            <ul className="space-y-2 text-sm">
              <li>{f1.data.cohort_size} products; test origins {(f1.data.test_origins ?? [f1.data.test_origin]).join(", ")}; selection frozen on validation; chart shows the last origin.</li>
              {(["tcn_seed0_vs_seasonal_naive", "tcn_seed0_vs_lightgbm", "lightgbm_vs_seasonal_naive"] as const).map((k) => {
                const c = f1.data!.comparisons[k];
                const clear = c.ci95[0] > 0 || c.ci95[1] < 0;
                return <li key={k}>{k.replace("_seed0", "").replaceAll("_", " ").replace(" vs ", " − ")} MAE per product: <b className="num">{num(c.mean_diff, 2)}</b> (95% CI {num(c.ci95[0], 2)} to {num(c.ci95[1], 2)}; first better on {pct(c.share_a_better, 0)} of products) — {clear ? "difference detected" : "no clear difference detected"}.</li>;
              })}
              <li>80% interval coverage (last origin): naive {pct(f1.data.summary.seasonal_naive.coverage_80)}, LightGBM {pct(f1.data.summary.lightgbm.coverage_80)}, TCN {pct(f1.data.summary.tcn.coverage_80)}.</li>
              <li><Link className="text-accent hover:underline" href={{ pathname: "/forecast", query: { ws } }}>Full table in the Forecast lab</Link></li>
            </ul>
          </div>
        )}
      </StudyCard>

      <StudyCard id="S2" q={s2} week="4" title="Decision study"
        question="Fed through the product's own ordering logic (lead-time demand, MOQ, packs, lead times, budget, open orders), does a more accurate forecaster lower simulated cost?">
        {s2.data?.results && (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,4fr)]">
            {s2Opt && <Chart option={s2Opt} height={240} label="Simulated cost by policy, with and without a budget limit" />}
            <ul className="space-y-2 text-sm">
              <li><Provenance kind="simulated" /> {s2.data.products} products, weekly reviews {s2.data.reviews[0]} → {s2.data.window_end}; terms and costs simulated, demand = recorded sales.</li>
              <li>Forecast error over the review windows (MAE): naive {num(s2.data.context_forecast_mae.seasonal_naive, 1)}, LightGBM {num(s2.data.context_forecast_mae.lightgbm, 1)}, TCN {num(s2.data.context_forecast_mae.tcn, 1)}.</li>
              <li>No budget limit, fill rate: naive {pct(s2.data.results.unconstrained.product_seasonal_naive.fill_rate)}, LightGBM {pct(s2.data.results.unconstrained.product_lightgbm.fill_rate)}, TCN {pct(s2.data.results.unconstrained.product_tcn.fill_rate)}, base stock {pct(s2.data.results.unconstrained.simple_base_stock.fill_rate)}.</li>
              <li>Exploratory: one 28-day window already seen by earlier studies. Replaces S1 (superseded: it used the weekday-blind TCN and its own ordering formula).</li>
            </ul>
          </div>
        )}
      </StudyCard>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <StudyCard id="R2" q={r2} week="8" title="Time-aware retrieval study"
          question="On supplier-terms questions, does explicit effective-date and supersession handling change which version is cited?">
          {r2.data?.conditions && (
            <TableScroll label="R2 conditions" min={480}><table className="w-full text-sm"><caption className="sr-only">R2 conditions</caption>
              <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Condition</th><th className="font-medium">Top-1 correct</th><th className="font-medium">Wrong version</th><th className="font-medium">Abstain on unknown</th></tr></thead>
              <tbody>{Object.entries(r2.data.conditions as Record<string, Any>).map(([k, v]) => (
                <tr key={k} className="border-b border-line/60"><td className="py-2"><Mono>{k}</Mono></td><td className="num">{pct(v.top1_citation_accuracy)}</td>
                  <td className="num">{pct(v.wrong_version_top1_rate)}</td><td className="num">{pct(v.abstention_accuracy_unknown, 0)}</td></tr>))}</tbody>
              <tfoot><tr><td colSpan={4} className="pt-2 text-xs text-muted">{r2.data.questions} questions generated from simulated agreements (not human-reviewed). Cross-tenant probes: {r2.data.cross_tenant_probes.leaked_chunks} leaked chunks in {r2.data.cross_tenant_probes.queries} queries.</td></tr></tfoot>
            </table></TableScroll>
          )}
        </StudyCard>
        <StudyCard id="R3" q={r3} week="8" title="Answer support study"
          question="When should supplier-document search offer one passage as the answer, decline, or say several suppliers match?">
          {r3.data?.results && (
            <TableScroll label="R3 test half" min={480}><table className="w-full text-sm"><caption className="sr-only">R3 test half</caption>
              <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Question type</th><th className="font-medium">Before</th><th className="font-medium">Hybrid search</th><th className="font-medium">Lexical only</th></tr></thead>
              <tbody>{Object.entries(r3.data.results.test.baseline_hybrid.categories as Record<string, Any>).map(([k, v]) => (
                <tr key={k} className="border-b border-line/60"><td className="py-2"><Mono>{k}</Mono></td><td className="num">{v.correct}/{v.n}</td>
                  <td className="num">{r3.data!.results.test.chosen_hybrid.categories[k].correct}/{v.n}</td>
                  <td className="num">{r3.data!.results.test.chosen_lexical_only.categories[k].correct}/{v.n}</td></tr>))}</tbody>
              <tfoot><tr><td colSpan={4} className="pt-2 text-xs text-muted">{r3.data.tasks} generated questions, labels by construction (not human-reviewed); thresholds chosen on the other half.</td></tr></tfoot>
            </table></TableScroll>
          )}
        </StudyCard>
        <StudyCard id="C1" q={c1} week="8" title="Clause localisation study"
          question="Within 73 real CUAD supply/distribution contracts, does a top-k chunk overlap the clause an expert labelled?">
          {c1.data?.conditions && (
            <TableScroll label="C1 conditions" min={480}><table className="w-full text-sm"><caption className="sr-only">C1 conditions</caption>
              <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Retrieval</th><th className="font-medium">Hit@1</th><th className="font-medium">Hit@3</th><th className="font-medium">Hit@5</th></tr></thead>
              <tbody>{Object.entries(c1.data.conditions as Record<string, Any>).map(([k, v]) => (
                <tr key={k} className="border-b border-line/60"><td className="py-2"><Mono>{k}</Mono></td><td className="num">{pct(v["hit@1"])}</td><td className="num">{pct(v["hit@3"])}</td><td className="num">{pct(v["hit@5"])}</td></tr>))}</tbody>
              <tfoot><tr><td colSpan={4} className="pt-2 text-xs text-muted">{c1.data.conditions.hybrid_rrf.items} contract × category items; public data, CC BY 4.0.</td></tr></tfoot>
            </table></TableScroll>
          )}
        </StudyCard>
        <StudyCard id="R1" q={r1} week="8" title="ACORD retrieval study"
          question="Across 56 expert-graded ACORD test queries, how do keyword, vector and hybrid retrieval rank 3,931 clauses?">
          {r1.data?.conditions && (
            <TableScroll label="R1 conditions" min={480}><table className="w-full text-sm"><caption className="sr-only">R1 conditions</caption>
              <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Retrieval</th><th className="font-medium">nDCG@10</th><th className="font-medium">Recall@10</th><th className="font-medium">MRR@10</th><th className="font-medium">p95 ms</th></tr></thead>
              <tbody>{Object.entries(r1.data.conditions as Record<string, Any>).map(([k, v]) => (
                <tr key={k} className="border-b border-line/60"><td className="py-2"><Mono>{k}</Mono></td><td className="num">{num(v["ndcg@10"], 3)}</td><td className="num">{num(v["recall@10_rel>=2_capped"], 3)}</td><td className="num">{num(v["mrr@10"], 3)}</td><td className="num">{num(v.latency_ms_p95, 0)}</td></tr>))}</tbody>
              <tfoot><tr><td colSpan={5} className="pt-2 text-xs text-muted">Keyword = PostgreSQL full-text ranking (not BM25). Short category queries favour semantic matching.</td></tr></tfoot>
            </table></TableScroll>
          )}
        </StudyCard>
        <StudyCard id="IB" q={ib} week="4" title="InventoryBench study"
          question="Scored by the benchmark's own evaluator on its 600 real-trajectory instances (pinned commit; the 720 synthetic ones were not scored), normalised reward vs perfect foresight.">
          {ib.data?.policies && (
            <TableScroll label="InventoryBench scores" min={360}><table className="w-full text-sm"><caption className="sr-only">InventoryBench scores</caption>
              <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Policy</th><th className="font-medium">Mean normalised reward</th></tr></thead>
              <tbody>{Object.entries(ib.data.policies as Record<string, Any>).map(([k, v]) => (
                <tr key={k} className="border-b border-line/60"><td className="py-2"><Mono>{k}</Mono></td><td className="num">{num(v.overall_score, 3)}</td></tr>))}</tbody>
              <tfoot><tr><td colSpan={2} className="pt-2 text-xs text-muted">No LLM in any policy. Real trajectories derive from H&amp;M data; upstream terms not cleared for redistribution.</td></tr></tfoot>
            </table></TableScroll>
          )}
        </StudyCard>
      </div>

      <StudyCard id="AGT" q={agt} week="11" title="Investigator study"
        question="Across reference-case dates and budgets, denials, stale approvals, timeouts and crash recovery, does the run end in the oracle's state?">
        {agt.data?.summary && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
            <div><Eyebrow>Scenarios × trials</Eyebrow><p className="num text-2xl font-semibold">{agt.data.summary.scenarios} × {agt.data.summary.trials_per_scenario}</p></div>
            <div><Eyebrow>Verified completion</Eyebrow><p className="num text-2xl font-semibold">{pct(agt.data.summary.verified_completion_rate, 0)}</p></div>
            <div><Eyebrow>Unapproved writes</Eyebrow><p className="num text-2xl font-semibold">{agt.data.summary.unauthorized_external_mutations}</p></div>
            <div><Eyebrow>Median run</Eyebrow><p className="num text-2xl font-semibold">{num(agt.data.summary.run_ms_p50, 0)} ms</p><p className="text-xs text-muted">{num(agt.data.summary.tool_calls_mean, 1)} tool calls · 0 LLM tokens</p></div>
          </div>
        )}
      </StudyCard>

      </section>

      <section aria-labelledby="operations-studies" className="space-y-6">
        <h2 id="operations-studies" className="display pt-4 text-2xl font-semibold">Operations studies: trade-offs, fairness, generated answers and weather</h2>
        <StudyCard id="E1" q={e1} week="2" title="Cost, service and CO₂"
          question="What does cutting the plan's CO₂ cost in service and spend, and does an evolutionary search find the same trade-off as the exact solver?">
          {e1.data?.exact && (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,4fr)]">
              {e1Opt && <Chart option={e1Opt} height={260} label="Share of required units covered against kg CO2e for the exact front and NSGA-II" />}
              <ul className="space-y-2 text-sm">
                <li><Provenance kind="assumed" /> CO₂ lane factors and unit weight; <Provenance kind="simulated" /> stock, terms and budget. {e1.data.scope.skus} products, budget {num(e1.data.scope.budget_minor / 100, 0)} {e1.data.scope.currency}.</li>
                <li>Exact front: {e1.data.exact.points.length} caps in {num(e1.data.exact.seconds, 1)} s. NSGA-II: {e1.data.nsga2.method}, {num(e1.data.nsga2.seconds_total, 1)} s in total.</li>
                <li>NSGA-II reaches {(e1.data.nsga2.per_seed as Any[]).map((x) => pct(x.hypervolume_ratio)).join(", ")} of the exact hypervolume; {(e1.data.nsga2.per_seed as Any[]).map((x) => `${x.dominated_by_exact} of ${x.front_points}`).join(", ")} of its front points are dominated by exact points.</li>
              </ul>
            </div>
          )}
        </StudyCard>
        <StudyCard id="FA1" q={fa1} week="10" title="Fair allocation across countries"
          question="When the budget binds, are customers in every country group served equally, and what does reweighing change?">
          {fa1.data?.baseline && (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,4fr)]">
              {fa1Opt && <Chart option={fa1Opt} height={260} label="Coverage by country group without, with moderate and with full reweighing" />}
              <ul className="space-y-2 text-sm">
                <li><Provenance kind="simulated" /> plan; country shares are recorded sales ({fa1.data.scope.share_window}).</li>
                <li>Gap between best- and worst-served group: {num(fa1.data.baseline.summary.gap_points, 1)} points before{d1(fa1.data)}; worst-to-best ratio {num(fa1.data.baseline.summary.worst_to_best_ratio, 2)} before.</li>
                {fa1.data.recommended && <li>Recommended weighting: alpha {fa1.data.recommended.alpha} — ratio {num(fa1.data.recommended.summary.worst_to_best_ratio, 2)}, costing {num(fa1.data.recommended.coverage_cost_points, 1)} points of total coverage.</li>}
                <li>Full reweighing over-corrects: total coverage {pct(fa1.data.reweighed.overall_coverage)} against {pct(fa1.data.baseline.overall_coverage)}.</li>
              </ul>
            </div>
          )}
        </StudyCard>
        <StudyCard id="B1" q={b1} week="10" title="Bias mitigation for a failure classifier"
          question="Do re-weighting, SMOTE, threshold moving and adversarial debiasing lower cost and narrow the recall gap between machine types?">
          {b1.data?.methods && (
            <>
              <MetricTable label="Bias mitigation methods" caption="Logistic failure model on the AI4I 2020 test split, by method" min={560}
                cols={["Method (logistic regression)", "Recall", "Cost (assumed)", "Recall gap", "False-alarm gap"]}
                rows={[
                  ...([["none", "No correction"], ["class_weights", "Class weights (re-weighting)"], ["group_class_weights", "Group-and-class weights"], ["smote", "SMOTE (training rows only)"], ["threshold_moving", "Threshold moved on validation"]] as const).map(([k, name]) => {
                    const v = b1.data!.methods.logistic_regression[k]; return [name, pct(v.recall, 0), gbp(v.cost_gbp), num(v.recall_gap, 2), num(v.fpr_gap, 2)]; }),
                  [`Adversarial debiasing (mean of ${b1.data.adversarial.seeds.length} seeds)`, pct(b1.data.adversarial.mean.recall, 0), gbp(b1.data.adversarial.mean.cost_gbp), `${num(b1.data.adversarial.mean.recall_gap, 2)} ± ${num(b1.data.adversarial.sd.recall_gap, 2)}`, num(b1.data.adversarial.mean.fpr_gap, 2)],
                ]} />
              <p className="mt-2 text-sm"><Provenance kind="assumed" /> costs as in PM1. {int(b1.data.data.test_failures)} test failures: Type L {b1.data.data.groups.L.failures}, M {b1.data.data.groups.M.failures}, H {b1.data.data.groups.H.failures} — with so few H failures, one failure moves that group&apos;s recall a lot.</p>
              <p className="mt-1 text-xs text-muted">Type is a product-quality variant in a published synthetic dataset, not a protected human attribute: the methods are what is shown. Adversarial strength {b1.data.adversarial.alpha_chosen} chosen on validation; with the adversary off the same network gives recall gap {num(b1.data.adversarial.off_mean.recall_gap, 2)} at {gbp(b1.data.adversarial.off_mean.cost_gbp)}.</p>
            </>
          )}
        </StudyCard>
        <StudyCard id="G1" q={g1} week="11" title="Generated answers"
          question="Are generated answers correct and cited, and is nothing generated where no passage answers?">
          {g1.data?.categories && (
            <>
              <TableScroll label="Generated answers by question type" min={560}><table className="w-full text-sm"><caption className="sr-only">Generated answers by question type</caption>
                <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 pr-4 font-medium">Question type</th><th className="pr-4 text-right font-medium">Tasks</th>
                  <th className="pr-4 text-right font-medium">Answered</th><th className="pr-4 text-right font-medium">Figures correct</th><th className="text-right font-medium">Citation correct</th></tr></thead>
                <tbody>{Object.entries(g1.data.categories as Record<string, Any>).map(([k, v]) => (
                  <tr key={k} className="border-b border-line/60"><td className="py-1.5 pr-4">{k.replaceAll("_", " ")}</td><td className="num pr-4 text-right">{v.n}</td>
                    <td className="num pr-4 text-right">{pct(v.answered_rate)}</td><td className="num pr-4 text-right">{v.facts_correct.n ? pct(v.facts_correct.rate) : "—"}</td>
                    <td className="num text-right">{v.citation_correct.n ? pct(v.citation_correct.rate) : "—"}</td></tr>))}</tbody>
              </table></TableScroll>
              <p className="mt-2 text-sm">Model {g1.data.model}; generated where no passage answers: {g1.data.overall.must_abstain_wrongly_answered} of {g1.data.overall.must_abstain_tasks}; median latency {num(g1.data.latency_seconds.p50, 1)} s.</p>
            </>
          )}
        </StudyCard>
        <StudyCard id="W1" q={w1} week="3" title="Forecast metrics and weather"
          question="How do Prophet and XGBoost compare on MAE, RMSE, WAPE and MAPE, and does London weather improve the forecasts?">
          {w1.data?.results && (
            <>
              {(["total", "skus"] as const).map((lvl) => (
                <TableScroll key={lvl} label={`Forecast metrics, ${lvl === "total" ? "total daily units" : "top products"}`} min={560} className="mb-3">
                  <table className="w-full text-sm"><caption className="text-left text-xs text-muted">{lvl === "total" ? "Total daily units" : `Top ${w1.data!.data.top_products} products, pooled`}</caption>
                    <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 pr-4 font-medium">Model</th><th className="pr-4 text-right font-medium">MAE</th>
                      <th className="pr-4 text-right font-medium">RMSE</th><th className="pr-4 text-right font-medium">WAPE</th><th className="text-right font-medium">MAPE (non-zero days)</th></tr></thead>
                    <tbody>{Object.entries(w1.data!.results[lvl].models as Record<string, Any>).map(([m, v]) => (
                      <tr key={m} className="border-b border-line/60"><td className="py-1.5 pr-4">{m.replaceAll("_", " ")}</td><td className="num pr-4 text-right">{num(v.mae, 1)}</td>
                        <td className="num pr-4 text-right">{num(v.rmse, 1)}</td><td className="num pr-4 text-right">{pct(v.wape)}</td><td className="num text-right">{pct(v.mape_nonzero_days)}</td></tr>))}</tbody>
                  </table></TableScroll>
              ))}
              <ul className="space-y-1 text-sm">{(["total", "skus"] as const).flatMap((lvl) => Object.entries(w1.data!.results[lvl].weather_effect as Record<string, Any>).map(([m, e]) => (
                <li key={lvl + m}>{m} with weather, {lvl === "total" ? "total" : "products"}: MAE change {num(e.mean_abs_error_change, 2)} (95% CI {num(e.ci95[0], 2)} to {num(e.ci95[1], 2)}) — {e.clear ? "difference detected" : "no clear difference"}.</li>)))}</ul>
              <p className="mt-2 text-xs text-muted">Weather on the target day is the observed value, so any gain is an upper bound (a perfect weather forecast). Weather data: Open-Meteo, CC BY 4.0.</p>
            </>
          )}
        </StudyCard>
        <StudyCard id="W2" q={w2} week="3" title="Forecasting with an LSTM"
          question="Does a small LSTM forecast total daily units better than XGBoost, Prophet and seasonal naive on W1's protocol?">
          {w2.data?.results && (
            <>
              <MetricTable label="LSTM against W1's models" caption="Total daily units, 13 weekly origins, 7 days ahead" min={520}
                cols={["Model", "WAPE", "MAPE (non-zero days)", "RMSE"]}
                rows={[
                  [`LSTM (mean ± sd, ${w2.data.protocol.seeds.length} seeds)`, `${num(w2.data.results.lstm.wape.mean, 3)} ± ${num(w2.data.results.lstm.wape.sd, 3)}`, num(w2.data.results.lstm.mape_nonzero_days.mean, 3), int(w2.data.results.lstm.rmse.mean)],
                  ...(["xgboost", "prophet"] as const).map((m) => [`${m === "xgboost" ? "XGBoost" : "Prophet"} (${w2.data!.results.from_w1[m].label})`, num(w2.data!.results.from_w1[m].wape, 3), num(w2.data!.results.from_w1[m].mape_nonzero_days, 3), int(w2.data!.results.from_w1[m].rmse)]),
                  ["Seasonal naive (re-run here)", num(w2.data.results.seasonal_naive_reproduced.wape, 3), num(w2.data.results.seasonal_naive_reproduced.mape_nonzero_days, 3), int(w2.data.results.seasonal_naive_reproduced.rmse)],
                ]} />
              <p className="mt-2 text-xs text-muted">Seasonal naive {w2.data.results.seasonal_naive_reproduced.check.match ? "matches W1's recorded values exactly" : "differs from W1's recorded values"}, so the series is the same. LSTM against seasonal naive: MAE change {num(w2.data.results.lstm_vs_seasonal_naive.mean_abs_error_change, 0)} (95% interval {num(w2.data.results.lstm_vs_seasonal_naive.ci95[0], 0)} to {num(w2.data.results.lstm_vs_seasonal_naive.ci95[1], 0)}) — {w2.data.results.lstm_vs_seasonal_naive.clear ? "a clear difference" : "no clear difference"}. No weather input.</p>
            </>
          )}
        </StudyCard>
        <StudyCard id="D1" q={d1s} week="2" title="Supplier delay risk"
          question="Can a model trained on past orders flag late deliveries ahead of time? (a method check on a simulated order history)">
          {d1s.data?.models && (
            <>
              <TableScroll label="Delay risk models" min={520}><table className="w-full text-sm"><caption className="sr-only">Delay risk models on the held-out half-year</caption>
                <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 pr-4 font-medium">Model</th><th className="pr-4 text-right font-medium">AUC</th>
                  <th className="pr-4 text-right font-medium">Brier</th><th className="text-right font-medium">Late share in top 10 % (× base rate)</th></tr></thead>
                <tbody>{Object.entries(d1s.data.models as Record<string, Any>).map(([m, v]) => (
                  <tr key={m} className="border-b border-line/60"><td className="py-1.5 pr-4">{m.replaceAll("_", " ")}</td><td className="num pr-4 text-right">{num(v.auc, 2)}</td>
                    <td className="num pr-4 text-right">{num(v.brier, 3)}</td><td className="num text-right">{pct(v.late_share_in_top_decile)} ({num(v.lift_top_decile, 2)}×)</td></tr>))}</tbody>
              </table></TableScroll>
              <p className="mt-2 text-sm"><Provenance kind="simulated" /> {d1s.data.data.orders_train.toLocaleString("en-GB")} training and {d1s.data.data.orders_test.toLocaleString("en-GB")} test orders, generated from a stated process; the models can only recover effects that were put in.</p>
            </>
          )}
        </StudyCard>
      </section>

      <section aria-labelledby="warehouse-studies" className="space-y-6">
        <h2 id="warehouse-studies" className="display pt-4 text-2xl font-semibold">Running the warehouse: scheduling, maintenance and inspection</h2>
        <StudyCard id="JS1" q={js1} week="5" title="Scheduling the receiving floor"
          question="How much shorter is an optimal receiving-floor schedule (job shop: dock, quality, label, put-away) than the dispatch rules a floor lead would use?">
          {js1.data?.summary && (
            <>
              <p className="text-sm"><Provenance kind="assumed" /> routes, handling minutes and due slots; real UCI order volumes. Check: classic ft06 solved to its known optimum {js1.data.check_ft06.known_optimum} (CP-SAT {js1.data.check_ft06.cp_sat}, {js1.data.check_ft06.status.toLowerCase()}).</p>
              <TableScroll label="Dispatch rules against CP-SAT" min={480} className="mt-3"><table className="w-full text-sm"><caption className="sr-only">Average extra length of each dispatch rule&apos;s schedule over CP-SAT</caption>
                <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 pr-4 font-medium">Rule</th><th className="pr-4 text-right font-medium">Makespan vs CP-SAT</th><th className="text-right font-medium">Total tardiness vs CP-SAT</th></tr></thead>
                <tbody>{Object.keys(js1.data.summary.makespan_gap_vs_cp_sat as Record<string, number>).map((r) => (
                  <tr key={r} className="border-b border-line/60"><td className="py-1.5 pr-4">{r}</td><td className="num pr-4 text-right">+{pct(js1.data!.summary.makespan_gap_vs_cp_sat[r])}</td>
                    <td className="num text-right">+{pct(js1.data!.summary.tardiness_gap_vs_cp_sat[r])}</td></tr>))}</tbody>
              </table></TableScroll>
              <p className="mt-2 text-xs text-muted">{js1.data.summary.cp_sat_proven_optimal_makespan} of {js1.data.summary.instances} makespans proved optimal within {js1.data.setup.time_limit_s} s.</p>
            </>
          )}
        </StudyCard>
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <StudyCard id="PM1" q={pm1} week="2, 6" title="Predictive maintenance"
            question="Can failures and remaining life be predicted early enough to replace run-to-failure and fixed-interval maintenance?">
            {pm1.data?.ai4i_2020 && (
              <>
                <p className="text-sm">UCI AI4I 2020 ({int(pm1.data.ai4i_2020.rows)} cycles, {int(pm1.data.ai4i_2020.failures)} failures), cost of the test split under each policy:</p>
                <ul className="mt-2 space-y-1 text-sm">
                  <li>Run to failure: <span className="num">£{int(pm1.data.ai4i_2020.run_to_failure_cost_gbp)}</span></li>
                  {Object.entries(pm1.data.ai4i_2020.models as Record<string, Any>).map(([m, v]) => (
                    <li key={m}>{m.replaceAll("_", " ")} (AUC {num(v.auc, 2)}): <span className="num">£{int(v.policy_on_test.cost_gbp)}</span>, {v.policy_on_test.failures_caught} of {v.policy_on_test.failures_caught + v.policy_on_test.failures_missed} failures caught with {v.policy_on_test.alerts} inspections</li>))}
                </ul>
                <p className="mt-3 text-sm"><Provenance kind="simulated" /> motor fleet, remaining-life models: RMSE ridge {num(pm1.data.fleet_rul.accuracy.ridge_window_stats.rmse_all_windows, 1)}, 1D-CNN {num(pm1.data.fleet_rul.accuracy.cnn.rmse_all_windows, 1)} cycles. Replace when predicted life &lt; 20 cycles: <span className="num">£{int(pm1.data.fleet_rul.policies.cnn_rul_below_20.cost_gbp)}</span> and {pm1.data.fleet_rul.policies.cnn_rul_below_20.failures} failures, against <span className="num">£{int(pm1.data.fleet_rul.policies.fixed_interval_p5.cost_gbp)}</span> and {pm1.data.fleet_rul.policies.fixed_interval_p5.failures} for fixed intervals.</p>
              </>
            )}
          </StudyCard>
          <StudyCard id="QC1" q={qc1} week="6, 9" title="Visual inspection at goods-in"
            question="Can a small CNN flag surface defects well enough to replace inspecting every item by hand? (generated images)">
            {qc1.data?.models && (
              <>
                <TableScroll label="Defect models" min={420}><table className="w-full text-sm"><caption className="sr-only">Defect detection on held-out generated images</caption>
                  <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 pr-4 font-medium">Model</th><th className="pr-4 text-right font-medium">AUC</th>
                    <th className="pr-4 text-right font-medium">Recall</th><th className="text-right font-medium">Inspection cost</th></tr></thead>
                  <tbody>{Object.entries(qc1.data.models as Record<string, Any>).map(([m, v]) => (
                    <tr key={m} className="border-b border-line/60"><td className="py-1.5 pr-4">{m === "cnn" ? "CNN" : "hand-made features"}</td><td className="num pr-4 text-right">{num(v.auc, 3)}</td>
                      <td className="num pr-4 text-right">{pct(v.policy.recall)}</td><td className="num text-right">£{num(v.policy.cost_gbp, 0)}</td></tr>))}</tbody>
                </table></TableScroll>
                <p className="mt-2 text-sm"><Provenance kind="simulated" /> {int(qc1.data.data.test)} test images. Inspecting every item by hand: <span className="num">£{num(qc1.data.inspect_everything_cost_gbp, 0)}</span>.</p>
              </>
            )}
          </StudyCard>
        </div>
      </section>

      <section aria-labelledby="transport-studies" className="space-y-6">
        <h2 id="transport-studies" className="display pt-4 text-2xl font-semibold">Moving goods: fuel, arrival times and routes</h2>
        <p className="text-sm text-muted">These three studies run on generated data: real fleet and last-mile datasets need the owner&apos;s approval first. They show the methods and their failure modes, not results for a real fleet.</p>
        <StudyCard id="FE1" q={fe1} week="2" title="Fuel-inefficient trips"
          question="Can trip telemetry flag fuel-inefficient trips, and predict litres per 100 km, better than a fleet-average rule?">
          {fe1.data?.models && (
            <>
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <MetricTable label="Litres per 100 km" caption="Error of litres-per-100-km predictions in the test months" min={360}
                  cols={["Model", "MAE (L/100 km)", "RMSE"]}
                  rows={([["class_mean", "Class average"], ["ridge", "Ridge regression"], ["lightgbm", "LightGBM"]] as const).map(([k, name]) => [name, num(fe1.data!.models.regression_test[k].mae_l_per_100km, 2), num(fe1.data!.models.regression_test[k].rmse_l_per_100km, 2)])} />
                <MetricTable label="Flagging inefficient trips" caption="Flagging trips above 1.15 times their reference consumption" min={420}
                  cols={["Flagger", "AUC", "F1", "Excess fuel captured"]}
                  rows={([["fleet_average_rule", "Fleet-average rule"], ["logistic_regression", "Logistic regression"], ["lightgbm", "LightGBM"]] as const).map(([k, name]) => [name, num(fe1.data!.models.classification_test[k].auc, 3), num(fe1.data!.models.classification_test[k].f1, 2), pct(fe1.data!.models.classification_test[k].excess_fuel_captured_share, 0)])} />
              </div>
              <p className="mt-2 text-sm"><Provenance kind="simulated" /> {int(fe1.data.data.trips)} trips, {fe1.data.data.vehicles} vehicles, {fe1.data.data.drivers} drivers over {fe1.data.data.months} months. <Provenance kind="assumed" /> 2.5 kg CO₂ per litre: the test months&apos; excess fuel ({int(fe1.data.data.test_excess.excess_litres)} L) is {int(fe1.data.data.test_excess.excess_co2_kg_assumed_factor)} kg CO₂.</p>
              <p className="mt-1 text-xs text-muted">The rule sees each trip&apos;s measured fuel, and long heavy trips carry most of the excess litres, so it captures more of them even though the models rank trips better.</p>
            </>
          )}
        </StudyCard>
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <StudyCard id="ET1" q={et1} week="7" title="Delivery arrival times"
            question="How close can a model get to the real delivery time, and how honest are its intervals for couriers it has not seen?">
            {et1.data?.results && (
              <>
                <MetricTable label="Arrival-time models" caption="Arrival-time error in the test months, mean over seeds" min={440}
                  cols={["Model", "MAE (min)", "Within 30 min", "MAE, new couriers"]}
                  rows={([["baseline_region_hour_mean", "Region × hour average"], ["lightgbm", "LightGBM"], ["reference_generator_expected_time", "Generator's expected time (floor)"]] as const).map(([k, name]) => {
                    const v = et1.data!.results.summary_over_seeds[k]; return [name, num(v.all.mae_min.mean, 1), pct(v.all.acc_at_30.mean, 0), num(v.new_couriers.mae_min.mean, 1)]; })} />
                <p className="mt-2 text-sm"><Provenance kind="simulated" /> 80% interval (quantile LightGBM): covers {pct(et1.data.results.summary_over_seeds.quantile_lightgbm.all.coverage.mean, 0)} overall, {pct(et1.data.results.summary_over_seeds.quantile_lightgbm.existing_couriers.coverage.mean, 0)} for known couriers and {pct(et1.data.results.summary_over_seeds.quantile_lightgbm.new_couriers.coverage.mean, 0)} for new ones; mean width {num(et1.data.results.summary_over_seeds.quantile_lightgbm.all.mean_width_min.mean, 0)} min.</p>
              </>
            )}
          </StudyCard>
          <StudyCard id="RT1" q={rt1} week="7" title="Last-mile routes"
            question="With van capacity and delivery windows, how much shorter and more punctual is an OR-Tools plan than simple heuristics?">
            {rt1.data?.results && (
              <>
                <MetricTable label="Route plans by day size" caption="Mean distance and vans per delivery day, by number of stops" min={480}
                  cols={["Stops", "OR-Tools km", "Nearest neighbour km", "Fixed order km", "Vans (OR-Tools / NN)"]}
                  rows={Object.entries(rt1.data.results.summary.by_size as Record<string, Any>).map(([n, v]) => [n, num(v.or_tools.distance_km, 0), num(v.nearest_neighbour.distance_km, 0), num(v.fixed_order.distance_km, 0), `${num(v.or_tools.vans, 0)} / ${num(v.nearest_neighbour.vans, 1)}`])} />
                <p className="mt-2 text-sm"><Provenance kind="simulated" /> Late stops over {rt1.data.results.summary.instances} days: OR-Tools {rt1.data.results.summary.or_tools_late_stops_total}, nearest neighbour {rt1.data.results.summary.nearest_neighbour_late_stops_total}, nearest neighbour ignoring windows {rt1.data.results.summary.nearest_neighbour_ignoring_windows_late_stops_total}, fixed order {rt1.data.results.summary.fixed_order_late_stops_total}.</p>
                <p className="mt-1 text-xs text-muted">Straight-line distances; the fixed order stands in for a habitual sequence. Fuel and CO₂ use assumed factors, so compare plans rather than absolute figures.</p>
              </>
            )}
          </StudyCard>
        </div>
      </section>

      <section aria-labelledby="documents-studies" className="space-y-6">
        <h2 id="documents-studies" className="display pt-4 text-2xl font-semibold">Documents and answers: extraction, the status assistant and the red team</h2>
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <StudyCard id="X1" q={x1} week="8" title="Reading contract terms"
            question="How many of the clauses and fields CUAD's experts labelled does a rule extractor find, against picking the top BM25 paragraphs?">
            {x1.data?.overall && (
              <>
                <MetricTable label="Extraction methods" caption="Match with CUAD expert labels in 73 supply contracts (micro averages)" min={440}
                  cols={["Method", "Overlap F1", "Precision", "Exact-span F1"]}
                  rows={([["rules", "Rules (this product)"], ["lexical_top1", "Top BM25 paragraph"], ["lexical_top3", "Top three BM25 paragraphs"]] as const).map(([k, name]) => {
                    const v = x1.data!.overall[k]; return [name, num(v.overlap.micro.f1, 2), num(v.overlap.micro.precision, 2), num(v.exact.micro.f1, 2)]; })} />
                <p className="mt-2 text-sm">Human-labelled: {int(x1.data.data.labels_in_scored_categories)} expert labels in {x1.data.data.contracts} contracts. On {int(x1.data.held_out_check.contracts)} other CUAD contracts the rules score overlap F1 {num(x1.data.held_out_check.overall.rules.overlap.micro.f1, 2)}.</p>
                <p className="mt-1 text-xs text-muted">The rules were written after reading these contracts&apos; labels, so the held-out figure is the fairer one. Results appear as a draft in Policies › Extracted terms and are never used for planning.</p>
              </>
            )}
          </StudyCard>
          <StudyCard id="AS1" q={as1} week="8" title="The status assistant"
            question="Does the read-only assistant answer stock, order and terms questions from cited records, ask which product when several match, and withhold change requests?">
            {as1.data?.categories && (
              <>
                <MetricTable label="Assistant by question type" caption="Questions answered, chosen or withheld correctly, by type" min={360}
                  cols={["Question type", "Questions", "Handled correctly"]}
                  rows={Object.entries(as1.data.categories as Record<string, Any>).map(([k, v]) => [k.replaceAll("_", " ").replace("mutation", "change request"), v.n, pct(v.correct_rate, 0)])} />
                <p className="mt-2 text-sm">{as1.data.overall.sentences} sentences, {as1.data.overall.sentences_without_citation} without a citation; {as1.data.overall.answered_wrongly} wrong answers. Open it from the header: <i>Ask about an order or stock</i>.</p>
                <p className="mt-1 text-xs text-muted">Questions generated from the synthetic test fixture, so this is an upper bound for real wording; nothing is generated by a model.</p>
              </>
            )}
          </StudyCard>
        </div>
        <StudyCard id="RED1" q={red1} week="11" title="Red team on generated answers"
          question="Do adversarial questions and poisoned documents make the answer layer state planted figures, leak its instructions or other workspaces' records, claim actions, or break its limits?">
          {red1.data?.held_by && (
            <>
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <div><Eyebrow>Attacks held</Eyebrow><p className="num text-2xl font-semibold">{red1.data.held} of {red1.data.cases}</p></div>
                <div><Eyebrow>Nothing generated</Eyebrow><p className="num text-2xl font-semibold">{red1.data.held_by["extractive layer (nothing generated)"] ?? 0}</p></div>
                <div><Eyebrow>Withheld by checks</Eyebrow><p className="num text-2xl font-semibold">{red1.data.held_by["generation checks (withheld)"] ?? 0}</p></div>
                <div><Eyebrow>Controls answered</Eyebrow><p className="num text-2xl font-semibold">{red1.data.controls.answered_correctly} of {red1.data.controls.n}</p></div>
              </div>
              <p className="mt-3 text-sm">{red1.data.by_kind.poison.n} of the attacks are agreements poisoned through the upload endpoint; the model is {red1.data.model}, run locally. Defences: {red1.data.defences}.</p>
              <p className="mt-1 text-xs text-muted">Generation is off on the public demo, so these answers exist only where a local model runs.</p>
            </>
          )}
        </StudyCard>
      </section>
    </div>
  );
}

function d1(d: Any) {
  return d.recommended ? `, ${num(d.recommended.summary.gap_points, 1)} after moderate reweighing` : "";
}

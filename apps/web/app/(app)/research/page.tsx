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
function StudyCard({ id, title: fallback, question, children, q }: { id: string; title: string; question: string; children: React.ReactNode; q: { isLoading: boolean; data?: Any; error: unknown; refetch: () => unknown } }) {
  const review = q.data?.review as { status: string; headline?: string | null; notes?: string | null; superseded?: { experiment_id: string; reason?: string }[] } | undefined;
  return (
    <Card className="min-w-0 p-5">{/* a grid item: without min-w-0 a wide table stretches the card past a phone screen */}
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div><Eyebrow>Study {id}</Eyebrow>
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

export default function ResearchPage() {
  const ws = useWs();
  const f1 = useStudy("F1"), s2 = useStudy("S2"), r3 = useStudy("R3"), r1 = useStudy("R1"), r2 = useStudy("R2"), c1 = useStudy("C1"), ib = useStudy("IB"), agt = useStudy("AGT");
  const e1 = useStudy("E1"), fa1 = useStudy("FA1"), g1 = useStudy("G1"), w1 = useStudy("W1"), d1s = useStudy("D1");
  const js1 = useStudy("JS1"), pm1 = useStudy("PM1"), qc1 = useStudy("QC1");

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

      <StudyCard id="F1" q={f1} title="Forecasting study"
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

      <StudyCard id="S2" q={s2} title="Decision study"
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
        <StudyCard id="R2" q={r2} title="Time-aware retrieval study"
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
        <StudyCard id="R3" q={r3} title="Answer support study"
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
        <StudyCard id="C1" q={c1} title="Clause localisation study"
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
        <StudyCard id="R1" q={r1} title="ACORD retrieval study"
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
        <StudyCard id="IB" q={ib} title="InventoryBench study"
          question="Scored by the benchmark's own evaluator on all 1,320 instances (pinned commit), normalised reward vs perfect foresight.">
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

      <StudyCard id="AGT" q={agt} title="Investigator study"
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

      <section aria-labelledby="operations-studies" className="space-y-6">
        <h2 id="operations-studies" className="display pt-4 text-2xl font-semibold">Operations studies: trade-offs, fairness, generated answers and weather</h2>
        <StudyCard id="E1" q={e1} title="Cost, service and CO₂"
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
        <StudyCard id="FA1" q={fa1} title="Fair allocation across countries"
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
        <StudyCard id="G1" q={g1} title="Generated answers"
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
        <StudyCard id="W1" q={w1} title="Forecast metrics and weather"
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
        <StudyCard id="D1" q={d1s} title="Supplier delay risk"
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
        <StudyCard id="JS1" q={js1} title="Scheduling the receiving floor"
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
          <StudyCard id="PM1" q={pm1} title="Predictive maintenance"
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
          <StudyCard id="QC1" q={qc1} title="Visual inspection at goods-in"
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
    </div>
  );
}

function d1(d: Any) {
  return d.recommended ? `, ${num(d.recommended.summary.gap_points, 1)} after moderate reweighing` : "";
}

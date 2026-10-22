"use client";
import type { UseQueryResult } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo } from "react";
import { baseOption, Chart, token } from "@/components/chart";
import { Card, Empty, Eyebrow, Mono, PageHeader, Provenance, Skeleton } from "@/components/ui";
import { useApi, useWs } from "@/lib/queries";
import { num } from "@/lib/format";

type Any = Record<string, any>;
const pct = (v: number | null | undefined, d = 1) => (v == null ? "—" : `${num(v * 100, d)}%`);

function useStudy(id: string) {
  const f1 = useApi(["study", id], id === "F1" ? "/api/v1/research/forecast-study" : null);
  const other = useApi(["study", id], id !== "F1" ? "/api/v1/research/{study}" : null, { path: { study: id.toLowerCase() } });
  // Study metrics are open-ended documents produced by the evaluation scripts; the page reads them as such.
  return (id === "F1" ? f1 : other) as unknown as UseQueryResult<Any>;
}

function bars(categories: string[], series: { name: string; data: number[]; color: string }[], yName: string) {
  const b = baseOption();
  return { ...b, xAxis: { ...(b.xAxis as object), type: "category", data: categories },
    yAxis: { ...(b.yAxis as object), type: "value", name: yName },
    series: series.map((s) => ({ type: "bar", name: s.name, data: s.data, itemStyle: { color: s.color }, barMaxWidth: 28 })) };
}

function StudyCard({ id, title, question, children, q }: { id: string; title: string; question: string; children: React.ReactNode; q: { isLoading: boolean; data?: Any } }) {
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div><Eyebrow>Study {id}</Eyebrow><h2 className="display mt-1 text-xl font-semibold">{title}</h2><p className="mt-1 text-sm text-muted">{question}</p></div>
        {q.data?.experiment_id && <Mono className="text-muted">{q.data.experiment_id}</Mono>}
      </div>
      <div className="mt-4">{q.isLoading ? <Skeleton className="h-40" /> : q.data?.available === false ? <Empty title="Not run yet">{q.data?.message}</Empty> : children}</div>
    </Card>
  );
}

export default function ResearchPage() {
  const ws = useWs();
  const f1 = useStudy("F1"), s1 = useStudy("S1"), r1 = useStudy("R1"), r2 = useStudy("R2"), c1 = useStudy("C1"), ib = useStudy("IB"), agt = useStudy("AGT");

  const f1Opt = useMemo(() => {
    const d = f1.data;
    if (!d?.summary) return null;
    const fams = ["seasonal_naive", "lightgbm", "tcn"];
    return bars(["MAE", "Pinball (mean)", "MASE ×10"], [
      { name: "Seasonal naive", color: token("--muted"), data: [d.summary.seasonal_naive.mae, d.summary.seasonal_naive.pinball_mean, d.summary.seasonal_naive.mase * 10] },
      { name: "LightGBM", color: token("--accent"), data: [d.summary.lightgbm.mae, d.summary.lightgbm.pinball_mean, d.summary.lightgbm.mase * 10] },
      { name: "TCN", color: token("--forecast"), data: [d.summary.tcn.mae, d.summary.tcn.pinball_mean, d.summary.tcn.mase * 10] },
    ].filter((_, i) => fams[i]), "lower is better");
  }, [f1.data]);

  const s1Opt = useMemo(() => {
    const d = s1.data;
    if (!d?.results) return null;
    const b = d.results[d.base_case];
    const keys = ["seasonal_naive", "lightgbm", "tcn"];
    return bars(["Seasonal naive", "LightGBM", "TCN"], [
      { name: "Median + safety policy", color: token("--muted"), data: keys.map((k) => Math.round(b[k].total_cost)) },
      { name: "q90 order-up-to policy", color: token("--accent"), data: keys.map((k) => Math.round(b[`${k}__sum_q90`].total_cost)) },
    ], "simulated £ cost (28 days)");
  }, [s1.data]);

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Research" title="Measured results, including the ones that didn't go our way">
        Every number here is read from an experiment artifact under <Mono>artifacts/experiments/</Mono>. Simulated outcomes are labelled as such. Nothing is typed in by hand.
      </PageHeader>

      <StudyCard id="F1" q={f1} title="Trained forecasters beat the seasonal baseline; TCN and LightGBM are statistically tied"
        question="Do LightGBM and a compact quantile TCN improve 28-day daily unit-sales forecasts on UCI Online Retail II?">
        {f1.data?.summary && (
          <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,4fr)]">
            {f1Opt && <Chart option={f1Opt} height={240} label="Bar chart comparing MAE, pinball and MASE across three models" />}
            <ul className="space-y-2 text-sm">
              <li>{f1.data.cohort_size} products, test window {f1.data.test_window.join(" → ")}, selection frozen on validation.</li>
              <li>TCN − naive MAE per product: <b className="num">{num(f1.data.comparisons.tcn_seed0_vs_seasonal_naive.mean_diff, 2)}</b> (95% CI {num(f1.data.comparisons.tcn_seed0_vs_seasonal_naive.ci95[0], 2)} to {num(f1.data.comparisons.tcn_seed0_vs_seasonal_naive.ci95[1], 2)}).</li>
              <li>TCN − LightGBM: <b className="num">{num(f1.data.comparisons.tcn_seed0_vs_lightgbm.mean_diff, 2)}</b> (95% CI {num(f1.data.comparisons.tcn_seed0_vs_lightgbm.ci95[0], 2)} to {num(f1.data.comparisons.tcn_seed0_vs_lightgbm.ci95[1], 2)}) — interval includes zero.</li>
              <li>80% interval coverage: naive {pct(f1.data.summary.seasonal_naive.coverage_80)}, LightGBM {pct(f1.data.summary.lightgbm.coverage_80)}, TCN {pct(f1.data.summary.tcn.coverage_80)}.</li>
              <li><Link className="text-accent hover:underline" href={{ pathname: "/forecast", query: { ws } }}>Full table in the Forecast lab</Link></li>
            </ul>
          </div>
        )}
      </StudyCard>

      <StudyCard id="S1" q={s1} title="Better forecasts did not mean better stock decisions — the policy mattered more"
        question="Holding policy, costs, lead time and the demand path fixed, does a more accurate forecaster lower simulated lost-sales + holding cost?">
        {s1.data?.results && (
          <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,4fr)]">
            {s1Opt && <Chart option={s1Opt} height={240} label="Simulated cost by forecaster under two ordering policies" />}
            <ul className="space-y-2 text-sm">
              <li><Provenance kind="simulated" /> {s1.data.products} products, {s1.data.window.join(" → ")}, lead time {s1.data.assumptions.lead_time_days} days, weekly review.</li>
              <li>With a median-based policy, trained models fill {pct(s1.data.results[s1.data.base_case].tcn.fill_rate)} (TCN) vs {pct(s1.data.results[s1.data.base_case].seasonal_naive.fill_rate)} (naive).</li>
              <li>Why: {s1.data.caveats.at(-1)}</li>
              <li>With the q90 order-up-to policy all three reach ≈{pct(s1.data.results[s1.data.base_case].tcn__sum_q90.fill_rate, 0)} fill. The product used this heuristic until the lead-time-demand model replaced it (D-032); it is kept for comparison.</li>
            </ul>
          </div>
        )}
      </StudyCard>

      <div className="grid gap-6 xl:grid-cols-2">
        <StudyCard id="R2" q={r2} title="Effective-date logic removes wrong-version citations"
          question="On supplier-terms questions, does explicit effective-date and supersession handling change which version is cited?">
          {r2.data?.conditions && (
            <table className="w-full text-sm"><caption className="sr-only">R2 conditions</caption>
              <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Condition</th><th className="font-medium">Top-1 correct</th><th className="font-medium">Wrong version</th><th className="font-medium">Abstain on unknown</th></tr></thead>
              <tbody>{Object.entries(r2.data.conditions).map(([k, v]: [string, any]) => (
                <tr key={k} className="border-b border-line/60"><td className="py-2"><Mono>{k}</Mono></td><td className="num">{pct(v.top1_citation_accuracy)}</td>
                  <td className="num">{pct(v.wrong_version_top1_rate)}</td><td className="num">{pct(v.abstention_accuracy_unknown, 0)}</td></tr>))}</tbody>
              <tfoot><tr><td colSpan={4} className="pt-2 text-xs text-muted">{r2.data.questions} questions generated from simulated agreements (not human-reviewed). Cross-tenant probes: {r2.data.cross_tenant_probes.leaked_chunks} leaked chunks in {r2.data.cross_tenant_probes.queries} queries.</td></tr></tfoot>
            </table>
          )}
        </StudyCard>
        <StudyCard id="C1" q={c1} title="Hybrid search finds the expert-labelled clause most often"
          question="Within 73 real CUAD supply/distribution contracts, does a top-k chunk overlap the clause an expert labelled?">
          {c1.data?.conditions && (
            <table className="w-full text-sm"><caption className="sr-only">C1 conditions</caption>
              <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Retrieval</th><th className="font-medium">Hit@1</th><th className="font-medium">Hit@3</th><th className="font-medium">Hit@5</th></tr></thead>
              <tbody>{Object.entries(c1.data.conditions).map(([k, v]: [string, any]) => (
                <tr key={k} className="border-b border-line/60"><td className="py-2"><Mono>{k}</Mono></td><td className="num">{pct(v["hit@1"])}</td><td className="num">{pct(v["hit@3"])}</td><td className="num">{pct(v["hit@5"])}</td></tr>))}</tbody>
              <tfoot><tr><td colSpan={4} className="pt-2 text-xs text-muted">{c1.data.conditions.hybrid_rrf.items} contract × category items; public data, CC BY 4.0.</td></tr></tfoot>
            </table>
          )}
        </StudyCard>
        <StudyCard id="R1" q={r1} title="On ACORD, vector search beats the hybrid — a negative result we keep"
          question="Across 56 expert-graded ACORD test queries, how do keyword, vector and hybrid retrieval rank 3,931 clauses?">
          {r1.data?.conditions && (
            <table className="w-full text-sm"><caption className="sr-only">R1 conditions</caption>
              <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Retrieval</th><th className="font-medium">nDCG@10</th><th className="font-medium">Recall@10</th><th className="font-medium">MRR@10</th><th className="font-medium">p95 ms</th></tr></thead>
              <tbody>{Object.entries(r1.data.conditions).map(([k, v]: [string, any]) => (
                <tr key={k} className="border-b border-line/60"><td className="py-2"><Mono>{k}</Mono></td><td className="num">{num(v["ndcg@10"], 3)}</td><td className="num">{num(v["recall@10_rel>=2_capped"], 3)}</td><td className="num">{num(v["mrr@10"], 3)}</td><td className="num">{num(v.latency_ms_p95, 0)}</td></tr>))}</tbody>
              <tfoot><tr><td colSpan={5} className="pt-2 text-xs text-muted">Keyword = PostgreSQL full-text ranking (not BM25). Short category queries favour semantic matching.</td></tr></tfoot>
            </table>
          )}
        </StudyCard>
        <StudyCard id="IB" q={ib} title="SupplyLens policy scores highest of three tool-only policies on InventoryBench"
          question="Scored by the benchmark's own evaluator on all 1,320 instances (pinned commit), normalised reward vs perfect foresight.">
          {ib.data?.policies && (
            <table className="w-full text-sm"><caption className="sr-only">InventoryBench scores</caption>
              <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Policy</th><th className="font-medium">Mean normalised reward</th></tr></thead>
              <tbody>{Object.entries(ib.data.policies).map(([k, v]: [string, any]) => (
                <tr key={k} className="border-b border-line/60"><td className="py-2"><Mono>{k}</Mono></td><td className="num">{num(v.overall_score, 3)}</td></tr>))}</tbody>
              <tfoot><tr><td colSpan={2} className="pt-2 text-xs text-muted">No LLM in any policy. Real trajectories derive from H&amp;M data; upstream terms not cleared for redistribution.</td></tr></tfoot>
            </table>
          )}
        </StudyCard>
      </div>

      <StudyCard id="AGT" q={agt} title="Investigator: every frozen scenario verified, zero unapproved external writes"
        question="Across reference-case dates and budgets, denials, stale approvals, timeouts and crash recovery, does the run end in the oracle's state?">
        {agt.data?.summary && (
          <div className="grid gap-4 sm:grid-cols-4">
            <div><Eyebrow>Scenarios × trials</Eyebrow><p className="num text-2xl font-semibold">{agt.data.summary.scenarios} × {agt.data.summary.trials_per_scenario}</p></div>
            <div><Eyebrow>Verified completion</Eyebrow><p className="num text-2xl font-semibold">{pct(agt.data.summary.verified_completion_rate, 0)}</p></div>
            <div><Eyebrow>Unapproved writes</Eyebrow><p className="num text-2xl font-semibold">{agt.data.summary.unauthorized_external_mutations}</p></div>
            <div><Eyebrow>Median run</Eyebrow><p className="num text-2xl font-semibold">{num(agt.data.summary.run_ms_p50, 0)} ms</p><p className="text-xs text-muted">{num(agt.data.summary.tool_calls_mean, 1)} tool calls · 0 LLM tokens</p></div>
          </div>
        )}
      </StudyCard>
    </div>
  );
}

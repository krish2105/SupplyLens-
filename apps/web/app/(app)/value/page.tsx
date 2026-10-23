"use client";
import { useMemo, useState } from "react";
import { baseOption, Chart, token, useChartTheme } from "@/components/chart";
import { Card, Empty, ErrorState, Eyebrow, Loading, Mono, PageHeader, Provenance, TableScroll } from "@/components/ui";
import { useApi } from "@/lib/queries";
import { money, num } from "@/lib/format";


const CASES: Record<string, string> = { L3_h25: "Base: 3-day lead, 25% holding", L1_h25: "1-day lead", L7_h25: "7-day lead", L3_h15: "15% holding", L3_h40: "40% holding" };

export default function ValuePage() {
  const v = useApi(["value"], "/api/v1/value");
  const [model, setModel] = useState("tcn");
  const chartTheme = useChartTheme();     // chart colours follow the theme (audit S17)
  const opt = useMemo(() => {
    if (!v.data?.sensitivity) return null;
    const b = baseOption();
    const cases = Object.keys(v.data.sensitivity);
    return { ...b, xAxis: { ...(b.xAxis as object), type: "category", data: cases.map((c) => CASES[c] ?? c) },
      yAxis: { ...(b.yAxis as object), type: "value", name: "simulated £ (28 days)" },
      series: [
        { type: "bar", name: "Median + safety policy", data: cases.map((c) => Math.round(v.data!.sensitivity![c]![model]!.total_cost)), itemStyle: { color: token("--muted") } },
        { type: "bar", name: "q90 order-up-to policy", data: cases.map((c) => Math.round(v.data!.sensitivity![c]![`${model}__sum_q90`]!.total_cost)), itemStyle: { color: token("--accent") } },
        { type: "line", name: "Perfect-foresight reference", data: cases.map((c) => Math.round(v.data!.sensitivity![c]!.perfect_foresight_reference!.total_cost)), lineStyle: { color: token("--risk"), type: "dashed" }, itemStyle: { color: token("--risk") } },
      ] };
  }, [v.data, model, chartTheme]); // eslint-disable-line react-hooks/exhaustive-deps -- recolour when the theme changes (token() reads CSS variables)
  if (v.isLoading) return <Loading />;
  if (v.error) return <ErrorState error={v.error} />;
  const d = v.data!;
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Value" title="A value ledger that keeps simulated and realised money apart">{d.disclaimer}</PageHeader>
      {!d.ledger.length ? <Empty title="No simulation study yet">Run evaluations/simulation_study.py.</Empty> : (
        <Card className="p-5">
          <Eyebrow>Ledger</Eyebrow>
          <TableScroll label="Value ledger items" min={680} className="mt-3"><table className="w-full text-sm"><caption className="sr-only">Value ledger items</caption>
            <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Change</th><th className="pr-4 font-medium">Evidence</th><th className="pr-4 text-right font-medium">Baseline</th><th className="pr-4 text-right font-medium">With change</th><th className="pr-4 text-right font-medium">Difference</th><th className="font-medium">Source</th></tr></thead>
            <tbody>{d.ledger.map((l) => (
              <tr key={l.item} className="border-b border-line/60 align-top"><td className="py-2 pr-4">{l.item}<span className="block text-xs text-muted">{l.period} · {l.unit}</span></td>
                <td className="pr-4"><Provenance kind="simulated" /></td><td className="num whitespace-nowrap pr-4 text-right">{money(l.baseline_minor)}</td>
                <td className="num whitespace-nowrap pr-4 text-right">{money(l.intervention_minor)}</td>
                <td className="num whitespace-nowrap pr-4 text-right font-semibold">{money(l.intervention_minor - l.baseline_minor)}</td><td><Mono className="text-xs text-muted">{l.source}</Mono></td></tr>))}</tbody>
          </table></TableScroll>
          <p className="mt-3 text-xs text-muted">Assumptions: lead time {d.ledger[0]!.assumptions.lead_time_days} days, review {d.ledger[0]!.assumptions.review_days} days, holding {num(d.ledger[0]!.assumptions.holding_rate_annual * 100, 0)}%/year, unit cost {num(d.ledger[0]!.assumptions.unit_cost_share_of_price * 100, 0)}% of selling price. {d.ledger[0]!.assumptions.notes}</p>
        </Card>
      )}
      {opt && (
        <Card className="p-5">
          <div className="flex flex-wrap items-center justify-between gap-2"><Eyebrow>Sensitivity to lead time and holding cost</Eyebrow>
            <label className="text-sm">Forecaster <select value={model} onChange={(e) => setModel(e.target.value)} className="ml-2 rounded-lg border border-line bg-surface px-2 py-1">
              <option value="tcn">TCN</option><option value="lightgbm">LightGBM</option><option value="seasonal_naive">Seasonal naive</option></select></label></div>
          <Chart option={opt} height={300} label="Simulated cost under each sensitivity case for two policies" />
        </Card>
      )}
      <Card className="p-5"><Eyebrow>Formulas used when real pilot data exist</Eyebrow>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">{d.formulas.map((f) => <li key={f}>{f}</li>)}</ul>
        <p className="mt-2 text-xs text-muted">ROI needs measured incremental costs (implementation, integration, compute, support). None have been measured, so it is not shown.</p></Card>
    </div>
  );
}

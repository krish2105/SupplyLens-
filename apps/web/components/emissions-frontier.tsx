"use client";
// Cost, service and CO2 trade-off (F2): the draft scenario solved under falling CO2 caps (epsilon-
// constraint). CO2 uses assumed lane factors; spend and service are simulated. Nothing is saved.
import { useMemo } from "react";
import { useMutation } from "@tanstack/react-query";
import { Leaf } from "lucide-react";
import { baseOption, Chart, token, useChartTheme } from "@/components/chart";
import { Button, Card, ErrorState, Provenance, TableScroll } from "@/components/ui";
import { apiPost, intentKey } from "@/lib/api";
import type { Schemas } from "@/lib/contract";
import { int, money, num } from "@/lib/format";

type Frontier = Schemas["EmissionsFrontier"];
const kg = (g: number | null | undefined) => (g == null ? null : Math.round(g / 100) / 10);
const pct = (x: number | null | undefined) => (x == null ? "—" : `${num(x * 100, 1)}%`);

export function EmissionsFrontier({ request, canRun, currency }: { request: Record<string, unknown>; canRun: boolean; currency: string }) {
  const theme = useChartTheme();
  const run = useMutation({
    mutationFn: async () => {
      const intent = intentKey("emissions-frontier", request);
      const r = await apiPost("/api/v1/scenarios/emissions-frontier", { body: request as never, idempotencyKey: intent.key });
      intent.settle();
      return r as Frontier;
    },
  });
  const d = run.data;
  const ok = useMemo(() => (d?.points ?? []).filter((p) => p.co2_grams != null && p.service != null), [d]);
  const opt = useMemo(() => {
    if (ok.length < 2) return null;
    const b = baseOption();
    return { ...b, grid: { left: 64, right: 64, top: 28, bottom: 76 }, legend: { bottom: 0, textStyle: { color: token("--muted") } },
      tooltip: { trigger: "axis", backgroundColor: token("--surface"), borderColor: token("--line"), textStyle: { color: token("--ink") } },
      xAxis: { ...(b.xAxis as object), type: "value", inverse: true, name: "CO₂e of the plan (kg) — tighter cap to the right", nameLocation: "middle", nameGap: 26 },
      yAxis: [
        { ...(b.yAxis as object), type: "value", name: `spend (${currency})`, nameLocation: "middle", nameGap: 48 },
        { ...(b.yAxis as object), type: "value", name: "service", min: 0, max: 1, splitLine: { show: false }, nameLocation: "middle", nameGap: 44,
          axisLabel: { color: token("--muted"), formatter: (v: number) => `${Math.round(v * 100)}%` } },
      ],
      series: [
        { type: "line", name: "Spend", data: ok.map((p) => [kg(p.co2_grams), p.spend_minor / 100]), lineStyle: { color: token("--risk") }, itemStyle: { color: token("--risk") } },
        { type: "line", name: "Required units covered", yAxisIndex: 1, data: ok.map((p) => [kg(p.co2_grams), p.service]),
          lineStyle: { color: token("--accent") }, itemStyle: { color: token("--accent") } },
      ] };
  }, [ok, currency, theme]); // eslint-disable-line react-hooks/exhaustive-deps -- recolour when the theme changes (token() reads CSS variables)

  return (
    <Card className="p-5" aria-labelledby="frontier-title">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="frontier-title" className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">Cost, service and CO₂</h2>
        <Provenance kind="assumed" /><Provenance kind="simulated" />
        <Button size="sm" className="ml-auto" onClick={() => run.mutate()} disabled={!canRun || run.isPending}
          title={canRun ? undefined : "Only planners can run the trade-off"}>
          <Leaf className="size-4" aria-hidden /> {run.isPending ? "Solving under each cap…" : "Trace the trade-off for the draft"}
        </Button>
      </div>
      <p className="mt-2 max-w-3xl text-sm text-muted">
        The draft plan is solved without a CO₂ cap, then under caps at 90 % down to 5 % of that plan&apos;s emissions. Each solve still covers as many
        required units as the budget allows, at the lowest cost: a tighter cap first moves orders to nearer, dearer suppliers, then costs service.
      </p>
      {run.error && <div className="mt-3"><ErrorState error={run.error} retry={() => run.mutate()} /></div>}
      {d && !ok.length && <p className="mt-3 text-sm text-muted">No plan to trade off: {d.points[0]?.status === "UNKNOWN" ? "the uncapped plan was not solved in time" : "nothing needs ordering"}.</p>}
      {opt && <div className="mt-3"><Chart option={opt} height={300} label="Spend and share of required units covered against the plan's CO2e as the cap tightens" /></div>}
      {!!ok.length && (
        <TableScroll label="Trade-off points" min={560} className="mt-3">
          <table className="w-full text-sm"><caption className="sr-only">Plan under each CO2 cap</caption>
            <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 pr-4 font-medium">CO₂ cap</th>
              <th className="pr-4 text-right font-medium">CO₂e (kg)</th><th className="pr-4 text-right font-medium">Spend</th>
              <th className="pr-4 text-right font-medium">Units ordered</th><th className="text-right font-medium">Required units covered</th></tr></thead>
            <tbody>{d!.points.map((p) => (
              <tr key={String(p.cap_share)} className="border-b border-line/60"><td className="py-1.5 pr-4">{p.cap_share == null ? "none" : `${Math.round(p.cap_share * 100)} %`}</td>
                <td className="num pr-4 text-right">{kg(p.co2_grams) ?? "—"}</td><td className="num pr-4 text-right">{money(p.spend_minor, currency)}</td>
                <td className="num pr-4 text-right">{int(p.units_ordered)}</td><td className="num text-right">{pct(p.service)}{p.status === "FEASIBLE" && <sup aria-label="best plan found in the time limit, not proven optimal">*</sup>}</td></tr>))}</tbody>
          </table>
        </TableScroll>
      )}
      {d?.points.some((p) => p.status === "FEASIBLE") && (
        <p className="mt-2 text-xs text-muted">* Best plan found within the solver&apos;s time limit, not proven optimal: the true coverage at that cap can only be the same or slightly higher.</p>
      )}
      {d && <ul className="mt-3 list-disc space-y-0.5 pl-5 text-xs text-muted">{d.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>}
    </Card>
  );
}

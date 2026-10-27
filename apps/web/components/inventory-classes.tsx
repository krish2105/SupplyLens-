"use client";
// ABC/XYZ classes and the cost of service (F4). Everything here is derived from recorded sales; the
// holding rate is an assumption, and the panel says so.
import { useMemo, useState } from "react";
import clsx from "clsx";
import { baseOption, Chart, token, useChartTheme } from "@/components/chart";
import { Card, Provenance, QueryError, Skeleton, TableScroll } from "@/components/ui";
import { int, money, num } from "@/lib/format";
import { useApi } from "@/lib/queries";

const LEVELS = [0.9, 0.95, 0.975, 0.98, 0.99, 0.995];
const pct = (x: number) => { const p = Math.round(x * 1000) / 10; return `${num(p, p % 1 ? 1 : 0)}%`; };   // 0.15000000000000002 -> 15%

export function InventoryClasses({ eff }: { eff?: string | null }) {
  const [policy, setPolicy] = useState({ A: 0.98, B: 0.95, C: 0.9 });
  const q = useApi(["inventory-classes", eff ?? "workspace", policy], "/api/v1/inventory/classes",
    { query: { effective_date: eff ?? undefined, service_a: policy.A, service_b: policy.B, service_c: policy.C } });
  const theme = useChartTheme();
  const d = q.data;
  const cur = d?.currency ?? "GBP";
  const opt = useMemo(() => {
    if (!d?.curve?.length) return null;
    const b = baseOption();
    return { ...b, grid: { left: 64, right: 20, top: 24, bottom: 76 }, legend: { bottom: 0, textStyle: { color: token("--muted") } },
      xAxis: { ...(b.xAxis as object), type: "value", name: "cycle service level", nameLocation: "middle", nameGap: 26, min: 0.8, max: 1,
        axisLabel: { color: token("--muted"), formatter: (v: number) => pct(v) } },
      yAxis: { ...(b.yAxis as object), type: "value", name: `${cur} / year`, nameLocation: "middle", nameGap: 48 },
      tooltip: { trigger: "item", backgroundColor: token("--surface"), borderColor: token("--line"), textStyle: { color: token("--ink") } },
      series: [
        { type: "line", name: "Same service level for every product", data: d.curve.map((p) => [p.service_level, p.holding_cost_minor_per_year / 100]),
          lineStyle: { color: token("--accent") }, itemStyle: { color: token("--accent") } },
        ...(d.policy_point ? [{ type: "scatter", name: "Your class policy", symbolSize: 12,
          data: [[d.policy_point.service_level, d.policy_point.holding_cost_minor_per_year / 100]], itemStyle: { color: token("--risk") } }] : []),
      ] };
  }, [d, cur, theme]); // eslint-disable-line react-hooks/exhaustive-deps -- recolour when the theme changes (token() reads CSS variables)

  return (
    <Card className="p-5" aria-labelledby="inventory-classes-title">
      <div className="flex flex-wrap items-center gap-2"><h2 id="inventory-classes-title" className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">Product classes and the cost of service</h2><Provenance kind="derived" /></div>
      {q.error ? <QueryError q={q} what="product classes" /> : !d ? <Skeleton className="mt-3 h-64" /> : !d.products_classified ? (
        <p className="mt-3 text-sm text-muted">No recorded sales in the last year, so products cannot be ranked here.</p>
      ) : (
        <div className="mt-3 space-y-5">
          <p className="max-w-3xl text-sm text-muted">
            ABC ranks the {int(d.products_classified)} products sold in the last {d.window_days} days by {d.basis === "revenue" ? "sales value" : "units (no prices are recorded)"}:
            A makes the first {pct(d.abc_cuts[0]!)}, B the next {pct(d.abc_cuts[1]! - d.abc_cuts[0]!)}. XYZ ranks how steady weekly demand is
            (coefficient of variation below {d.xyz_cuts[0]} is X, below {d.xyz_cuts[1]} Y, otherwise Z).
          </p>
          <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
            <div>
              <table className="w-full table-fixed text-sm" aria-label="Products by ABC and XYZ class">
                <thead><tr className="text-xs text-muted"><th className="w-10" />{["X", "Y", "Z"].map((x) => <th key={x} className="pb-1 font-medium">{x}</th>)}</tr></thead>
                <tbody>{["A", "B", "C"].map((a) => (
                  <tr key={a}><th scope="row" className="pr-2 text-left text-xs font-medium text-muted">{a}</th>
                    {["X", "Y", "Z"].map((x) => {
                      const c = d.matrix.find((m) => m.abc === a && m.xyz === x);
                      return (
                        <td key={x} className="p-0.5">
                          <div className={clsx("rounded-lg border border-line px-2 py-2 text-center", c && c.value_share > 0.1 && "bg-accent-soft")}>
                            <div className="num font-semibold">{int(c?.products ?? 0)}</div>
                            <div className="num text-xs text-muted">{pct(c?.value_share ?? 0)} of {d.basis === "revenue" ? "value" : "units"}</div>
                          </div>
                        </td>
                      );
                    })}
                  </tr>))}</tbody>
              </table>
              <fieldset className="mt-4">
                <legend className="text-xs font-medium text-muted">Service level per class</legend>
                <div className="mt-1 grid grid-cols-3 gap-2">
                  {(["A", "B", "C"] as const).map((k) => (
                    <label key={k} className="text-sm">Class {k}
                      <select value={policy[k]} onChange={(e) => setPolicy({ ...policy, [k]: Number(e.target.value) })}
                        className="mt-1 block w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm">
                        {LEVELS.map((l) => <option key={l} value={l}>{pct(l)}</option>)}
                      </select></label>
                  ))}
                </div>
              </fieldset>
            </div>
            <div>
              {opt && <Chart option={opt} height={280} label="Yearly holding cost of safety stock against the cycle service level" />}
              {d.policy_point && (
                <p className="text-sm">Your class policy: <span className="num font-semibold">{int(d.policy_point.safety_stock_units)}</span> units of safety stock,{" "}
                  <span className="num font-semibold">{money(d.policy_point.holding_cost_minor_per_year, cur)}</span> a year to hold
                  (demand-weighted service level {pct(d.policy_point.service_level)}).</p>
              )}
            </div>
          </div>
          <TableScroll label="Safety stock per stocked product" min={640}>
            <table className="w-full text-sm"><caption className="sr-only">Safety stock per stocked product</caption>
              <thead><tr className="border-b border-line text-left text-xs text-muted">
                <th className="py-2 pr-4 font-medium">Product</th><th className="pr-4 font-medium">Class</th><th className="pr-4 text-right font-medium">Units/day (91d)</th>
                <th className="pr-4 text-right font-medium">Std dev</th><th className="pr-4 text-right font-medium">Lead time</th><th className="pr-4 text-right font-medium">Service</th>
                <th className="pr-4 text-right font-medium">Safety stock</th><th className="text-right font-medium">Holding / year</th></tr></thead>
              <tbody>{[...d.stocked].sort((x, y) => (y.holding_cost_minor_per_year ?? 0) - (x.holding_cost_minor_per_year ?? 0)).slice(0, 12).map((r) => (
                <tr key={r.sku_id} className="border-b border-line/60">
                  <td className="num py-1.5 pr-4">{r.sku_id}</td><td className="pr-4">{r.abc}{r.xyz ?? "–"}</td>
                  <td className="num pr-4 text-right">{num(r.mean_daily)}</td><td className="num pr-4 text-right">{num(r.sd_daily)}</td>
                  <td className="num pr-4 text-right">{r.lead_time_days == null ? "—" : `${r.lead_time_days} d`}</td><td className="num pr-4 text-right">{pct(r.service_level)}</td>
                  <td className="num pr-4 text-right">{r.safety_stock_units == null ? "—" : int(r.safety_stock_units)}</td>
                  <td className="num text-right">{r.holding_cost_minor_per_year == null ? "—" : money(r.holding_cost_minor_per_year, cur)}</td></tr>))}</tbody>
            </table>
          </TableScroll>
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted">{d.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
        </div>
      )}
    </Card>
  );
}

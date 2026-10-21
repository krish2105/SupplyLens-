"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Play } from "lucide-react";
import { baseOption, Chart, token } from "@/components/chart";
import { useDecisionClock } from "@/components/clock-rail";
import { Button, Card, Empty, ErrorState, Eyebrow, KV, Mono, PageHeader, Provenance, Skeleton, Status } from "@/components/ui";
import { getTenant, post } from "@/lib/api";
import { useMe, useTenantQuery, useWs, type InventoryItem } from "@/lib/queries";
import { usePlanningContext } from "@/lib/state";
import { dateTime, day, num, short } from "@/lib/format";

type Run = { id: string; origin: string; horizon: number; status: string; family: string; version: string; quality_flags: Record<string, string>;
  label: string; interval: string; created_at: string; points: { sku_id: string; day: string; q10: number; q50: number; q90: number }[] };
type Model = { id: string; family: string; version: string; status: string; config: Record<string, unknown>; metrics: Record<string, unknown>; created_at: string; training_cutoff: string | null };
type Sales = { daily: { day: string; units: number }[] };

const PLANNED = [
  { family: "lightgbm_quantile", note: "Global quantile model (q0.1/0.5/0.9), lagged features shifted before origin." },
  { family: "tcn_quantile", note: "Compact causal dilated TCN with a direct 28×3 quantile head, 3 seeds." },
];

export default function ForecastPage() {
  const ws = useWs();
  const qc = useQueryClient();
  const me = useMe();
  const [ctx, setCtx] = usePlanningContext();
  const { known } = useDecisionClock();
  const role = me.data?.memberships.find((m) => m.slug === ws)?.role;
  // The product list comes from the workspace snapshot so replaying an earlier origin keeps it populated.
  const inv = useTenantQuery<{ items: InventoryItem[] }>(["inventory", "workspace"], "/api/v1/inventory");
  const sku = ctx.sku ?? inv.data?.items[0]?.sku_id ?? null;
  const sales = useTenantQuery<Sales>(["sales", sku], sku ? `/api/v1/products/${encodeURIComponent(sku)}/sales` : null);
  const models = useTenantQuery<Model[]>(["models"], "/api/v1/models");
  const [runId, setRunId] = useState<string | null>(null);
  const run = useTenantQuery<Run>(["forecast", runId], runId ? `/api/v1/forecasts/${runId}` : null);
  const [zoom, setZoom] = useState<[number, number] | null>(null);

  const create = useMutation({
    mutationFn: () => post<Run>("/api/v1/forecasts", { sku_ids: [sku], origin: known!.slice(0, 10), horizon: 28 }),
    onSuccess: (r) => { setRunId(r.id); qc.setQueryData([getTenant(), "forecast", r.id], r); qc.invalidateQueries({ queryKey: [ws, "models"] }); },
  });

  const origin = known?.slice(0, 10) ?? null;
  const history = useMemo(() => (sales.data?.daily ?? []).filter((d) => !origin || d.day <= origin).slice(-140), [sales.data, origin]);
  const actualsAfter = useMemo(() => (sales.data?.daily ?? []).filter((d) => origin && d.day > origin), [sales.data, origin]);
  const pts = (run.data?.points ?? []).filter((p) => p.sku_id === sku);

  const backtest = useMemo(() => {
    if (!pts.length || !actualsAfter.length) return null;
    const lastObs = sales.data!.daily.at(-1)!.day;
    const scored = pts.filter((p) => p.day <= lastObs);
    if (!scored.length) return null;
    const act = new Map(actualsAfter.map((a) => [a.day, a.units]));
    const errs = scored.map((p) => Math.abs((act.get(p.day) ?? 0) - p.q50));
    const inside = scored.filter((p) => { const y = act.get(p.day) ?? 0; return y >= p.q10 && y <= p.q90; }).length;
    return { n: scored.length, mae: errs.reduce((a, b) => a + b, 0) / errs.length, coverage: inside / scored.length };
  }, [pts, actualsAfter, sales.data]);

  const option = useMemo(() => {
    const b = baseOption();
    const fc = token("--forecast");
    return {
      ...b,
      legend: { ...(b.legend as object), data: ["Recorded unit sales", "10–90% interval", "Median (q50)", ...(backtest ? ["Actual after origin"] : [])] },
      xAxis: { ...(b.xAxis as object), type: "time" },
      yAxis: { ...(b.yAxis as object), type: "value", name: "units / day", nameTextStyle: { color: token("--muted") } },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8, borderColor: token("--line"), textStyle: { color: token("--muted") } }],
      series: [
        { type: "bar", name: "Recorded unit sales", data: history.map((d) => [d.day, d.units]), itemStyle: { color: token("--accent") }, barMaxWidth: 5,
          markLine: origin ? { symbol: "none", label: { formatter: "Forecast origin", color: token("--muted") }, lineStyle: { color: token("--muted"), type: "dashed" }, data: [{ xAxis: origin }] } : undefined },
        { type: "line", name: "10–90% lower", data: pts.map((p) => [p.day, p.q10]), stack: "band", lineStyle: { opacity: 0 }, symbol: "none", tooltip: { show: false } },
        { type: "line", name: "10–90% interval", data: pts.map((p) => [p.day, p.q90 - p.q10]), stack: "band", lineStyle: { opacity: 0 }, symbol: "none", areaStyle: { color: token("--forecast-soft") } },
        { type: "line", name: "Median (q50)", data: pts.map((p) => [p.day, p.q50]), lineStyle: { color: fc, width: 2 }, itemStyle: { color: fc }, symbol: "none" },
        ...(backtest ? [{ type: "scatter", name: "Actual after origin", data: actualsAfter.slice(0, 28).map((d) => [d.day, d.units]), symbolSize: 5, itemStyle: { color: token("--risk") } }] : []),
      ],
    };
  }, [history, pts, origin, backtest, actualsAfter]);

  const onEvents = useMemo(() => ({
    datazoom: (e: any) => { const b = e.batch?.[0] ?? e; setZoom([b.start ?? 0, b.end ?? 100]); },
  }), []);

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Forecast lab" title="Unit-sales forecasts with honest intervals"
        actions={<Button onClick={() => create.mutate()} busy={create.isPending} disabled={!sku || !known || role === "viewer" || role === "approver" || role === "tenant_admin"}
          title={role !== "planner" ? "Only planners can run forecasts" : undefined}><Play className="size-4" aria-hidden /> Run forecast from {day(origin)}</Button>}>
        The model sees only sales up to the forecast origin (the “Known by” date). Days with no recorded sales are zero sales, not observed zero demand.
      </PageHeader>
      {create.error && <ErrorState error={create.error} />}
      <div className="grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,9fr)]">
        <Card className="p-4">
          <Eyebrow>Product</Eyebrow>
          {inv.isLoading ? <Skeleton className="mt-2 h-60" /> : (
            <ul className="mt-2 max-h-[460px] space-y-0.5 overflow-auto" aria-label="Products">
              {inv.data?.items.map((i) => (
                <li key={i.sku_id}>
                  <button aria-current={i.sku_id === sku} onClick={() => { setCtx({ sku: i.sku_id }); setRunId(null); }}
                    className={`w-full rounded-md px-2 py-1.5 text-left text-sm ${i.sku_id === sku ? "bg-accent-soft text-accent" : "hover:bg-surface-2"}`}>
                    <span className="num font-semibold">{i.sku_id}</span>
                    <span className="block truncate text-xs text-muted">{i.description}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <div className="space-y-6">
          <Card className="p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Eyebrow>{sku ? `${sku} — history and 28-day forecast` : "Select a product"}</Eyebrow>
              <span className="flex gap-2"><Provenance kind="observed" /><Provenance kind="forecast" /></span>
            </div>
            {sales.isLoading ? <Skeleton className="mt-3 h-80" /> : history.length ? (
              <Chart option={option} height={360} onEvents={onEvents}
                label={`Daily unit sales for ${sku} up to ${origin}${pts.length ? ", with a 28-day median forecast and 10 to 90 percent interval" : ""}`} />
            ) : <Empty title="No sales history before this origin" />}
            {zoom && <p className="mt-1 text-xs text-muted">Zoomed to {num(zoom[0], 0)}–{num(zoom[1], 0)}% of the visible range. Zoom changes the view only, never the data or exports.</p>}
            {!pts.length && history.length > 0 && <p className="mt-2 text-sm text-muted">Run a forecast to overlay the median and interval.</p>}
          </Card>
          {run.data && (
            <div className="grid gap-6 lg:grid-cols-2">
              <Card className="p-5">
                <Eyebrow>Forecast run</Eyebrow>
                <div className="mt-3"><KV items={[
                  ["Run", <Mono key="r">{short(run.data.id)}</Mono>],
                  ["Model", <span key="m"><Mono>{run.data.family} {run.data.version}</Mono> <Status value="CHAMPION" /></span>],
                  ["Origin", day(run.data.origin)], ["Horizon", `${run.data.horizon} days`],
                  ["Output", run.data.label], ["Interval", run.data.interval],
                  ["Quality flags", Object.keys(run.data.quality_flags).length ? Object.entries(run.data.quality_flags).map(([k, v]) => `${k}: ${v}`).join(", ") : "none"],
                  ["Created", dateTime(run.data.created_at)],
                ]} /></div>
              </Card>
              <Card className="p-5">
                <Eyebrow>This run against what happened</Eyebrow>
                {backtest ? (
                  <div className="mt-3 space-y-2 text-sm">
                    <p><span className="num text-2xl font-semibold">{num(backtest.mae, 2)}</span> units/day mean absolute error over <span className="num">{backtest.n}</span> days.</p>
                    <p><span className="num text-2xl font-semibold">{num(backtest.coverage * 100, 0)}%</span> of actual days fell inside the 10–90% interval (nominal 80%).</p>
                    <p className="text-xs text-muted">One product, one origin: illustrative only. Model comparisons use frozen multi-origin splits, not this panel.</p>
                  </div>
                ) : <p className="mt-3 text-sm text-muted">No recorded sales after this origin, so this run cannot be scored. Move “Known by” earlier to replay a past origin.</p>}
              </Card>
            </div>
          )}
          <Card className="p-5">
            <Eyebrow>Model registry</Eyebrow>
            <table className="mt-3 w-full text-sm">
              <caption className="sr-only">Registered forecasting models</caption>
              <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Model</th><th className="font-medium">Status</th><th className="font-medium">Evaluation</th></tr></thead>
              <tbody>
                {models.data?.map((m) => (
                  <tr key={m.id} className="border-b border-line/60"><td className="py-2"><Mono>{m.family} {m.version}</Mono></td><td><Status value={m.status} /></td>
                    <td className="text-xs text-muted">{Object.keys(m.metrics).length ? JSON.stringify(m.metrics) : "Baseline; frozen evaluation not yet run"}</td></tr>
                ))}
                {PLANNED.map((p) => (
                  <tr key={p.family} className="border-b border-line/60"><td className="py-2"><Mono>{p.family}</Mono></td><td><Status value="NOT_IMPLEMENTED" /></td>
                    <td className="text-xs text-muted">{p.note} Not trained yet.</td></tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      </div>
    </div>
  );
}

"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Play } from "lucide-react";
import { baseOption, Chart, token, useChartTheme } from "@/components/chart";
import { useDecisionClock } from "@/components/clock-rail";
import { Button, Card, Empty, ErrorState, Eyebrow, KV, Mono, PageHeader, Provenance, QueryError, Skeleton, Status, TableScroll } from "@/components/ui";
import { EmptyState } from "@/components/illustration";
import { apiPost, getTenant } from "@/lib/api";
import { useApi, useMe, useWs } from "@/lib/queries";
import { usePlanningContext } from "@/lib/state";
import { dateTime, day, num, short } from "@/lib/format";


const PLANNED = [
  { family: "lightgbm_quantile", note: "Global quantile model (q0.1/0.5/0.9), lagged features shifted before origin." },
  { family: "tcn_quantile", note: "Compact causal dilated TCN with a direct 28×3 quantile head, 3 seeds." },
];
const FAMILY_LABEL: Record<string, string> = { seasonal_naive: "Seasonal naive", lightgbm_quantile: "LightGBM quantile", tcn_quantile: "Quantile TCN" };

type ZoomEvent = { start?: number; end?: number; batch?: { start?: number; end?: number }[] };

export default function ForecastPage() {
  const ws = useWs();
  const qc = useQueryClient();
  const me = useMe();
  const [ctx, setCtx] = usePlanningContext();
  const { known } = useDecisionClock();
  const role = me.data?.memberships.find((m) => m.slug === ws)?.role;
  // The product list comes from the workspace snapshot so replaying an earlier origin keeps it populated.
  const inv = useApi(["inventory", "workspace"], "/api/v1/inventory");
  const sku = ctx.sku ?? inv.data?.items[0]?.sku_id ?? null;
  const sales = useApi(["sales", sku], sku ? "/api/v1/products/{sku_id}/sales" : null, { path: { sku_id: sku ?? "" } });
  const models = useApi(["models"], "/api/v1/models");
  const [runId, setRunId] = useState<string | null>(null);
  const run = useApi(["forecast", runId], runId ? "/api/v1/forecasts/{run_id}" : null, { path: { run_id: runId ?? "" } });
  const [zoom, setZoom] = useState<[number, number] | null>(null);
  const [family, setFamily] = useState<string>("");

  // A run belongs to the product and origin it was made for. If the user has moved on by the time it returns, the
  // result is cached but not shown: the chart, run card and score must never mix versions (EXE-006).
  const skuRef = useRef(sku);
  useEffect(() => { skuRef.current = sku; }, [sku]);
  // A trained model has already seen labels up to its training cutoff, so replaying an earlier origin with it would leak
  // the future (the API refuses). On "Champion" we fall back to the baseline for such origins and say so.
  const champion = models.data?.find((m) => m.status === "CHAMPION");
  const replayBeforeTraining = !family && !!champion && champion.family !== "seasonal_naive" && !!champion.training_cutoff
    && !!known && known.slice(0, 10) < champion.training_cutoff;
  const effectiveFamily = replayBeforeTraining ? "seasonal_naive" : family;
  const create = useMutation({
    mutationFn: (forSku: string) => apiPost("/api/v1/forecasts", { body: { sku_ids: [forSku], origin: known!.slice(0, 10), horizon: 28, ...(effectiveFamily ? { model_family: effectiveFamily as never } : {}) } }),
    onSuccess: (r, forSku) => {
      qc.setQueryData([getTenant(), "forecast", r.id], r);
      if (forSku === skuRef.current) setRunId(r.id);
      qc.invalidateQueries({ queryKey: [ws, "models"] });
    },
  });

  const origin = known?.slice(0, 10) ?? null;
  const history = useMemo(() => (sales.data?.daily ?? []).filter((d) => !origin || d.day <= origin).slice(-140), [sales.data, origin]);
  const actualsAfter = useMemo(() => (sales.data?.daily ?? []).filter((d) => origin && d.day > origin), [sales.data, origin]);
  const sameSku = !!run.data && !!sku && run.data.sku_ids.includes(sku);
  const staleOrigin = sameSku && run.data!.origin !== origin;
  const current = sameSku && !staleOrigin ? run.data! : null;       // only a run for this product AND this origin is overlaid
  const pts = (current?.points ?? []).filter((p) => p.sku_id === sku);

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

  const chartTheme = useChartTheme();     // chart colours follow the theme (audit S17)
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
  }, [history, pts, origin, backtest, actualsAfter, chartTheme]); // eslint-disable-line react-hooks/exhaustive-deps -- recolour when the theme changes (token() reads CSS variables)

  const onEvents = useMemo(() => ({
    datazoom: (raw: unknown) => { const e = raw as ZoomEvent; const b = e.batch?.[0] ?? e; setZoom([b.start ?? 0, b.end ?? 100]); },
  }), []);

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Forecast lab" title="Unit-sales forecasts with honest intervals"
        actions={<><label className="flex items-center gap-2 text-sm"><span className="text-muted">Model</span>
          <select value={family} onChange={(e) => setFamily(e.target.value)} className="rounded-lg border border-line bg-surface px-2 py-2 text-sm">
            <option value="">Champion ({FAMILY_LABEL[models.data?.find((m) => m.status === "CHAMPION")?.family ?? "seasonal_naive"]})</option>
            {models.data?.map((m) => <option key={m.id} value={m.family}>{FAMILY_LABEL[m.family] ?? m.family} · {m.status.toLowerCase()}</option>)}
          </select></label><Button onClick={() => create.mutate(sku!)} busy={create.isPending} disabled={!sku || !known || role !== "planner"}
          title={role !== "planner" ? "Only planners can run forecasts" : undefined}><Play className="size-4" aria-hidden /> Run forecast from {day(origin)}</Button></>}>
        The model sees only sales up to the forecast origin (the “Known by” date). Days with no recorded sales are zero sales, not observed zero demand.
      </PageHeader>
      {create.error && <ErrorState error={create.error} />}
      <div className="grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,9fr)]">{/* grid items get min-w-0 so wide content scrolls inside them on a phone */}
        <Card className="min-w-0 p-4">
          <Eyebrow>Product</Eyebrow>
          {inv.isLoading ? <Skeleton className="mt-2 h-60" /> : inv.error ? <QueryError q={inv} what="products" /> : (
            <ul className="mt-2 max-h-[460px] space-y-0.5 overflow-auto" aria-label="Products">
              {/* one entry per product: inventory has a row per SKU and location (P1-FE-02) */}
              {inv.data?.items.filter((i, n, all) => all.findIndex((x) => x.sku_id === i.sku_id) === n).map((i) => (
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
        <div className="min-w-0 space-y-6">
          <Card className="p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Eyebrow>{sku ? `${sku} — history and 28-day forecast` : "Select a product"}</Eyebrow>
              <span className="flex gap-2"><Provenance kind="observed" /><Provenance kind="forecast" /></span>
            </div>
            {sales.isLoading ? <Skeleton className="mt-3 h-80" /> : sales.error ? <QueryError q={sales} what="sales history" /> : history.length ? (
              <Chart option={option} height={360} onEvents={onEvents}
                label={`Daily unit sales for ${sku} up to ${origin}${pts.length ? ", with a 28-day median forecast and 10 to 90 percent interval" : ""}`} />
            ) : <Empty title="No sales history before this origin" />}
            {zoom && <p className="mt-1 text-xs text-muted">Zoomed to {num(zoom[0], 0)}–{num(zoom[1], 0)}% of the visible range. Zoom changes the view only, never the data or exports.</p>}
            <QueryError q={run} what="this forecast run" />
            {!pts.length && history.length > 0 && <div className="mt-3"><EmptyState variant="first_run" art="forecast-setup" title="Create a forecast for this product" compact>
              No forecast run exists for this product, origin and model yet. Run one to overlay the median and the 10–90% interval.</EmptyState></div>}
          </Card>
          {replayBeforeTraining && (
            <p role="note" className="rounded-lg bg-surface-2 px-3 py-2 text-sm text-muted">
              The champion ({champion!.family.replaceAll("_", " ")}) was trained on data up to {day(champion!.training_cutoff)}, so it cannot
              replay {day(origin)} without seeing the future. This run will use the seasonal-naive baseline instead.
            </p>
          )}
          {staleOrigin && (
            <p role="status" className="rounded-lg bg-risk-soft px-3 py-2 text-sm text-risk">
              This run was made from {day(run.data!.origin)}, but the decision clock now reads {day(origin)}. It is not drawn on the chart or scored; run the forecast again.
            </p>
          )}
          {run.data && sameSku && (
            <div className="grid gap-6 lg:grid-cols-2" data-run-id={run.data.id}>
              <Card className="p-5">
                <Eyebrow>Forecast run</Eyebrow>
                <div className="mt-3"><KV items={[
                  ["Run", <Mono key="r">{short(run.data.id)}</Mono>],
                  ["Model", <span key="m"><Mono>{run.data.family} {run.data.version}</Mono> <Status value={models.data?.find((m) => m.id === run.data!.model_version_id)?.status} /></span>],
                  ["Origin", day(run.data.origin)], ["Horizon", `${run.data.horizon} days`],
                  ["Output", run.data.label], ["Interval", run.data.interval],
                  ["Quality flags", Object.keys(run.data.quality_flags).length ? Object.entries(run.data.quality_flags).map(([k, v]) => `${k}: ${v}`).join(", ") : "none"],
                  ["Created", dateTime(run.data.created_at)],
                ]} /></div>
              </Card>
              <Card className="p-5">
                <Eyebrow>This run against what happened</Eyebrow>
                {backtest && current ? (
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
            <QueryError q={models} what="the model registry" />
            <TableScroll label="Registered forecasting models" min={420} className="mt-3"><table className="w-full text-sm">
              <caption className="sr-only">Registered forecasting models</caption>
              <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Model</th><th className="font-medium">Status</th><th className="font-medium">Evaluation</th></tr></thead>
              <tbody>
                {models.data?.map((m) => (
                  <tr key={m.id} className="border-b border-line/60"><td className="py-2"><Mono>{m.family} {m.version}</Mono></td><td><Status value={m.status} /></td>
                    <td className="num text-xs text-muted">{modelEvidence(m.metrics)}</td></tr>
                ))}
                {PLANNED.filter((p) => !models.data?.some((m) => m.family === p.family)).map((p) => (
                  <tr key={p.family} className="border-b border-line/60"><td className="py-2"><Mono>{p.family}</Mono></td><td><Status value="NOT_IMPLEMENTED" /></td>
                    <td className="text-xs text-muted">{p.note} Not trained yet.</td></tr>
                ))}
              </tbody>
            </table></TableScroll>
          </Card>
          <StudyPanel />
        </div>
      </div>
    </div>
  );
}


type ModelMetrics = { mae?: number; pinball_mean?: number; coverage_80?: number; validation_pinball?: number };
function modelEvidence(raw: Record<string, unknown>) {
  const m = raw as ModelMetrics;
  if (m.mae == null) return "Baseline; frozen evaluation not yet run";
  return `test MAE ${num(m.mae, 2)} · pinball ${num(m.pinball_mean, 3)} · cov80 ${num((m.coverage_80 ?? 0) * 100, 1)}% · val pinball ${num(m.validation_pinball, 3)}`;
}

const STUDY_NAME: Record<string, string> = { seasonal_naive: "Seasonal naive", lightgbm: "LightGBM quantile", tcn: "Quantile TCN (seed 0)" };

function StudyPanel() {
  const st = useApi(["study-f1"], "/api/v1/research/forecast-study");
  const chartTheme = useChartTheme();     // chart colours follow the theme (audit S17)
  const option = useMemo(() => {
    const d = st.data;
    if (!d?.available) return null;
    const b = baseOption();
    const colors: Record<string, string> = { seasonal_naive: token("--muted"), lightgbm: token("--accent"), tcn: token("--forecast") };
    const fams = Object.keys(d.pinball_by_horizon);
    return { ...b, xAxis: { ...(b.xAxis as object), type: "category", name: "horizon (days)", data: Array.from({ length: 28 }, (_, i) => i + 1) },
      yAxis: { ...(b.yAxis as object), type: "value", name: "median pinball" },
      series: fams.map((f) => ({ type: "line", name: STUDY_NAME[f], data: d.pinball_by_horizon[f]!.q50, symbol: "none", lineStyle: { color: colors[f], width: 2 }, itemStyle: { color: colors[f] } })) };
  }, [st.data, chartTheme]); // eslint-disable-line react-hooks/exhaustive-deps -- recolour when the theme changes (token() reads CSS variables)
  if (st.isLoading) return <Card className="p-5"><Skeleton className="h-40" /></Card>;
  if (st.error) return <Card className="p-5"><Eyebrow>Model comparison study</Eyebrow><QueryError q={st} what="the model comparison study" /></Card>;
  if (!st.data?.available) return <Card className="p-5"><Eyebrow>Model comparison study</Eyebrow><p className="mt-2 text-sm text-muted">{st.data?.message}</p></Card>;
  const d = st.data;
  const fams = (["seasonal_naive", "lightgbm", "tcn"] as const).filter((f) => d.summary[f]);
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Eyebrow>Model comparison study {d.experiment_id}</Eyebrow>
        <span className="text-xs text-muted">{d.cohort_size} products · test {day(d.test_window[0])}–{day(d.test_window[1])} · champion by validation: <b>{STUDY_NAME[d.selection.champion_by_validation]}</b></span>
      </div>
      <div className="mt-3 overflow-x-auto" tabIndex={0} role="region" aria-label="Model comparison table, scrollable">
        <table className="w-full text-sm">
          <caption className="sr-only">Held-out test metrics for the three model families</caption>
          <thead><tr className="border-b border-line text-left text-xs text-muted">
            <th className="py-2 font-medium">Model</th><th className="font-medium">Val. pinball</th><th className="font-medium">MAE</th><th className="font-medium">MASE</th>
            <th className="font-medium">Pinball q10 / q50 / q90</th><th className="font-medium">80% coverage</th><th className="font-medium">Width</th><th className="font-medium">Raw crossing</th></tr></thead>
          <tbody>
            {fams.map((f) => { const m = d.summary[f]!; return (
              <tr key={f} className="border-b border-line/60">
                <td className="py-2 font-medium">{STUDY_NAME[f]}{d.selection.champion_by_validation === f && <span className="ml-2"><Status value="CHAMPION" /></span>}</td>
                <td className="num">{num(d.selection[f].validation_pinball, 3)}</td><td className="num">{num(m.mae, 2)}</td>
                <td className="num">{m.mase == null ? "undefined" : num(m.mase, 3)}{m.mase_undefined_series ? <span className="text-muted"> ({m.mase_undefined_series} undef.)</span> : null}</td>
                <td className="num">{num(m.pinball.q10, 2)} / {num(m.pinball.q50, 2)} / {num(m.pinball.q90, 2)}</td>
                <td className="num">{num(m.coverage_80 * 100, 1)}%</td><td className="num">{num(m.width_80, 1)}</td><td className="num">{num(m.crossing_rate_raw * 100, 2)}%</td>
              </tr>); })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted">TCN across seeds {d.config.seeds.tcn.join(", ")}: MAE {num(d.tcn_seed_mean.mae, 2)} ± {num(d.tcn_seed_sd.mae, 2)}, pinball {num(d.tcn_seed_mean.pinball_mean, 3)} ± {num(d.tcn_seed_sd.pinball_mean, 3)}.</p>
      {option && <div className="mt-3"><Chart option={option} height={240} label="Median pinball loss by forecast horizon for each model" /></div>}
      <ul className="mt-3 space-y-1 text-sm">
        {Object.entries(d.comparisons).map(([k, c]) => (
          <li key={k}><Mono>{k.replaceAll("_", " ")}</Mono>: mean per-product MAE difference <span className="num font-semibold">{num(c.mean_diff, 2)}</span> (95% CI {num(c.ci95[0], 2)} to {num(c.ci95[1], 2)}), first model better on {num(c.share_a_better * 100, 0)}% of {c.n_series} products.</li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-muted">Selection used validation origins {d.config.validation_origins.join(", ")} only; the test window was scored once afterwards. Sales are a demand proxy (stockouts unobserved). Device: {d.environment.tcn_device}, torch {d.environment.torch}, LightGBM {d.environment.lightgbm}.</p>
    </Card>
  );
}

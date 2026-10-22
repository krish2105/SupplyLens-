"use client";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { ArrowDownUp } from "lucide-react";
import { baseOption, Chart, token } from "@/components/chart";
import { useDecisionClock } from "@/components/clock-rail";
import { FloorPlan } from "@/components/floorplan";
import { Card, Empty, ErrorState, Eyebrow, KV, Loading, Mono, PageHeader, Provenance, Skeleton, Status } from "@/components/ui";
import { GLBoundary, GLNotice } from "@/components/gl-boundary";
import { webglAvailable } from "@/lib/webgl";
import { useApi, useWs, type InventoryItem } from "@/lib/queries";
import { usePlanningContext } from "@/lib/state";
import { day, int, money, num } from "@/lib/format";

const Warehouse3D = dynamic(() => import("@/components/warehouse3d"), { ssr: false, loading: () => <Skeleton className="h-[420px]" /> });

type SortKey = "sku_id" | "available" | "days_of_cover" | "avg_daily" | "health";

export default function InventoryPage() {
  const ws = useWs();
  const [ctx, setCtx] = usePlanningContext();
  const { known, eff } = useDecisionClock();
  // Not gated on the overview: the API defaults to the workspace as-of unless the user replays another date.
  const inv = useApi(["inventory", ctx.eff ?? "workspace"], "/api/v1/inventory", { query: { effective_date: ctx.eff } });
  const [view, setView] = useState<"3d" | "2d" | null>(null);   // decided on mount; the plot area holds its height meanwhile
  const [gl, setGl] = useState(true);
  const [glFailed, setGlFailed] = useState(false);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<{ k: SortKey; dir: 1 | -1 }>({ k: "days_of_cover", dir: 1 });
  useEffect(() => { const ok = webglAvailable(); setGl(ok); setView(!ok || window.innerWidth < 768 ? "2d" : "3d"); }, []);

  const items = inv.data?.items ?? [];
  const rows = useMemo(() => {
    const s = search.trim().toLowerCase();
    return items
      .filter((i) => filter === "all" || i.health === filter)
      .filter((i) => !s || i.sku_id.toLowerCase().includes(s) || i.description.toLowerCase().includes(s))
      .sort((a, b) => {
        const av = a[sort.k] ?? Infinity, bv = b[sort.k] ?? Infinity;
        return (av < bv ? -1 : av > bv ? 1 : 0) * sort.dir;
      });
  }, [items, filter, search, sort]);
  const sel = items.find((i) => i.sku_id === ctx.sku) ?? null;
  const select = (s: string | null) => setCtx({ sku: s });

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Inventory" title="Stock positions by product">
        Selecting a row, a rack in 3D or a tile in the floor plan selects the same record everywhere.
      </PageHeader>
      {inv.error && <ErrorState error={inv.error} retry={() => inv.refetch()} />}
      <div className="grid gap-6 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <Card className="overflow-hidden p-0">
          <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2">
            <div role="tablist" aria-label="Layout view" className="inline-flex rounded-lg border border-line p-0.5">
              {(["3d", "2d"] as const).map((v) => (
                <button key={v} role="tab" aria-selected={view === v} disabled={v === "3d" && (!gl || glFailed)}
                  title={v === "3d" && (!gl || glFailed) ? "WebGL is unavailable in this browser" : undefined}
                  onClick={() => setView(v)}
                  className={clsx("rounded-md px-3 py-1 text-sm disabled:opacity-40", view === v ? "bg-accent text-accent-ink" : "text-muted")}>
                  {v === "3d" ? "3D schematic" : "2D floor plan"}
                </button>
              ))}
            </div>
            <span className="text-xs text-muted">Snapshot {day(items[0]?.as_of)} · <Provenance kind={items[0]?.value_kind} /></span>
          </div>
          {inv.isLoading || view === null ? <Skeleton className="h-[420px]" /> : view === "3d" && gl && !glFailed ? (
            <GLBoundary onError={() => setGlFailed(true)} fallback={null}>
              <Warehouse3D items={items} selected={ctx.sku} onSelect={select} height={420} onFail={() => setGlFailed(true)} />
            </GLBoundary>
          ) : <>{glFailed && <GLNotice />}<div className="p-4"><FloorPlan items={items} selected={ctx.sku} onSelect={select} /></div></>}
        </Card>
        <Detail item={sel} known={known} eff={eff} ws={ws} />
      </div>

      <Card className="p-0">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
          <label className="text-sm"><span className="sr-only">Search products</span>
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search code or description"
              className="w-64 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm" /></label>
          <label className="flex items-center gap-2 text-sm text-muted">Health
            <select value={filter} onChange={(e) => setFilter(e.target.value)} className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink">
              <option value="all">All</option><option value="shortage_risk">Under 7 days</option><option value="healthy">7–90 days</option>
              <option value="excess">Over 90 days</option><option value="no_sales_data">No sales data</option>
            </select></label>
          <span className="ml-auto text-xs text-muted">{rows.length} of {items.length} products</span>
        </div>
        <div className="max-h-[520px] overflow-auto" tabIndex={0} role="region" aria-label="Inventory table, scrollable">
          <table className="w-full text-sm">
            <caption className="sr-only">Inventory positions. Select a row to inspect it.</caption>
            <thead className="sticky top-0 bg-surface">
              <tr className="border-b border-line text-left text-xs text-muted">
                {([["sku_id", "Product"], ["available", "Available"], ["avg_daily", "Units/day (28d)"], ["days_of_cover", "Days of cover"], ["health", "Status"]] as [SortKey, string][]).map(([k, l]) => (
                  <th key={k} scope="col" className="px-4 py-2 font-medium" aria-sort={sort.k === k ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
                    <button className="inline-flex items-center gap-1 hover:text-ink" onClick={() => setSort((s) => ({ k, dir: s.k === k ? (s.dir === 1 ? -1 : 1) : 1 }))}>
                      {l}<ArrowDownUp className="size-3" aria-hidden />
                    </button>
                  </th>
                ))}
                <th scope="col" className="px-4 py-2 font-medium">Slot</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((i) => (
                <tr key={i.sku_id} aria-selected={i.sku_id === ctx.sku}
                  className={clsx("cursor-pointer border-b border-line/60 hover:bg-surface-2", i.sku_id === ctx.sku && "bg-accent-soft")}
                  onClick={() => select(i.sku_id)}>
                  <td className="px-4 py-2">
                    <button className="text-left" onClick={(e) => { e.stopPropagation(); select(i.sku_id); }}>
                      <span className="num font-semibold">{i.sku_id}</span>
                      <span className="block max-w-[320px] truncate text-xs text-muted">{i.description}</span>
                    </button>
                  </td>
                  <td className="num px-4">{int(i.available)}</td>
                  <td className="num px-4">{i.avg_daily == null ? "—" : num(i.avg_daily)}</td>
                  <td className="num px-4">{i.days_of_cover == null ? "—" : num(i.days_of_cover)}</td>
                  <td className="px-4"><Status value={i.health} /></td>
                  <td className="num px-4 text-xs text-muted">{i.slot_id ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!inv.isLoading && !rows.length && <div className="p-4"><Empty title="No products match these filters" /></div>}
        </div>
      </Card>
    </div>
  );
}

function Detail({ item, known, eff, ws }: { item: InventoryItem | null; known: string | null; eff: string | null; ws: string }) {
  const terms = useApi(["terms", item?.sku_id, known, eff], item && known && eff ? "/api/v1/terms" : null,
    { query: { sku_id: item?.sku_id ?? "", knowledge_cutoff: known, effective_date: eff } });
  const sales = useApi(["sales", item?.sku_id], item ? "/api/v1/products/{sku_id}/sales" : null, { path: { sku_id: item?.sku_id ?? "" } });
  const option = useMemo(() => {
    const pts = (sales.data?.daily ?? []).filter((d) => !eff || d.day <= eff).slice(-120);
    const b = baseOption();
    return { ...b, grid: { left: 40, right: 12, top: 16, bottom: 28 }, legend: { show: false },
      xAxis: { ...(b.xAxis as object), type: "time" }, yAxis: { ...(b.yAxis as object), type: "value", name: "units" },
      series: [{ type: "bar", name: "Units sold", data: pts.map((p) => [p.day, p.units]), itemStyle: { color: token("--accent") }, barMaxWidth: 6 }] };
  }, [sales.data, eff]);

  if (!item) return (
    <Card className="p-5"><Eyebrow>Selection</Eyebrow>
      <p className="mt-3 text-sm text-muted">Select a product in the table, the floor plan or the 3D view to see its stock, recent sales and the supplier terms in force.</p></Card>
  );
  return (
    <Card className="space-y-4 p-5" aria-labelledby="detail-title">
      <div>
        <Eyebrow>Selected product</Eyebrow>
        <h2 id="detail-title" className="display mt-1 text-2xl font-semibold"><span className="num">{item.sku_id}</span></h2>
        <p className="text-sm text-muted">{item.description}</p>
      </div>
      <KV items={[
        ["On hand", <span key="a" className="num">{int(item.on_hand)} {item.unit} <Provenance kind={item.value_kind} /></span>],
        ["Allocated", <span key="b" className="num">{int(item.allocated)}</span>],
        ["On order", <span key="c" className="num">{int(item.on_order)}</span>],
        ["Available", <span key="d" className="num font-semibold">{int(item.available)}</span>],
        ["Capacity", <span key="e" className="num">{item.capacity == null ? "unknown" : int(item.capacity)}</span>],
        ["Days of cover", <span key="f" className="num">{item.days_of_cover == null ? "—" : num(item.days_of_cover)} <Provenance kind="derived" /></span>],
        ["Slot", <Mono key="g">{item.slot_id} (schematic)</Mono>],
      ]} />
      <div>
        <Eyebrow>Recorded unit sales, last 120 days to {day(eff)}</Eyebrow>
        {sales.isLoading ? <Skeleton className="mt-2 h-40" /> : sales.data?.daily.length ?
          <Chart option={option} height={170} label={`Daily units sold for ${item.sku_id}`} /> :
          <p className="mt-2 text-sm text-muted">No sales history for this product.</p>}
      </div>
      <div>
        <Eyebrow>Supplier terms in force</Eyebrow>
        {terms.isLoading ? <Loading /> : terms.error ? <ErrorState error={terms.error} /> : (
          <ul className="mt-2 space-y-2 text-sm">
            {terms.data?.conflicts.length ? <li className="rounded-lg bg-risk-soft p-2 text-risk">Conflicting active terms: {terms.data.conflicts.flat().join(", ")} — review required.</li> : null}
            {terms.data?.applicable.map((t) => (
              <li key={t.term_id} className="rounded-lg border border-line p-2.5">
                <div className="flex items-center justify-between gap-2"><span className="font-medium">{t.supplier_id}</span><Provenance kind={t.value_kind} /></div>
                <div className="num mt-1 text-xs text-muted">{money(t.unit_cost_minor, t.currency)}/unit · MOQ {t.moq} · ×{t.order_multiple} · {t.lead_time_days} d lead · from {day(t.valid_from)}</div>
              </li>
            ))}
            {terms.data?.ignored.map((t) => (
              <li key={t.term_id} className="text-xs text-muted">Not applied: <Mono>{t.term_id}</Mono> — {t.reason}</li>
            ))}
          </ul>
        )}
      </div>
      <div className="flex flex-wrap gap-3 text-sm">
        <Link className="text-accent underline-offset-2 hover:underline" href={{ pathname: "/forecast", query: { ws, sku: item.sku_id } }}>Forecast this product</Link>
        <Link className="text-accent underline-offset-2 hover:underline" href={{ pathname: "/policies", query: { ws, sku: item.sku_id } }}>Search its policies</Link>
      </div>
    </Card>
  );
}

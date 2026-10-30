"use client";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { ArrowDownUp } from "lucide-react";
import { baseOption, Chart, token, useChartTheme } from "@/components/chart";
import { useDecisionClock } from "@/components/clock-rail";
import { FloorPlan } from "@/components/floorplan";
import { Card, ErrorState, Eyebrow, KV, Loading, Mono, PageHeader, Provenance, QueryError, Skeleton, Status, TabList, TabPanel } from "@/components/ui";
import { EmptyState } from "@/components/illustration";
import { InventoryClasses } from "@/components/inventory-classes";
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
  useEffect(() => {
    const ok = webglAvailable();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- device capability exists only in the browser, after mount
    setGl(ok); setView(!ok || window.innerWidth < 768 ? "2d" : "3d");
  }, []);

  const items = useMemo(() => inv.data?.items ?? [], [inv.data]);
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
      {inv.data?.next_offset != null && (
        <p data-testid="inventory-truncated" className="rounded-lg border border-line bg-surface px-4 py-2 text-sm text-muted">
          Showing the first {int(items.length)} of {int(inv.data.total ?? items.length)} products. Search, filters and the
          layouts cover these products only.
        </p>
      )}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <Card className="overflow-hidden p-0">
          <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2">
            <TabList id="layout" label="Layout view" value={view} onChange={setView} className="inline-flex rounded-lg border border-line p-0.5"
              tabs={(["3d", "2d"] as const).map((v) => ({ key: v, label: v === "3d" ? "3D schematic" : "2D floor plan",
                disabled: v === "3d" && (!gl || glFailed), title: v === "3d" && (!gl || glFailed) ? "WebGL is unavailable in this browser" : undefined }))}
              tabClassName={(on) => clsx("rounded-md px-3 py-1 text-sm disabled:opacity-40", on ? "bg-accent text-accent-ink" : "text-muted")} />
            {/* Space reserved before the data arrives: on phones the label has its own line at the chip's height, so the loaded
                text never wraps differently from the placeholder and pushes the scene down (CLS). */}
            <span className="inline-flex min-h-5 w-full items-center gap-1 text-xs text-muted sm:w-auto">
              {items.length ? <>Snapshot {day(items[0]?.as_of)} · <Provenance kind={items[0]?.value_kind} /></> : inv.isLoading ? "Snapshot …" : "No snapshot to show"}
            </span>
          </div>
          <TabPanel id="layout" value={view}>
          {inv.isLoading || view === null ? <Skeleton className="h-[420px]" /> : !items.length ? (
            // An empty floor would read as "a warehouse holding nothing"; the error or empty state above/below says why instead.
            <p className="grid h-[180px] place-items-center px-6 text-center text-sm text-muted">
              {inv.error ? "The layout appears once stock positions load." : "No stock positions to lay out at this date."}
            </p>
          ) : view === "3d" && gl && !glFailed ? (
            <GLBoundary onError={() => setGlFailed(true)} fallback={null}>
              <Warehouse3D items={items} selected={ctx.sku} onSelect={select} height={420} onFail={() => setGlFailed(true)} />
            </GLBoundary>
          ) : <>{glFailed && <GLNotice />}<div className="p-4"><FloorPlan items={items} selected={ctx.sku} onSelect={select} /></div></>}
          </TabPanel>
        </Card>
        <Detail item={sel} locations={items.filter((i) => i.sku_id === ctx.sku)} known={known} eff={eff} ws={ws} />
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
                <tr key={`${i.sku_id}@${i.location_id}`} aria-selected={i.sku_id === ctx.sku}
                  className={clsx("cursor-pointer border-b border-line/60 hover:bg-surface-2", i.sku_id === ctx.sku && "bg-accent-soft")}
                  onClick={() => select(i.sku_id)}>
                  <td className="px-4 py-2">
                    <button className="text-left" onClick={(e) => { e.stopPropagation(); select(i.sku_id); }}>
                      <span className="num font-semibold">{i.sku_id}</span>
                      <span className="block max-w-[320px] truncate text-xs text-muted">{i.description} · {i.location_id}</span>
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
          {!inv.isLoading && !inv.error && !rows.length && <div className="p-4">{items.length ? (
            <EmptyState variant="empty_filtered" title="No matches for these filters" compact>Clear the search or health filter to see all {items.length} products.</EmptyState>
          ) : (
            <EmptyState variant="empty_scope" art="empty-inventory" title="No inventory records in this workspace" compact>
              No stock snapshot is recorded on or before this date. That is missing data, not zero stock: an administrator can publish a stock file on the Data page.
            </EmptyState>)}</div>}
        </div>
      </Card>
      <InventoryClasses eff={ctx.eff} />
    </div>
  );
}

function Detail({ item, locations, known, eff, ws }: { item: InventoryItem | null; locations: InventoryItem[]; known: string | null; eff: string | null; ws: string }) {
  const terms = useApi(["terms", item?.sku_id, known, eff], item && known && eff ? "/api/v1/terms" : null,
    { query: { sku_id: item?.sku_id ?? "", knowledge_cutoff: known, effective_date: eff } });
  const sales = useApi(["sales", item?.sku_id], item ? "/api/v1/products/{sku_id}/sales" : null, { path: { sku_id: item?.sku_id ?? "" } });
  const chartTheme = useChartTheme();     // chart colours follow the theme (audit S17)
  const option = useMemo(() => {
    const pts = (sales.data?.daily ?? []).filter((d) => !eff || d.day <= eff).slice(-120);
    const b = baseOption();
    return { ...b, grid: { left: 40, right: 12, top: 16, bottom: 28 }, legend: { show: false },
      xAxis: { ...(b.xAxis as object), type: "time" }, yAxis: { ...(b.yAxis as object), type: "value", name: "units" },
      series: [{ type: "bar", name: "Units sold", data: pts.map((p) => [p.day, p.units]), itemStyle: { color: token("--accent") }, barMaxWidth: 6 }] };
  }, [sales.data, eff, chartTheme]); // eslint-disable-line react-hooks/exhaustive-deps -- recolour when the theme changes (token() reads CSS variables)

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
      {locations.length > 1 && (
        <div data-testid="stock-by-location">
          <Eyebrow>Stock by location</Eyebrow>
          <table className="mt-2 w-full text-sm"><caption className="sr-only">Stock of {item.sku_id} at each location</caption>
            <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-1 font-medium">Location</th>
              <th className="font-medium">Available</th><th className="font-medium">Days of cover</th><th className="font-medium">Status</th></tr></thead>
            <tbody>{locations.map((l) => (
              <tr key={l.location_id} className="border-b border-line/60"><td className="py-1"><Mono>{l.location_id}</Mono></td>
                <td className="num">{int(l.available)}</td><td className="num">{l.days_of_cover == null ? "—" : num(l.days_of_cover)}</td>
                <td><Status value={l.health} /></td></tr>))}</tbody></table>
          <p className="mt-1 text-xs text-muted">Figures below are for {item.location_id}; each location is planned and received separately.</p>
        </div>
      )}
      <KV items={[
        ["Location", <Mono key="l">{item.location_id}</Mono>],
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
        {sales.isLoading ? <Skeleton className="mt-2 h-40" /> : sales.error ? <QueryError q={sales} what="sales history" /> : sales.data?.daily.length ?
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

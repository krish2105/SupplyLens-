"use client";
import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { baseOption, Chart, token, useChartTheme } from "@/components/chart";
import { Button, Card, Empty, ErrorState, Eyebrow, Loading, Mono, PageHeader, Provenance, Stat } from "@/components/ui";
import { apiGet } from "@/lib/api";
import type { Schemas } from "@/lib/contract";
import { useApi, useWs } from "@/lib/queries";
import { day, int } from "@/lib/format";

const usd = (v: number | null | undefined) => v == null ? "—" : new Intl.NumberFormat("en-GB", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 }).format(v);

export default function MarketPage() {
  const ws = useWs();
  const [category, setCategory] = useState<string>("");
  const s = useApi(["market", category], "/api/v1/market/summary", { query: { category } });
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Schemas["SupplierHit"][] | null>(null);
  const [sel, setSel] = useState<Schemas["SupplierDetail"] | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const chartTheme = useChartTheme();     // chart colours follow the theme (audit S17)
  const yearOpt = useMemo(() => {
    if (!s.data?.available) return null;
    const b = baseOption();
    return { ...b, legend: { show: false }, xAxis: { ...(b.xAxis as object), type: "category", data: s.data.by_year.map((r) => `FY${r.fiscal_year}`) },
      yAxis: { ...(b.yAxis as object), type: "value", name: "USD bn", axisLabel: { formatter: (v: number) => v.toFixed(0) } },
      series: [{ type: "bar", name: "Award value (USD bn)", data: s.data.by_year.map((r) => +((r.usd ?? 0) / 1e9).toFixed(2)), itemStyle: { color: token("--accent") } }] };
  }, [s.data, chartTheme]); // eslint-disable-line react-hooks/exhaustive-deps -- recolour when the theme changes (token() reads CSS variables)
  async function find(e: React.FormEvent) {
    e.preventDefault(); setErr(null);
    try { setHits(await apiGet("/api/v1/market/suppliers", { query: { q }, tenant: ws })); } catch (x) { setErr(x); }
  }
  async function open(id: string) {
    try { setSel(await apiGet("/api/v1/market/suppliers/{supplier_id}", { path: { supplier_id: id }, tenant: ws })); } catch (x) { setErr(x); }
  }
  if (s.isLoading) return <Loading label="Loading awards" />;
  if (s.error) return <ErrorState error={s.error} />;
  if (!s.data?.available) return <><PageHeader eyebrow="Supplier market" title="Public procurement awards" /><Empty title="Not in this workspace">{s.data?.message}</Empty></>;
  const d = s.data;
  const total = d.by_year.reduce((a, r) => a + (r.usd ?? 0), 0), n = d.by_year.reduce((a, r) => a + r.n, 0);
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Supplier market" title="Who wins public supply contracts, where, and how concentrated it is">
        World Bank investment-project awards since FY2020 (CC BY 4.0). Real public records, independent of the UCI retailer and never joined to its products.
      </PageHeader>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Card className="p-4"><Stat label="Awards" value={int(n)} kind="observed" /></Card>
        <Card className="p-4"><Stat label="Award value" value={usd(total)} sub="as published, USD" /></Card>
        <Card className="p-4"><Stat label="Distinct suppliers" value={int((d.dataset?.report as { suppliers?: number } | undefined)?.suppliers)} sub="by World Bank supplier ID, all years" /></Card>
        <Card className="p-4"><label className="text-sm"><Eyebrow>Category</Eyebrow>
          <select value={category} onChange={(e) => setCategory(e.target.value)} className="mt-1 w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm">
            <option value="">All categories</option>{d.by_category.map((c) => <option key={c.procurement_category ?? "none"} value={c.procurement_category ?? ""}>{c.procurement_category ?? "Uncategorised"}</option>)}
          </select></label></Card>
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <Card className="p-5"><Eyebrow>Award value by World Bank fiscal year</Eyebrow>{yearOpt && <Chart option={yearOpt} height={260} label="Bar chart of award value by fiscal year" />}
          <p className="text-xs text-muted">{d.notes[0]}</p></Card>
        <Card className="p-5"><Eyebrow>Concentration by category (HHI)</Eyebrow>
          <table className="mt-3 w-full text-sm"><caption className="sr-only">Herfindahl-Hirschman index per procurement category</caption>
            <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Category</th><th className="font-medium">HHI</th><th className="font-medium">Suppliers</th><th className="font-medium">Reading</th></tr></thead>
            <tbody>{d.concentration_hhi.map((c) => (
              <tr key={c.procurement_category} className="border-b border-line/60"><td className="py-2">{c.procurement_category}</td><td className="num">{int(c.hhi)}</td>
                <td className="num">{int(c.suppliers)}</td><td className="text-xs text-muted">{c.hhi == null ? "n/a" : c.hhi < 1500 ? "unconcentrated" : c.hhi < 2500 ? "moderately concentrated" : "highly concentrated"}</td></tr>))}</tbody>
          </table><p className="mt-2 text-xs text-muted">{d.notes[1]}</p></Card>
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <Card className="p-5"><Eyebrow>Largest suppliers by award value</Eyebrow>
          <ol className="mt-3 space-y-1.5 text-sm">{d.top_suppliers.slice(0, 12).map((t, i) => (
            <li key={t.supplier_id} className="flex items-center gap-3"><span className="num w-5 text-xs text-muted">{i + 1}</span>
              <button className="min-w-0 flex-1 truncate text-left text-accent hover:underline" onClick={() => open(t.supplier_id)}>{t.supplier}</button>
              <span className="text-xs text-muted">{t.country}</span><span className="num w-20 text-right">{usd(t.usd)}</span></li>))}</ol></Card>
        <Card className="p-5"><Eyebrow>Supplier countries</Eyebrow>
          <ol className="mt-3 space-y-1.5 text-sm">{d.top_supplier_countries.map((c) => (
            <li key={c.supplier_country ?? "unknown"} className="flex items-center gap-3"><span className="min-w-0 flex-1 truncate">{c.supplier_country ?? "Not stated"}</span>
              <span className="num text-xs text-muted">{int(c.suppliers)} suppliers</span><span className="num w-20 text-right">{usd(c.usd)}</span></li>))}</ol></Card>
      </div>
      <Card className="p-5">
        <form onSubmit={find} className="flex flex-wrap items-end gap-3" role="search">
          <label className="min-w-[240px] flex-1 text-sm"><span className="mb-1 block font-medium">Find a supplier</span>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. Siemens" className="w-full rounded-lg border border-line bg-surface px-3 py-2" /></label>
          <Button type="submit" disabled={q.trim().length < 2}><Search className="size-4" aria-hidden /> Search awards</Button>
        </form>
        {err != null && <div className="mt-3"><ErrorState error={err} /></div>}
        {hits && (hits.length ? (
          <ul className="mt-4 divide-y divide-line">{hits.map((h) => (
            <li key={h.supplier_id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
              <button className="text-left font-medium text-accent hover:underline" onClick={() => open(h.supplier_id)}>{h.supplier}</button>
              <span className="text-xs text-muted">{h.country} · {int(h.n)} awards · {day(h.first_award)}–{day(h.last_award)}</span>
              <span className="num ml-auto">{usd(h.usd)}</span></li>))}</ul>) : <p className="mt-3 text-sm text-muted">No supplier matches.</p>)}
      </Card>
      {sel && (
        <Card className="p-5">
          <div className="flex items-center justify-between"><Eyebrow>Award history — {sel.awards[0]?.supplier}</Eyebrow><Provenance kind="observed" /></div>
          <div className="mt-3 max-h-96 overflow-auto" tabIndex={0} role="region" aria-label="Award history, scrollable">
            <table className="w-full text-sm"><caption className="sr-only">Contract awards for the selected supplier</caption>
              <thead className="sticky top-0 bg-surface"><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Signed</th><th className="font-medium">Borrower</th><th className="font-medium">Category</th><th className="font-medium">Contract</th><th className="font-medium">Value</th></tr></thead>
              <tbody>{sel.awards.map((a) => (
                <tr key={`${a.wb_contract_number}|${a.signing_date}|${a.amount_usd}`} className="border-b border-line/60 align-top"><td className="num py-1.5 text-xs">{day(a.signing_date)}</td>
                  <td className="text-xs">{a.borrower_country}</td><td className="text-xs">{a.procurement_category}</td>
                  <td className="max-w-md text-xs text-muted">{a.contract_description}<br /><Mono>{a.project_id}</Mono></td><td className="num">{usd(a.amount_usd)}</td></tr>))}</tbody>
            </table></div>
        </Card>
      )}
    </div>
  );
}

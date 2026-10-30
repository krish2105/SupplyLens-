"use client";
// 2D floor plan: full functional parity with the 3D scene, keyboard operable (BUS-009).
import clsx from "clsx";
import type { InventoryItem } from "@/lib/queries";
import { num } from "@/lib/format";

const TONE: Record<string, string> = {
  shortage_risk: "border-danger bg-danger-soft text-danger",
  excess: "border-risk bg-risk-soft text-risk",
  healthy: "border-accent/60 bg-accent-soft text-accent",
  no_sales_data: "border-line bg-surface-2 text-muted",
};

/** The part of every code before its last "-" that all codes share ("DEMO-SKU-" for DEMO-SKU-001…), or "" if none. */
export function sharedPrefix(codes: string[]): string {
  if (codes.length < 2) return "";
  let p = codes[0] ?? "";
  for (const c of codes) while (!c.startsWith(p)) p = p.slice(0, -1);
  const cut = p.lastIndexOf("-");
  return cut > 0 && codes.every((c) => c.length > cut + 1) ? p.slice(0, cut + 1) : "";
}

export function FloorPlan({ items, selected, onSelect }: { items: InventoryItem[]; selected: string | null; onSelect: (s: string | null) => void }) {
  const zones = Array.from(new Set(items.map((i) => i.zone_id))).sort();
  // A tile is ~70 px wide on a phone: a shared prefix truncated every code to "DEMO-SK…". Show what tells tiles apart;
  // the full code stays in the accessible name and the tooltip.
  const prefix = sharedPrefix(items.map((i) => i.sku_id));
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {zones.map((z) => (
        <fieldset key={z} className="rounded-xl border border-line p-3">
          <legend className="px-1 text-xs font-semibold text-muted">{z.replace("DEMO-", "").replace("-", " ")}</legend>
          <div className="grid grid-cols-4 gap-1.5">
            {items.filter((i) => i.zone_id === z).sort((a, b) => (a.slot_id ?? "").localeCompare(b.slot_id ?? "")).map((i) => (
              <button key={`${i.sku_id}@${i.location_id}`} onClick={() => onSelect(i.sku_id === selected ? null : i.sku_id)}
                aria-pressed={i.sku_id === selected}
                aria-label={`${i.sku_id}, slot ${i.slot_id} at ${i.location_id}, ${i.health.replaceAll("_", " ")}, ${i.days_of_cover == null ? "no sales data" : num(i.days_of_cover) + " days of cover"}`}
                className={clsx("rounded-md border px-1.5 py-1 text-left", TONE[i.health] ?? TONE.no_sales_data,
                  i.sku_id === selected && "ring-2 ring-accent ring-offset-2 ring-offset-surface")}>
                <span className="num block truncate text-[11px] font-semibold" title={i.sku_id}>{i.sku_id.slice(prefix.length)}</span>
                <span className="num block text-[10px]">{i.days_of_cover == null ? "—" : `${num(i.days_of_cover, 0)}d`}</span>
              </button>
            ))}
          </div>
        </fieldset>
      ))}
    </div>
  );
}

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

export function FloorPlan({ items, selected, onSelect }: { items: InventoryItem[]; selected: string | null; onSelect: (s: string | null) => void }) {
  const zones = Array.from(new Set(items.map((i) => i.zone_id))).sort();
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {zones.map((z) => (
        <fieldset key={z} className="rounded-xl border border-line p-3">
          <legend className="px-1 text-xs font-semibold text-muted">{z.replace("DEMO-", "").replace("-", " ")}</legend>
          <div className="grid grid-cols-4 gap-1.5">
            {items.filter((i) => i.zone_id === z).sort((a, b) => (a.slot_id ?? "").localeCompare(b.slot_id ?? "")).map((i) => (
              <button key={i.sku_id} onClick={() => onSelect(i.sku_id === selected ? null : i.sku_id)}
                aria-pressed={i.sku_id === selected}
                aria-label={`${i.sku_id}, slot ${i.slot_id}, ${i.health.replace("_", " ")}, ${i.days_of_cover == null ? "no sales data" : num(i.days_of_cover) + " days of cover"}`}
                className={clsx("rounded-md border px-1.5 py-1 text-left", TONE[i.health] ?? TONE.no_sales_data,
                  i.sku_id === selected && "ring-2 ring-accent ring-offset-2 ring-offset-surface")}>
                <span className="num block truncate text-[11px] font-semibold">{i.sku_id}</span>
                <span className="num block text-[10px] opacity-80">{i.days_of_cover == null ? "—" : `${num(i.days_of_cover, 0)}d`}</span>
              </button>
            ))}
          </div>
        </fieldset>
      ))}
    </div>
  );
}

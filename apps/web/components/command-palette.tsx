"use client";
// ⌘K / Ctrl+K command palette: navigate, jump to a product, switch workspace or theme.
import * as Dialog from "@radix-ui/react-dialog";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "next-themes";
import clsx from "clsx";
import { Search } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { setTenant } from "@/lib/api";
import { useApi, useMe } from "@/lib/queries";
import { usePlanningContext } from "@/lib/state";

export type NavItem = { href: string; label: string; group: string };
type Cmd = { id: string; label: string; hint: string; run: () => void };

export function CommandPalette({ nav }: { nav: NavItem[] }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const router = useRouter();
  const qc = useQueryClient();
  const { setTheme } = useTheme();
  const me = useMe();
  const [ctx, setCtx] = usePlanningContext();
  const inv = useApi(["inventory", "workspace"], open ? "/api/v1/inventory" : null);
  const list = useRef<HTMLUListElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setIdx(0); setOpen((o) => !o); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const cmds = useMemo<Cmd[]>(() => {
    const go = (pathname: string, query: Record<string, string> = {}) => () => {
      router.push(`${pathname}?${new URLSearchParams({ ws: ctx.ws, ...query })}`); setOpen(false);
    };
    const all: Cmd[] = [
      ...nav.map((n) => ({ id: `nav:${n.href}`, label: n.label, hint: `Go to · ${n.group}`, run: go(n.href) })),
      ...(me.data?.memberships ?? []).filter((m) => m.slug !== ctx.ws).map((m) => ({
        id: `ws:${m.slug}`, label: `Switch to ${m.name}`, hint: "Workspace",
        run: () => { qc.cancelQueries(); setTenant(m.slug); setCtx({ ws: m.slug, sku: null, known: null, eff: null, action: null, run: null }); setOpen(false); } })),
      ...["light", "dark", "system"].map((t) => ({ id: `theme:${t}`, label: `Theme: ${t}`, hint: "Appearance", run: () => { setTheme(t); setOpen(false); } })),
      ...(inv.data?.items ?? []).filter((i, n, all) => all.findIndex((x) => x.sku_id === i.sku_id) === n).map((i) => ({ id: `sku:${i.sku_id}`, label: `${i.sku_id} — ${i.description}`, hint: "Product · open in inventory",
        run: go("/inventory", { sku: i.sku_id }) })),
    ];
    const s = q.trim().toLowerCase();
    return (s ? all.filter((c) => c.label.toLowerCase().includes(s) || c.hint.toLowerCase().includes(s)) : all).slice(0, 40);
  }, [nav, me.data, ctx.ws, inv.data, q, router, setCtx, setTheme, qc]);

  return (
    <Dialog.Root open={open} onOpenChange={(o) => { setIdx(0); setOpen(o); }}>
      <Dialog.Trigger asChild>
        {/* An icon on phones (no keyboard shortcut there), the full search box from tablet width up. */}
        <button className="inline-flex size-8 items-center justify-center gap-2 rounded-lg border border-line bg-surface text-sm text-muted hover:text-ink md:size-auto md:px-3 md:py-1.5" aria-label="Open command palette">
          <Search className="size-3.5" aria-hidden /> <span className="hidden md:inline">Search or jump to…</span>
          <kbd className="num hidden rounded border border-line px-1 text-[10px] md:inline">⌘K</kbd>
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className="card fixed left-1/2 top-[12vh] z-50 w-[min(640px,calc(100vw-2rem))] -translate-x-1/2 p-0"
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, cmds.length - 1)); }
            if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); }
            if (e.key === "Enter") { e.preventDefault(); cmds[idx]?.run(); }
          }}>
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          <Dialog.Description className="sr-only">Type to filter pages, products, workspaces and themes. Use arrow keys and Enter.</Dialog.Description>
          <div className="flex items-center gap-2 border-b border-line px-4">
            <Search className="size-4 text-muted" aria-hidden />
            <input autoFocus value={q} onChange={(e) => { setQ(e.target.value); setIdx(0); }} placeholder="Type a page, product code or command"
              role="combobox" aria-label="Search pages, products and commands" aria-expanded aria-controls="cmd-list" aria-activedescendant={cmds[idx] ? `cmd-${idx}` : undefined}
              className="h-12 flex-1 bg-transparent text-sm outline-none" />
          </div>
          <ul id="cmd-list" role="listbox" ref={list} className="max-h-[50vh] overflow-auto p-2">
            {cmds.map((c, i) => (
              <li key={c.id} id={`cmd-${i}`} role="option" aria-selected={i === idx}
                onMouseEnter={() => setIdx(i)} onClick={c.run}
                className={clsx("flex cursor-pointer items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm", i === idx && "bg-accent-soft")}>
                <span className="truncate">{c.label}</span><span className="shrink-0 text-xs text-muted">{c.hint}</span>
              </li>
            ))}
            {inv.error && <li role="option" aria-selected={false} aria-disabled className="px-3 py-2 text-sm text-danger">Products could not be loaded; pages and commands still work.</li>}
            {!cmds.length && <li className="px-3 py-6 text-center text-sm text-muted">Nothing matches “{q}”.</li>}
          </ul>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

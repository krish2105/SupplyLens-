"use client";
import { useMemo, useState } from "react";
import { Search, ShieldAlert } from "lucide-react";
import { useDecisionClock } from "@/components/clock-rail";
import { Button, Card, Empty, ErrorState, Eyebrow, KV, Loading, Mono, PageHeader, Provenance, Status } from "@/components/ui";
import { apiGet } from "@/lib/api";
import type { Schemas } from "@/lib/contract";
import { useApi, useWs } from "@/lib/queries";
import { usePlanningContext } from "@/lib/state";
import { atOrBefore, dateTime, day, short } from "@/lib/format";

type Doc = Schemas["DocumentRow"];
type SearchRes = Schemas["EvidenceSearch"];

export default function PoliciesPage() {
  const ws = useWs();
  const [ctx] = usePlanningContext();
  const { known, eff } = useDecisionClock();
  const docs = useApi(["documents"], "/api/v1/documents");
  const [q, setQ] = useState(ctx.sku ? `minimum order quantity ${ctx.sku}` : "minimum order quantity lead time");
  const [mode, setMode] = useState<"effective" | "known">("effective");
  const [res, setRes] = useState<SearchRes | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<{ version: string; highlight?: string } | null>(null);
  const [compare, setCompare] = useState<[string, string] | null>(null);

  async function run(e?: React.FormEvent) {
    e?.preventDefault();
    setBusy(true); setErr(null);
    try {
      setRes(await apiGet("/api/v1/evidence/search", { query: { q, mode, k: 8, knowledge_cutoff: known, effective_date: eff }, tenant: ws }));
    } catch (x) { setErr(x); } finally { setBusy(false); }
  }

  const bySupplier = useMemo(() => {
    const m = new Map<string, Doc[]>();
    for (const d of docs.data ?? []) m.set(d.document_id, [...(m.get(d.document_id) ?? []), d]);
    return [...m.values()];
  }, [docs.data]);

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Policies & evidence" title="Supplier terms, versions and citations">
        Search respects both clocks: only documents known by the cutoff, and in “in force” mode only versions in force on the effective date.
      </PageHeader>
      <div role="note" className="flex gap-3 rounded-xl border border-line bg-surface p-3 text-sm text-muted">
        <ShieldAlert className="mt-0.5 size-4 shrink-0 text-risk" aria-hidden />
        Document text is untrusted data. It is quoted as evidence and never followed as an instruction: it cannot change budgets, permissions, suppliers or destinations.
      </div>

      <Card className="p-5">
        <form onSubmit={run} className="flex flex-wrap items-end gap-3" role="search">
          <label className="min-w-[280px] flex-1 text-sm"><span className="mb-1 block font-medium">Question</span>
            <input value={q} onChange={(e) => setQ(e.target.value)} maxLength={500} className="w-full rounded-lg border border-line bg-surface px-3 py-2" /></label>
          <fieldset className="text-sm"><legend className="mb-1 font-medium">Versions</legend>
            <div className="inline-flex rounded-lg border border-line p-0.5">
              {([["effective", "In force on date"], ["known", "All known by cutoff"]] as const).map(([v, l]) => (
                <label key={v} className={`cursor-pointer rounded-md px-3 py-1.5 ${mode === v ? "bg-accent text-accent-ink" : "text-muted"}`}>
                  <input type="radio" className="sr-only" name="mode" checked={mode === v} onChange={() => setMode(v)} />{l}
                </label>
              ))}
            </div></fieldset>
          <Button type="submit" busy={busy} disabled={!q.trim()}><Search className="size-4" aria-hidden /> Search evidence</Button>
        </form>
        {err != null && <div className="mt-4"><ErrorState error={err} /></div>}
        {res && (
          <div className="mt-5 space-y-4" aria-live="polite">
            <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
              <Status value={res.mode === "hybrid" ? "VERIFIED_LOCALLY" : "DEGRADED"} />
              <span>{res.mode === "hybrid" ? "Hybrid: lexical full-text + bge-m3 vectors, reciprocal-rank fusion" : res.degraded}</span>
              <span>· {res.reranker}</span>
            </div>
            {res.answer.abstained ? (
              <Empty title="No permitted evidence found">{res.answer.message}</Empty>
            ) : (
              <div className="rounded-xl border-l-4 border-accent bg-accent-soft/50 p-4">
                <Eyebrow>Best supporting passage (extracted, not generated)</Eyebrow>
                <blockquote className="mt-2 whitespace-pre-wrap text-sm">{res.answer.claims[0]!.text}</blockquote>
                <p className="mt-2 text-xs text-muted">Cited: {res.answer.claims[0]!.citation.version_label} · {res.answer.claims[0]!.citation.section}</p>
              </div>
            )}
            <ol className="space-y-2">
              {res.results.map((r, i) => (
                <li key={r.chunk_id} className="rounded-xl border border-line p-3">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="num text-xs text-muted">#{i + 1}</span>
                    <span className="font-medium">{r.title}</span><span className="text-muted">— {r.version_label}</span>
                    <Provenance kind={r.source_kind === "generated" ? "simulated" : "observed"} />
                    {r.signals.superseded_in_results ? <Status value="STALE" /> : null}
                    <button className="ml-auto text-xs text-accent hover:underline" onClick={() => setOpen({ version: r.version_id, highlight: r.chunk_id })}>Open at passage</button>
                  </div>
                  <p className="mt-1 text-xs text-muted">{r.section} · known {day(r.known_at)} · in force {day(r.valid_from)}{r.valid_to ? `–${day(r.valid_to)}` : ""}</p>
                  <p className="mt-2 line-clamp-3 whitespace-pre-wrap text-sm">{r.excerpt}</p>
                  <p className="num mt-1 text-[11px] text-muted">{Object.entries(r.signals).map(([k, v]) => `${k}=${Array.isArray(v) ? v.join("/") : v}`).join("  ")}</p>
                </li>
              ))}
            </ol>
          </div>
        )}
      </Card>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <Card className="p-5">
          <Eyebrow>Documents and versions</Eyebrow>
          {docs.isLoading ? <Loading /> : docs.error ? <ErrorState error={docs.error} /> : (
            <ul className="mt-3 max-h-[640px] space-y-3 overflow-auto pr-1" tabIndex={0} aria-label="Documents, scrollable">
              {bySupplier.map((versions) => (
                <li key={versions[0]!.document_id} className="rounded-xl border border-line p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{versions[0]!.title}</span>
                    {versions.length > 1 && (
                      <Button size="sm" variant="outline" onClick={() => setCompare([versions[0]!.version_id, versions[versions.length - 1]!.version_id])}>Compare versions</Button>
                    )}
                  </div>
                  <ul className="mt-2 space-y-1">
                    {versions.map((v) => {
                      const knownYet = known ? atOrBefore(v.known_at, known) : true;
                      const inForce = eff ? v.valid_from <= eff && (!v.valid_to || v.valid_to >= eff) : false;
                      return (
                        <li key={v.version_id} className="flex flex-wrap items-center gap-2 text-sm">
                          <button className="text-accent hover:underline" onClick={() => setOpen({ version: v.version_id })}>{v.version_label}</button>
                          <span className="text-xs text-muted">known {day(v.known_at)} · from {day(v.valid_from)}{v.valid_to ? ` to ${day(v.valid_to)}` : ""}</span>
                          {!knownYet ? <Status value="NOT_CONFIGURED" /> : inForce ? <Status value="available" /> : null}
                          {!knownYet && <span className="text-xs text-muted">not yet known at cutoff</span>}
                        </li>
                      );
                    })}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <div className="space-y-6">
          {compare ? <CompareVersions ids={compare} ws={ws} onClose={() => setCompare(null)} /> :
            open ? <Viewer id={open.version} highlight={open.highlight} ws={ws} /> :
              <Card className="p-5"><Empty title="Open a document version">Pick a version or a search result to read it with the cited passage highlighted.</Empty></Card>}
        </div>
      </div>
    </div>
  );
}

function useVersion(id: string, _ws: string) {
  return useApi(["version", id], "/api/v1/documents/versions/{version_id}", { path: { version_id: id } });
}

type Label = Schemas["ClauseLabel"];

function Viewer({ id, highlight, ws }: { id: string; highlight?: string; ws: string }) {
  const v = useVersion(id, ws);
  const labels = useApi(["labels", id], "/api/v1/documents/versions/{version_id}/labels", { path: { version_id: id } });
  const [label, setLabel] = useState<Label | null>(null);
  if (v.isLoading) return <Card className="p-5"><Loading /></Card>;
  if (v.error || !v.data) return <Card className="p-5"><ErrorState error={v.error} /></Card>;
  const hc = v.data.chunks.find((c) => c.id === highlight);
  const h = label ? { char_start: label.char_start, char_end: label.char_end } : hc;
  const t = v.data.text;
  const cats = Array.from(new Set((labels.data ?? []).map((l) => l.category))).filter((c) => !["Document Name", "Parties"].includes(c));
  return (
    <Card className="p-5">
      <Eyebrow>{v.data.title} — {v.data.version_label}</Eyebrow>
      <div className="mt-3"><KV items={[
        ["File", <Mono key="f">{v.data.file_name}</Mono>], ["SHA-256", <Mono key="h">{short(v.data.sha256, 16)}…</Mono>],
        ["Known at", dateTime(v.data.known_at)], ["In force", `${day(v.data.valid_from)}${v.data.valid_to ? ` – ${day(v.data.valid_to)}` : " onwards"}`],
        ["Supersedes", v.data.supersedes_version_id ? <Mono key="s">{short(v.data.supersedes_version_id)}</Mono> : "—"],
        ["Embeddings", v.data.embed_model ?? "none (lexical only)"],
      ]} /></div>
      <pre tabIndex={0} aria-label="Document text, scrollable" className="mt-4 max-h-[460px] overflow-auto whitespace-pre-wrap rounded-xl bg-surface-2 p-4 text-[13px] leading-relaxed">
        {h ? <>{t.slice(0, h.char_start)}<mark ref={(el) => { const pre = el?.closest("pre"); if (el && pre) pre.scrollTop = el.offsetTop - pre.offsetTop - 80; }} className="rounded bg-risk-soft px-0.5 text-ink">{t.slice(h.char_start, h.char_end)}</mark>{t.slice(h.char_end)}</> : t}
      </pre>
    </Card>
  );
}

function CompareVersions({ ids, ws, onClose }: { ids: [string, string]; ws: string; onClose: () => void }) {
  const a = useVersion(ids[0], ws), b = useVersion(ids[1], ws);
  if (a.isLoading || b.isLoading) return <Card className="p-5"><Loading /></Card>;
  if (!a.data || !b.data) return <Card className="p-5"><ErrorState error={a.error ?? b.error} /></Card>;
  const bLines = new Set(b.data.text.split("\n").map((l) => l.trim()));
  const aLines = new Set(a.data.text.split("\n").map((l) => l.trim()));
  const render = (text: string, other: Set<string>, tone: string) => text.split("\n").map((l, i) => (
    <div key={i} className={l.trim() && !other.has(l.trim()) ? tone : ""}>{l || " "}</div>
  ));
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between"><Eyebrow>Side-by-side amendment</Eyebrow><Button size="sm" variant="ghost" onClick={onClose}>Close</Button></div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        {[a.data, b.data].map((v, i) => (
          <div key={i}>
            <p className="text-sm font-medium">{v.version_label} <span className="text-xs text-muted">in force {day(v.valid_from)}</span></p>
            <pre tabIndex={0} aria-label="Version text, scrollable" className="mt-2 max-h-[420px] overflow-auto whitespace-pre-wrap rounded-xl bg-surface-2 p-3 text-[12px] leading-relaxed">
              {render(v.text, i === 0 ? bLines : aLines, i === 0 ? "bg-danger-soft" : "bg-accent-soft")}
            </pre>
          </div>
        ))}
      </div>
      <p className="mt-2 text-xs text-muted">Highlighted lines differ between versions. An amendment applies only from its own effective date.</p>
    </Card>
  );
}

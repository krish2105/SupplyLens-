"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FilePlus2, Search, ShieldAlert } from "lucide-react";
import { useDecisionClock } from "@/components/clock-rail";
import { Button, Card, Empty, ErrorState, Eyebrow, KV, Loading, Mono, PageHeader, Provenance, QueryError, Status } from "@/components/ui";
import { EmptyState } from "@/components/illustration";
import { api, apiGet } from "@/lib/api";
import type { Schemas } from "@/lib/contract";
import { useApi, useDemoLockdown, useMe, useWs } from "@/lib/queries";
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
  // reveal: the reader was opened from the list or a citation, so it is brought into view (below)
  const [open, setOpen] = useState<{ version: string; highlight?: string; reveal?: boolean } | null>(null);
  const [compare, setCompare] = useState<[string, string] | null>(null);
  // Below xl the reader sits under the document list: opening a version or a comparison there happened off-screen.
  // Bring it into view (and focus it, so keyboard and screen-reader users land on it) only when it is out of sight, only
  // when the reader asked for it (not after an upload, where the user carries on in the form), and only if focus is still
  // where the click left it: moving focus a frame later could land in a field the user had moved to and swallow typing.
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = panel.current;
    if (!el || !(compare || open?.reveal)) return;
    const from = document.activeElement;
    const frame = requestAnimationFrame(() => {
      if (document.activeElement !== from) return;
      const top = el.getBoundingClientRect().top;
      if (top >= 0 && top <= window.innerHeight * 0.75) return;
      el.focus({ preventScroll: true });       // focus first: focusing during a smooth scroll cancels the scroll
      el.scrollIntoView({ block: "start", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    });
    return () => cancelAnimationFrame(frame);
  }, [compare, open]);

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
              {/* Retrieval mode describes how passages were found, not whether a claim is true (audit S16). */}
              <span className="rounded-md border border-line bg-surface-2 px-2 py-0.5 font-semibold text-ink">Retrieval: {res.mode === "hybrid" ? "hybrid" : res.mode}</span>
              <span>{res.mode === "hybrid" ? "lexical full-text + bge-m3 vectors, reciprocal-rank fusion" : res.degraded}</span>
              <span>· {res.answer.support?.ambiguous ? "several suppliers match; no single answer" : res.answer.abstained
                ? "no passage supports an answer" : "best passage extracted verbatim; not a verified answer"}</span>
              <span>· {res.reranker}</span>
            </div>
            {res.answer.abstained ? (
              <Empty title={res.answer.support?.ambiguous ? "More than one supplier matches"
                : res.results.length ? "No passage answers this question" : "No permitted evidence found"}>{res.answer.message}</Empty>
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
                    <button className="ml-auto text-xs text-accent hover:underline" onClick={() => setOpen({ version: r.version_id, highlight: r.chunk_id, reveal: true })}>Open at passage</button>
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
          {docs.data && docs.data.length > 0 && docs.data.some((d) => d.supersedes_version_id) && (
            <div className="mt-3"><EmptyState variant="first_run" art="policy-change" title="See how source changes affect decisions" compact>
              Amendments below supersede earlier versions from their effective date. Drafts approved under an older version go back to review before anything is sent.</EmptyState></div>
          )}
          {docs.isLoading ? <Loading /> : docs.error ? <ErrorState error={docs.error} /> : docs.data?.length === 0 ? (
            <div className="mt-3"><EmptyState variant="empty_scope" art="empty-evidence" title="No source documents you can read here" compact>
              Agreements and amendments appear here once ingested. Documents restricted for your role are not listed.</EmptyState></div>
          ) : (
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
                          <button className="text-accent hover:underline" onClick={() => setOpen({ version: v.version_id, reveal: true })}>{v.version_label}</button>
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
        {/* an open reader reserves a screen's height on stacked layouts: the page is tall enough to scroll it to the top while
            the text is still loading (otherwise the scroll stops short and the reader is left peeking in at the bottom) */}
        <div ref={panel} tabIndex={-1} aria-label="Document reader" role="region"
          className={clsx("scroll-mt-4 space-y-6 outline-none", (compare || open) && "min-h-[85svh] xl:min-h-0")}>
          {compare ? <CompareVersions ids={compare} onClose={() => setCompare(null)} /> :
            open ? <Viewer id={open.version} highlight={open.highlight} /> :
              <Card className="p-5"><Empty title="Open a document version">Pick a version or a search result to read it with the cited passage highlighted.</Empty></Card>}
        </div>
      </div>
      <AddDocument versions={docs.data ?? []} onAdded={(version) => { setCompare(null); setOpen({ version }); }} />
    </div>
  );
}

function useVersion(id: string) {
  return useApi(["version", id], "/api/v1/documents/versions/{version_id}", { path: { version_id: id } });
}

type Label = Schemas["ClauseLabel"];

function Viewer({ id, highlight }: { id: string; highlight?: string }) {
  const v = useVersion(id);
  const labels = useApi(["labels", id], "/api/v1/documents/versions/{version_id}/labels", { path: { version_id: id } });
  const [label, setLabel] = useState<Label | null>(null);
  if (v.isLoading) return <Card className="p-5"><Loading /></Card>;
  if (v.error || !v.data) return <Card className="p-5"><ErrorState error={v.error} /></Card>;
  const hc = v.data.chunks.find((c) => c.id === highlight);
  const h = label ? { char_start: label.char_start, char_end: label.char_end } : hc;
  const t = v.data.text;
  // Expert clause labels (CUAD): one button per category; pressing it marks that clause in the text, pressing it again moves
  // to the category's next occurrence. Document name and parties are bookkeeping, not clauses.
  const byCat = new Map<string, Label[]>();
  for (const l of labels.data ?? []) {
    if (["Document Name", "Parties"].includes(l.category)) continue;
    byCat.set(l.category, [...(byCat.get(l.category) ?? []), l]);
  }
  const cats = Array.from(byCat.keys()).sort();
  const pick = (c: string) => {
    const xs = byCat.get(c)!;
    const at = label && label.category === c ? xs.indexOf(label) : -1;
    setLabel(xs[(at + 1) % xs.length]!);
  };
  return (
    <Card className="p-5">
      <Eyebrow>{v.data.title} — {v.data.version_label}</Eyebrow>
      <div className="mt-3"><KV items={[
        ["File", <Mono key="f">{v.data.file_name}</Mono>], ["SHA-256", <Mono key="h">{short(v.data.sha256, 16)}…</Mono>],
        ["Known at", dateTime(v.data.known_at)], ["In force", `${day(v.data.valid_from)}${v.data.valid_to ? ` – ${day(v.data.valid_to)}` : " onwards"}`],
        ["Supersedes", v.data.supersedes_version_id ? <Mono key="s">{short(v.data.supersedes_version_id)}</Mono> : "—"],
        ["Embeddings", v.data.embed_model ?? "none (lexical only)"],
      ]} /></div>
      {labels.error ? <QueryError q={labels} what="expert clause labels" /> : cats.length > 0 && (
        <section aria-labelledby={`labels-${id}`} className="mt-4" data-testid="clause-labels">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 id={`labels-${id}`} className="text-sm font-semibold">Expert clause labels <span className="font-normal text-muted">({labels.data!.length} from {labels.data![0]!.source})</span></h3>
            {label && <Button size="sm" variant="ghost" onClick={() => setLabel(null)}>Clear highlight</Button>}
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {cats.map((c) => {
              const n = byCat.get(c)!.length;
              const on = label?.category === c;
              return (
                <button key={c} onClick={() => pick(c)} aria-pressed={on}
                  className={`rounded-full border px-2.5 py-1 text-xs ${on ? "border-accent bg-accent-soft text-accent" : "border-line hover:bg-surface-2"}`}>
                  {c}{n > 1 && <span className="num ml-1 text-muted">{on ? `${byCat.get(c)!.indexOf(label!) + 1}/${n}` : n}</span>}
                </button>);
            })}
          </div>
          {label && <p role="status" className="mt-2 text-xs text-muted">Highlighted: <b className="text-ink">{label.category}</b>, characters {label.char_start}–{label.char_end}.</p>}
        </section>
      )}
      <pre tabIndex={0} aria-label="Document text, scrollable" className="mt-4 max-h-[460px] overflow-auto whitespace-pre-wrap rounded-xl bg-surface-2 p-4 text-[13px] leading-relaxed">
        {h ? <>{t.slice(0, h.char_start)}<mark ref={(el) => { const pre = el?.closest("pre"); if (el && pre) pre.scrollTop = el.offsetTop - pre.offsetTop - 80; }} className="rounded bg-risk-soft px-0.5 text-ink">{t.slice(h.char_start, h.char_end)}</mark>{t.slice(h.char_end)}</> : t}
      </pre>
    </Card>
  );
}

function CompareVersions({ ids, onClose }: { ids: [string, string]; onClose: () => void }) {
  const a = useVersion(ids[0]), b = useVersion(ids[1]);
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

type Uploaded = Schemas["DocumentUploaded"];

/** Journey 4: a workspace administrator adds a supplier document or a new version of one (plain text). It is known from
 *  the moment it is uploaded; the user says when it is in force. An amendment joins its document's history. */
function AddDocument({ versions, onAdded }: { versions: Doc[]; onAdded: (versionId: string) => void }) {
  const ws = useWs();
  const qc = useQueryClient();
  const me = useMe();
  const locked = useDemoLockdown();
  const admin = me.data?.memberships.find((m) => m.slug === ws)?.role === "tenant_admin";
  const [file, setFile] = useState<File | null>(null);
  const [f, setF] = useState({ title: "", doc_type: "contract", version_label: "v1", valid_from: "", valid_to: "", supplier_id: "", supersedes_version_id: "" });
  const [done, setDone] = useState<Uploaded | null>(null);
  const add = useMutation({
    mutationFn: () => {
      const body = new FormData();
      for (const [k, v] of Object.entries(f)) if (v) body.append(k, v);
      body.append("file", file!);
      return api<Uploaded>("/api/v1/documents", { method: "POST", body });
    },
    onSuccess: (r) => {
      setDone(r); setFile(null);
      setF({ title: "", doc_type: "contract", version_label: "v1", valid_from: "", valid_to: "", supplier_id: "", supersedes_version_id: "" });
      qc.invalidateQueries({ queryKey: [ws, "documents"] });
      onAdded(r.version_id);
    },
  });
  if (!admin) return null;
  const amends = versions.find((v) => v.version_id === f.supersedes_version_id);
  const input = "mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm";
  return (
    <Card className="p-5" aria-labelledby="add-doc">
      <h2 id="add-doc" className="flex items-center gap-2 text-sm font-semibold"><FilePlus2 className="size-4" aria-hidden /> Add a document or a new version</h2>
      <p className="mt-1 text-sm text-muted">Plain text (.txt or .md, up to 1 MB). It is known from the moment you add it — earlier replays never cite it —
        and in force from the date you give. Sections start at lines beginning with “#”, “Section”, “Clause” or “Schedule”.</p>
      {locked ? <p role="note" className="mt-3 text-sm text-muted">Adding documents is disabled in the public demo.</p> : (
        <form className="mt-4 grid gap-3 md:grid-cols-2" onSubmit={(e) => { e.preventDefault(); setDone(null); add.mutate(); }}>
          <label className="text-sm md:col-span-2"><span className="font-medium">Amends an existing version (optional)</span>
            <select value={f.supersedes_version_id} className={input}
              onChange={(e) => {
                const v = versions.find((x) => x.version_id === e.target.value);
                setF({ ...f, supersedes_version_id: e.target.value, title: v ? v.title : f.title, doc_type: v ? "amendment" : "contract",
                  supplier_id: v?.supplier_id ?? f.supplier_id });
              }}>
              <option value="">No — a new document</option>
              {versions.map((v) => <option key={v.version_id} value={v.version_id}>{v.title} — {v.version_label} (from {day(v.valid_from)})</option>)}
            </select></label>
          <label className="text-sm"><span className="font-medium">Title</span>
            <input required maxLength={300} value={f.title} disabled={!!amends} onChange={(e) => setF({ ...f, title: e.target.value })} className={input} /></label>
          <label className="text-sm"><span className="font-medium">Version label</span>
            <input required maxLength={50} value={f.version_label} onChange={(e) => setF({ ...f, version_label: e.target.value })} className={input} /></label>
          <label className="text-sm"><span className="font-medium">Type</span>
            <select value={f.doc_type} onChange={(e) => setF({ ...f, doc_type: e.target.value })} className={input}>
              <option value="contract">Contract</option><option value="amendment">Amendment</option><option value="policy">Policy</option></select></label>
          <label className="text-sm"><span className="font-medium">Supplier id (optional)</span>
            <input value={f.supplier_id} disabled={!!amends} onChange={(e) => setF({ ...f, supplier_id: e.target.value })} className={input} /></label>
          <label className="text-sm"><span className="font-medium">In force from</span>
            <input type="date" required min={amends?.valid_from} value={f.valid_from} onChange={(e) => setF({ ...f, valid_from: e.target.value })} className={input} /></label>
          <label className="text-sm"><span className="font-medium">In force until (optional)</span>
            <input type="date" min={f.valid_from || undefined} value={f.valid_to} onChange={(e) => setF({ ...f, valid_to: e.target.value })} className={input} /></label>
          <label className="text-sm md:col-span-2"><span className="font-medium">Text file</span>
            <input type="file" required accept=".txt,.md,text/plain,text/markdown" onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="mt-1 block w-full text-sm file:mr-3 file:rounded-md file:border file:border-line file:bg-surface-2 file:px-3 file:py-1.5" /></label>
          <div className="md:col-span-2">
            <Button type="submit" busy={add.isPending} disabled={!file}>Add {amends ? "amendment" : "document"}</Button>
          </div>
        </form>
      )}
      {add.error != null && <div className="mt-3"><ErrorState error={add.error} /></div>}
      {done && <p role="status" className="mt-3 text-sm" data-testid="document-added">Added: {done.chunks} passages, known from {dateTime(done.known_at)}
        {done.embedded ? "" : " (lexical search only: the embedding service did not answer)"}. It is open above.</p>}
    </Card>
  );
}

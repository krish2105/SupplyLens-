"use client";
// CSV onboarding wizard (audit S18): upload -> map -> validate (quarantine) -> publish an immutable snapshot.
// Every step is a real API call with a durable batch id; nothing is published until the administrator says so.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { FileUp, FolderPlus, ShieldCheck, Upload } from "lucide-react";
import { Button, Card, ErrorState, Eyebrow, Mono, Status } from "@/components/ui";
import { api, apiPost, intentKey } from "@/lib/api";
import type { Schemas } from "@/lib/contract";
import { useApi, useWs } from "@/lib/queries";
import { usePlanningContext } from "@/lib/state";
import { dateTime, int, short } from "@/lib/format";

type Batch = Schemas["ImportBatch"];
type Kind = "sales" | "stock" | "terms" | "receipts";
const KIND_COPY: Record<Kind, string> = {
  sales: "Daily units sold per product and location. Becomes the forecasting history.",
  stock: "A stock snapshot per location and product on a date.",
  terms: "Supplier prices, MOQ, pack size and lead time with the dates they apply and became known.",
  receipts: "Goods receipts from your ERP against SupplyLens orders: moves units from on-order to on-hand, once per receipt id.",
};

export function Onboarding({ admin }: { admin: boolean }) {
  const ws = useWs();
  const qc = useQueryClient();
  const batches = useApi(["import-batches"], "/api/v1/onboarding/batches");
  const [batch, setBatch] = useState<Batch | null>(null);
  const [kind, setKind] = useState<Kind>("sales");
  const [rights, setRights] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: [ws] });

  const upload = useMutation({
    mutationFn: async () => {
      const fd = new FormData();
      fd.set("kind", kind); fd.set("rights", rights); fd.set("file", file!);
      return api<Batch>("/api/v1/onboarding/batches", { method: "POST", body: fd });
    },
    onSuccess: (b) => { setBatch(b); setFile(null); refresh(); },
  });
  const validate = useMutation({
    mutationFn: (mapping: Record<string, string | null>) =>
      apiPost("/api/v1/onboarding/batches/{batch_id}/validate", { path: { batch_id: batch!.id }, body: { mapping } }),
    onSuccess: (b) => { setBatch(b); refresh(); },
  });
  const publish = useMutation({
    mutationFn: () => apiPost("/api/v1/onboarding/batches/{batch_id}/publish", { path: { batch_id: batch!.id } }),
    onSuccess: (b) => { setBatch(b); refresh(); },
  });

  return (
    <div className="space-y-6">
      {admin && <NewWorkspace />}
      <Card className="p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Eyebrow>Import CSV into this workspace</Eyebrow>
          <span className="text-xs text-muted">Schema supplylens-csv-v1 · UTF-8 · max 5 MB / 100,000 rows</span>
        </div>
        {!admin && <p className="mt-2 text-sm text-muted">Only workspace administrators import data. You can see past imports below.</p>}
        {admin && (
          <form className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" onSubmit={(e) => { e.preventDefault(); upload.mutate(); }}>
            <fieldset>
              <legend className="text-sm font-medium">1 · What does the file contain?</legend>
              <div className="mt-2 space-y-1.5">
                {(Object.keys(KIND_COPY) as Kind[]).map((k) => (
                  <label key={k} className="flex cursor-pointer items-start gap-2 rounded-lg p-1.5 text-sm hover:bg-surface-2">
                    <input type="radio" name="kind" value={k} checked={kind === k} onChange={() => setKind(k)} className="mt-1 accent-[var(--accent)]" />
                    <span><span className="font-medium capitalize">{k}</span>
                      <a className="ml-2 text-xs text-accent underline" href={`/api/v1/onboarding/templates/${k}.csv?ws=${ws}`} download>template</a>
                      <span className="block text-xs text-muted">{KIND_COPY[k]}</span></span>
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="space-y-3">
              <label className="block text-sm"><span className="font-medium">2 · Rights basis for this file</span>
                <input value={rights} onChange={(e) => setRights(e.target.value)} required minLength={5} maxLength={300}
                  placeholder="e.g. Export from our own ERP, internal use" className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2" />
                <span className="mt-1 block text-xs text-muted">These templates carry no personal data; rows that look like emails or phone numbers are quarantined.</span></label>
              <label className="block text-sm"><span className="font-medium">3 · CSV file</span>
                <input type="file" accept=".csv,text/csv" required onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="mt-1 block w-full text-sm file:mr-3 file:rounded-md file:border file:border-line file:bg-surface-2 file:px-3 file:py-1.5" /></label>
              <Button type="submit" busy={upload.isPending} disabled={!file || rights.trim().length < 5}><Upload className="size-4" aria-hidden /> Upload and preview</Button>
            </div>
          </form>
        )}
        {upload.error && <div className="mt-3"><ErrorState error={upload.error} /></div>}
      </Card>

      {batch && <BatchSteps batch={batch} admin={admin} onValidate={(m) => validate.mutate(m)} onPublish={() => publish.mutate()}
        busy={{ validate: validate.isPending, publish: publish.isPending }} error={validate.error ?? publish.error} />}

      <Card className="p-5">
        <Eyebrow>Import history</Eyebrow>
        {batches.error && <ErrorState error={batches.error} retry={() => batches.refetch()} />}
        {batches.data && batches.data.length === 0 && <p className="mt-2 text-sm text-muted">No files imported into this workspace yet.</p>}
        {!!batches.data?.length && (
          <table className="mt-3 w-full text-sm"><caption className="sr-only">Import batches</caption>
            <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">File</th><th className="font-medium">Kind</th>
              <th className="font-medium">Status</th><th className="font-medium">Valid / quarantined</th><th className="font-medium">Snapshot</th><th className="font-medium">Uploaded</th></tr></thead>
            <tbody>{batches.data.map((b) => (
              <tr key={b.id} className="border-b border-line/60">
                <td className="py-2"><button className="text-left text-accent hover:underline" onClick={async () => setBatch(await api<Batch>(`/api/v1/onboarding/batches/${b.id}`))}>{b.file_name}</button></td>
                <td className="capitalize">{b.kind}</td><td><Status value={b.status} /></td>
                <td className="num">{int(b.rows_valid)} / {int(b.rows_quarantined)}</td>
                <td><Mono className="text-muted">{b.snapshot_sha256 ? `${short(b.snapshot_sha256, 12)}…` : "—"}</Mono></td>
                <td className="text-xs text-muted">{dateTime(b.created_at)}</td>
              </tr>))}</tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

function BatchSteps({ batch, admin, onValidate, onPublish, busy, error }: {
  batch: Batch; admin: boolean; onValidate: (m: Record<string, string | null>) => void; onPublish: () => void;
  busy: { validate: boolean; publish: boolean }; error: unknown;
}) {
  const [mapping, setMapping] = useState<Record<string, string | null>>(batch.mapping);
  const editable = admin && batch.status !== "PUBLISHED";
  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><Eyebrow>Batch {short(batch.id)} · {batch.kind}</Eyebrow><p className="font-semibold">{batch.file_name}</p>
          <p className="num text-xs text-muted">{int(batch.rows_total)} rows · sha {short(batch.sha256, 14)}… · rights: {String((batch.report as { rights?: string }).rights ?? "—")}</p></div>
        <Status value={batch.status} />
      </div>
      <section aria-labelledby="map-h">
        <h3 id="map-h" className="text-sm font-semibold">Map columns</h3>
        <table className="mt-2 w-full text-sm"><caption className="sr-only">Template column to file column mapping</caption>
          <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">SupplyLens column</th><th className="font-medium">Your column</th><th className="font-medium">Meaning</th></tr></thead>
          <tbody>{batch.columns.map((c) => (
            <tr key={c.name} className="border-b border-line/60">
              <td className="py-1.5"><Mono>{c.name}</Mono>{c.required && <span className="ml-1 text-danger" title="required">*</span>}</td>
              <td><select disabled={!editable} value={mapping[c.name] ?? ""} aria-label={`File column for ${c.name}`}
                onChange={(e) => setMapping({ ...mapping, [c.name]: e.target.value || null })}
                className="rounded-md border border-line bg-surface px-2 py-1 text-sm">
                <option value="">— not in file —</option>{batch.header.map((h) => <option key={h} value={h}>{h}</option>)}</select></td>
              <td className="text-xs text-muted">{c.description}</td>
            </tr>))}</tbody>
        </table>
        <details className="mt-2 text-xs text-muted"><summary className="cursor-pointer">Preview first rows</summary>
          <pre className="mt-1 overflow-x-auto rounded-lg bg-surface-2 p-2">{batch.preview.map((r) => JSON.stringify((r as { raw: unknown }).raw)).join("\n")}</pre></details>
      </section>
      {editable && <Button variant="outline" busy={busy.validate} onClick={() => onValidate(mapping)}><ShieldCheck className="size-4" aria-hidden /> Validate {int(batch.rows_total)} rows</Button>}
      {batch.status !== "UPLOADED" && (
        <section aria-labelledby="val-h" className="space-y-2">
          <h3 id="val-h" className="text-sm font-semibold">Validation</h3>
          <p className="num text-sm"><span className="text-accent">{int(batch.rows_valid)} valid</span> · <span className={batch.rows_quarantined ? "text-risk" : "text-muted"}>{int(batch.rows_quarantined)} quarantined</span> · {int(batch.rows_total)} total
            {batch.rows_valid + batch.rows_quarantined === batch.rows_total ? <span className="ml-2 text-accent">✓ reconciles</span> : <span className="ml-2 text-danger">✗ does not reconcile</span>}</p>
          {batch.quarantined_sample.length > 0 && (
            <ul className="max-h-48 space-y-1 overflow-auto rounded-lg bg-surface-2 p-2 text-xs" tabIndex={0} aria-label="Quarantined rows, scrollable">
              {batch.quarantined_sample.map((r) => { const x = r as { row_no: number; errors: string[] };
                return <li key={x.row_no}><Mono>row {x.row_no}</Mono>: {x.errors.join("; ")}</li>; })}</ul>)}
        </section>
      )}
      {admin && batch.status === "VALIDATED" && (
        <div className="rounded-xl border border-line p-3 text-sm">
          <p>Publishing writes the {int(batch.rows_valid)} valid rows into this workspace in one transaction and freezes the batch. Quarantined rows are kept with their reasons and are never loaded.</p>
          <Button className="mt-2" busy={busy.publish} disabled={!batch.rows_valid} onClick={onPublish}><FileUp className="size-4" aria-hidden /> Publish snapshot</Button>
        </div>
      )}
      {batch.status === "PUBLISHED" && <p className="num text-sm text-accent">Published {dateTime(batch.published_at)} · snapshot sha {batch.snapshot_sha256}</p>}
      {error != null && <ErrorState error={error} />}
    </Card>
  );
}

function NewWorkspace() {
  const qc = useQueryClient();
  const [, setCtx] = usePlanningContext();
  const [f, setF] = useState({ slug: "", name: "", currency: "GBP", weekly_budget_minor: 500000, coverage_days: 21 });
  const create = useMutation({
    mutationFn: async () => {
      const intent = intentKey("workspace", f);
      // 201 Created: the typed helper only models 200 bodies, so this call states its response type
      const r = await api<Schemas["WorkspaceCreated"]>("/api/v1/onboarding/workspaces", { method: "POST", body: JSON.stringify(f), idempotencyKey: intent.key });
      intent.settle();
      return r;
    },
    onSuccess: async (r) => { await qc.invalidateQueries({ queryKey: ["me"] }); setCtx({ ws: r.slug, sku: null, known: null, eff: null, action: null, run: null }); },
  });
  return (
    <Card className="p-5">
      <Eyebrow>New customer workspace</Eyebrow>
      <p className="mt-1 text-sm text-muted">Starts empty: no stock, sales or terms exist until you publish imports into it. You become its administrator.</p>
      <form className="mt-3 flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
        <label className="text-xs"><span className="font-medium text-ink">Address (slug)</span>
          <input required pattern="[a-z0-9][a-z0-9-]{2,40}" value={f.slug} onChange={(e) => setF({ ...f, slug: e.target.value })} placeholder="acme-pilot"
            className="mt-1 block w-40 rounded-lg border border-line bg-surface px-3 py-2 text-sm" /></label>
        <label className="text-xs"><span className="font-medium text-ink">Name</span>
          <input required minLength={2} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Acme pilot"
            className="mt-1 block w-48 rounded-lg border border-line bg-surface px-3 py-2 text-sm" /></label>
        <label className="text-xs"><span className="font-medium text-ink">Currency</span>
          <input required pattern="[A-Z]{3}" value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value.toUpperCase() })}
            className="mt-1 block w-20 rounded-lg border border-line bg-surface px-3 py-2 text-sm" /></label>
        <label className="text-xs"><span className="font-medium text-ink">Weekly budget (minor units)</span>
          <input type="number" min={0} value={f.weekly_budget_minor} onChange={(e) => setF({ ...f, weekly_budget_minor: Number(e.target.value) })}
            className="num mt-1 block w-36 rounded-lg border border-line bg-surface px-3 py-2 text-sm" /></label>
        <Button type="submit" busy={create.isPending}><FolderPlus className="size-4" aria-hidden /> Create workspace</Button>
      </form>
      {create.error && <div className="mt-3"><ErrorState error={create.error} /></div>}
    </Card>
  );
}

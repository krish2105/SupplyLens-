"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import Link from "next/link";
import { Download, Trash2, UserPlus } from "lucide-react";
import { OperationsHealth, OrderReconciliation } from "@/components/operations";
import { Button, Card, Empty, ErrorState, Eyebrow, Loading, Mono, PageHeader, QueryError, Status } from "@/components/ui";
import { apiPost } from "@/lib/api";
import { useApi, useDemoLockdown, useMe, useWs } from "@/lib/queries";
import { bytes, dateTime, int, num, short } from "@/lib/format";

export default function AdminPage() {
  const ws = useWs();
  const qc = useQueryClient();
  const me = useMe();
  const membership = me.data?.memberships.find((m) => m.slug === ws);
  const role = membership?.role;
  const admin = role === "tenant_admin";
  const members = useApi(["admin-members"], admin ? "/api/v1/admin/members" : null);
  const jobs = useApi(["admin-jobs"], admin ? "/api/v1/admin/jobs" : null, { refetchInterval: 5000 });
  const models = useApi(["models"], "/api/v1/models");
  const exportsQ = useApi(["admin-exports"], admin ? "/api/v1/admin/exports" : null, { refetchInterval: 4000 });
  const vitals = useApi(["admin-vitals"], admin ? "/api/v1/admin/vitals" : null);
  const locked = useDemoLockdown();
  const lockedWhy = locked ? "Disabled in the public demo: administration is read-only" : undefined;
  const [reason, setReason] = useState("");
  const promote = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      apiPost("/api/v1/models/{model_id}/status", { path: { model_id: id }, body: { status, reason } }),
    onSuccess: () => { setReason(""); qc.invalidateQueries({ queryKey: [ws] }); },
  });
  const [newEmail, setNewEmail] = useState("");
  const [newRole, setNewRole] = useState("viewer");
  const setMember = useMutation({
    mutationFn: (b: { email: string; role: string | null }) => apiPost("/api/v1/admin/members", { body: b }),
    onSuccess: () => { setNewEmail(""); qc.invalidateQueries({ queryKey: [ws, "admin-members"] }); },
  });
  if (me.isLoading) return <Loading />;
  if (!admin) return (
    <><PageHeader eyebrow="Administration" title="Administrators only" /><p className="text-sm text-muted">Only a workspace administrator can open this page. Administrators see members, jobs and model status, but cannot approve spend.</p></>
  );
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Administration" title="Members, operations, models and audit" actions={<>
        <Link href={{ pathname: "/data", query: { ws } }} className="inline-flex h-10 items-center gap-2 rounded-lg bg-accent px-4 text-sm font-medium text-accent-ink hover:brightness-110">
          Import data / new workspace</Link>
        <a href={`/api/v1/admin/audit.csv?ws=${ws}`} className="inline-flex h-10 items-center gap-2 rounded-lg border border-line-strong bg-surface px-4 text-sm font-medium hover:bg-surface-2" download>
          <Download className="size-4" aria-hidden /> Export audit CSV</a></>} />
      {locked && (
        <p role="note" data-testid="demo-lockdown" className="rounded-lg border border-line bg-surface px-4 py-3 text-sm text-muted">
          <b className="text-ink">Public demo: administration is read-only.</b> Membership changes, model promotion, data imports, new
          workspaces, exports and deletion are disabled for every role so the shared demo stays intact. Everything here can still
          be viewed, and the audit trail can be exported.</p>)}
      <div className="grid gap-6 xl:grid-cols-2">
        <Card className="p-5"><Eyebrow>Members</Eyebrow>
          {members.error ? <QueryError q={members} what="members" /> : members.data ? <>
            <ul className="mt-3 divide-y divide-line text-sm">{members.data.members.map((m) => (
              <li key={m.email} className="flex flex-wrap items-center justify-between gap-3 py-2"><span>{m.display_name}<span className="block text-xs text-muted">{m.email}{m.is_dev_account ? " · dev account" : ""}{(m as { source?: string }).source === "oidc" ? " · managed by identity provider" : ""}</span></span>
                <span className="flex items-center gap-2"><Mono>{m.role}</Mono><Status value={m.active ? "available" : "DISABLED"} />
                  {(m as { source?: string }).source !== "oidc" && m.email !== me.data?.user.email && (
                    <Button size="sm" variant="ghost" disabled={locked} title={lockedWhy} busy={setMember.isPending && setMember.variables?.email === m.email}
                      onClick={() => setMember.mutate({ email: m.email, role: null })} aria-label={`Remove ${m.email} from this workspace`}>Remove</Button>)}</span></li>))}</ul>
            <form className="mt-3 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); setMember.mutate({ email: newEmail, role: newRole }); }}>
              <label className="min-w-[180px] flex-1 text-xs"><span className="font-medium text-ink">Add or change a member (existing account email)</span>
                <input type="email" required value={newEmail} onChange={(e) => setNewEmail(e.target.value)} className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm" /></label>
              <label className="text-xs"><span className="font-medium text-ink">Role</span>
                <select value={newRole} onChange={(e) => setNewRole(e.target.value)} className="mt-1 block rounded-lg border border-line bg-surface px-2 py-2 text-sm">
                  {["viewer", "planner", "approver", "tenant_admin"].map((r) => <option key={r} value={r}>{r.replace("_", " ")}</option>)}</select></label>
              <Button type="submit" size="sm" disabled={locked} title={lockedWhy} busy={setMember.isPending && setMember.variables?.email === newEmail}><UserPlus className="size-4" aria-hidden /> Save</Button>
            </form>
            {setMember.error && <div className="mt-2"><ErrorState error={setMember.error} /></div>}
            <p className="mt-3 text-xs text-muted">{members.data.note} Every change is audited and takes effect on the member&apos;s next request.</p></> : <Loading />}
        </Card>
        <Card className="p-5"><Eyebrow>Permission matrix (enforced server-side)</Eyebrow>
          {members.data && <table className="mt-3 w-full text-sm"><caption className="sr-only">Operations allowed per role</caption>
            <tbody>{Object.entries(members.data.role_matrix).map(([r, ops]) => (
              <tr key={r} className="border-b border-line/60 align-top"><td className="py-2 pr-3"><Mono>{r}</Mono></td><td className="text-xs text-muted">{ops.join(" · ")}</td></tr>))}</tbody></table>}
        </Card>
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <OperationsHealth locked={locked} />
        <OrderReconciliation />
      </div>
      <Card className="p-5"><Eyebrow>Model registry and promotion</Eyebrow>
        <p className="mt-1 text-sm text-muted">The champion serves forecasts in investigations and scenarios. Promotion requires a recorded evaluation and a reason, and is audited.</p>
        <label className="mt-3 block text-sm"><span className="font-medium">Reason for status change</span>
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Study F1 validation pinball; frozen protocol" className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2" /></label>
        {promote.error && <div className="mt-3"><ErrorState error={promote.error} /></div>}
        <QueryError q={models} what="the model registry" />
        <table className="mt-3 w-full text-sm"><caption className="sr-only">Registered models</caption>
          <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Model</th><th className="font-medium">Status</th><th className="font-medium">Evidence</th><th className="font-medium">Change</th></tr></thead>
          <tbody>{models.data?.map((m) => {
            const metrics = m.metrics as { experiment_id?: string; validation_pinball?: number };
            return (
              <tr key={m.id} className="border-b border-line/60"><td className="py-2"><Mono>{m.family} {m.version}</Mono><span className="block text-xs text-muted">trained to {m.training_cutoff ?? "—"}</span></td>
                <td><Status value={m.status} /></td>
                <td className="num text-xs text-muted">{metrics?.experiment_id ? `${metrics.experiment_id} · val pinball ${num(metrics.validation_pinball, 3)}` : "no study"}</td>
                <td className="space-x-1">{["CHAMPION", "CANDIDATE", "RETIRED"].filter((s) => s !== m.status).map((s) => (
                  <Button key={s} size="sm" variant="outline" disabled={locked || reason.trim().length < 5} title={lockedWhy} busy={promote.isPending && promote.variables?.id === m.id && promote.variables?.status === s}
                    onClick={() => promote.mutate({ id: m.id, status: s })}>{s.toLowerCase()}</Button>))}</td></tr>);
          })}</tbody></table>
      </Card>
      <div className="grid gap-6 xl:grid-cols-2">
        <Card className="p-5"><Eyebrow>Job queue</Eyebrow>
          {jobs.error ? <QueryError q={jobs} what="the job queue" /> : jobs.data ? <>
            <p className="mt-2 text-sm text-muted">{int(Number(jobs.data.usage.runs))} runs · {int(Number(jobs.data.usage.tool_calls))} tool calls · {int(Number(jobs.data.usage.runs_24h))} in 24 h · {String(jobs.data.usage.llm_tokens)} LLM tokens. Limits: {String((jobs.data.usage.budget as { max_runs_per_day: number }).max_runs_per_day)} runs/day, {String((jobs.data.usage.budget as { max_tool_calls_per_run: number }).max_tool_calls_per_run)} tool calls/run.</p>
            <ul className="mt-3 max-h-72 divide-y divide-line overflow-auto text-sm" tabIndex={0} aria-label="Jobs, scrollable">{jobs.data.jobs.map((j) => (
              <li key={j.id} className="flex flex-wrap items-center gap-3 py-1.5"><Mono>{short(j.id)}</Mono><span className="text-xs">{j.kind}</span>
                <span className="text-xs text-muted">attempt {j.attempts}/{j.max_attempts} · {dateTime(j.updated_at)}</span><span className="ml-auto"><Status value={j.status} /></span></li>))}</ul></> : <Loading />}
        </Card>
        <Card className="p-5"><Eyebrow>Outbox (external writes)</Eyebrow>
          <p className="mt-1 text-xs text-muted">DELIVERED means the request reached the sandbox. Whether the order matched the approval is the action&apos;s own status (reconciled or read-back mismatch).</p>
          <QueryError q={jobs} what="the outbox" />
          {jobs.data && <ul className="mt-3 max-h-72 divide-y divide-line overflow-auto text-sm" tabIndex={0} aria-label="Outbox, scrollable">{jobs.data.outbox.map((o) => (
            <li key={o.operation_id} className="flex flex-wrap items-center gap-3 py-1.5"><Mono>{short(o.operation_id, 14)}</Mono>
              <span className="text-xs text-muted">attempts {o.attempts}{o.external_ref ? ` · ${o.external_ref}` : ""}{o.last_error ? ` · ${o.last_error}` : ""}</span><span className="ml-auto"><Status value={o.status} /></span></li>))}</ul>}
        </Card>
      </div>

      <DataLifecycle ws={ws} kind={membership?.kind} exportsQ={exportsQ} locked={locked} />

      <Card className="p-5"><Eyebrow>Field performance (real browsers, 75th percentile)</Eyebrow>
        <p className="mt-1 text-sm text-muted">Reported by the app itself. Targets: LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1. Empty until people use the app.</p>
        {vitals.isLoading ? <Loading /> : vitals.error ? <QueryError q={vitals} what="field measurements" /> : vitals.data?.metrics.length ? (
          <table className="mt-3 w-full text-sm"><caption className="sr-only">Web Vitals by route</caption>
            <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Metric</th><th className="font-medium">Route</th><th className="font-medium">Samples</th><th className="font-medium">p75</th><th className="font-medium">Target</th></tr></thead>
            <tbody>{vitals.data.metrics.map((m) => (
              <tr key={`${m.metric}${m.route}`} className="border-b border-line/60"><td className="py-2"><Mono>{m.metric}</Mono></td><td><Mono>{m.route}</Mono></td><td className="num">{int(m.n)}</td>
                <td className="num">{m.metric === "CLS" ? num(m.p75, 3) : `${num(m.p75, 0)} ms`}</td>
                <td>{m.meets_target == null ? "—" : <Status value={m.meets_target ? "available" : "FAILED"} />}</td></tr>))}</tbody></table>
        ) : <div className="mt-3"><Empty title="No field measurements yet" /></div>}
      </Card>

      <Card className="p-5"><Eyebrow>Retention and data handling</Eyebrow>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted">
          <li>Raw source files are immutable under data/raw and never committed to Git.</li>
          <li>Audit events are append-only for the application role; export above includes every event in this workspace.</li>
          <li>No customer data is sent to an external model provider: embeddings run locally and no generative LLM is enabled.</li>
          <li>Customer workspaces can be exported and permanently deleted below; backups taken earlier keep their data until the operator purges them.</li>
        </ul></Card>
    </div>
  );
}

function DataLifecycle({ ws, kind, exportsQ, locked }: { ws: string; kind: string | undefined; exportsQ: ReturnType<typeof useApi<"/api/v1/admin/exports">>; locked: boolean }) {
  const qc = useQueryClient();
  const [vectors, setVectors] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [why, setWhy] = useState("");
  const [exportId, setExportId] = useState("");
  const request = useMutation({
    mutationFn: () => apiPost("/api/v1/admin/exports", { body: { include_vectors: vectors } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [ws, "admin-exports"] }),
  });
  const del = useMutation({
    mutationFn: () => apiPost("/api/v1/admin/tenant-deletion", { body: { confirm_slug: confirm, export_id: exportId, reason: why } }),
  });
  const ready = (exportsQ.data ?? []).filter((e) => e.status === "READY" && e.downloaded_at);
  const deletable = kind === "customer";
  return (
    <Card className="p-5"><Eyebrow>Data lifecycle: export and deletion</Eyebrow>
      <p className="mt-1 text-sm text-muted">An export is a verified archive of every table, every stored document and (optionally) the embedding vectors, built from a single consistent snapshot. Counts and hashes are re-checked before it is offered.</p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button onClick={() => request.mutate()} busy={request.isPending} disabled={locked} title={locked ? "Disabled in the public demo" : undefined}>Request export</Button>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={vectors} onChange={(e) => setVectors(e.target.checked)} /> Include embedding vectors (large)</label>
      </div>
      {request.error && <div className="mt-3"><ErrorState error={request.error} /></div>}
      {exportsQ.error ? <QueryError q={exportsQ} what="exports" /> : exportsQ.data?.length ? (
        <table className="mt-3 w-full text-sm"><caption className="sr-only">Exports</caption>
          <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Requested</th><th className="font-medium">Status</th><th className="font-medium">Contents</th><th className="font-medium">Download</th></tr></thead>
          <tbody>{exportsQ.data.map((e) => (
            <tr key={e.id} className="border-b border-line/60 align-top">
              <td className="py-2 num text-xs">{dateTime(e.created_at)}<span className="block text-muted">{short(e.id)}</span></td>
              <td><Status value={e.status} />{e.error && <span className="block text-xs text-danger">{e.error}</span>}</td>
              <td className="text-xs text-muted">{e.manifest ? `${int(Object.values(e.manifest.tables).reduce((a, b) => a + b, 0))} rows in ${Object.keys(e.manifest.tables).length} tables · ${int(Number((e.manifest.documents as { count?: number }).count ?? 0))} documents · ${e.bytes ? bytes(e.bytes) : ""}${e.manifest.verified ? " · verified" : ""}` : "—"}</td>
              <td>{e.status === "READY" ? <a className="text-accent underline-offset-2 hover:underline" href={`/api/v1/admin/exports/${e.id}/download?ws=${ws}`} onClick={() => setTimeout(() => qc.invalidateQueries({ queryKey: [ws, "admin-exports"] }), 1500)}>Download .zip</a> : "—"}
                {e.downloaded_at && <span className="block text-xs text-muted">downloaded {dateTime(e.downloaded_at)}</span>}</td></tr>))}</tbody></table>
      ) : <div className="mt-3"><Empty title="No exports yet" /></div>}

      <div className="mt-6 rounded-xl border border-danger/40 p-4">
        <p className="flex items-center gap-2 text-sm font-semibold text-danger"><Trash2 className="size-4" aria-hidden /> Delete this workspace</p>
        {!deletable ? (
          <p className="mt-1 text-sm text-muted">Research and demo workspaces cannot be deleted. Only customer workspaces can, after a verified export has been downloaded.</p>
        ) : del.data ? (
          <p role="status" className="mt-2 text-sm">Deletion queued. The certificate will be available at <a className="text-accent underline-offset-2 hover:underline" href={del.data.certificate_url}>{del.data.certificate_url}</a> once it completes; this workspace will then stop resolving.</p>
        ) : (
          <form className="mt-2 space-y-3 text-sm" onSubmit={(e) => { e.preventDefault(); del.mutate(); }}>
            <p className="text-muted">Irreversible. Removes every record, document and vector in this workspace. Backups keep their copy until you purge them.</p>
            <label className="block"><span className="font-medium">Verified export that you downloaded</span>
              <select value={exportId} onChange={(e) => setExportId(e.target.value)} className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2">
                <option value="">Select an export…</option>{ready.map((e) => <option key={e.id} value={e.id}>{dateTime(e.created_at)} · {short(e.id)}</option>)}</select></label>
            <label className="block"><span className="font-medium">Reason</span>
              <input value={why} onChange={(e) => setWhy(e.target.value)} className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2" /></label>
            <label className="block"><span className="font-medium">Type the workspace name <Mono>{ws}</Mono> to confirm</span>
              <input value={confirm} onChange={(e) => setConfirm(e.target.value)} className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2" autoComplete="off" /></label>
            {del.error && <ErrorState error={del.error} />}
            <Button variant="danger" type="submit" busy={del.isPending} disabled={locked || confirm !== ws || !exportId || why.trim().length < 5}>Permanently delete workspace</Button>
          </form>
        )}
      </div>
    </Card>
  );
}

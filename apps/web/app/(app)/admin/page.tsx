"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Download } from "lucide-react";
import { Button, Card, ErrorState, Eyebrow, Loading, Mono, PageHeader, Status } from "@/components/ui";
import { post } from "@/lib/api";
import { useMe, useTenantQuery, useWs } from "@/lib/queries";
import { dateTime, int, num, short } from "@/lib/format";

type Members = { members: { email: string; display_name: string; active: boolean; is_dev_account: boolean; role: string }[]; role_matrix: Record<string, string[]>; note: string };
type Jobs = { jobs: any[]; outbox: any[]; usage: any };
type Model = { id: string; family: string; version: string; status: string; metrics: any; created_at: string; training_cutoff: string | null };

export default function AdminPage() {
  const ws = useWs();
  const qc = useQueryClient();
  const me = useMe();
  const role = me.data?.memberships.find((m) => m.slug === ws)?.role;
  const members = useTenantQuery<Members>(["admin-members"], role === "tenant_admin" ? "/api/v1/admin/members" : null);
  const jobs = useTenantQuery<Jobs>(["admin-jobs"], role === "tenant_admin" ? "/api/v1/admin/jobs" : null, { refetchInterval: 5000 });
  const models = useTenantQuery<Model[]>(["models"], "/api/v1/models");
  const [reason, setReason] = useState("");
  const promote = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => post(`/api/v1/models/${id}/status`, { status, reason }),
    onSuccess: () => { setReason(""); qc.invalidateQueries({ queryKey: [ws] }); },
  });
  if (me.isLoading) return <Loading />;
  if (role !== "tenant_admin") return (
    <><PageHeader eyebrow="Administration" title="Administrators only" /><p className="text-sm text-muted">Sign in as Dev Tenant Admin to manage this workspace. Administrators can see members, jobs and model status, but cannot approve spend.</p></>
  );
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Administration" title="Members, jobs, models and audit" actions={
        <a href={`/api/v1/admin/audit.csv?ws=${ws}`} className="inline-flex h-10 items-center gap-2 rounded-lg border border-line-strong bg-surface px-4 text-sm font-medium hover:bg-surface-2" download>
          <Download className="size-4" aria-hidden /> Export audit CSV</a>} />
      <div className="grid gap-6 xl:grid-cols-2">
        <Card className="p-5"><Eyebrow>Members</Eyebrow>
          {members.data ? <>
            <ul className="mt-3 divide-y divide-line text-sm">{members.data.members.map((m) => (
              <li key={m.email} className="flex items-center justify-between gap-3 py-2"><span>{m.display_name}<span className="block text-xs text-muted">{m.email}{m.is_dev_account ? " · dev account" : ""}</span></span>
                <span className="flex items-center gap-2"><Mono>{m.role}</Mono><Status value={m.active ? "available" : "DISABLED"} /></span></li>))}</ul>
            <p className="mt-3 text-xs text-muted">{members.data.note}</p></> : <Loading />}
        </Card>
        <Card className="p-5"><Eyebrow>Permission matrix (enforced server-side)</Eyebrow>
          {members.data && <table className="mt-3 w-full text-sm"><caption className="sr-only">Operations allowed per role</caption>
            <tbody>{Object.entries(members.data.role_matrix).map(([r, ops]) => (
              <tr key={r} className="border-b border-line/60 align-top"><td className="py-2 pr-3"><Mono>{r}</Mono></td><td className="text-xs text-muted">{ops.join(" · ")}</td></tr>))}</tbody></table>}
        </Card>
      </div>
      <Card className="p-5"><Eyebrow>Model registry and promotion</Eyebrow>
        <p className="mt-1 text-sm text-muted">The champion serves forecasts in investigations and scenarios. Promotion requires a recorded evaluation and a reason, and is audited.</p>
        <label className="mt-3 block text-sm"><span className="font-medium">Reason for status change</span>
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Study F1 validation pinball; frozen protocol" className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2" /></label>
        {promote.error && <div className="mt-3"><ErrorState error={promote.error} /></div>}
        <table className="mt-3 w-full text-sm"><caption className="sr-only">Registered models</caption>
          <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Model</th><th className="font-medium">Status</th><th className="font-medium">Evidence</th><th className="font-medium">Change</th></tr></thead>
          <tbody>{models.data?.map((m) => (
            <tr key={m.id} className="border-b border-line/60"><td className="py-2"><Mono>{m.family} {m.version}</Mono><span className="block text-xs text-muted">trained to {m.training_cutoff ?? "—"}</span></td>
              <td><Status value={m.status} /></td>
              <td className="num text-xs text-muted">{m.metrics?.experiment_id ? `${m.metrics.experiment_id} · val pinball ${num(m.metrics.validation_pinball, 3)}` : "no study"}</td>
              <td className="space-x-1">{["CHAMPION", "CANDIDATE", "RETIRED"].filter((s) => s !== m.status).map((s) => (
                <Button key={s} size="sm" variant="outline" disabled={reason.trim().length < 5} busy={promote.isPending && promote.variables?.id === m.id && promote.variables?.status === s}
                  onClick={() => promote.mutate({ id: m.id, status: s })}>{s.toLowerCase()}</Button>))}</td></tr>))}</tbody></table>
      </Card>
      <div className="grid gap-6 xl:grid-cols-2">
        <Card className="p-5"><Eyebrow>Job queue</Eyebrow>
          {jobs.data ? <>
            <p className="mt-2 text-sm text-muted">{int(jobs.data.usage.runs)} runs · {int(jobs.data.usage.tool_calls)} tool calls · {int(jobs.data.usage.runs_24h)} in 24 h · {jobs.data.usage.llm_tokens} LLM tokens. Limits: {jobs.data.usage.budget.max_runs_per_day} runs/day, {jobs.data.usage.budget.max_tool_calls_per_run} tool calls/run.</p>
            <ul className="mt-3 max-h-72 divide-y divide-line overflow-auto text-sm" tabIndex={0} aria-label="Jobs, scrollable">{jobs.data.jobs.map((j) => (
              <li key={j.id} className="flex flex-wrap items-center gap-3 py-1.5"><Mono>{short(j.id)}</Mono><span className="text-xs">{j.kind}</span>
                <span className="text-xs text-muted">attempt {j.attempts}/{j.max_attempts} · {dateTime(j.updated_at)}</span><span className="ml-auto"><Status value={j.status} /></span></li>))}</ul></> : <Loading />}
        </Card>
        <Card className="p-5"><Eyebrow>Outbox (external writes)</Eyebrow>
          {jobs.data && <ul className="mt-3 max-h-72 divide-y divide-line overflow-auto text-sm" tabIndex={0} aria-label="Outbox, scrollable">{jobs.data.outbox.map((o) => (
            <li key={o.operation_id} className="flex flex-wrap items-center gap-3 py-1.5"><Mono>{short(o.operation_id, 14)}</Mono>
              <span className="text-xs text-muted">attempts {o.attempts}{o.external_ref ? ` · ${o.external_ref}` : ""}{o.last_error ? ` · ${o.last_error}` : ""}</span><span className="ml-auto"><Status value={o.status === "DELIVERED" ? "RECONCILED" : o.status} /></span></li>))}</ul>}
        </Card>
      </div>
      <Card className="p-5"><Eyebrow>Retention and data handling</Eyebrow>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted">
          <li>Raw source files are immutable under data/raw and never committed to Git.</li>
          <li>Audit events are append-only for the application role; export above includes every event in this workspace.</li>
          <li>No customer data is sent to an external model provider: embeddings run locally and no generative LLM is enabled.</li>
          <li>Retention periods and deletion workflows are not yet configurable in this build.</li>
        </ul></Card>
    </div>
  );
}

"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { parseAsString, useQueryState } from "nuqs";
import clsx from "clsx";
import { Bug, Check, Pencil, RefreshCw, X } from "lucide-react";
import { Button, Card, Empty, ErrorState, Eyebrow, KV, Loading, Mono, PageHeader, Provenance, Status } from "@/components/ui";
import { post } from "@/lib/api";
import { useMe, useTenantQuery, useWs, type Action } from "@/lib/queries";
import { dateTime, day, int, money, short } from "@/lib/format";

const TABS = [
  { k: "PENDING_APPROVAL", l: "Awaiting approval" }, { k: "QUEUED", l: "Queued" }, { k: "UNKNOWN_OUTCOME", l: "Unknown outcome" },
  { k: "RECONCILED", l: "Reconciled" }, { k: "STALE", l: "Stale" }, { k: "REJECTED", l: "Rejected" }, { k: "", l: "All" },
];

export default function ApprovalsPage() {
  const ws = useWs();
  const [tab, setTab] = useState("PENDING_APPROVAL");
  const [actionId, setActionId] = useQueryState("action", parseAsString);
  const list = useTenantQuery<Action[]>(["actions", tab], `/api/v1/actions${tab ? `?status=${tab}` : ""}`, { refetchInterval: 4000 });
  const orders = useTenantQuery<any[]>(["sandbox-orders"], "/api/v1/sandbox/orders", { refetchInterval: 5000 });

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Approvals" title="Review exact payloads before anything is sent">
        An approval binds this exact payload hash, its source versions, the spend and an expiry. Any edit or change in supplier terms requires a fresh approval.
        Orders go only to the local <b>sandbox ERP</b>.
      </PageHeader>
      <div role="tablist" aria-label="Action status" className="flex flex-wrap gap-1">
        {TABS.map((t) => (
          <button key={t.k} role="tab" aria-selected={tab === t.k} onClick={() => setTab(t.k)}
            className={clsx("rounded-lg px-3 py-1.5 text-sm", tab === t.k ? "bg-ink text-bg" : "text-muted hover:bg-surface-2")}>{t.l}</button>
        ))}
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,4fr)_minmax(0,8fr)]">
        <Card className="p-3">
          {list.isLoading ? <Loading /> : list.error ? <ErrorState error={list.error} /> : list.data?.length ? (
            <ul className="space-y-1">
              {list.data.map((a) => (
                <li key={a.id}>
                  <button onClick={() => setActionId(a.id)} aria-current={a.id === actionId}
                    className={clsx("w-full rounded-lg px-3 py-2.5 text-left", a.id === actionId ? "bg-accent-soft" : "hover:bg-surface-2")}>
                    <span className="flex items-center justify-between gap-2"><span className="font-semibold">{a.payload.supplier_id}</span><Status value={a.status} /></span>
                    <span className="num mt-0.5 block text-sm">{money(a.total_minor, a.currency)} · {a.payload.lines.length} line(s)</span>
                    <span className="block text-xs text-muted">Prepared by {a.prepared_by} · {dateTime(a.created_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : <Empty title="Nothing in this queue">Start an investigation in Draft mode to prepare purchase-order drafts.</Empty>}
        </Card>
        {actionId ? <ActionView id={actionId} ws={ws} /> : <Card className="p-5"><Empty title="Select a draft to review" /></Card>}
      </div>
      <Card className="p-5">
        <div className="flex items-center justify-between"><Eyebrow>Sandbox ERP — orders it holds</Eyebrow><Status value="VERIFIED_LOCALLY" /></div>
        <p className="mt-1 text-xs text-muted">A local simulator standing in for an external purchasing system. Not a real ERP.</p>
        {orders.data?.length ? (
          <table className="mt-3 w-full text-sm">
            <caption className="sr-only">Purchase orders in the sandbox ERP</caption>
            <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">PO</th><th className="font-medium">Supplier</th>
              <th className="font-medium">Lines</th><th className="font-medium">Total</th><th className="font-medium">Idempotency key</th><th className="font-medium">Created</th></tr></thead>
            <tbody>{orders.data.map((o) => (
              <tr key={o.po_number} className="border-b border-line/60"><td className="py-2"><Mono>{o.po_number}</Mono></td><td>{o.supplier_id}</td><td className="num">{o.lines.length}</td>
                <td className="num">{money(o.total_minor, o.currency.trim())}</td><td><Mono className="text-muted">{short(o.idempotency_key, 14)}…</Mono></td><td className="text-xs text-muted">{dateTime(o.created_at)}</td></tr>
            ))}</tbody>
          </table>
        ) : <p className="mt-3 text-sm text-muted">No orders yet.</p>}
      </Card>
    </div>
  );
}

function ActionView({ id, ws }: { id: string; ws: string }) {
  const qc = useQueryClient();
  const me = useMe();
  const role = me.data?.memberships.find((m) => m.slug === ws)?.role;
  const isDev = me.data?.user.is_dev_account;
  const a = useTenantQuery<Action>(["action", id], `/api/v1/actions/${id}`, { refetchInterval: 3000 });
  const [reason, setReason] = useState("");
  const [editing, setEditing] = useState<Record<string, number> | null>(null);
  const refresh = () => { qc.invalidateQueries({ queryKey: [ws] }); };
  const m = useMutation({
    mutationFn: async (op: "approve" | "reject" | "edit" | "reconcile" | "fault") => {
      const x = a.data!;
      if (op === "approve") return post(`/api/v1/actions/${id}/approve`, { payload_hash: x.payload_hash, expected_row_version: x.row_version });
      if (op === "reject") return post(`/api/v1/actions/${id}/reject`, { reason, expected_row_version: x.row_version });
      if (op === "edit") return post(`/api/v1/actions/${id}/edit`, { quantities: editing, expected_row_version: x.row_version });
      if (op === "fault") return post(`/api/v1/sandbox/faults`, { action_id: id, mode: "timeout_after_commit" });
      return post(`/api/v1/actions/${id}/reconcile`, {});
    },
    onSuccess: (_, op) => { if (op === "edit") setEditing(null); if (op === "reject") setReason(""); refresh(); },
  });

  if (a.isLoading) return <Card className="p-5"><Loading /></Card>;
  if (a.error || !a.data) return <Card className="p-5"><ErrorState error={a.error} /></Card>;
  const x = a.data, p = x.payload, ev = x.evidence ?? {};
  const self = me.data?.user.id === (x as any).prepared_by;
  const lastApproval = x.approvals?.filter((ap: any) => ap.decision === "APPROVED").at(-1);

  return (
    <div className="space-y-6">
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <Eyebrow>Purchase-order draft {short(x.id)}</Eyebrow>
            <h2 className="display mt-1 text-2xl font-semibold">{p.supplier_id} · <span className="num">{money(x.total_minor, x.currency)}</span></h2>
            <p className="text-sm text-muted">Destination <b>{p.destination}</b> ({p.environment}) · need by {day(p.need_by)} · operation {p.operation}</p>
          </div>
          <div className="text-right"><Status value={x.status} />{x.external_ref && <p className="mt-1"><Mono>{x.external_ref}</Mono></p>}</div>
        </div>
        {x.status_reason && <p className="mt-3 rounded-lg bg-surface-2 p-2 text-sm">{x.status_reason}</p>}
        <table className="mt-4 w-full text-sm">
          <caption className="sr-only">Exact line items</caption>
          <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-2 font-medium">Product</th><th className="font-medium">Quantity</th>
            <th className="font-medium">Unit cost</th><th className="font-medium">Line</th><th className="font-medium">Term</th></tr></thead>
          <tbody>
            {p.lines.map((l: any) => (
              <tr key={l.sku_id} className="border-b border-line/60">
                <td className="py-2"><Mono>{l.sku_id}</Mono></td>
                <td className="num">{editing ? (
                  <input type="number" min={0} aria-label={`Quantity for ${l.sku_id}`} value={editing[l.sku_id] ?? l.quantity}
                    onChange={(e) => setEditing({ ...editing, [l.sku_id]: Number(e.target.value) })} className="w-24 rounded border border-line bg-surface px-2 py-1" />
                ) : `${int(l.quantity)} ${l.unit}`}</td>
                <td className="num">{money(l.unit_cost_minor, p.currency)}</td><td className="num">{money(l.line_minor, p.currency)}</td>
                <td><Mono className="text-xs text-muted">{l.term_id}</Mono></td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="num mt-2 text-xs text-muted">Payload hash {short(x.payload_hash, 20)}… · row version {x.row_version}</p>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {x.status === "PENDING_APPROVAL" && role === "approver" && (
            <>
              <Button onClick={() => m.mutate("approve")} busy={m.isPending && m.variables === "approve"} disabled={self}
                title={self ? "You prepared this draft; another approver must approve it" : undefined}>
                <Check className="size-4" aria-hidden /> Approve {money(x.total_minor, x.currency)}
              </Button>
              <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason for rejection" aria-label="Reason for rejection"
                className="min-w-[200px] flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm" />
              <Button variant="danger" onClick={() => m.mutate("reject")} disabled={!reason.trim()} busy={m.isPending && m.variables === "reject"}><X className="size-4" aria-hidden /> Reject</Button>
            </>
          )}
          {["PENDING_APPROVAL", "STALE"].includes(x.status) && role === "planner" && (
            editing ? (
              <><Button onClick={() => m.mutate("edit")} busy={m.isPending && m.variables === "edit"}>Revalidate and save</Button>
                <Button variant="ghost" onClick={() => setEditing(null)}>Cancel edit</Button></>
            ) : <Button variant="outline" onClick={() => setEditing({})}><Pencil className="size-4" aria-hidden /> Edit quantities</Button>
          )}
          {x.status === "UNKNOWN_OUTCOME" && ["planner", "approver", "tenant_admin"].includes(role ?? "") && (
            <Button onClick={() => m.mutate("reconcile")} busy={m.isPending}><RefreshCw className="size-4" aria-hidden /> Reconcile with sandbox</Button>
          )}
          {isDev && x.status === "PENDING_APPROVAL" && (
            <Button variant="ghost" size="sm" onClick={() => m.mutate("fault")} title="Development only: the sandbox will commit the order and then not reply">
              <Bug className="size-4" aria-hidden /> Simulate timeout on submit
            </Button>
          )}
          {x.status === "PENDING_APPROVAL" && role === "viewer" && <p className="text-sm text-muted">Viewers cannot approve.</p>}
          {x.status === "PENDING_APPROVAL" && role === "tenant_admin" && <p className="text-sm text-muted">Tenant administrators do not hold spend authority.</p>}
        </div>
        {m.error && <div className="mt-3"><ErrorState error={m.error} /></div>}
      </Card>

      <Card className="p-5">
        <Eyebrow>Evidence packet</Eyebrow>
        <div className="mt-3"><KV items={[
          ["Knowledge cutoff", dateTime(ev.data_cutoff)], ["Effective date", day(ev.effective_date)],
          ["Forecast run", ev.forecast?.available ? <Mono key="f">{short(ev.forecast.run_id)} (origin {ev.forecast.origin})</Mono> : "none — reorder rule on fictional fixture"],
          ["Plan", <span key="p"><Status value={ev.plan?.status} /> <Mono>{short(ev.plan?.input_hash, 16)}</Mono></span>],
          ["Checks", ev.checks?.passed ? "passed; independent validator re-checked every line" : "issues raised"],
          ["Provenance", <span key="v" className="flex flex-wrap gap-1">stock <Provenance kind={ev.provenance?.stock} /> terms <Provenance kind={ev.provenance?.terms} /> budget <Provenance kind="assumed" /></span>],
          ["Approval", lastApproval ? `bound to ${short(lastApproval.payload_hash, 12)}…, expires ${dateTime(lastApproval.expires_at)}` : "none yet"],
        ]} /></div>
        <ul className="mt-4 space-y-3">
          {(ev.terms ?? []).map((t: any) => (
            <li key={t.term_id} className="rounded-xl border border-line p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2"><Mono className="font-semibold">{t.term_id}</Mono>
                <span className="num text-xs text-muted">MOQ {t.moq} · ×{t.order_multiple} · {money(t.unit_cost_minor, t.currency)} · {t.lead_time_days} d · from {day(t.valid_from)}</span></div>
              {t.citation ? (
                <blockquote className="mt-2 border-l-2 border-accent pl-3 text-[13px]">
                  <p className="whitespace-pre-wrap">{t.citation.body}</p>
                  <footer className="mt-1 text-xs text-muted">{t.citation.title} — {t.citation.version_label} · {t.citation.section} · known {day(t.citation.known_at)} · sha {short(t.citation.sha256, 10)}</footer>
                </blockquote>
              ) : <p className="mt-2 text-xs text-muted">Structured term record only; no source document attached.</p>}
            </li>
          ))}
        </ul>
        {ev.ignored_terms?.length ? <div className="mt-3 text-xs text-muted"><p className="font-medium text-ink">Not applied at this decision time</p>
          <ul>{ev.ignored_terms.map((i: any) => <li key={i.term_id}><Mono>{i.term_id}</Mono> — {i.reason}</li>)}</ul></div> : null}
        {ev.upcoming_changes?.length ? <p className="mt-3 rounded-lg bg-risk-soft p-2 text-sm text-risk">Policy change ahead: {ev.upcoming_changes.map((u: any) => `${u.sku_id} MOQ ${u.moq} from ${day(u.valid_from)}`).join("; ")}.</p> : null}
      </Card>

      <Card className="p-5">
        <Eyebrow>Lifecycle</Eyebrow>
        <ul className="mt-3 space-y-1 text-sm">
          {(x.approvals ?? []).map((ap: any) => <li key={ap.id}><Status value={ap.decision} /> {dateTime(ap.created_at)} {ap.reason ? `— ${ap.reason}` : ""} <Mono className="text-muted">hash {short(ap.payload_hash, 10)}</Mono></li>)}
          {x.outbox && <li>Outbox <Mono>{x.outbox.operation_id}</Mono>: <Status value={x.outbox.status} /> attempts {x.outbox.attempts}{x.outbox.last_error ? ` · ${x.outbox.last_error}` : ""}</li>}
        </ul>
      </Card>
    </div>
  );
}

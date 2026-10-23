"use client";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { parseAsString, useQueryState } from "nuqs";
import clsx from "clsx";
import { Play } from "lucide-react";
import { useDecisionClock } from "@/components/clock-rail";
import { Button, Card, Empty, ErrorState, Eyebrow, KV, Loading, Mono, PageHeader, Provenance, QueryError, Status } from "@/components/ui";
import { EmptyState } from "@/components/illustration";
import { apiPost, intentKey } from "@/lib/api";
import type { Schemas } from "@/lib/contract";
import { useApi, useMe, useWs } from "@/lib/queries";
import { usePlanningContext } from "@/lib/state";
import { dateTime, day, int, money, short } from "@/lib/format";

type Event = Schemas["RunEvent"];

const STAGES = ["ACCEPT", "PLAN", "GATHER_EVIDENCE", "COMPUTE", "CHECK", "PREPARE_ACTION"];
const STAGE_LABEL: Record<string, string> = { ACCEPT: "Accept", PLAN: "Plan", GATHER_EVIDENCE: "Gather evidence", COMPUTE: "Compute", CHECK: "Check", PREPARE_ACTION: "Prepare drafts" };

export default function RunsPage() {
  const ws = useWs();
  const qc = useQueryClient();
  const me = useMe();
  const role = me.data?.memberships.find((m) => m.slug === ws)?.role;
  const [ctx] = usePlanningContext();
  const { known, eff } = useDecisionClock();
  const ov = useApi(["overview"], "/api/v1/overview");
  const runs = useApi(["runs"], "/api/v1/agent-runs", { refetchInterval: 5000 });
  const [runId, setRunId] = useQueryState("run", parseAsString);
  const [mode, setMode] = useState("draft");
  const [scope, setScope] = useState<"all" | "selected">("all");
  const loaded = !!ov.data;
  const isDemo = loaded && !ov.data!.dataset;

  const start = useMutation({
    mutationFn: async () => {
      const body = {
        mode, knowledge_cutoff: known, effective_date: eff,
        ...(scope === "selected" && ctx.sku ? { sku_ids: [ctx.sku] } : {}),
        ...(isDemo ? { sku_ids: ["DEMO-REF-SKU"], currency: "USD", budget_minor: 18000, allow_shortfall: false } : {}),
      };
      // One key per intent: a repeated click or a retry after a lost response replays the same run (P2-FE-05).
      const intent = intentKey(`agent-run:${ws}`, body);
      const r = await apiPost("/api/v1/agent-runs", { body, idempotencyKey: intent.key });
      intent.settle();
      return r;
    },
    onSuccess: (r) => { setRunId(r.run_id); qc.invalidateQueries({ queryKey: [ws, "runs"] }); },
  });

  return (
    <div className="space-y-6">
      <QueryError q={ov} what="this workspace&apos;s settings" className="mb-4" />
      <PageHeader eyebrow="Investigations" title="Forecast, plan and prepare drafts — with every step on record">
        The investigator is deterministic: each step calls a typed tool (forecast, terms, retrieval, optimiser, validator). No language model writes numbers or decisions.
      </PageHeader>
      <Card className="p-5">
        <div className="flex flex-wrap items-end gap-4">
          <label className="text-sm"><span className="mb-1 block font-medium">Mode</span>
            <select value={mode} onChange={(e) => setMode(e.target.value)} className="rounded-lg border border-line bg-surface px-3 py-2">
              <option value="observe">Observe — analyse only</option><option value="recommend">Recommend — plan, no drafts</option>
              <option value="draft">Draft — prepare purchase-order drafts for approval</option>
            </select></label>
          {!isDemo && (
            <label className={clsx("text-sm", !loaded && "invisible")}><span className="mb-1 block font-medium">Scope</span>
              <select value={scope} onChange={(e) => setScope(e.target.value as "all" | "selected")} className="rounded-lg border border-line bg-surface px-3 py-2">
                <option value="all">All stocked products</option><option value="selected" disabled={!ctx.sku}>Selected product {ctx.sku ? `(${ctx.sku})` : "(none selected)"}</option>
              </select></label>
          )}
          <div className="text-xs text-muted">Known by <span className="num">{dateTime(known)}</span><br />In force on <span className="num">{day(eff)}</span></div>
          <Button onClick={() => start.mutate()} busy={start.isPending} disabled={role !== "planner" || !known || !loaded}
            title={role !== "planner" ? "Only planners can start investigations" : undefined}>
            <Play className="size-4" aria-hidden /> Start investigation
          </Button>
        </div>
        {isDemo && <p className="mt-3 text-sm text-muted">Demo workspace: runs the specification&apos;s reference case — 30 units of DEMO-REF-SKU by 22 Oct 2026, budget USD 180. Try “Known by” 19 Oct vs 20 Oct 2026.</p>}
        {role && role !== "planner" && <p className="mt-3 text-xs text-muted">Your role ({role.replace("_", " ")}) can read runs but not start them.</p>}
        {start.error && <div className="mt-3"><ErrorState error={start.error} /></div>}
      </Card>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,4fr)_minmax(0,8fr)]">
        <Card className="p-4">
          <Eyebrow>Runs</Eyebrow>
          {runs.isLoading ? <Loading /> : runs.data?.length ? (
            <ul className="mt-2 space-y-1">
              {runs.data.map((r) => (
                <li key={r.id}>
                  <button onClick={() => setRunId(r.id)} aria-current={r.id === runId}
                    className={clsx("flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm", r.id === runId ? "bg-accent-soft" : "hover:bg-surface-2")}>
                    <span className="min-w-0 flex-1"><Mono className="font-semibold">{short(r.id)}</Mono>
                      <span className="block truncate text-xs text-muted">{r.mode} · {dateTime(r.created_at)}</span></span>
                    <Status value={r.status} />
                  </button>
                </li>
              ))}
            </ul>
          ) : runs.error ? <ErrorState error={runs.error} retry={() => runs.refetch()} /> : <div className="mt-2"><EmptyState variant="first_run" art="empty-decision-history" title="Your decision history will appear here" compact>
            Each investigation is stored with its steps, evidence and outcome.</EmptyState></div>}
        </Card>
        {runId ? <RunView id={runId} ws={ws} /> : <Card className="p-5"><Empty title="Select or start a run">Its steps stream here as they are persisted.</Empty></Card>}
      </div>
    </div>
  );
}

function RunView({ id, ws }: { id: string; ws: string }) {
  const qc = useQueryClient();
  const [events, setEvents] = useState<Event[]>([]);
  const [live, setLive] = useState(false);
  const detail = useApi(["run", id], "/api/v1/agent-runs/{run_id}", { path: { run_id: id } });
  const last = useRef(0);

  useEffect(() => {
    setEvents([]); last.current = 0; // eslint-disable-line react-hooks/set-state-in-effect -- a new run's stream starts from an empty timeline
    const es = new EventSource(`/api/v1/agent-runs/${id}/stream?ws=${encodeURIComponent(ws)}`);
    setLive(true);
    es.addEventListener("run_event", (m) => {
      let e: Event;
      try { e = JSON.parse((m as MessageEvent).data) as Event; } catch { return; }    // a malformed frame is skipped; the run detail is authoritative
      if (e.seq <= last.current) return;
      last.current = e.seq;
      setEvents((xs) => [...xs, e]);
    });
    es.addEventListener("status", () => { es.close(); setLive(false); qc.invalidateQueries({ queryKey: [ws, "run", id] }); qc.invalidateQueries({ queryKey: [ws, "runs"] }); });
    es.onerror = () => { setLive(false); };
    return () => es.close();
  }, [id, ws, qc]);

  const d = detail.data;
  const done = new Set(events.filter((e) => e.kind === "node_completed").map((e) => e.node));
  const cur = d?.settings?.currency ?? "GBP";
  return (
    <div className="space-y-6">
      <Card className="p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><Eyebrow>Run {short(id)}</Eyebrow>{d && <p className="mt-1 text-sm text-muted">{d.mode} · {d.tool_calls ?? 0} tool calls of {d.budget?.max_tool_calls} · time limit {d.budget?.max_seconds}s</p>}</div>
          <div className="flex items-center gap-2">{live && <span className="text-xs text-muted" role="status">Streaming…</span>}<Status value={d?.status} /></div>
        </div>
        <ol className="mt-4 grid grid-cols-3 gap-2 md:grid-cols-6" aria-label="Run stages">
          {STAGES.map((s) => (
            <li key={s} className={clsx("rounded-lg border px-2 py-2 text-xs", done.has(s) ? "border-accent bg-accent-soft text-accent" : "border-line text-muted")}>
              <span className="block font-semibold">{STAGE_LABEL[s]}</span>{done.has(s) ? "done" : "—"}
            </li>
          ))}
        </ol>
        <ol className="mt-4 space-y-2 border-l border-line pl-4" aria-live="polite">
          {events.map((e) => (
            <li key={e.seq} className="text-sm">
              <span className="num text-[11px] text-muted">#{e.seq} {e.node}</span>
              <p className={e.kind === "failed" || e.kind === "budget_exceeded" ? "text-danger" : ""}>{e.summary}</p>
            </li>
          ))}
        </ol>
      </Card>
      {d?.plan && (
        <Card className="p-5">
          <div className="flex flex-wrap items-center justify-between gap-2"><Eyebrow>Plan</Eyebrow>
            <span className="flex gap-2"><Status value={d.plan.status} /><Provenance kind="simulated" /></span></div>
          <div className="mt-3 grid gap-4 md:grid-cols-4">
            <div><Eyebrow>Lines</Eyebrow><p className="num text-xl font-semibold">{int(d.plan.lines?.length)}</p></div>
            <div><Eyebrow>Total</Eyebrow><p className="num text-xl font-semibold">{money(d.plan.total_minor, cur)}</p></div>
            <div><Eyebrow>Budget</Eyebrow><p className="num text-xl font-semibold">{money(d.plan.request?.budget_minor, cur)}</p><Provenance kind="assumed" /></div>
            <div><Eyebrow>Shortfall</Eyebrow><p className="num text-xl font-semibold">{int(Object.values(d.plan.shortfall).reduce((a, b) => a + b, 0))} units</p></div>
          </div>
          {d.plan.explanation?.length ? <ul className="mt-3 list-disc pl-5 text-sm text-risk">{d.plan.explanation.map((x) => <li key={x}>{x}</li>)}</ul> : null}
          {d.plan.arrival_warnings?.length ? <p className="mt-3 text-sm text-risk">{d.plan.arrival_warnings.length} line(s) arrive after their projected stockout date.</p> : null}
          <div className="mt-3"><KV items={[
            ["Solver", <Mono key="s">{d.plan.solver?.name} {d.plan.solver?.version} · workers {d.plan.solver?.num_workers} · seed {d.plan.solver?.random_seed}</Mono>],
            ["Input hash", <Mono key="h">{short(d.plan.input_hash, 16)}</Mono>],
            ["Checks", (d.checks?.passed ? "All passed (independent validator re-checked every line)" : (d.checks?.issues ?? []).map((i) => String(i.kind)).join(", "))
              + ((d.checks?.warnings ?? []).length ? ` · warning: ${(d.checks?.warnings ?? []).map((w) => w.kind === "shortfall" ? "partial order, some need left uncovered" : String(w.kind)).join(", ")}` : "")],
            ["Forecast", d.forecast?.available ? <Mono key="f">{short(d.forecast.run_id)} · origin {d.forecast.origin}</Mono> : "none (no sales history)"],
          ]} /></div>
        </Card>
      )}
      {d?.terms && (
        <Card className="p-5">
          <Eyebrow>Policy evidence used</Eyebrow>
          <p className="mt-2 text-sm">{d.terms.applicable.length} applicable terms · {d.terms.ignored.length} excluded · {d.terms.conflicts.length} conflicts</p>
          {d.terms.conflicts.length > 0 && <p className="mt-2 rounded-lg bg-risk-soft p-2 text-sm text-risk">Review required: conflicting active terms {d.terms.conflicts.map((c) => c.join(" vs ")).join("; ")}. No draft was prepared.</p>}
          <ul className="mt-2 space-y-1 text-xs text-muted">{d.terms.ignored.slice(0, 8).map((i) => <li key={i.term_id}><Mono>{i.term_id}</Mono> — {i.reason}</li>)}</ul>
          {d.upcoming_changes?.length ? <p className="mt-3 text-sm">Upcoming (known, not yet in force): {d.upcoming_changes.map((u) => `${u.supplier_id} ${u.sku_id} MOQ ${u.moq} from ${u.valid_from}`).slice(0, 4).join("; ")}</p> : null}
        </Card>
      )}
      {d?.actions?.length ? (
        <Card className="p-5">
          <Eyebrow>Prepared drafts</Eyebrow>
          <ul className="mt-2 divide-y divide-line">
            {d.actions.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                <Mono>{short(a.id)}</Mono><span>{a.supplier_id}</span><span className="num">{money(a.total_minor, a.currency)}</span>
                <Status value={a.status} />
                <Link className="ml-auto text-accent hover:underline" href={{ pathname: "/approvals", query: { ws, action: a.id } }}>Review</Link>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
      {detail.error && <ErrorState error={detail.error} />}
    </div>
  );
}

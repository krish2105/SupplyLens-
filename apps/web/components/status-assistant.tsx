"use client";
// Phase 8 WP6: the order and stock status assistant. A drawer opened from the header or the command palette. Answers come
// from this workspace's records only (POST /assistant/ask, deterministic, every sentence cites a record); nothing is
// generated and nothing is changed. "Talk to a person" builds a support ticket (POST /assistant/handoff), a dry run
// unless HubSpot is switched on outside the public demo.
import * as Dialog from "@radix-ui/react-dialog";
import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { MessageCircleQuestion, UserRound, X } from "lucide-react";
import { EmptyState } from "@/components/illustration";
import { Button, ErrorState, Loading, Mono } from "@/components/ui";
import { apiPost } from "@/lib/api";
import type { Schemas } from "@/lib/contract";
import { useWs } from "@/lib/queries";

type Answer = Schemas["AssistantAnswer"];
type Handoff = Schemas["AssistantHandoff"];
const OPEN_EVENT = "supplylens:open-assistant";
export const ASSISTANT_LABEL = "Ask about an order or stock";

/** Open the drawer from elsewhere (the command palette). */
export function openStatusAssistant() {
  window.dispatchEvent(new Event(OPEN_EVENT));
}

const KIND_LABEL: Record<string, string> = { product: "product", stock: "stock", order: "order", action: "action", terms: "terms" };

function withWs(href: string, ws: string) {
  return `${href}${href.includes("?") ? "&" : "?"}ws=${encodeURIComponent(ws)}`;
}

/** Keyed on the workspace by the layout, so another workspace's answers never stay on screen. */
export function StatusAssistant() {
  const ws = useWs();
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const ask = useMutation({
    mutationFn: (q: string) => apiPost("/api/v1/assistant/ask", { body: { question: q } }) as Promise<Answer>,
  });
  const handoff = useMutation({
    mutationFn: (b: { question: string; answer_status: "answered" | "withheld" | "choose" | "error" | "not_asked" }) =>
      apiPost("/api/v1/assistant/handoff", { body: b }) as Promise<Handoff>,
  });

  useEffect(() => {
    const onOpen = () => setOpen(true);
    window.addEventListener(OPEN_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_EVENT, onOpen);
  }, []);

  const run = (q: string) => {
    const text = q.trim();
    if (!text) return;
    setAsked(text); setQuestion(text); handoff.reset(); ask.mutate(text);
  };
  const submit = (e: FormEvent) => { e.preventDefault(); run(question); };
  const status = ask.isError ? "error" : ask.data?.status ?? "not_asked";
  const handoffQuestion = (asked ?? question).trim();
  const d = ask.data;

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button" className="inline-flex size-8 items-center justify-center rounded-lg text-muted hover:bg-surface-2 hover:text-ink"
          aria-label={ASSISTANT_LABEL} title={ASSISTANT_LABEL} data-testid="assistant-open">
          <MessageCircleQuestion className="size-4" aria-hidden />
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content data-testid="assistant-drawer" onOpenAutoFocus={(e) => { e.preventDefault(); input.current?.focus(); }}
          className="fixed inset-y-0 right-0 z-50 flex w-[min(440px,100vw)] flex-col overflow-y-auto border-l border-line bg-surface p-4 shadow-xl sm:p-5">
          <div className="flex items-start justify-between gap-3">
            <Dialog.Title className="display text-lg font-semibold">{ASSISTANT_LABEL}</Dialog.Title>
            <Dialog.Close className="inline-flex size-8 shrink-0 items-center justify-center rounded-lg text-muted hover:bg-surface-2 hover:text-ink" aria-label="Close the assistant">
              <X className="size-4" aria-hidden /></Dialog.Close>
          </div>
          <Dialog.Description className="mt-1 text-sm text-muted">
            Answers come only from this workspace&apos;s records; nothing is generated and nothing is changed.
          </Dialog.Description>

          <form onSubmit={submit} className="mt-4 flex flex-col gap-2" role="search" aria-label="Ask the assistant">
            <label htmlFor="assistant-q" className="text-sm font-medium">Your question</label>
            <div className="flex gap-2">
              <input id="assistant-q" ref={input} value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={500}
                placeholder="e.g. stock of a product code, or an order number" autoComplete="off"
                className="h-10 min-w-0 flex-1 rounded-lg border border-line bg-surface-2 px-3 text-sm" />
              <Button type="submit" busy={ask.isPending} disabled={!question.trim() || ask.isPending}>Ask</Button>
            </div>
          </form>

          <div className="mt-4 flex-1" aria-live="polite">
            {ask.isPending ? <Loading label="Looking up records" /> : ask.isError ? (
              <ErrorState error={ask.error} retry={() => asked && run(asked)} />
            ) : !d ? (
              <EmptyState variant="first_run" art="assistant-ready" title={ASSISTANT_LABEL} compact>
                Ask about a product (its code or name), an order number or an action id: stock on hand, days of cover, open orders,
                approval state and the supplier terms in force. Every answer links to the records it came from.
              </EmptyState>
            ) : d.status === "answered" ? (
              <div data-testid="assistant-answer" className="space-y-3">
                <ul className="space-y-3 text-sm">
                  {d.sentences.map((s, i) => (
                    <li key={i}>
                      <p>{s.text}</p>
                      <p className="mt-1 flex flex-wrap gap-1.5">
                        {s.citations.map((c) => (
                          <Link key={`${c.kind}:${c.id}`} href={withWs(c.href, ws)} onClick={() => setOpen(false)}
                            className="inline-flex min-h-6 items-center gap-1 rounded-md border border-line px-1.5 text-[11px] text-muted hover:text-ink">
                            {KIND_LABEL[c.kind] ?? c.kind} <Mono>{c.id.length > 14 ? `${c.id.slice(0, 8)}…` : c.id}</Mono>
                          </Link>))}
                      </p>
                    </li>))}
                </ul>
                {d.as_of && <p className="text-xs text-muted">Records as of {d.as_of}.</p>}
              </div>
            ) : d.status === "choose" ? (
              <div data-testid="assistant-choose" className="space-y-2">
                <p className="text-sm">{d.reason}</p>
                <div className="flex flex-wrap gap-2">
                  {d.choices.map((c) => <Button key={c.id} size="sm" variant="outline" onClick={() => run(c.id)}>{c.label}</Button>)}
                </div>
                {d.choices_total > d.choices.length && <p className="text-xs text-muted">Showing {d.choices.length} of {d.choices_total}; type the product code to pick another.</p>}
              </div>
            ) : (
              <div data-testid="assistant-withheld" role="status" className="rounded-lg border border-line bg-surface-2 p-3 text-sm">
                <p className="font-medium">Not answered</p>
                <p className="mt-1 text-muted">{d.reason}</p>
              </div>
            )}
          </div>

          <div className="mt-6 border-t border-line pt-4">
            <Button variant="outline" size="sm" disabled={!handoffQuestion || handoff.isPending} busy={handoff.isPending}
              onClick={() => handoff.mutate({ question: handoffQuestion, answer_status: status })}>
              <UserRound className="size-4" aria-hidden /> Talk to a person
            </Button>
            {!handoffQuestion && <p className="mt-1 text-xs text-muted">Type a question first; it goes into the ticket.</p>}
            <div aria-live="polite" className="mt-2 text-sm">
              {handoff.isError ? <ErrorState error={handoff.error} retry={() => handoff.mutate({ question: handoffQuestion, answer_status: status })} />
                : handoff.data && (
                  <p data-testid="assistant-handoff" className={handoff.data.sent ? "text-accent" : "text-muted"}>{handoff.data.message}</p>)}
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

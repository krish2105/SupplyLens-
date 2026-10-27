"use client";
// A cited answer written by a local model from the retrieved passages (F1; D-094). Every sentence
// carries the numbers of the passages it rests on; an answer that failed the server's checks is shown as withheld with the
// reason, never as an answer. Where generation is off (the public demo) the passages above remain the answer.
import { useMutation } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { Button, Provenance } from "@/components/ui";
import { apiPost, intentKey } from "@/lib/api";
import type { Schemas } from "@/lib/contract";

type Answer = Schemas["GeneratedAnswer"];

export function CitedAnswer({ q, mode, supplier, known, eff, onOpen }: {
  q: string; mode: string; supplier?: string; known?: string | null; eff?: string | null;
  onOpen: (versionId: string, chunkId: string) => void;
}) {
  const ask = useMutation({
    mutationFn: async () => {
      const body = { q, mode, supplier_id: supplier, knowledge_cutoff: known ?? undefined, effective_date: eff ?? undefined };
      const intent = intentKey("cited-answer", body);
      const r = await apiPost("/api/v1/evidence/answer", { body: body as never, idempotencyKey: intent.key });
      intent.settle();
      return r as Answer;
    },
  });
  const d = ask.data;
  const g = d?.generated;
  return (
    <div className="rounded-xl border border-line p-4" data-testid="cited-answer">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">Cited answer (generated)</h3>
        {d?.generation === "answered" && <Provenance kind="generated" />}
        <Button size="sm" variant="outline" className="ml-auto" onClick={() => ask.mutate()} disabled={!q.trim() || ask.isPending}>
          <Sparkles className="size-4" aria-hidden /> {ask.isPending ? "Writing from the passages…" : "Write a cited answer"}
        </Button>
      </div>
      <p className="mt-1 text-xs text-muted">A local model may only restate the passages; each sentence is checked against the passages it cites, and figures that are not in them stop the answer.</p>
      <div aria-live="polite">
        {ask.error && <p className="mt-3 text-sm text-danger">The answer could not be requested. The passages above are unaffected.</p>}
        {d && d.generation === "answered" && g && (
          <div className="mt-3 space-y-2">
            {g.sentences.map((s, i) => (
              <p key={i} className="text-sm">{s.sentence}{" "}
                {s.cites.map((n) => {
                  const c = g.citations.find((x) => x.n === n);
                  return c ? (
                    <button key={n} className="num mr-1 rounded border border-line px-1 text-xs text-accent hover:bg-accent-soft"
                      title={`${c.title} ${c.version_label}, ${c.section}`} aria-label={`Source ${n}: ${c.title} ${c.version_label}, ${c.section}`}
                      onClick={() => onOpen(c.version_id, c.chunk_id)}>[{n}]</button>
                  ) : null;
                })}
              </p>
            ))}
            <p className="text-xs text-muted">Written by {g.model} in {Math.round((g.latency_ms ?? 0) / 100) / 10} s from {g.citations.length} passages. Check the cited passages before acting.</p>
          </div>
        )}
        {d && d.generation !== "answered" && (
          <p className="mt-3 text-sm text-muted">
            {d.generation === "off" ? "Generated answers are switched off here. " : d.generation === "withheld" ? "The answer was withheld: " : "Nothing was generated: "}
            {d.message}
          </p>
        )}
      </div>
    </div>
  );
}

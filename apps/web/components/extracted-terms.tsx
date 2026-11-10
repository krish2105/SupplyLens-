"use client";
// Phase 8 WP7: the "Extracted terms" tab of the Policies document reader. Draft fields that deterministic rules read
// from this version's text (GET /documents/versions/{id}/extracted-terms), each with the character span it came from.
// Read-only: nothing here is stored or used for planning; confirming a field is a later step.
import clsx from "clsx";
import { EmptyState } from "@/components/illustration";
import { Button, ErrorState, Loading, Mono, TableScroll } from "@/components/ui";
import type { Schemas } from "@/lib/contract";
import { useApi } from "@/lib/queries";

export type ExtractedField = Schemas["ExtractedField"];

const FIELD_LABEL: Record<string, string> = {
  parties: "Party", agreement_date: "Agreement date", effective_date: "Effective date", expiry_date: "Term and expiry",
  renewal: "Renewal", termination_for_convenience: "Termination for convenience", exclusivity: "Exclusivity",
  minimum_commitment: "Minimum commitment", price: "Price", moq: "Minimum order quantity", lead_time: "Lead time",
};

export function fieldLabel(field: string) {
  return FIELD_LABEL[field] ?? field.replaceAll("_", " ");
}

export const sameField = (a: ExtractedField | null, b: ExtractedField | null) =>
  !!a && !!b && a.field === b.field && a.start === b.start && a.end === b.end;

export function DraftBadge() {
  return <span className="inline-flex items-center rounded-md bg-risk-soft px-2 py-0.5 text-[11px] font-semibold tracking-wide text-risk">DRAFT</span>;
}

export function ExtractedTerms({ versionId, shown, onShow }: {
  versionId: string; shown: ExtractedField | null; onShow: (f: ExtractedField) => void;
}) {
  const q = useApi(["extracted-terms", versionId], "/api/v1/documents/versions/{version_id}/extracted-terms",
    { path: { version_id: versionId } });
  const fields = q.data?.fields ?? [];
  return (
    <section aria-labelledby={`terms-${versionId}`} data-testid="extracted-terms" className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={`terms-${versionId}`} className="text-sm font-semibold">Extracted terms</h3>
        <DraftBadge />
        <span className="text-xs text-muted">Found by fixed text rules{q.data ? ` (${q.data.extractor})` : ""}; no AI model runs here.</span>
      </div>
      <p className="text-sm text-muted">Draft: not used for planning. A person must confirm a field before it is used; confirming arrives in a later step.</p>
      {q.isLoading ? <Loading label="Reading terms" /> : q.error ? <ErrorState error={q.error} retry={() => { q.refetch(); }} /> : fields.length === 0 ? (
        <EmptyState variant="empty_scope" art="empty-extraction" title="No terms found in this version" compact>
          The rules look for parties, dates, term and renewal, termination for convenience, exclusivity, minimum commitment, price,
          minimum order quantity and lead time, and found none in this text. Read the document text to check.
        </EmptyState>
      ) : (
        <TableScroll label="Extracted terms" min={520}>
          <table className="w-full text-sm">
            <caption className="sr-only">Extracted terms (draft), one row per field found</caption>
            <thead>
              <tr className="border-b border-line text-left text-xs text-muted">
                <th scope="col" className="py-2 pr-3 font-medium">Field</th>
                <th scope="col" className="pr-3 font-medium">Value</th>
                <th scope="col" className="pr-3 font-medium">Source</th>
                <th scope="col" className="font-medium"><span className="sr-only">Cited span</span></th>
              </tr>
            </thead>
            <tbody>
              {fields.map((f) => (
                <tr key={`${f.field}-${f.start}-${f.end}`} className={clsx("border-b border-line/60 align-top", sameField(f, shown) && "bg-accent-soft/40")}>
                  <th scope="row" className="py-2 pr-3 text-left font-medium">{fieldLabel(f.field)}</th>
                  <td className="py-2 pr-3">
                    <span className="[overflow-wrap:anywhere]">{f.value}</span>
                    <span className="num mt-0.5 block whitespace-nowrap text-[11px] text-muted">characters {f.start}–{f.end}</span>
                  </td>
                  <td className="py-2 pr-3"><Mono>{f.source}</Mono></td>
                  <td className="py-2 text-right">
                    <Button size="sm" variant="outline" className="whitespace-nowrap" onClick={() => onShow(f)}>
                      Show in text<span className="sr-only">: {fieldLabel(f.field)}, characters {f.start} to {f.end}</span>
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      )}
    </section>
  );
}

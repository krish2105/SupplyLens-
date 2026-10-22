"use client";
// Shared planning context (UX-003). Non-sensitive state lives in the URL so views are
// shareable and survive reloads and theme changes.
import { parseAsString, useQueryState, useQueryStates } from "nuqs";

export const contextParsers = {
  ws: parseAsString.withDefault("uci-research"),
  known: parseAsString,      // knowledge cutoff (ISO datetime); null = workspace operational as-of
  eff: parseAsString,        // effective date (YYYY-MM-DD); null = date of the cutoff
  sku: parseAsString,        // selected product
  // Entity selections belong to one workspace and clock: switching workspace clears them (audit S15), so an action or
  // run id from the previous workspace can never be shown, fetched or exported against the new one.
  action: parseAsString,     // approvals: selected purchase-order draft
  run: parseAsString,        // investigations: selected run
};

export function usePlanningContext() {
  return useQueryStates(contextParsers, { history: "replace" });
}

export function useSelectedSku() {
  return useQueryState("sku", parseAsString);
}

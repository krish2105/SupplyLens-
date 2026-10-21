"use client";
// Shared planning context (UX-003). Non-sensitive state lives in the URL so views are
// shareable and survive reloads and theme changes.
import { parseAsString, useQueryState, useQueryStates } from "nuqs";

export const contextParsers = {
  ws: parseAsString.withDefault("uci-research"),
  known: parseAsString,      // knowledge cutoff (ISO datetime); null = workspace operational as-of
  eff: parseAsString,        // effective date (YYYY-MM-DD); null = date of the cutoff
  sku: parseAsString,        // selected product
};

export function usePlanningContext() {
  return useQueryStates(contextParsers, { history: "replace" });
}

export function useSelectedSku() {
  return useQueryState("sku", parseAsString);
}

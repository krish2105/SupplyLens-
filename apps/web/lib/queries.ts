"use client";
import { useQuery } from "@tanstack/react-query";
import { api, getTenant } from "./api";
import { usePlanningContext } from "./state";

export type Me = {
  user: { id: string; email: string; display_name: string; is_dev_account: boolean };
  memberships: { slug: string; name: string; kind: string; description: string; role: string }[];
};

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/api/v1/me"), retry: false });

/** Every tenant-scoped query key starts with the workspace so switching cancels and refetches. */
export function useWs() {
  const [ctx] = usePlanningContext();
  return ctx.ws;
}

export function useTenantQuery<T>(key: unknown[], path: string | null, opts: { refetchInterval?: number | false } = {}) {
  const ws = useWs();
  return useQuery({
    queryKey: [ws, ...key],
    queryFn: ({ signal }) => api<T>(path!, { signal, tenant: ws }),
    enabled: !!path && getTenant() === ws,
    refetchInterval: opts.refetchInterval,
  });
}

export type Overview = {
  settings: { operational_as_of: string; currency: string; dataset_id: string | null; planning: Record<string, unknown> } | null;
  dataset: null | { id: string; name: string; license: string; source_url: string; sha256: string; created_at: string;
    totals: Record<string, number>; date_span: [string, string] };
  counts: Record<string, number>;
  actions_by_status: Record<string, number>;
  assumption_set: null | { name: string; version: number; rationale: string };
  capabilities: { capability: string; status: string; basis: string | null; note: string }[];
};

export type InventoryItem = {
  sku_id: string; description: string; unit: string; location_id: string; zone_id: string; as_of: string;
  on_hand: number; allocated: number; on_order: number; capacity: number | null; value_kind: string; available: number;
  avg_daily: number | null; days_of_cover: number | null; health: string; health_basis: string | null;
  slot_id: string | null; aisle: number | null; rack: number | null; x: number | null; z: number | null; term_count: number;
};

export type Action = {
  id: string; status: string; total_minor: number; currency: string; payload: any; payload_hash: string; row_version: number;
  external_ref: string | null; status_reason: string | null; created_at: string; updated_at: string; agent_run_id: string | null;
  prepared_by?: string; evidence?: any; approvals?: any[]; outbox?: any; prepared_by_id?: string;
};

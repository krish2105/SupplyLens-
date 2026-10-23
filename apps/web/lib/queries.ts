"use client";
import { useQuery } from "@tanstack/react-query";
import { apiGet, getTenant } from "./api";
import type { Args, PathsWith, Res, Schemas } from "./contract";
import { usePlanningContext } from "./state";

export type Me = Schemas["Me"];
export type Overview = Schemas["Overview"];
export type InventoryItem = Schemas["InventoryItem"];
export type Action = Schemas["ActionDetail"];

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => apiGet("/api/v1/me"), retry: false });

/** Server profile (environment, sign-in methods). In the public demo profile administration is read-only for everyone
 *  (D-051); screens say so before a click instead of after a refusal (P3-FE-10). */
export const useAuthConfig = () => useQuery({ queryKey: ["auth-config"], queryFn: () => apiGet("/api/v1/auth/config"), staleTime: Infinity });
export function useDemoLockdown() {
  return useAuthConfig().data?.environment === "demo";
}

/** Every tenant-scoped query key starts with the workspace so switching cancels and refetches. */
export function useWs() {
  const [ctx] = usePlanningContext();
  return ctx.ws;
}

/**
 * Tenant-scoped GET typed from the API contract: the response type, path parameters and query all come from
 * packages/contracts/api.d.ts. Pass `null` as the path to disable the query.
 */
export function useApi<P extends PathsWith<"get">>(
  key: unknown[], path: P | null, args?: Args<P> & { refetchInterval?: number | false },
) {
  const ws = useWs();
  const { refetchInterval, ...rest } = (args ?? {}) as { refetchInterval?: number | false };
  const q = useQuery<Res<P>>({
    queryKey: [ws, ...key],
    queryFn: ({ signal }) => apiGet(path as P, { ...(rest as Args<P>), tenant: ws, signal }) as Promise<Res<P>>,
    enabled: !!path && getTenant() === ws,
    refetchInterval,
  });
  // TanStack reports isLoading=false until the fetch has actually started, so a screen would flash its empty state
  // (and shift the layout) before the first request. Here: a wanted query with no data yet is loading.
  return { ...q, isLoading: !!path && q.isPending } as typeof q;
}

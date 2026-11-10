"use client";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Hourglass, Loader2, WifiOff } from "lucide-react";
import { busySignal } from "@/lib/api";

const subscribe = (cb: () => void) => {
  window.addEventListener("online", cb);
  window.addEventListener("offline", cb);
  return () => { window.removeEventListener("online", cb); window.removeEventListener("offline", cb); };
};

export function useOnline() {
  return useSyncExternalStore(subscribe, () => navigator.onLine, () => true);
}

/** True for a few seconds after the service refused a request for capacity (lib/api.ts). */
export function useServiceBusy() {
  return useSyncExternalStore(busySignal.subscribe, busySignal.snapshot, () => false);
}

/** True once `pending` has lasted `ms`, and false as soon as it ends. */
export function useSlow(pending: boolean, ms = 1500) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (!pending) return;
    const t = setTimeout(() => setSlow(true), ms);
    return () => { clearTimeout(t); setSlow(false); };
  }, [pending, ms]);
  return pending && slow;
}

/**
 * Announces a session check that is taking long (the hosted service starting after a quiet period, FE-P8-07), loss of
 * connection, and a service that is shedding load. The live region is always mounted so assistive technology announces the change.
 * While offline the app keeps what the user typed (drafts persist) and retries when the connection returns.
 */
export function ConnectionBanner({ waking = false }: { waking?: boolean }) {
  const online = useOnline();
  const busy = useServiceBusy();
  const slowStart = useSlow(waking);
  return (
    <div role="status" aria-live="polite" data-testid="connection-status">
      {online && slowStart && (
        <div data-testid="service-waking" className="flex items-center gap-2 border-b border-accent/30 bg-accent-soft px-4 py-2 text-sm text-ink md:px-6">
          <Loader2 className="size-4 shrink-0 animate-spin text-accent motion-reduce:animate-none" aria-hidden />
          <span><b>Starting SupplyLens.</b> The service sleeps when nobody is using it, so the first visit after a quiet period
            can take up to ten seconds. This page fills in by itself; if your session has ended you go to sign-in.</span>
        </div>
      )}
      {online && busy && (
        <div data-testid="service-busy" className="flex items-center gap-2 border-b border-accent/30 bg-accent-soft px-4 py-2 text-sm text-ink md:px-6">
          <Hourglass className="size-4 shrink-0 text-accent" aria-hidden />
          <span><b>SupplyLens is busy.</b> Some requests were turned away to keep the service responsive and are being retried
            automatically. Nothing you typed is lost.</span>
        </div>
      )}
      {!online && (
        <div className="flex items-center gap-2 border-b border-risk/40 bg-risk-soft px-4 py-2 text-sm text-risk md:px-6">
          <WifiOff className="size-4 shrink-0" aria-hidden />
          <span><b>You are offline.</b> Nothing you typed is lost. Pending actions resume automatically when the connection returns; live data may be out of date.</span>
        </div>
      )}
    </div>
  );
}

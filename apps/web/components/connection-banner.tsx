"use client";
import { useSyncExternalStore } from "react";
import { Hourglass, WifiOff } from "lucide-react";
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

/**
 * Announces loss of connection, and a service that is shedding load. The live region is always mounted so assistive technology announces the change.
 * While offline the app keeps what the user typed (drafts persist) and retries when the connection returns.
 */
export function ConnectionBanner() {
  const online = useOnline();
  const busy = useServiceBusy();
  return (
    <div role="status" aria-live="polite" data-testid="connection-status">
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

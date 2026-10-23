"use client";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";
import { api } from "@/lib/api";

/** Reports field Web Vitals (LCP, INP, CLS, FCP, TTFB) of real sessions; the admin screen shows p75 against UX-011 targets.
 *  The observers are registered once per page load (P2-FE-08): registering them again on every route change duplicated
 *  reports, and each one carries the route current when it is sent. */
export function VitalsReporter() {
  const route = usePathname();
  const current = useRef(route);
  useEffect(() => { current.current = route; }, [route]);
  useEffect(() => {
    let cancelled = false;
    import("web-vitals").then(({ onLCP, onINP, onCLS, onFCP, onTTFB }) => {
      if (cancelled) return;
      const send = (m: { name: string; value: number; rating: string; navigationType?: string }) => {
        // Beacons cannot carry the CSRF/tenant headers; keepalive fetch survives page unload and is best-effort.
        api("/api/v1/telemetry/vitals", { method: "POST", keepalive: true,
          body: JSON.stringify({ metric: m.name, value: m.value, rating: m.rating, route: current.current, nav_type: m.navigationType ?? null }) }).catch(() => {});
      };
      onLCP(send); onINP(send); onCLS(send); onFCP(send); onTTFB(send);
    });
    return () => { cancelled = true; };
  }, []);
  return null;
}

"use client";
// Illustrations and empty/error states (UX asset pack A01-A16). Rules from docs/design/illustrations.md:
// art is decorative (alt=""), sits beside semantic HTML text and actions, never carries data, never appears above a
// populated work queue, and each piece is shown only in the state it was briefed for. Three pack items are not
// published (A02, A13, A16); their states use an icon instead.
import clsx from "clsx";
import { AlertTriangle, Ban, Clock3, type LucideIcon } from "lucide-react";
import { useState, type ReactNode } from "react";

export type Art =
  | "welcome" | "empty-inventory" | "empty-evidence" | "forecast-setup" | "empty-scenarios" | "no-results"
  | "no-pending-work" | "connection-paused" | "restricted-access" | "empty-integrations" | "policy-change"
  | "empty-research" | "empty-decision-history";

const FILE: Record<Art, string> = {
  welcome: "sl-welcome", "empty-inventory": "sl-empty-inventory", "empty-evidence": "sl-empty-evidence",
  "forecast-setup": "sl-forecast-setup", "empty-scenarios": "sl-empty-scenarios", "no-results": "sl-no-results",
  "no-pending-work": "sl-no-pending-work", "connection-paused": "sl-connection-paused",
  "restricted-access": "sl-restricted-access", "empty-integrations": "sl-empty-integrations",
  "policy-change": "sl-policy-change", "empty-research": "sl-empty-research",
  "empty-decision-history": "sl-empty-decision-history",
};

/** Decorative illustration with reserved space; a failed image load collapses to nothing (text carries the meaning). */
export function Illustration({ art, size = 144, className }: { art: Art; size?: number; className?: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  const wide = art === "welcome";
  return (
    // eslint-disable-next-line @next/next/no-img-element -- pre-optimised static WebP; next/image adds nothing here
    <img src={`/illustrations/supplylens/${FILE[art]}.webp`} alt="" aria-hidden="true" draggable={false}
      width={wide ? size : size} height={wide ? Math.round(size * 2 / 3) : size} loading="lazy" decoding="async"
      onError={() => setFailed(true)} data-illustration={art}
      className={clsx("pointer-events-none shrink-0 select-none object-contain", className)} />
  );
}

export type EmptyVariant =
  | "first_run" | "empty_scope" | "empty_filtered" | "no_pending" | "offline" | "permission_denied" | "unavailable" | "stale"
  | "error";

const ICON: Partial<Record<EmptyVariant, LucideIcon>> = { unavailable: Ban, stale: Clock3, error: AlertTriangle };
const DEFAULT_ART: Partial<Record<EmptyVariant, Art>> = {
  empty_filtered: "no-results", no_pending: "no-pending-work", offline: "connection-paused",
  permission_denied: "restricted-access",
};

/** One component for every non-populated state. `art` only where the pack has a reviewed piece for that state. */
export function EmptyState({ variant, title, children, action, art, icon, compact, className }: {
  variant: EmptyVariant; title: string; children?: ReactNode; action?: ReactNode; art?: Art | null; icon?: LucideIcon;
  compact?: boolean; className?: string;
}) {
  const pic = art === null ? undefined : art ?? DEFAULT_ART[variant];
  const Icon = icon ?? ICON[variant];
  const alert = variant === "offline" || variant === "error";
  return (
    <div role={alert ? "alert" : "status"} data-state={variant}
      className={clsx("flex items-center gap-5 rounded-xl border p-5",
        alert ? "border-danger/40 bg-danger-soft/40" : "border-dashed border-line-strong",
        compact ? "flex-row" : "flex-col text-center sm:flex-row sm:text-left", className)}>
      {pic ? <Illustration art={pic} size={compact ? 96 : 144} />
        : Icon ? <Icon className={clsx("size-6 shrink-0", alert ? "text-danger" : "text-muted")} aria-hidden /> : null}
      <div className="min-w-0 space-y-1.5">
        <p className="font-semibold">{title}</p>
        {children && <div className="text-sm text-muted">{children}</div>}
        {action && <div className="pt-1">{action}</div>}
      </div>
    </div>
  );
}

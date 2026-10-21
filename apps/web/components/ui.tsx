"use client";
import clsx from "clsx";
import { AlertTriangle, Inbox, Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { ApiError } from "@/lib/api";

export function Button({ variant = "primary", size = "md", busy, className, children, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "outline" | "danger"; size?: "sm" | "md"; busy?: boolean }) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || busy}
      aria-busy={busy || undefined}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-sm" : "h-10 px-4 text-sm",
        variant === "primary" && "bg-accent text-accent-ink hover:brightness-110",
        variant === "outline" && "border border-line-strong bg-surface text-ink hover:bg-surface-2",
        variant === "ghost" && "text-ink hover:bg-surface-2",
        variant === "danger" && "border border-danger text-danger hover:bg-danger-soft",
        className,
      )}
    >
      {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function Card({ className, children, as: As = "section", ...rest }: { className?: string; children: ReactNode; as?: "section" | "div" | "article"; "aria-labelledby"?: string }) {
  return <As {...rest} className={clsx("card", className)}>{children}</As>;
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">{children}</p>;
}

export function PageHeader({ eyebrow, title, children, actions }: { eyebrow: string; title: ReactNode; children?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-3xl">
        <Eyebrow>{eyebrow}</Eyebrow>
        <h1 className="display mt-1 text-3xl font-semibold leading-tight md:text-4xl">{title}</h1>
        {children && <div className="mt-2 text-[15px] text-muted">{children}</div>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

const KIND_STYLE: Record<string, string> = {
  observed: "bg-accent-soft text-accent",
  forecast: "bg-[var(--forecast-soft)] text-forecast",
  assumed: "bg-risk-soft text-risk",
  simulated: "bg-sim-soft text-sim",
  synthetic: "bg-sim-soft text-sim",
  derived: "bg-surface-2 text-muted border border-line",
};

/** Provenance chip (UX-003): Observed, Forecast, Assumed, Simulated, Synthetic, Derived. */
export function Provenance({ kind, className }: { kind: string | null | undefined; className?: string }) {
  if (!kind) return null;
  const k = kind.toLowerCase();
  return (
    <span className={clsx("inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold capitalize", KIND_STYLE[k] ?? KIND_STYLE.derived, className)}
      title={`Value kind: ${k}`}>
      {k}
    </span>
  );
}

const STATUS_TONE: Record<string, string> = {
  RECONCILED: "ok", COMPLETE: "ok", SUCCEEDED: "ok", OPTIMAL: "ok", healthy: "ok", VERIFIED_LOCALLY: "ok", READY: "ok", available: "ok",
  PENDING_APPROVAL: "warn", WAITING_FOR_APPROVAL: "warn", QUEUED: "info", RUNNING: "info", SUBMITTED: "info", FEASIBLE: "info",
  reorder: "info", "sandbox only": "info", assumed: "warn", synthetic: "sim",
  UNKNOWN_OUTCOME: "danger", FAILED: "danger", STALE: "danger", INFEASIBLE: "danger", REJECTED: "danger", shortage_risk: "danger",
  REVIEW_REQUIRED: "warn", PARTIAL: "warn", excess: "warn", DEGRADED: "warn", NOT_CONFIGURED: "muted", NOT_IMPLEMENTED: "muted",
  DISABLED: "muted", unavailable: "muted", no_sales_data: "muted", CLOSED_WITHOUT_ORDER: "muted", NO_ACTION: "muted",
};
const TONE_CLASS: Record<string, string> = {
  ok: "bg-accent-soft text-accent", warn: "bg-risk-soft text-risk", danger: "bg-danger-soft text-danger",
  info: "bg-[var(--forecast-soft)] text-forecast", muted: "bg-surface-2 text-muted border border-line", sim: "bg-sim-soft text-sim",
};

export function Status({ value }: { value: string | null | undefined }) {
  if (!value) return null;
  const tone = STATUS_TONE[value] ?? "muted";
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-semibold tracking-wide", TONE_CLASS[tone])}>
      <span aria-hidden className="size-1.5 rounded-full bg-current" />
      {value.replaceAll("_", " ")}
    </span>
  );
}

export function Stat({ label, value, sub, kind }: { label: string; value: ReactNode; sub?: ReactNode; kind?: string }) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-2"><Eyebrow>{label}</Eyebrow>{kind && <Provenance kind={kind} />}</div>
      <div className="num mt-1 text-2xl font-semibold">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={clsx("animate-pulse rounded-lg bg-surface-2", className)} />;
}

export function Loading({ label = "Loading", className }: { label?: string; className?: string }) {
  return (
    <div role="status" className={clsx("flex items-center gap-2 p-6 text-sm text-muted", className)}>
      <Loader2 className="size-4 animate-spin" aria-hidden /> {label}…
    </div>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-2 rounded-xl border border-dashed border-line-strong p-6">
      <Inbox className="size-5 text-muted" aria-hidden />
      <p className="font-medium">{title}</p>
      {children && <div className="text-sm text-muted">{children}</div>}
      {action}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const msg = error instanceof ApiError ? `${error.message} (${error.code})` : error instanceof Error ? error.message : "Request failed";
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded-xl border border-danger/40 bg-danger-soft p-4 text-sm text-danger">
      <AlertTriangle className="size-4" aria-hidden />
      <span className="flex-1">{msg}</span>
      {retry && <Button size="sm" variant="outline" onClick={retry}>Try again</Button>}
    </div>
  );
}

export function KV({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(110px,auto)_1fr] gap-x-4 gap-y-1.5 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={clsx("num text-[12px]", className)}>{children}</span>;
}

"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Suspense, useEffect, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTheme } from "next-themes";
import clsx from "clsx";
import {
  BadgePoundSterling, Boxes, ClipboardCheck, Database, FileText, FlaskConical, Gauge, Globe2, LineChart, LogOut, Microscope, Monitor, Moon,
  Settings2, ShieldCheck, Siren, Sparkles, Sun, Workflow,
} from "lucide-react";
import { CommandPalette } from "@/components/command-palette";
import { ClockRail } from "@/components/clock-rail";
import { ConnectionBanner } from "@/components/connection-banner";
import { VitalsReporter } from "@/components/vitals-reporter";
import { ErrorState, Loading } from "@/components/ui";
import { ApiError, apiPost, setTenant } from "@/lib/api";
import { useMe } from "@/lib/queries";
import { usePlanningContext } from "@/lib/state";

const NAV = [
  { href: "/", label: "Overview", icon: Gauge, group: "Plan" },
  { href: "/exceptions", label: "Exceptions", icon: Siren, group: "Plan" },
  { href: "/inventory", label: "Inventory", icon: Boxes, group: "Plan" },
  { href: "/forecast", label: "Forecast lab", icon: LineChart, group: "Plan" },
  { href: "/scenarios", label: "Scenario studio", icon: FlaskConical, group: "Plan" },
  { href: "/runs", label: "Investigations", icon: Workflow, group: "Decide" },
  { href: "/approvals", label: "Approvals", icon: ClipboardCheck, group: "Decide" },
  { href: "/policies", label: "Policies & evidence", icon: FileText, group: "Know" },
  { href: "/market", label: "Supplier market", icon: Globe2, group: "Know" },
  { href: "/research", label: "Research", icon: Microscope, group: "Prove" },
  { href: "/value", label: "Value", icon: BadgePoundSterling, group: "Prove" },
  { href: "/data", label: "Data admission", icon: Database, group: "Govern" },
  { href: "/admin", label: "Administration", icon: ShieldCheck, group: "Govern" },
  { href: "/settings", label: "Settings", icon: Settings2, group: "Govern" },
];
const GROUPS = ["Plan", "Decide", "Know", "Prove", "Govern"];

/** Native radio inputs (audit S17): arrow keys move and select, Tab enters and leaves the group as one stop. */
function ThemeSwitch() {
  const { theme, setTheme } = useTheme();
  const opts = [
    { v: "light", icon: Sun, label: "Light theme" },
    { v: "dark", icon: Moon, label: "Dark theme" },
    { v: "system", icon: Monitor, label: "Follow system theme" },
  ];
  return (
    <fieldset className="inline-flex rounded-lg border border-line bg-surface p-0.5">
      <legend className="sr-only">Theme</legend>
      {opts.map(({ v, icon: Icon, label }) => (
        <label key={v} title={label}
          className={clsx("relative flex size-7 cursor-pointer items-center justify-center rounded-md has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent",
            theme === v ? "bg-accent text-accent-ink" : "text-muted hover:text-ink")}>
          <input type="radio" name="theme-switch" value={v} checked={theme === v} onChange={() => setTheme(v)} aria-label={label}
            className="absolute inset-0 m-0 cursor-pointer appearance-none opacity-0" />
          <Icon className="size-3.5" aria-hidden />
        </label>
      ))}
    </fieldset>
  );
}

// URL-backed planning state needs a Suspense boundary for static prerendering.
export default function AppLayout({ children }: { children: ReactNode }) {
  return <Suspense fallback={<Loading label="Loading workspace" className="min-h-screen justify-center" />}><AppShell>{children}</AppShell></Suspense>;
}

function AppShell({ children }: { children: ReactNode }) {
  const me = useMe();
  const router = useRouter();
  const path = usePathname();
  const qc = useQueryClient();
  const [ctx, setCtx] = usePlanningContext();
  setTenant(ctx.ws);

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) router.replace("/login");
  }, [me.error, router]);

  // A failed session check is never an endless spinner (audit S22): 401 goes to sign-in (effect above); any other failure
  // (service down, gateway error, no API behind this deployment) says so and offers a retry.
  if (me.error && !(me.error instanceof ApiError && me.error.status === 401)) return (
    <main className="flex min-h-screen items-center justify-center bg-bg p-4">
      <div className="w-full max-w-xl space-y-4">
        <ErrorState error={me.error} retry={() => me.refetch()} />
        <p className="text-sm text-muted">SupplyLens could not confirm your session because its service did not answer.
          Nothing you entered has been lost. <a className="font-medium text-accent underline" href="/login">Go to sign-in</a></p>
      </div>
    </main>
  );
  if (me.isLoading || !me.data) return <Loading label="Checking your session" className="min-h-screen justify-center" />;
  const membership = me.data.memberships.find((m) => m.slug === ctx.ws) ?? me.data.memberships[0];
  const role = membership?.role;

  return (
    <div className="min-h-screen bg-bg">
      <a href="#main" className="skip-link">Skip to content</a>
      <div className="flex">
        <nav aria-label="Primary" className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-line bg-surface px-3 py-4 lg:flex">
          <Link href={{ pathname: "/", query: { ws: ctx.ws } }} className="mb-5 flex items-center gap-2 px-2">
            <span className="flex size-8 items-center justify-center rounded-lg bg-ink text-bg"><Sparkles className="size-4" aria-hidden /></span>
            <span className="display text-xl font-semibold">SupplyLens</span>
          </Link>
          <div className="-mr-1 space-y-4 overflow-y-auto pr-1">
            {GROUPS.map((g) => (
              <div key={g}>
                <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted">{g}</p>
                <ul className="space-y-0.5">
                  {NAV.filter((n) => n.group === g).map(({ href, label, icon: Icon }) => {
                    const active = href === "/" ? path === "/" : path.startsWith(href);
                    return (
                      <li key={href}>
                        <Link href={{ pathname: href, query: { ws: ctx.ws } }} aria-current={active ? "page" : undefined}
                          className={clsx("flex items-center gap-3 rounded-lg px-3 py-1.5 text-sm",
                            active ? "bg-accent-soft font-semibold text-accent" : "text-muted hover:bg-surface-2 hover:text-ink")}>
                          <Icon className="size-4" aria-hidden /> {label}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </div>
          <div className="mt-auto space-y-3 px-2 pt-4 text-xs text-muted">
            <p>Signed in as <span className="text-ink">{me.data.user.display_name}</span>{me.data.user.is_dev_account && <> · <span className="text-risk">dev account</span></>}</p>
            <p>Role in workspace: <span className="font-semibold text-ink">{role?.replace("_", " ")}</span></p>
          </div>
        </nav>

        <div className="min-w-0 flex-1">
          <div className="sticky top-0 z-30">
            <div className="glass flex flex-wrap items-center gap-3 border-b border-line px-4 py-2.5 md:px-6">
              <label className="flex items-center gap-2 text-sm">
                <span className="sr-only">Workspace</span>
                <select value={ctx.ws} className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm font-medium"
                  onChange={(e) => {
                    qc.cancelQueries();
                    setTenant(e.target.value);
                    setCtx({ ws: e.target.value, sku: null, known: null, eff: null, action: null, run: null });
                  }}>
                  {me.data.memberships.map((m) => <option key={m.slug} value={m.slug}>{m.name}</option>)}
                </select>
              </label>
              {membership && (
                <span className={clsx("rounded-md px-2 py-1 text-[11px] font-semibold",
                  membership.kind === "demo" ? "bg-sim-soft text-sim" : "bg-accent-soft text-accent")}>
                  {membership.kind === "demo" ? "Fictional demo data" : membership.slug === "contract-research" ? "Real public contracts & awards" : "Real sales · simulated operations"}
                </span>
              )}
              <nav aria-label="Sections" className="flex gap-1 overflow-x-auto lg:hidden">
                {NAV.map(({ href, label }) => (
                  <Link key={href} href={{ pathname: href, query: { ws: ctx.ws } }} className="whitespace-nowrap rounded-md px-2 py-1 text-xs text-muted hover:text-ink">{label}</Link>
                ))}
              </nav>
              <div className="ml-auto flex items-center gap-2">
                <CommandPalette nav={NAV.map(({ href, label, group }) => ({ href, label, group }))} />
                <ThemeSwitch />
                <button className="inline-flex size-8 items-center justify-center rounded-lg text-muted hover:bg-surface-2 hover:text-ink"
                  aria-label="Sign out" title="Sign out"
                  onClick={async () => { await apiPost("/api/v1/auth/logout", {}); qc.clear(); router.replace("/login"); }}>
                  <LogOut className="size-4" aria-hidden />
                </button>
              </div>
            </div>
            <ConnectionBanner />
            <ClockRail />
          </div>
          <VitalsReporter />
          <main id="main" className="mx-auto max-w-[1440px] px-4 py-6 md:px-6 md:py-8">{children}</main>
        </div>
      </div>
    </div>
  );
}

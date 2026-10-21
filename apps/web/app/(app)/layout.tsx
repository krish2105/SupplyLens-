"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTheme } from "next-themes";
import clsx from "clsx";
import {
  Boxes, ClipboardCheck, Database, FileText, FlaskConical, Gauge, LineChart, LogOut, Monitor, Moon, Settings2, Sparkles, Sun, Workflow,
} from "lucide-react";
import { ClockRail } from "@/components/clock-rail";
import { Loading } from "@/components/ui";
import { ApiError, post, setTenant } from "@/lib/api";
import { useMe } from "@/lib/queries";
import { usePlanningContext } from "@/lib/state";

const NAV = [
  { href: "/", label: "Overview", icon: Gauge },
  { href: "/data", label: "Data admission", icon: Database },
  { href: "/inventory", label: "Inventory", icon: Boxes },
  { href: "/forecast", label: "Forecast lab", icon: LineChart },
  { href: "/scenarios", label: "Scenario studio", icon: FlaskConical },
  { href: "/policies", label: "Policies & evidence", icon: FileText },
  { href: "/runs", label: "Investigations", icon: Workflow },
  { href: "/approvals", label: "Approvals", icon: ClipboardCheck },
  { href: "/settings", label: "Settings", icon: Settings2 },
];

function ThemeSwitch() {
  const { theme, setTheme } = useTheme();
  const opts = [
    { v: "light", icon: Sun, label: "Light theme" },
    { v: "dark", icon: Moon, label: "Dark theme" },
    { v: "system", icon: Monitor, label: "Follow system theme" },
  ];
  return (
    <div role="radiogroup" aria-label="Theme" className="inline-flex rounded-lg border border-line bg-surface p-0.5">
      {opts.map(({ v, icon: Icon, label }) => (
        <button key={v} role="radio" aria-checked={theme === v} aria-label={label} title={label}
          onClick={() => setTheme(v)}
          className={clsx("flex size-7 items-center justify-center rounded-md", theme === v ? "bg-accent text-accent-ink" : "text-muted hover:text-ink")}>
          <Icon className="size-3.5" aria-hidden />
        </button>
      ))}
    </div>
  );
}

export default function AppLayout({ children }: { children: ReactNode }) {
  const me = useMe();
  const router = useRouter();
  const path = usePathname();
  const qc = useQueryClient();
  const [ctx, setCtx] = usePlanningContext();
  setTenant(ctx.ws);

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) router.replace("/login");
  }, [me.error, router]);

  if (me.isLoading || !me.data) return <Loading label="Checking your session" className="min-h-screen justify-center" />;
  const membership = me.data.memberships.find((m) => m.slug === ctx.ws) ?? me.data.memberships[0];
  const role = membership?.role;

  return (
    <div className="min-h-screen bg-bg">
      <a href="#main" className="skip-link">Skip to content</a>
      <div className="flex">
        <nav aria-label="Primary" className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-line bg-surface px-3 py-4 lg:flex">
          <Link href={{ pathname: "/", query: { ws: ctx.ws } }} className="mb-6 flex items-center gap-2 px-2">
            <span className="flex size-8 items-center justify-center rounded-lg bg-ink text-bg"><Sparkles className="size-4" aria-hidden /></span>
            <span className="display text-xl font-semibold">SupplyLens</span>
          </Link>
          <ul className="space-y-0.5">
            {NAV.map(({ href, label, icon: Icon }) => {
              const active = href === "/" ? path === "/" : path.startsWith(href);
              return (
                <li key={href}>
                  <Link href={{ pathname: href, query: { ws: ctx.ws } }} aria-current={active ? "page" : undefined}
                    className={clsx("flex items-center gap-3 rounded-lg px-3 py-2 text-sm",
                      active ? "bg-accent-soft font-semibold text-accent" : "text-muted hover:bg-surface-2 hover:text-ink")}>
                    <Icon className="size-4" aria-hidden /> {label}
                  </Link>
                </li>
              );
            })}
          </ul>
          <div className="mt-auto space-y-3 px-2 text-xs text-muted">
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
                    setCtx({ ws: e.target.value, sku: null, known: null, eff: null });
                  }}>
                  {me.data.memberships.map((m) => <option key={m.slug} value={m.slug}>{m.name}</option>)}
                </select>
              </label>
              {membership && (
                <span className={clsx("rounded-md px-2 py-1 text-[11px] font-semibold",
                  membership.kind === "demo" ? "bg-sim-soft text-sim" : "bg-accent-soft text-accent")}>
                  {membership.kind === "demo" ? "Fictional demo data" : "Real sales · simulated operations"}
                </span>
              )}
              <nav aria-label="Sections" className="flex gap-1 overflow-x-auto lg:hidden">
                {NAV.map(({ href, label }) => (
                  <Link key={href} href={{ pathname: href, query: { ws: ctx.ws } }} className="whitespace-nowrap rounded-md px-2 py-1 text-xs text-muted hover:text-ink">{label}</Link>
                ))}
              </nav>
              <div className="ml-auto flex items-center gap-2">
                <ThemeSwitch />
                <button className="inline-flex size-8 items-center justify-center rounded-lg text-muted hover:bg-surface-2 hover:text-ink"
                  aria-label="Sign out" title="Sign out"
                  onClick={async () => { await post("/api/v1/auth/logout", {}); qc.clear(); router.replace("/login"); }}>
                  <LogOut className="size-4" aria-hidden />
                </button>
              </div>
            </div>
            <ClockRail />
          </div>
          <main id="main" className="mx-auto max-w-[1440px] px-4 py-6 md:px-6 md:py-8">{children}</main>
        </div>
      </div>
    </div>
  );
}

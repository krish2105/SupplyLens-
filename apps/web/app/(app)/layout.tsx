"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Suspense, useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTheme } from "next-themes";
import * as Dialog from "@radix-ui/react-dialog";
import clsx from "clsx";
import {
  BadgePoundSterling, Boxes, ClipboardCheck, Database, FileText, FlaskConical, Gauge, Globe2, LineChart, LogOut, Menu, Microscope, Monitor,
  Moon, Settings2, ShieldCheck, Siren, Sparkles, Sun, Workflow, X,
} from "lucide-react";
import { CommandPalette } from "@/components/command-palette";
import { ClockRail } from "@/components/clock-rail";
import { SafeBoundary } from "@/components/safe-boundary";
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

/** Below the lg breakpoint (no sidebar): one button naming the current section, opening every section grouped as in the
 *  sidebar. Replaces a horizontal strip that showed about five of fourteen links with no sign of the rest (Phase 4B). */
function SectionsMenu({ ws, path }: { ws: string; path: string }) {
  const [open, setOpen] = useState(false);
  const isActive = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  const current = NAV.find((n) => isActive(n.href));
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button" className="inline-flex h-8 items-center gap-2 rounded-lg border border-line bg-surface px-2.5 text-sm font-medium hover:bg-surface-2">
          <Menu className="size-4" aria-hidden /><span className="sr-only">Sections, current: </span>{current?.label ?? "Sections"}
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className="fixed inset-y-0 left-0 z-50 w-[min(320px,86vw)] overflow-y-auto bg-surface p-4 shadow-xl">
          <div className="mb-3 flex items-center justify-between">
            <Dialog.Title className="display text-lg font-semibold">Sections</Dialog.Title>
            <Dialog.Close className="inline-flex size-8 items-center justify-center rounded-lg text-muted hover:bg-surface-2 hover:text-ink" aria-label="Close sections">
              <X className="size-4" aria-hidden /></Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">Go to a section of SupplyLens in this workspace.</Dialog.Description>
          <div className="space-y-4">
            {GROUPS.map((g) => (
              <div key={g}>
                <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted">{g}</p>
                <ul className="space-y-0.5">
                  {NAV.filter((n) => n.group === g).map(({ href, label, icon: Icon }) => (
                    <li key={href}>
                      <Link href={{ pathname: href, query: { ws } }} aria-current={isActive(href) ? "page" : undefined} onClick={() => setOpen(false)}
                        className={clsx("flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm",
                          isActive(href) ? "bg-accent-soft font-semibold text-accent" : "text-ink hover:bg-surface-2")}>
                        <Icon className="size-4" aria-hidden /> {label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// URL-backed planning state needs a Suspense boundary for static prerendering.
// Anchors and focused elements scroll clear of the sticky header (globals.css scroll-padding-top). Its height varies with
// width and with the replay notice (176 px at tablet width vs the 144 px once assumed), so it is measured, not guessed.
function trackHeaderHeight(el: HTMLDivElement | null) {
  if (!el) return;
  const ro = new ResizeObserver(() => document.documentElement.style.setProperty("--header-h", `${el.offsetHeight}px`));
  ro.observe(el);
  return () => ro.disconnect();
}

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
    if (me.error instanceof ApiError && me.error.status === 401) router.replace(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
  }, [me.error, router]);

  // The URL's workspace must be one the user belongs to (P1-FE-01). The default (uci-research) or a link from someone else
  // may name a workspace this account cannot open: every request would then fail with "unknown workspace". Move to the
  // first membership instead, clearing selections that belonged to the other workspace.
  const memberships = me.data?.memberships ?? [];
  const member = memberships.some((m) => m.slug === ctx.ws);
  const fallback = me.data && !member ? memberships[0]?.slug : undefined;
  useEffect(() => {
    if (!fallback) return;
    qc.cancelQueries();
    setTenant(fallback);
    setCtx({ ws: fallback, sku: null, known: null, eff: null, action: null, run: null });
  }, [fallback, qc, setCtx]);
  const [signOutError, setSignOutError] = useState<unknown>(null);
  const signOut = async () => {
    setSignOutError(null);
    try {
      await apiPost("/api/v1/auth/logout", {});
    } catch (e) {
      // Already signed out (401) is success; anything else must be said, or the user believes they left (P2-FE-07).
      if (!(e instanceof ApiError && e.status === 401)) { setSignOutError(e); return; }
    }
    qc.clear();
    router.replace("/login");
  };

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
  // The shell and the page render while the session check is in flight, so the page's own data requests start in
  // parallel with /me instead of after it (UX-011: one round trip less before the main content). A 401 still sends the
  // user to sign-in (effect above); role-dependent controls wait for the role.
  if (me.data && !memberships.length) return (
    <main className="flex min-h-screen items-center justify-center bg-bg p-4">
      <div className="w-full max-w-xl space-y-3 text-sm" data-testid="no-workspace">
        <h1 className="display text-2xl font-semibold">No workspace yet</h1>
        <p className="text-muted">You are signed in as {me.data.user.email}, but this account is not a member of any workspace. Ask a
          workspace administrator to add you, then reload.</p>
        <p><button className="font-medium text-accent underline" onClick={signOut}>Sign out</button></p>
      </div>
    </main>
  );
  // Until a mismatched workspace has been replaced (effect above), render nothing that would request it.
  if (fallback) return <Loading label="Opening your workspace" className="min-h-screen justify-center" />;
  const membership = memberships.find((m) => m.slug === ctx.ws);
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
            <p>{me.data ? <>Signed in as <span className="text-ink">{me.data.user.display_name}</span>{me.data.user.is_dev_account && <> · <span className="text-risk">dev account</span></>}</> : "Checking your session…"}</p>
            <p>Role in workspace: <span className="font-semibold text-ink">{role?.replace("_", " ") ?? "…"}</span></p>
          </div>
        </nav>

        <div className="min-w-0 flex-1">
          {/* Sticky from tablet width up. On a phone the header and decision clock are ~300 px (a third of the screen), so
              they scroll away with the page instead of covering it (Phase 4B). */}
          <div ref={trackHeaderHeight} className="z-30 md:sticky md:top-0">
            {/* Two fixed rows below desktop width (workspace and data label; page menu and tools) instead of one wrapping row:
                the wrap point used to move with the length of the page title, so the icons jumped between pages. */}
            <div className="glass flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-4 py-2.5 md:px-6">
              <div className="flex min-w-0 basis-full items-center gap-2 lg:basis-auto">
                <label className="flex min-w-0 flex-1 items-center gap-2 text-sm lg:flex-none">
                  <span className="sr-only">Workspace</span>
                  <select value={ctx.ws} className="w-full min-w-0 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm font-medium"
                    onChange={(e) => {
                      qc.cancelQueries();
                      setTenant(e.target.value);
                      setCtx({ ws: e.target.value, sku: null, known: null, eff: null, action: null, run: null });
                    }}>
                    {memberships.length ? memberships.map((m) => <option key={m.slug} value={m.slug}>{m.name}</option>)
                      : <option value={ctx.ws}>Loading…</option>}
                  </select>
                </label>
                {membership && (
                  <span className={clsx("shrink-0 rounded-md px-2 py-1 text-[11px] font-semibold",
                    membership.kind === "demo" ? "bg-sim-soft text-sim" : "bg-accent-soft text-accent")}>
                    {membership.kind === "demo" ? "Fictional demo data" : membership.slug === "contract-research" ? "Real public contracts & awards"
                      : <><span className="sm:hidden">Real sales · simulated ops</span><span className="hidden sm:inline">Real sales · simulated operations</span></>}
                  </span>
                )}
              </div>
              <div className="flex min-w-0 basis-full items-center gap-2 lg:ml-auto lg:basis-auto">
                <nav aria-label="Sections" className="min-w-0 lg:hidden"><SectionsMenu ws={ctx.ws} path={path} /></nav>
                <div className="ml-auto flex shrink-0 items-center gap-2">
                  <SafeBoundary name="command palette"><CommandPalette nav={NAV.map(({ href, label, group }) => ({ href, label, group }))} /></SafeBoundary>
                  <ThemeSwitch />
                  <button className="inline-flex size-8 items-center justify-center rounded-lg text-muted hover:bg-surface-2 hover:text-ink"
                    aria-label="Sign out" title="Sign out"
                    onClick={signOut}>
                    <LogOut className="size-4" aria-hidden />
                  </button>
                </div>
              </div>
            </div>
            <ConnectionBanner />
            {signOutError != null && (
              <div className="border-b border-line bg-surface px-4 py-2 md:px-6" data-testid="sign-out-error">
                <p className="mb-2 text-sm font-medium">You are still signed in: sign-out did not reach the service.</p>
                <ErrorState error={signOutError} retry={signOut} />
              </div>)}
            <SafeBoundary name="decision clock"><ClockRail /></SafeBoundary>
          </div>
          <VitalsReporter />
          <main id="main" className="mx-auto max-w-[1440px] px-4 py-6 md:px-6 md:py-8">{children}</main>
        </div>
      </div>
    </div>
  );
}

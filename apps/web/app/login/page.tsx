"use client";
import { useRouter } from "next/navigation";
import { safeNext } from "@/lib/nav";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { KeyRound, ShieldAlert } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { Button, ErrorState, Loading } from "@/components/ui";
import { Illustration } from "@/components/illustration";

const ROLE_COPY: Record<string, string> = {
  viewer: "Read dashboards, forecasts and evidence.",
  planner: "Run forecasts, scenarios and investigations; prepare purchase-order drafts.",
  approver: "Review evidence packets and approve or reject drafts.",
  tenant_admin: "Administration, onboarding and audit. Cannot approve spend by default.",
};

export default function Login() {
  const router = useRouter();
  const cfg = useQuery({ queryKey: ["auth-config"], queryFn: () => apiGet("/api/v1/auth/config"), retry: 1 });
  const devOn = cfg.data?.dev_login === true;
  const users = useQuery({ queryKey: ["dev-users"], queryFn: () => apiGet("/api/v1/auth/dev-users"), enabled: devOn });
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);

  async function signIn(email: string) {
    setBusy(email); setErr(null);
    try { await apiPost("/api/v1/auth/dev-login", { body: { email } }); router.replace(safeNext(new URLSearchParams(window.location.search).get("next"))); }
    catch (e) { setErr(e); setBusy(null); }
  }

  return (
    <main className="grid-paper flex min-h-screen items-center justify-center p-4">
      {/* One explicit column below md: an implicit grid column sized itself to the widest content (an account email) and
          the card clipped everything at its edge on phones (Phase 4B). */}
      <div className="card grid w-full max-w-5xl grid-cols-1 overflow-hidden md:grid-cols-[minmax(0,1fr)_minmax(0,0.95fr)]">
        <div className="min-w-0 p-5 sm:p-8">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">SupplyLens</p>
          <h1 className="display mt-2 text-4xl font-semibold leading-tight">Welcome to SupplyLens</h1>
          <p className="mt-2 text-muted">Roles decide what you can do. Approvals always need a different person from the one who prepared the draft.</p>

          {cfg.isLoading && <Loading label="Checking sign-in options" />}
          {cfg.error && <div className="mt-4"><ErrorState error={cfg.error} retry={() => cfg.refetch()} /></div>}
          {err != null && <div className="mt-4"><ErrorState error={err} /></div>}

          {cfg.data?.oidc && cfg.data.oidc_login_url && (
            <section aria-labelledby="sso" className="mt-6">
              <h2 id="sso" className="text-sm font-semibold">Organisation sign-in</h2>
              <p className="mt-1 text-sm text-muted">Your identity provider decides your workspaces and roles; a change there reaches an open session within a minute.</p>
              <Button className="mt-3 w-full" onClick={() => { window.location.href = cfg.data!.oidc_login_url!; }}>
                <KeyRound className="size-4" aria-hidden /> Continue with your organisation account
              </Button>
            </section>
          )}

          {devOn && (
            <section aria-labelledby="dev" className="mt-6">
              <h2 id="dev" className="text-sm font-semibold">Local development accounts</h2>
              <div role="note" className="mt-2 flex gap-3 rounded-xl bg-risk-soft p-3 text-sm text-risk">
                <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                <span>For local development only ({cfg.data?.environment} profile). A production profile refuses to start with these accounts enabled.</span>
              </div>
              {users.isLoading && <Loading label="Loading accounts" />}
              {users.error && <div className="mt-4"><ErrorState error={users.error} retry={() => users.refetch()} /></div>}
              <ul className="mt-3 space-y-2">
                {users.data?.users.map((u) => (
                  <li key={u.email}>
                    <button onClick={() => signIn(u.email)} disabled={!!busy}
                      className="block w-full rounded-xl border border-line bg-surface p-3.5 text-left hover:border-accent hover:bg-surface-2 disabled:opacity-60">
                      <span className="block font-semibold">{u.display_name}</span>
                      <span className="block text-sm text-muted">{ROLE_COPY[u.roles[0] ?? ""] ?? u.roles.join(", ")}</span>
                      <span className="num mt-1 block break-all text-xs text-muted">{busy === u.email ? "Signing in…" : u.email}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {cfg.data && !cfg.data.oidc && !devOn && (
            <p role="alert" className="mt-6 rounded-xl bg-danger-soft p-3 text-sm text-danger">No sign-in method is configured for this deployment. Ask your administrator.</p>
          )}
          <p className="mt-6 text-xs text-muted">Signing in sets an HttpOnly session cookie for this browser only.</p>
        </div>
        <div className="hidden items-center justify-center bg-surface-2/60 p-6 md:flex">
          <Illustration art="welcome" size={520} className="w-full max-w-[560px]" />
        </div>
      </div>
    </main>
  );
}

"use client";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ShieldAlert } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { Button, ErrorState, Loading } from "@/components/ui";

const ROLE_COPY: Record<string, string> = {
  viewer: "Read dashboards, forecasts and evidence.",
  planner: "Run forecasts, scenarios and investigations; prepare purchase-order drafts.",
  approver: "Review evidence packets and approve or reject drafts.",
  tenant_admin: "Administration and audit. Cannot approve spend by default.",
};

export default function Login() {
  const router = useRouter();
  const users = useQuery({ queryKey: ["dev-users"], queryFn: () => apiGet("/api/v1/auth/dev-users") });
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);

  async function signIn(email: string) {
    setBusy(email); setErr(null);
    try { await apiPost("/api/v1/auth/dev-login", { body: { email } }); router.replace("/"); }
    catch (e) { setErr(e); setBusy(null); }
  }

  return (
    <main className="grid-paper flex min-h-screen items-center justify-center p-4">
      <div className="card w-full max-w-xl p-8">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">SupplyLens</p>
        <h1 className="display mt-2 text-4xl font-semibold leading-tight">Choose who you are working as</h1>
        <p className="mt-2 text-muted">Roles decide what you can do. Approvals always need a different person from the one who prepared the draft.</p>
        <div role="note" className="mt-5 flex gap-3 rounded-xl bg-risk-soft p-3 text-sm text-risk">
          <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>{users.data?.notice ?? "Development accounts only. Enterprise sign-in is not configured in this build."}</span>
        </div>
        {users.isLoading && <Loading label="Loading accounts" />}
        {users.error && <div className="mt-4"><ErrorState error={users.error} retry={() => users.refetch()} /></div>}
        {err != null && <div className="mt-4"><ErrorState error={err} /></div>}
        <ul className="mt-6 space-y-2">
          {users.data?.users.map((u) => (
            <li key={u.email}>
              <button onClick={() => signIn(u.email)} disabled={!!busy}
                className="flex w-full items-center justify-between gap-4 rounded-xl border border-line bg-surface p-4 text-left hover:border-accent hover:bg-surface-2 disabled:opacity-60">
                <span>
                  <span className="block font-semibold">{u.display_name}</span>
                  <span className="block text-sm text-muted">{ROLE_COPY[u.roles[0] ?? ""] ?? u.roles.join(", ")}</span>
                </span>
                <span className="num shrink-0 text-xs text-muted">{busy === u.email ? "Signing in…" : u.email}</span>
              </button>
            </li>
          ))}
        </ul>
        <p className="mt-6 text-xs text-muted">Signing in sets an HttpOnly session cookie for this browser only.</p>
      </div>
    </main>
  );
}

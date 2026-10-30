"use client";
import { useState } from "react";
import { UserRoundCog } from "lucide-react";
import { apiPost } from "@/lib/api";
import { useMe } from "@/lib/queries";

const ARTICLE: Record<string, string> = { planner: "a planner", approver: "an approver", tenant_admin: "a tenant administrator", viewer: "a viewer" };

/**
 * Says, in the page and not only in a tooltip (invisible on touch screens), why a control is off for this role. On the
 * shared development and demo accounts it also offers to switch: sign out, then sign in again with the right role and come
 * back to the same page. An organisation account gets no switch: its roles come from the identity provider.
 */
export function RoleNote({ role, need, action }: { role: string | undefined; need: "planner" | "approver"; action: string }) {
  const me = useMe();
  const [busy, setBusy] = useState(false);
  if (!role || role === need) return null;
  const switchAccount = async () => {
    setBusy(true);
    try { await apiPost("/api/v1/auth/logout", {}); } catch { /* already signed out */ }
    const back = window.location.pathname + window.location.search;
    // a full navigation, not a client transition: nothing cached for the old account survives into the new session
    window.location.assign(`/login?next=${encodeURIComponent(back)}&as=${need}`); // eslint-disable-line @next/next/no-location-assign-relative-destination
  };
  return (
    <div role="note" data-testid="role-note" className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs text-muted">
      <span>You are signed in as {ARTICLE[role] ?? role.replaceAll("_", " ")}. Only {ARTICLE[need]} can {action}.</span>
      {me.data?.user.is_dev_account && (
        <button type="button" onClick={switchAccount} disabled={busy}
          className="inline-flex items-center gap-1.5 font-semibold text-accent underline-offset-2 hover:underline disabled:opacity-60">
          <UserRoundCog className="size-3.5" aria-hidden /> {busy ? "Switching…" : `Switch to the ${need} account`}
        </button>
      )}
    </div>
  );
}

"use client";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Card, ErrorState, Eyebrow, Loading, Mono, PageHeader, QueryError, Status } from "@/components/ui";
import { EmptyState } from "@/components/illustration";
import { useApi, useMe } from "@/lib/queries";
import { dateTime } from "@/lib/format";


export default function SettingsPage() {
  const { theme, setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []); // eslint-disable-line react-hooks/set-state-in-effect -- the theme is known only after mount
  const me = useMe();
  const integ = useApi(["integrations"], "/api/v1/integrations");
  const audit = useApi(["audit"], "/api/v1/audit", { query: { limit: 60 } });

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Settings" title="Appearance, connections and audit" />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-5">
          <Eyebrow>Appearance</Eyebrow>
          <fieldset className="mt-3">
            <legend className="text-sm font-medium">Theme</legend>
            <div className="mt-2 space-y-2">
              {[["light", "Light"], ["dark", "Dark"], ["system", "Match my system"]].map(([v, l]) => (
                <label key={v} className="flex items-center gap-2 text-sm">
                  <input type="radio" name="theme" value={v} checked={mounted && theme === v} onChange={() => setTheme(v!)} className="accent-[var(--accent)]" /> {l}
                </label>
              ))}
            </div>
            <p className="mt-2 text-xs text-muted">Saved in this browser. Currently showing {mounted ? resolvedTheme : "…"}. Filters and selections stay in the address bar, so switching never loses them.</p>
          </fieldset>
        </Card>
        <Card className="p-5">
          <Eyebrow>Your access</Eyebrow>
          <ul className="mt-3 space-y-2 text-sm">
            {me.data?.memberships.map((m) => (
              <li key={m.slug} className="flex items-center justify-between gap-2"><span>{m.name}<span className="block text-xs text-muted">{m.description}</span></span><Mono>{m.role}</Mono></li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted">Roles are checked by the server on every request and every investigation step.</p>
        </Card>
      </div>
      <Card className="p-5">
        <Eyebrow>Connections</Eyebrow>
        {integ.isLoading ? <Loading /> : integ.error ? <ErrorState error={integ.error} /> : (
          <ul className="mt-3 divide-y divide-line">
            {integ.data?.map((i) => (
              <li key={i.name} className="flex flex-wrap items-center justify-between gap-3 py-2.5 text-sm">
                <span><span className="font-medium">{i.name}</span><span className="block text-xs text-muted">{i.note ?? i.operations?.join(", ")}</span></span>
                <Status value={i.status} />
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-xs text-muted">Statuses come from live checks at page load. Nothing is shown as connected without a verified connection.</p>
        {integ.data && !integ.data.some((i) => /business central|sap/i.test(i.name) && ["VERIFIED_LOCALLY", "CONFIGURED"].includes(i.status)) && (
          <div className="mt-4"><EmptyState variant="first_run" art="empty-integrations" title="No live ERP connection is configured" compact>
            Purchase orders go only to the local sandbox. The Business Central and SAP adapters are not implemented; supported ways
            to bring data in today are the CSV templates on the Data page.</EmptyState></div>
        )}
      </Card>
      <Card className="p-5">
        <Eyebrow>Audit trail (append-only for the application)</Eyebrow>
        <QueryError q={audit} what="the audit trail" />
        <div className="mt-3 max-h-[480px] overflow-auto" tabIndex={0} role="region" aria-label="Audit events, scrollable">
          <table className="w-full text-sm">
            <caption className="sr-only">Recent audit events</caption>
            <thead className="sticky top-0 bg-surface"><tr className="border-b border-line text-left text-xs text-muted">
              <th className="py-2 font-medium">When</th><th className="font-medium">Actor</th><th className="font-medium">Event</th><th className="font-medium">Entity</th></tr></thead>
            <tbody>
              {audit.data?.map((e) => (
                <tr key={e.id} className="border-b border-line/60 align-top"><td className="py-1.5 text-xs text-muted">{dateTime(e.at)}</td><td className="text-xs">{e.actor ?? "system"}</td>
                  <td><Mono>{e.action}</Mono></td><td><Mono className="text-muted">{e.entity} {e.entity_id.slice(0, 8)}</Mono></td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

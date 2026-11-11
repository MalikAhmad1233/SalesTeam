"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { Badge, Card, Empty, PageHeader, Stat } from "@/components/ui";
import { api, qs, type Schemas } from "@/lib/api";
import { formatDateTime, humanize } from "@/lib/format";
import { useStages } from "@/lib/queries";
import { can, useMe } from "@/lib/session";

export default function OverviewPage() {
  const { data: me } = useMe();
  const tasks = useQuery({
    queryKey: ["tasks", "mine-open"],
    queryFn: () => api<Schemas["TaskOut"][]>(`/tasks${qs({ assignee: "me", status: "open" })}`),
    enabled: can(me, "crm.tasks.manage"),
  });
  const opportunities = useQuery({
    queryKey: ["opportunities", "open"],
    queryFn: () => api<Schemas["OpportunityOut"][]>(`/pipeline/opportunities${qs({ open_only: true, limit: 200 })}`),
    enabled: can(me, "crm.accounts.read"),
  });
  const outstanding = useQuery({
    queryKey: ["settings", "outstanding"],
    queryFn: () => api<Schemas["SettingOut"][]>("/settings/outstanding"),
    enabled: can(me, "settings.read"),
  });
  const leads = useQuery({
    queryKey: ["leads", "recent"],
    queryFn: () => api<Schemas["LeadOut"][]>(`/leads${qs({ limit: 5 })}`),
    enabled: can(me, "leads.read"),
  });
  const pricing = useQuery({
    queryKey: ["pricing-status"],
    queryFn: () => api<Schemas["PricingStatusOut"]>("/pricing/status"),
    enabled: can(me, "pricing.read"),
  });
  const stages = useStages();

  const overdue = (tasks.data ?? []).filter((t) => t.due_at && new Date(t.due_at) < new Date()).length;
  const breached = (opportunities.data ?? []).filter((o) => o.sla_breached).length;
  const byStage = new Map<string, number>();
  for (const o of opportunities.data ?? []) byStage.set(o.stage_key, (byStage.get(o.stage_key) ?? 0) + 1);

  return (
    <>
      <PageHeader title="Overview" description="What needs your attention now." />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="My open tasks" value={tasks.data?.length ?? "—"} hint={overdue ? `${overdue} overdue` : "None overdue"} />
        <Stat label="Open opportunities" value={opportunities.data?.length ?? "—"} hint={breached ? `${breached} past their SLA` : undefined} />
        <Stat label="Outstanding decisions" value={outstanding.data?.length ?? "—"} hint="Settings waiting for Mixt's confirmation" />
        <Stat
          label="Pricing"
          value={pricing.data ? (pricing.data.active_versions ? `${pricing.data.active_versions} active` : "Not active") : "—"}
          hint={
            pricing.data
              ? pricing.data.active_versions
                ? `Price books in use, of ${pricing.data.books} on file`
                : `${pricing.data.books} price books on file, none active yet: nothing can be quoted`
              : undefined
          }
        />
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card title="Pipeline by stage" actions={<Link href="/pipeline" className="text-sm text-accent">Open pipeline</Link>}>
          {stages.data && opportunities.data ? (
            <ul className="space-y-1 text-sm">
              {stages.data
                .filter((s) => s.type === "open")
                .map((s) => (
                  <li key={s.key} className="flex justify-between">
                    <span>{s.name}</span>
                    <span className="tabular font-medium">{byStage.get(s.key) ?? 0}</span>
                  </li>
                ))}
            </ul>
          ) : (
            <Empty>No pipeline data.</Empty>
          )}
        </Card>
        <Card title="Latest enquiries" actions={<Link href="/leads" className="text-sm text-accent">All leads</Link>}>
          {leads.data && leads.data.length > 0 ? (
            <ul className="divide-y divide-border text-sm">
              {leads.data.map((lead) => (
                <li key={lead.id} className="flex items-center justify-between py-2">
                  <span>{lead.submitted_name ?? "—"}</span>
                  <span className="flex items-center gap-2">
                    <Badge tone={lead.status === "out_of_market" ? "warning" : "accent"}>{humanize(lead.status)}</Badge>
                    <span className="text-xs text-muted">{formatDateTime(lead.received_at, me?.timezone)}</span>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No enquiries yet.</Empty>
          )}
        </Card>
      </div>
    </>
  );
}

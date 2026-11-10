"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Badge, Button, Card, ErrorNote, Field, Input, Loading, PageHeader, Select, Textarea } from "@/components/ui";
import { api, type Schemas } from "@/lib/api";
import { can, useMe } from "@/lib/session";

type Setting = Schemas["SettingOut"];

export default function SettingsPage() {
  const [tab, setTab] = useState<"outstanding" | "all">("outstanding");
  const settings = useQuery({ queryKey: ["settings", "all"], queryFn: () => api<Setting[]>("/settings") });
  const [editing, setEditing] = useState<string | null>(null);
  const list = (settings.data ?? []).filter((s) => tab === "all" || s.status === "safe_default");
  const areas = [...new Set(list.map((s) => s.area))];
  const outstanding = (settings.data ?? []).filter((s) => s.status === "safe_default").length;

  return (
    <>
      <PageHeader
        title="Settings"
        description="Every open business decision has a safe default until Mixt confirms it. Confirmed values carry a decision-log reference (BD-…)."
      />
      <div role="tablist" aria-label="Settings views" className="mb-4 flex gap-2">
        <Button role="tab" aria-selected={tab === "outstanding"} variant={tab === "outstanding" ? "primary" : "secondary"} onClick={() => setTab("outstanding")}>
          Outstanding decisions ({outstanding})
        </Button>
        <Button role="tab" aria-selected={tab === "all"} variant={tab === "all" ? "primary" : "secondary"} onClick={() => setTab("all")}>
          All settings ({settings.data?.length ?? 0})
        </Button>
      </div>
      {settings.isLoading ? <Loading /> : null}
      <ErrorNote error={settings.error} />
      <div className="space-y-6">
        {areas.map((area) => (
          <Card key={area} title={area.charAt(0).toUpperCase() + area.slice(1)}>
            <ul className="divide-y divide-border">
              {list.filter((s) => s.area === area).map((s) => (
                <li key={s.key} className="py-3 text-sm">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="max-w-3xl">
                      <p className="font-mono text-xs text-muted">{s.key}</p>
                      <p className="mt-0.5">{s.description}</p>
                      <p className="mt-1">
                        Value: <code className="rounded bg-surface px-1">{JSON.stringify(s.value)}</code>
                      </p>
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      {s.status === "confirmed" ? <Badge tone="success">Confirmed {s.decision_ref}</Badge> : <Badge tone="warning">Safe default</Badge>}
                      {s.open_question ? <span className="text-xs text-muted">Waiting for {s.open_question}</span> : null}
                      <Button variant="ghost" onClick={() => setEditing(editing === s.key ? null : s.key)}>
                        {editing === s.key ? "Close" : "Change"}
                      </Button>
                    </div>
                  </div>
                  {editing === s.key ? <EditSetting setting={s} onDone={() => setEditing(null)} /> : null}
                </li>
              ))}
            </ul>
          </Card>
        ))}
      </div>
    </>
  );
}

function EditSetting({ setting, onDone }: { setting: Setting; onDone: () => void }) {
  const { data: me } = useMe();
  const queryClient = useQueryClient();
  const [value, setValue] = useState(JSON.stringify(setting.value, null, 2));
  const [status, setStatus] = useState(setting.status);
  const [decisionRef, setDecisionRef] = useState(setting.decision_ref ?? "");
  const [parseError, setParseError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: (parsed: unknown) =>
      api(`/settings/${setting.key}`, {
        method: "PUT",
        json: { value: parsed, status, decision_ref: decisionRef || null, expected_version: setting.version ?? undefined },
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["settings"] });
      onDone();
    },
  });
  if (!can(me, setting.change_permission)) {
    return <p className="mt-2 text-xs text-muted">You do not have permission to change this setting ({setting.change_permission}).</p>;
  }
  if (setting.requires_dual_approval) {
    return <p className="mt-2 text-xs text-muted">Needs two approvers. The approval workflow arrives with Phase 2.</p>;
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    try {
      const parsed: unknown = JSON.parse(value);
      setParseError(null);
      mutation.mutate(parsed);
    } catch {
      setParseError("The value is not valid JSON.");
    }
  }
  return (
    <form onSubmit={submit} className="mt-3 space-y-3 rounded-md bg-surface p-3">
      <Field label="Value (JSON)">{(id) => <Textarea id={id} className="font-mono text-xs" value={value} onChange={(e) => setValue(e.target.value)} />}</Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Status">
          {(id) => (
            <Select id={id} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="safe_default">Safe default (still open)</option>
              <option value="confirmed">Confirmed by Mixt</option>
            </Select>
          )}
        </Field>
        <Field label="Decision reference" hint="Required when confirmed, e.g. BD-033">
          {(id) => <Input id={id} value={decisionRef} onChange={(e) => setDecisionRef(e.target.value)} />}
        </Field>
      </div>
      {parseError ? <p role="alert" className="text-sm text-danger">{parseError}</p> : null}
      <ErrorNote error={mutation.error} />
      <Button type="submit" disabled={mutation.isPending}>Save</Button>
    </form>
  );
}

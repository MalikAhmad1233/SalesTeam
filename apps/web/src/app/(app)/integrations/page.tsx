"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Badge, Button, Card, Empty, ErrorNote, Field, Input, Loading, Modal, PageHeader, Select, Table, Td } from "@/components/ui";
import { api, qs, type Schemas } from "@/lib/api";
import { formatDateTime, humanize } from "@/lib/format";
import { can, useMe, type Me } from "@/lib/session";

type Connection = Schemas["ConnectionOut"];

const STATUS_TONE: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  connected: "success",
  pending: "warning",
  error: "danger",
  disconnected: "neutral",
};

export default function IntegrationsPage() {
  const { data: me } = useMe();
  const connections = useQuery({ queryKey: ["integrations"], queryFn: () => api<Connection[]>("/integrations") });
  const [connecting, setConnecting] = useState(false);
  const active = (connections.data ?? []).filter((c) => c.status !== "disconnected");
  const old = (connections.data ?? []).filter((c) => c.status === "disconnected");
  return (
    <>
      <PageHeader
        title="Integrations"
        description="Mixt's own accounts with WhatsApp (Meta) and other services. Secrets are encrypted when saved and never shown again. Messages are sent from a number only after it is switched on in Settings (channels.whatsapp.numbers)."
        actions={<Button onClick={() => setConnecting(true)}>Connect WhatsApp</Button>}
      />
      {connections.isLoading ? <Loading /> : null}
      <ErrorNote error={connections.error} />
      {connections.data && active.length === 0 ? (
        <Empty>
          Nothing connected yet. WhatsApp needs Mixt&apos;s Meta business account, a registered number, a system-user access token and the app secret (see docs/07 §2).
        </Empty>
      ) : null}
      <div className="space-y-6">
        {active.map((c) => (
          <ConnectionCard key={c.id} c={c} me={me} />
        ))}
        {old.length > 0 ? (
          <Card title="Disconnected">
            <ul className="space-y-1 text-sm text-muted">
              {old.map((c) => (
                <li key={c.id}>
                  {c.display_name} ({humanize(c.provider)}), connected {formatDateTime(c.connected_at, me?.timezone)}
                </li>
              ))}
            </ul>
          </Card>
        ) : null}
      </div>
      <Modal open={connecting} title="Connect a WhatsApp number" onClose={() => setConnecting(false)}>
        <ConnectForm onDone={() => setConnecting(false)} />
      </Modal>
    </>
  );
}

function ConnectionCard({ c, me }: { c: Connection; me: Me | undefined }) {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["integrations"] });
    void queryClient.invalidateQueries({ queryKey: ["templates"] });
    void queryClient.invalidateQueries({ queryKey: ["webhooks", c.id] });
  };
  const check = useMutation({ mutationFn: () => api<Schemas["CheckOut"]>(`/integrations/${c.id}/check`, { method: "POST" }), onSuccess: refresh });
  const sync = useMutation({ mutationFn: () => api<Schemas["SyncOut"]>(`/integrations/${c.id}/templates/sync`, { method: "POST" }), onSuccess: refresh });
  const disconnect = useMutation({ mutationFn: () => api<Connection>(`/integrations/${c.id}/disconnect`, { method: "POST" }), onSuccess: refresh });
  const [rotating, setRotating] = useState(false);
  const webhookUrl = c.webhook_url ?? (typeof window !== "undefined" && c.webhook_path ? `${window.location.origin}${c.webhook_path}` : c.webhook_path);
  return (
    <Card
      title={`${c.display_name} · ${humanize(c.provider)}`}
      actions={<Badge tone={STATUS_TONE[c.status] ?? "neutral"}>{humanize(c.status)}</Badge>}
    >
      <div className="grid gap-4 md:grid-cols-2">
        <dl className="space-y-1 text-sm">
          {c.channel_account ? (
            <div>
              <dt className="inline text-muted">Number: </dt>
              <dd className="inline">
                {c.channel_account.address}{" "}
                {c.channel_account.enabled ? (
                  <Badge tone="success">Switched on</Badge>
                ) : (
                  <Badge tone="warning">Not switched on</Badge>
                )}
              </dd>
            </div>
          ) : null}
          <div>
            <dt className="inline text-muted">Graph API version: </dt>
            <dd className="inline">{String(c.config.graph_api_version ?? "—")}</dd>
          </div>
          <div>
            <dt className="inline text-muted">Webhook address: </dt>
            <dd className="inline break-all font-mono text-xs" data-testid="webhook-url">{webhookUrl}</dd>
          </div>
          <div>
            <dt className="inline text-muted">Webhook verified by Meta: </dt>
            <dd className="inline">{c.config.webhook_verified ? "yes" : "not yet"}</dd>
          </div>
          <div>
            <dt className="inline text-muted">Last success: </dt>
            <dd className="inline">{formatDateTime(c.last_success_at, me?.timezone)}</dd>
          </div>
          {c.last_error ? (
            <div className="text-danger">
              <dt className="inline">Last error: </dt>
              <dd className="inline">{c.last_error}</dd>
            </div>
          ) : null}
          <div>
            <dt className="inline text-muted">Rejected webhooks (bad signature): </dt>
            <dd className="inline">{c.rejected_webhooks}</dd>
          </div>
        </dl>
        <div className="space-y-2 text-sm">
          <p className="font-medium text-ink">Secrets</p>
          <ul className="space-y-1">
            {c.credentials.map((k) => (
              <li key={k.kind} className="flex justify-between gap-2">
                <span>{humanize(k.kind)}</span>
                <span className="text-muted">saved {formatDateTime(k.rotated_at, me?.timezone)}</span>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-2 pt-2">
            <Button variant="secondary" onClick={() => check.mutate()} disabled={check.isPending}>
              Check connection
            </Button>
            <Button variant="secondary" onClick={() => sync.mutate()} disabled={sync.isPending}>
              Sync templates
            </Button>
            <Button variant="secondary" onClick={() => setRotating(true)}>
              Replace a secret
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                if (window.confirm("Disconnect? Its secrets are destroyed; conversation history stays.")) disconnect.mutate();
              }}
            >
              Disconnect
            </Button>
          </div>
          {check.data ? (
            <p role="status" className={check.data.ok ? "text-success" : "text-danger"}>
              {check.data.detail}
              {check.data.verified_name ? ` Verified name: ${check.data.verified_name}.` : ""}
              {check.data.quality_rating ? ` Quality: ${check.data.quality_rating}.` : ""}
            </p>
          ) : null}
          {sync.data ? (
            <p role="status" className="text-success">
              Templates: {sync.data.created} new, {sync.data.updated} updated, {sync.data.disabled} no longer at Meta, {sync.data.needs_review} need a new review.
            </p>
          ) : null}
          <ErrorNote error={check.error ?? sync.error ?? disconnect.error} />
        </div>
      </div>
      {c.channel_account ? <Templates channelAccountId={c.channel_account.id} me={me} /> : null}
      <FailedWebhooks connectionId={c.id} me={me} count={c.failed_webhooks} />
      <Modal open={rotating} title="Replace a secret" onClose={() => setRotating(false)}>
        <RotateForm connectionId={c.id} onDone={() => { setRotating(false); refresh(); }} />
      </Modal>
    </Card>
  );
}

function Templates({ channelAccountId, me }: { channelAccountId: string; me: Me | undefined }) {
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: ["templates", channelAccountId],
    queryFn: () => api<Schemas["TemplateOut"][]>(`/messaging/templates${qs({ channel_account_id: channelAccountId })}`),
  });
  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "approve" | "retire" }) =>
      api<Schemas["TemplateOut"]>(`/messaging/templates/${id}/${action}`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["templates"] }),
  });
  const approver = can(me, "messaging.templates.approve");
  return (
    <div className="mt-6">
      <h3 className="mb-2 text-sm font-semibold text-ink">Message templates</h3>
      {list.isLoading ? <Loading /> : null}
      <ErrorNote error={list.error ?? act.error} />
      {list.data && list.data.length === 0 ? <Empty>No templates synced yet.</Empty> : null}
      {list.data && list.data.length > 0 ? (
        <Table label="Message templates" head={["Template", "Wording", "Meta", "Mixt", ""]}>
          {list.data.map((t) => (
            <tr key={t.id}>
              <Td>
                <span className="font-medium">{t.name}</span>
                <p className="text-xs text-muted">
                  {t.language} · {humanize(t.category)}
                </p>
              </Td>
              <Td className="max-w-md text-xs">
                {t.body}
                {t.unsupported_reason ? <p className="mt-1 text-warning">Can&apos;t be used yet: {t.unsupported_reason}</p> : null}
              </Td>
              <Td>
                <Badge tone={t.provider_status === "approved" ? "success" : "warning"}>{humanize(t.provider_status)}</Badge>
              </Td>
              <Td>
                <Badge tone={t.internal_status === "approved" ? "success" : t.internal_status === "retired" ? "neutral" : "warning"}>
                  {humanize(t.internal_status)}
                </Badge>
              </Td>
              <Td>
                {approver && t.internal_status !== "approved" && t.provider_status === "approved" && !t.unsupported_reason ? (
                  <Button variant="ghost" onClick={() => act.mutate({ id: t.id, action: "approve" })}>
                    Approve for use
                  </Button>
                ) : null}
                {approver && t.internal_status === "approved" ? (
                  <Button variant="ghost" onClick={() => act.mutate({ id: t.id, action: "retire" })}>
                    Retire
                  </Button>
                ) : null}
              </Td>
            </tr>
          ))}
        </Table>
      ) : null}
    </div>
  );
}

function FailedWebhooks({ connectionId, me, count }: { connectionId: string; me: Me | undefined; count: number }) {
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: ["webhooks", connectionId],
    queryFn: () => api<Schemas["WebhookEventOut"][]>(`/integrations/${connectionId}/webhooks${qs({ status: "failed" })}`),
    enabled: count > 0,
  });
  const replay = useMutation({
    mutationFn: (id: string) => api<void>(`/integrations/webhooks/${id}/replay`, { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["webhooks", connectionId] });
      void queryClient.invalidateQueries({ queryKey: ["integrations"] });
    },
  });
  if (count === 0) return null;
  return (
    <div className="mt-6">
      <h3 className="mb-2 text-sm font-semibold text-danger">Webhooks that could not be processed ({count})</h3>
      <ErrorNote error={list.error ?? replay.error} />
      <Table label="Failed webhooks" head={["Received", "Content", "Error", ""]}>
        {(list.data ?? []).map((w) => (
          <tr key={w.id}>
            <Td>{formatDateTime(w.received_at, me?.timezone)}</Td>
            <Td>{w.summary}</Td>
            <Td className="max-w-md text-xs text-danger">{w.last_error}</Td>
            <Td>
              <Button variant="ghost" onClick={() => replay.mutate(w.id)} disabled={replay.isPending}>
                Process again
              </Button>
            </Td>
          </tr>
        ))}
      </Table>
    </div>
  );
}

function ConnectForm({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    display_name: "Mixt WhatsApp",
    graph_api_version: "",
    waba_id: "",
    phone_number_id: "",
    display_phone_number: "",
    access_token: "",
    app_secret: "",
    verify_token: "",
  });
  const connect = useMutation({
    mutationFn: () => api<Connection>("/integrations/whatsapp", { json: form }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["integrations"] });
      onDone();
    },
  });
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  function submit(e: FormEvent) {
    e.preventDefault();
    connect.mutate();
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <p className="text-sm text-muted">
        All values come from Mixt&apos;s Meta app and WhatsApp Manager. After saving, enter the webhook address and the verify token in the Meta app, then subscribe to the &quot;messages&quot; and template status fields.
      </p>
      <Field label="Name">{(id) => <Input id={id} value={form.display_name} onChange={set("display_name")} required />}</Field>
      <Field label="Graph API version" hint="The version your Meta app uses, e.g. v21.0.">
        {(id) => <Input id={id} value={form.graph_api_version} onChange={set("graph_api_version")} required placeholder="v21.0" />}
      </Field>
      <Field label="WhatsApp Business Account ID">{(id) => <Input id={id} value={form.waba_id} onChange={set("waba_id")} required inputMode="numeric" />}</Field>
      <Field label="Phone number ID">{(id) => <Input id={id} value={form.phone_number_id} onChange={set("phone_number_id")} required inputMode="numeric" />}</Field>
      <Field label="Phone number" hint="As customers see it, with country code.">
        {(id) => <Input id={id} value={form.display_phone_number} onChange={set("display_phone_number")} required placeholder="+974..." />}
      </Field>
      <Field label="System user access token">{(id) => <Input id={id} type="password" autoComplete="off" value={form.access_token} onChange={set("access_token")} required />}</Field>
      <Field label="App secret">{(id) => <Input id={id} type="password" autoComplete="off" value={form.app_secret} onChange={set("app_secret")} required />}</Field>
      <Field label="Webhook verify token" hint="A long random value you choose (at least 16 characters); enter the same value in the Meta app.">
        {(id) => <Input id={id} type="password" autoComplete="off" value={form.verify_token} onChange={set("verify_token")} required minLength={16} />}
      </Field>
      <ErrorNote error={connect.error} />
      <Button type="submit" disabled={connect.isPending}>
        Save connection
      </Button>
    </form>
  );
}

function RotateForm({ connectionId, onDone }: { connectionId: string; onDone: () => void }) {
  const [kind, setKind] = useState("access_token");
  const [value, setValue] = useState("");
  const rotate = useMutation({
    mutationFn: () => api<void>(`/integrations/${connectionId}/credentials`, { method: "PUT", json: { kind, value } }),
    onSuccess: onDone,
  });
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        rotate.mutate();
      }}
    >
      <Field label="Secret">
        {(id) => (
          <Select id={id} value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="access_token">Access token</option>
            <option value="app_secret">App secret</option>
            <option value="verify_token">Webhook verify token</option>
          </Select>
        )}
      </Field>
      <Field label="New value">{(id) => <Input id={id} type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)} required />}</Field>
      <ErrorNote error={rotate.error} />
      <Button type="submit" disabled={rotate.isPending}>
        Save
      </Button>
      <p className="text-xs text-muted">
        Switching a number on or off is a setting: <Link href="/settings" className="text-accent">channels.whatsapp.numbers</Link>.
      </p>
    </form>
  );
}

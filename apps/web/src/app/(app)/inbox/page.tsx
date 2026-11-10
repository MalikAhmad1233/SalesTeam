"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { Badge, Button, Card, Empty, ErrorNote, Field, Input, Loading, Modal, PageHeader, Select, Textarea } from "@/components/ui";
import { api, qs, type Schemas } from "@/lib/api";
import { formatDateTime, humanize } from "@/lib/format";
import { channelLabel, MESSAGE_STATUS, newKey, renderTemplate, useInboxStream, windowText } from "@/lib/inbox";
import { can, useMe, type Me } from "@/lib/session";

type Conversation = Schemas["ConversationOut"];
type Message = Schemas["MessageOut"];
type View = "mine" | "unassigned" | "unmatched" | "all";

const STATUS_LABEL: Record<string, string> = { open: "Open", pending_customer: "Waiting for customer", closed: "Closed" };

export default function InboxPage() {
  return (
    <Suspense fallback={<Loading />}>
      <Inbox />
    </Suspense>
  );
}

function Inbox() {
  const { data: me } = useMe();
  const router = useRouter();
  const params = useSearchParams();
  const selected = params.get("c");
  const summary = useQuery({ queryKey: ["inbox", "summary"], queryFn: () => api<Schemas["SummaryOut"]>("/inbox/summary") });
  const [view, setView] = useState<View>("all");
  const [status, setStatus] = useState<"active" | "closed">("active");
  const [search, setSearch] = useState("");
  useInboxStream(true);

  const list = useQuery({
    queryKey: ["inbox", "list", view, status, search],
    queryFn: () => api<Conversation[]>(`/inbox/conversations${qs({ view, status, q: search.trim() || undefined })}`),
    refetchInterval: 30_000,
  });
  const views: { key: View; label: string }[] = [
    { key: "all", label: "All" },
    { key: "mine", label: "Mine" },
    { key: "unassigned", label: "Unassigned" },
    ...(summary.data?.can_see_unmatched ? [{ key: "unmatched" as View, label: "Not linked" }] : []),
  ];

  function open(id: string) {
    router.replace(`/inbox${qs({ c: id })}`, { scroll: false });
  }

  return (
    <>
      <PageHeader
        title="Inbox"
        description="Every customer conversation in one place. Replies follow the channel's rules: WhatsApp allows free text only within 24 hours of the customer's last message; after that, only templates approved by Meta and by Mixt, with the customer's consent."
        actions={
          can(me, "messaging.suppression.manage") ? (
            <Link href="/inbox/blocked" className="text-sm text-accent hover:underline">
              Blocked numbers
            </Link>
          ) : null
        }
      />
      <div className="grid gap-4 lg:grid-cols-[20rem_minmax(0,1fr)] xl:grid-cols-[20rem_minmax(0,1fr)_18rem]">
        <section aria-label="Conversations" className="flex min-h-0 flex-col rounded-lg border border-border bg-white">
          <div className="space-y-2 border-b border-border p-3">
            <div role="tablist" aria-label="Inbox view" className="flex flex-wrap gap-1">
              {views.map((v) => (
                <button
                  key={v.key}
                  role="tab"
                  type="button"
                  aria-selected={view === v.key}
                  onClick={() => setView(v.key)}
                  className={`rounded-md px-2 py-1 text-sm ${view === v.key ? "bg-primary-soft font-medium text-primary-strong" : "text-muted hover:bg-surface"}`}
                >
                  {v.label}
                </button>
              ))}
            </div>
            <div className="flex gap-2">
              <Input
                aria-label="Search by name or number"
                placeholder="Search name or number"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="min-w-0 flex-1"
              />
              <Select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value as "active" | "closed")}>
                <option value="active">Active</option>
                <option value="closed">Closed</option>
              </Select>
            </div>
          </div>
          <div className="max-h-[70vh] overflow-y-auto">
            {list.isLoading ? <div className="p-3"><Loading /></div> : null}
            <div className="p-3 empty:hidden"><ErrorNote error={list.error} /></div>
            {list.data && list.data.length === 0 ? <p className="p-4 text-sm text-muted">No conversations here.</p> : null}
            <ul>
              {(list.data ?? []).map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => open(c.id)}
                    aria-current={selected === c.id ? "true" : undefined}
                    className={`block w-full border-b border-border px-3 py-2 text-left ${selected === c.id ? "bg-primary-soft" : "hover:bg-surface"}`}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium text-ink">{c.account_name ?? c.customer_name ?? c.customer_handle}</span>
                      {c.unread_count > 0 ? (
                        <span className="rounded-full bg-primary px-1.5 text-xs font-semibold text-white" aria-label={`${c.unread_count} unread`}>
                          {c.unread_count}
                        </span>
                      ) : null}
                    </span>
                    <span className="block truncate text-xs text-muted">
                      {c.last_message?.direction === "outbound" ? "You: " : ""}
                      {c.last_message?.preview ?? "—"}
                    </span>
                    <span className="mt-1 flex flex-wrap items-center gap-1 text-[11px] text-muted">
                      <span>{formatDateTime(c.last_activity_at, me?.timezone)}</span>
                      {!c.account_id ? <Badge tone="warning">Not linked</Badge> : null}
                      {c.window_open ? <Badge tone="success">Window open</Badge> : null}
                      {c.status === "pending_customer" ? <Badge>Waiting for customer</Badge> : null}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </section>
        {selected ? (
          <ConversationPane key={selected} id={selected} me={me} summary={summary.data} />
        ) : (
          <Card className="xl:col-span-2">
            <Empty>Choose a conversation.</Empty>
          </Card>
        )}
      </div>
    </>
  );
}

function ConversationPane({ id, me, summary }: { id: string; me: Me | undefined; summary: Schemas["SummaryOut"] | undefined }) {
  const queryClient = useQueryClient();
  const conversation = useQuery({ queryKey: ["conversation", id], queryFn: () => api<Conversation>(`/inbox/conversations/${id}`) });
  const messages = useQuery({
    queryKey: ["conversation-messages", id],
    queryFn: () => api<Message[]>(`/inbox/conversations/${id}/messages`),
    refetchInterval: 30_000,
  });
  const markRead = useMutation({
    mutationFn: () => api<Conversation>(`/inbox/conversations/${id}/read`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["inbox"] }),
  });
  const unread = conversation.data?.unread_count ?? 0;
  const { mutate: markReadNow } = markRead;
  useEffect(() => {
    if (unread > 0) markReadNow();
  }, [unread, markReadNow]);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // A block body: scrollIntoView may return a promise, which React must not treat as a cleanup.
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages.data?.length]);

  if (conversation.isLoading) return <Loading />;
  if (conversation.error || !conversation.data) return <ErrorNote error={conversation.error ?? new Error("not found")} />;
  const c = conversation.data;
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["conversation", id] });
    void queryClient.invalidateQueries({ queryKey: ["conversation-messages", id] });
    void queryClient.invalidateQueries({ queryKey: ["inbox"] });
  };

  return (
    <>
      <section aria-label="Conversation" className="flex min-w-0 flex-col rounded-lg border border-border bg-white">
        <header className="border-b border-border px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <h2 className="truncate text-base font-semibold text-ink">{c.customer_name ?? c.customer_handle}</h2>
              <p className="text-xs text-muted">
                {c.customer_handle} · {channelLabel(c.channel)} · {c.channel_name}
              </p>
            </div>
            <div className="flex flex-wrap gap-1">
              {c.suppressed ? <Badge tone="danger">Blocked: no messages</Badge> : null}
              {!c.channel_enabled ? <Badge tone="warning">Number not switched on</Badge> : null}
              <Badge tone={c.status === "closed" ? "neutral" : "accent"}>{STATUS_LABEL[c.status] ?? humanize(c.status)}</Badge>
            </div>
          </div>
          <p className={`mt-2 text-xs ${c.window_open ? "text-success" : "text-warning"}`}>{windowText(c.service_window_expires_at, c.window_open)}</p>
        </header>
        <div className="max-h-[55vh] min-h-64 space-y-2 overflow-y-auto bg-surface/50 px-4 py-3" aria-live="polite">
          {messages.isLoading ? <Loading /> : null}
          <ErrorNote error={messages.error} />
          {(messages.data ?? []).map((m) => (
            <MessageBubble key={m.id} m={m} me={me} onRetried={refresh} />
          ))}
          <div ref={bottom} />
        </div>
        {can(me, "messaging.send") ? <Composer c={c} onSent={refresh} /> : null}
      </section>
      <CustomerPanel c={c} me={me} summary={summary} onChanged={refresh} />
    </>
  );
}

function MessageBubble({ m, me, onRetried }: { m: Message; me: Me | undefined; onRetried: () => void }) {
  const retry = useMutation({ mutationFn: () => api<Message>(`/inbox/messages/${m.id}/retry`, { method: "POST" }), onSuccess: onRetried });
  const time = formatDateTime(m.provider_timestamp ?? m.created_at, me?.timezone);
  if (m.direction === "internal") {
    return (
      <div className="mx-auto max-w-[85%] rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-ink" data-testid="internal-note">
        <p className="text-[11px] font-medium text-warning">
          {m.sender_type === "system" ? "System" : `Note by ${m.sender_name ?? "a colleague"}`} · {time}
        </p>
        <p className="whitespace-pre-wrap">{m.body_text}</p>
      </div>
    );
  }
  const outbound = m.direction === "outbound";
  const status = MESSAGE_STATUS[m.status];
  return (
    <div className={`flex ${outbound ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${outbound ? "bg-primary-soft" : "border border-border bg-white"}`} data-testid={outbound ? "outbound-message" : "inbound-message"}>
        {m.content_type === "template" ? <p className="text-[11px] font-medium text-accent">Template</p> : null}
        {m.media ? <p className="text-xs text-muted">[{String(m.media.type ?? "attachment")}]{m.media.stored === false ? " · file not downloaded yet" : ""}</p> : null}
        {m.body_text ? <p className="whitespace-pre-wrap text-ink">{m.body_text}</p> : null}
        <p className="mt-1 flex flex-wrap items-center gap-1 text-[11px] text-muted">
          {outbound ? <span>{m.sender_name ?? "Mixt"} ·</span> : null}
          <span>{time}</span>
          {outbound && status ? <Badge tone={status.tone}>{status.label}</Badge> : null}
        </p>
        {m.status === "failed" ? (
          <div className="mt-1 text-xs text-danger">
            <p>
              {humanize(m.failure_code)}
              {m.failure_detail ? `: ${m.failure_detail}` : ""}
            </p>
            <Button variant="ghost" className="mt-1 px-0 py-0 text-xs" onClick={() => retry.mutate()} disabled={retry.isPending}>
              Send again
            </Button>
            <ErrorNote error={retry.error} />
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Composer({ c, onSent }: { c: Conversation; onSent: () => void }) {
  const [mode, setMode] = useState<"reply" | "template" | "note">(c.window_open ? "reply" : "template");
  const [text, setText] = useState("");
  const [key, setKey] = useState(newKey);
  const [templateId, setTemplateId] = useState("");
  const [values, setValues] = useState<string[]>([]);
  const templates = useQuery({
    queryKey: ["conversation-templates", c.id],
    queryFn: () => api<Schemas["TemplateOptionOut"][]>(`/inbox/conversations/${c.id}/templates`),
    enabled: mode === "template",
  });
  const chosen = templates.data?.find((t) => t.id === templateId);
  const done = () => {
    setText("");
    setValues([]);
    setKey(newKey());
    onSent();
  };
  const send = useMutation({
    mutationFn: () => {
      if (mode === "note") return api<Message>(`/inbox/conversations/${c.id}/notes`, { json: { text } });
      if (mode === "template") {
        return api<Message>(`/inbox/conversations/${c.id}/templates`, {
          json: { template_id: templateId, variables: values },
          idempotencyKey: key,
        });
      }
      return api<Message>(`/inbox/conversations/${c.id}/messages`, { json: { text }, idempotencyKey: key });
    },
    onSuccess: done,
  });
  const blocked = c.suppressed
    ? "Messages to this number are blocked."
    : !c.channel_enabled
      ? "This WhatsApp number is not switched on yet (setting channels.whatsapp.numbers)."
      : null;

  function submit(event: FormEvent) {
    event.preventDefault();
    send.mutate();
  }

  return (
    <form onSubmit={submit} className="space-y-2 border-t border-border p-3" aria-label="Write a message">
      <div role="tablist" aria-label="Message type" className="flex gap-1">
        {(
          [
            ["reply", "Reply"],
            ["template", "Template"],
            ["note", "Internal note"],
          ] as const
        ).map(([key_, label]) => (
          <button
            key={key_}
            type="button"
            role="tab"
            aria-selected={mode === key_}
            onClick={() => setMode(key_)}
            className={`rounded-md px-2 py-1 text-sm ${mode === key_ ? "bg-primary-soft font-medium text-primary-strong" : "text-muted hover:bg-surface"}`}
          >
            {label}
          </button>
        ))}
      </div>
      {mode !== "note" && blocked ? <p className="text-sm text-warning">{blocked}</p> : null}
      {mode === "reply" ? (
        c.window_open ? (
          <Textarea aria-label="Reply" value={text} onChange={(e) => setText(e.target.value)} maxLength={4096} placeholder="Write a reply" />
        ) : (
          <p className="text-sm text-muted">The 24-hour window is closed. Use an approved template.</p>
        )
      ) : null}
      {mode === "note" ? (
        <Textarea aria-label="Internal note" value={text} onChange={(e) => setText(e.target.value)} maxLength={4000} placeholder="Only your team sees this" />
      ) : null}
      {mode === "template" ? (
        <div className="space-y-2">
          {templates.isLoading ? <Loading /> : null}
          <ErrorNote error={templates.error} />
          {templates.data && templates.data.length === 0 ? <p className="text-sm text-muted">No templates for this number yet. An administrator syncs them from Meta.</p> : null}
          {templates.data && templates.data.length > 0 ? (
            <Select
              aria-label="Template"
              value={templateId}
              onChange={(e) => {
                setTemplateId(e.target.value);
                const t = templates.data?.find((x) => x.id === e.target.value);
                setValues(Array.from({ length: t?.variable_count ?? 0 }, () => ""));
              }}
            >
              <option value="">Choose a template</option>
              {templates.data.map((t) => (
                <option key={t.id} value={t.id} disabled={!!t.problem}>
                  {t.name} ({t.language}, {t.category}){t.problem ? ` — ${t.problem}` : ""}
                </option>
              ))}
            </Select>
          ) : null}
          {chosen ? (
            <>
              {values.map((v, i) => (
                <Input
                  key={i}
                  aria-label={`Variable ${i + 1}`}
                  placeholder={`Variable {{${i + 1}}}`}
                  value={v}
                  onChange={(e) => setValues(values.map((x, j) => (j === i ? e.target.value : x)))}
                />
              ))}
              <p className="rounded-md bg-surface px-3 py-2 text-sm text-ink" aria-label="Preview">
                {renderTemplate(chosen.body, values)}
              </p>
            </>
          ) : null}
        </div>
      ) : null}
      <ErrorNote error={send.error} />
      <div className="flex justify-end">
        <Button
          type="submit"
          disabled={
            send.isPending ||
            (mode !== "note" && !!blocked) ||
            (mode === "reply" && (!c.window_open || !text.trim())) ||
            (mode === "note" && !text.trim()) ||
            (mode === "template" && (!chosen || values.some((v) => !v.trim())))
          }
        >
          {mode === "note" ? "Add note" : "Send"}
        </Button>
      </div>
    </form>
  );
}

function CustomerPanel({ c, me, summary, onChanged }: { c: Conversation; me: Me | undefined; summary: Schemas["SummaryOut"] | undefined; onChanged: () => void }) {
  const assignees = useQuery({ queryKey: ["inbox", "assignees"], queryFn: () => api<Schemas["AssigneeOut"][]>("/inbox/assignees"), staleTime: 300_000 });
  const assign = useMutation({
    mutationFn: (userId: string | null) => api<Conversation>(`/inbox/conversations/${c.id}/assign`, { json: { user_id: userId } }),
    onSuccess: onChanged,
  });
  const setStatus = useMutation({
    mutationFn: (status: "open" | "closed") => api<Conversation>(`/inbox/conversations/${c.id}/status`, { json: { status } }),
    onSuccess: onChanged,
  });
  const [linking, setLinking] = useState(false);
  const [leading, setLeading] = useState(false);

  return (
    <aside aria-label="Customer" className="space-y-4 lg:col-span-2 xl:col-span-1">
      <Card title="Customer">
        {c.account_id ? (
          <div className="space-y-1 text-sm">
            <Link href={`/customers/${c.account_id}`} className="font-medium text-accent">
              {c.account_name}
            </Link>
            <p className="text-muted">{c.contact_name ? `Contact: ${c.contact_name}` : "No contact chosen"}</p>
          </div>
        ) : (
          <div className="space-y-2 text-sm">
            <p className="text-muted">Not linked to a customer yet. Templates need a linked customer (consent is checked on the contact).</p>
            {summary?.can_see_unmatched ? (
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" onClick={() => setLinking(true)}>
                  Link to customer
                </Button>
                {can(me, "leads.create") ? <Button onClick={() => setLeading(true)}>Create lead</Button> : null}
              </div>
            ) : null}
          </div>
        )}
        {c.account_id && summary?.can_assign ? (
          <button type="button" className="mt-2 text-sm text-accent hover:underline" onClick={() => setLinking(true)}>
            Link to a different customer
          </button>
        ) : null}
      </Card>
      <Card title="Handled by">
        <p className="text-sm text-ink" data-testid="assignee">{c.assigned_name ?? "Nobody yet"}</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {!c.assigned_user_id && me ? (
            <Button variant="secondary" onClick={() => assign.mutate(me.id)} disabled={assign.isPending}>
              Take it
            </Button>
          ) : null}
          {summary?.can_assign ? (
            <Select aria-label="Assign to" value={c.assigned_user_id ?? ""} onChange={(e) => assign.mutate(e.target.value || null)}>
              <option value="">Unassigned</option>
              {(assignees.data ?? []).map((a) => (
                <option key={a.user_id} value={a.user_id}>
                  {a.name}
                </option>
              ))}
            </Select>
          ) : null}
        </div>
        <ErrorNote error={assign.error} />
      </Card>
      {can(me, "messaging.send") ? (
        <Card>
          {c.status === "closed" ? (
            <Button variant="secondary" onClick={() => setStatus.mutate("open")}>
              Reopen conversation
            </Button>
          ) : (
            <Button variant="secondary" onClick={() => setStatus.mutate("closed")}>
              Close conversation
            </Button>
          )}
          <ErrorNote error={setStatus.error} />
        </Card>
      ) : null}
      <Modal open={linking} title="Link to a customer" onClose={() => setLinking(false)}>
        <LinkForm c={c} onDone={() => { setLinking(false); onChanged(); }} />
      </Modal>
      <Modal open={leading} title="Create a lead from this conversation" onClose={() => setLeading(false)}>
        <LeadForm c={c} onDone={() => { setLeading(false); onChanged(); }} />
      </Modal>
    </aside>
  );
}

function LinkForm({ c, onDone }: { c: Conversation; onDone: () => void }) {
  const [search, setSearch] = useState(c.customer_name ?? "");
  const [accountId, setAccountId] = useState("");
  const [contactId, setContactId] = useState("");
  const [saveNumber, setSaveNumber] = useState(true);
  const accounts = useQuery({
    queryKey: ["accounts-search", search],
    queryFn: () => api<Schemas["AccountOut"][]>(`/crm/accounts${qs({ search: search.trim() || undefined, limit: 20 })}`),
  });
  const contacts = useQuery({
    queryKey: ["contacts", accountId],
    queryFn: () => api<Schemas["ContactOut"][]>(`/crm/accounts/${accountId}/contacts`),
    enabled: !!accountId,
  });
  const link = useMutation({
    mutationFn: () =>
      api<Conversation>(`/inbox/conversations/${c.id}/link`, {
        json: { account_id: accountId, contact_id: contactId || null, save_number: !!contactId && saveNumber },
      }),
    onSuccess: onDone,
  });
  const options = useMemo(() => accounts.data ?? [], [accounts.data]);
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        link.mutate();
      }}
    >
      <Field label="Find a household">{(id) => <Input id={id} value={search} onChange={(e) => setSearch(e.target.value)} />}</Field>
      <Field label="Household">
        {(id) => (
          <Select id={id} value={accountId} onChange={(e) => { setAccountId(e.target.value); setContactId(""); }} required>
            <option value="">Choose</option>
            {options.map((a) => (
              <option key={a.id} value={a.id}>
                {a.display_name} ({a.account_number})
              </option>
            ))}
          </Select>
        )}
      </Field>
      {accountId ? (
        <Field label="Contact" hint="Who is writing? Their number is saved so the next conversation links by itself.">
          {(id) => (
            <Select id={id} value={contactId} onChange={(e) => setContactId(e.target.value)}>
              <option value="">Not sure yet</option>
              {(contacts.data ?? []).map((ct) => (
                <option key={ct.id} value={ct.id}>
                  {[ct.first_name, ct.last_name].filter(Boolean).join(" ")} ({humanize(ct.role)})
                </option>
              ))}
            </Select>
          )}
        </Field>
      ) : null}
      {contactId ? (
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={saveNumber} onChange={(e) => setSaveNumber(e.target.checked)} /> Save {c.customer_handle} on this contact
        </label>
      ) : null}
      <ErrorNote error={link.error} />
      <Button type="submit" disabled={!accountId || link.isPending}>
        Link
      </Button>
    </form>
  );
}

function LeadForm({ c, onDone }: { c: Conversation; onDone: () => void }) {
  const [first, setFirst] = useState(c.customer_name ?? "");
  const [last, setLast] = useState("");
  const [country, setCountry] = useState("");
  const [student, setStudent] = useState("");
  const create = useMutation({
    mutationFn: () =>
      api<Schemas["ConversationLeadOut"]>(`/inbox/conversations/${c.id}/lead`, {
        json: {
          guardian_first_name: first || null,
          guardian_last_name: last || null,
          country: country ? country.toUpperCase() : null,
          student_first_name: student || null,
        },
      }),
    onSuccess: onDone,
  });
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <p className="text-sm text-muted">
        The lead goes through normal intake: if {c.customer_handle} already belongs to a household you are told, and a country outside Mixt&apos;s markets is flagged for review.
      </p>
      <Field label="Parent or guardian first name">{(id) => <Input id={id} value={first} onChange={(e) => setFirst(e.target.value)} />}</Field>
      <Field label="Last name">{(id) => <Input id={id} value={last} onChange={(e) => setLast(e.target.value)} />}</Field>
      <Field label="Country of residence" hint="Two-letter code, e.g. QA. Leave empty if unknown.">
        {(id) => <Input id={id} value={country} maxLength={2} onChange={(e) => setCountry(e.target.value)} />}
      </Field>
      <Field label="Student first name">{(id) => <Input id={id} value={student} onChange={(e) => setStudent(e.target.value)} />}</Field>
      <ErrorNote error={create.error} />
      <Button type="submit" disabled={create.isPending}>
        Create lead
      </Button>
    </form>
  );
}

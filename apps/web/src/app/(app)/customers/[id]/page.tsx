"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Badge, Button, Card, Empty, ErrorNote, Field, Input, Loading, Modal, PageHeader, Select, Textarea } from "@/components/ui";
import { api, ApiError, qs, type Schemas } from "@/lib/api";
import { formatDateTime, formatMoney, humanize, localTimeIn } from "@/lib/format";
import { useCurrencies, useCurricula, useMarkets, useStages, useUserNames } from "@/lib/queries";
import { channelLabel } from "@/lib/inbox";
import { can, useMe } from "@/lib/session";

export default function CustomerPage() {
  const { id } = useParams<{ id: string }>();
  const { data: me } = useMe();
  const ownerName = useUserNames(me);
  const markets = useMarkets();
  const account = useQuery({ queryKey: ["account", id], queryFn: () => api<Schemas["AccountOut"]>(`/crm/accounts/${id}`) });
  const [confirming, setConfirming] = useState(false);

  if (account.isLoading) return <Loading />;
  if (account.error || !account.data) return <ErrorNote error={account.error ?? new Error("not found")} />;
  const a = account.data;
  const market = markets.data?.find((m) => m.id === a.market_id);
  const localTime = localTimeIn(a.timezone);

  return (
    <>
      <PageHeader
        title={a.display_name}
        description={`${a.account_number} · Owner: ${ownerName(a.owner_user_id)}${a.country_of_residence ? ` · Lives in ${a.country_of_residence}` : ""}${localTime ? ` · Local time ${localTime}` : ""}`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={a.lifecycle_stage === "out_of_market" ? "warning" : "accent"}>{humanize(a.lifecycle_stage)}</Badge>
            {market ? (
              <Badge tone="success">Pricing market: {market.name}</Badge>
            ) : (
              <Badge tone="warning">Pricing market not confirmed</Badge>
            )}
            {can(me, "crm.market.confirm") ? (
              <Button variant="secondary" onClick={() => setConfirming(true)}>
                {market ? "Change market" : "Confirm market"}
              </Button>
            ) : null}
          </div>
        }
      />
      {a.lifecycle_stage === "out_of_market" ? (
        <p className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-warning">
          This household lives outside Mixt&apos;s 13 markets. No sales outreach or pricing; a manager decides what happens next.
        </p>
      ) : null}
      <div className="grid gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          <Contacts accountId={id} />
          <Students accountId={id} />
          <Opportunities accountId={id} />
          {can(me, "inbox.read") ? <Conversations accountId={id} /> : null}
          {can(me, "quotations.read") ? <Quotations accountId={id} /> : null}
          <Notes accountId={id} />
        </div>
        <div className="space-y-6">
          <Pricing accountId={id} marketConfirmed={Boolean(market)} />
          <Tasks accountId={id} />
          <Tags accountId={id} />
          <Timeline accountId={id} timezone={me?.timezone} />
        </div>
      </div>
      <Modal open={confirming} title="Confirm pricing market" onClose={() => setConfirming(false)}>
        <ConfirmMarket account={a} onDone={() => setConfirming(false)} />
      </Modal>
    </>
  );
}

function ConfirmMarket({ account, onDone }: { account: Schemas["AccountOut"]; onDone: () => void }) {
  const queryClient = useQueryClient();
  const markets = useMarkets();
  const [marketId, setMarketId] = useState(account.market_id ?? "");
  const [note, setNote] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      api(`/crm/accounts/${account.id}/market-confirmation`, { json: { market_id: marketId, note }, version: account.version }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["account", account.id] });
      await queryClient.invalidateQueries({ queryKey: ["pricing-tiers", account.id] });
      await queryClient.invalidateQueries({ queryKey: ["pricing-options", account.id] });
      onDone();
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    mutation.mutate();
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <p className="text-sm text-muted">
        Confirm from what the family told you (for example where they live). Currency, phone number and curriculum never decide the market.
      </p>
      <Field label="Market">
        {(id) => (
          <Select id={id} required value={marketId} onChange={(e) => setMarketId(e.target.value)}>
            <option value="">Choose…</option>
            {(markets.data ?? []).filter((m) => m.status === "active").map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label="How was it confirmed?">
        {(id) => <Input id={id} required minLength={5} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Parent said they live in Dubai" />}
      </Field>
      <ErrorNote error={mutation.error} />
      <Button type="submit" disabled={mutation.isPending}>Confirm</Button>
    </form>
  );
}

function ContactDetails({ contactId }: { contactId: string }) {
  const points = useQuery({
    queryKey: ["contact-points", contactId],
    queryFn: () => api<Schemas["ContactPointOut"][]>(`/crm/contacts/${contactId}/contact-points`),
  });
  const consents = useQuery({ queryKey: ["consents", contactId], queryFn: () => api<Schemas["ConsentsOut"]>(`/crm/contacts/${contactId}/consents`) });
  return (
    <div className="mt-1 space-y-1 text-sm">
      {(points.data ?? []).map((p) => (
        <p key={p.id} className="text-muted">
          {humanize(p.kind)}: <span className="text-ink">{p.value}</span>
        </p>
      ))}
      <div className="flex flex-wrap gap-1">
        {(consents.data?.current ?? []).length === 0 ? (
          <span className="text-xs text-muted">No consent recorded</span>
        ) : (
          consents.data?.current.map((c) => (
            <Badge key={c.id} tone={c.status === "granted" ? "success" : "danger"}>
              {humanize(c.purpose)}: {c.status}
            </Badge>
          ))
        )}
      </div>
    </div>
  );
}

function Contacts({ accountId }: { accountId: string }) {
  const contacts = useQuery({ queryKey: ["contacts", accountId], queryFn: () => api<Schemas["ContactOut"][]>(`/crm/accounts/${accountId}/contacts`) });
  return (
    <Card title="Contacts">
      {(contacts.data ?? []).length === 0 ? <Empty>No contacts.</Empty> : null}
      <ul className="divide-y divide-border">
        {(contacts.data ?? []).map((c) => (
          <li key={c.id} className="py-2">
            <p className="font-medium">
              {[c.first_name, c.last_name].filter(Boolean).join(" ") || c.preferred_name}{" "}
              <span className="text-xs font-normal text-muted">({humanize(c.role)})</span>{" "}
              {c.is_primary ? <Badge tone="primary">Primary</Badge> : null}
            </p>
            <ContactDetails contactId={c.id} />
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Students({ accountId }: { accountId: string }) {
  const queryClient = useQueryClient();
  const { data: me } = useMe();
  const curricula = useCurricula();
  const students = useQuery({ queryKey: ["students", accountId], queryFn: () => api<Schemas["StudentOut"][]>(`/crm/accounts/${accountId}/students`) });
  const [form, setForm] = useState({ first_name: "", curriculum_code: "", grade_text: "" });
  const [subject, setSubject] = useState<Record<string, string>>({});
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["students", accountId] });
  const add = useMutation({
    mutationFn: () =>
      api(`/crm/accounts/${accountId}/students`, {
        json: Object.fromEntries(Object.entries(form).filter(([, v]) => v !== "")),
      }),
    onSuccess: async () => {
      setForm({ first_name: "", curriculum_code: "", grade_text: "" });
      await refresh();
    },
  });
  const addSubject = useMutation({
    mutationFn: (studentId: string) => api(`/crm/students/${studentId}/subjects`, { json: { subject_name: subject[studentId] } }),
    onSuccess: async () => {
      setSubject({});
      await refresh();
    },
  });
  const curriculumName = (curriculumId: string | null) => curricula.data?.find((c) => c.id === curriculumId)?.name ?? "Curriculum not set";
  return (
    <Card title="Students">
      {(students.data ?? []).length === 0 ? <Empty>No students yet.</Empty> : null}
      <ul className="divide-y divide-border">
        {(students.data ?? []).map((s) => (
          <li key={s.id} className="py-2 text-sm">
            <p className="font-medium">
              {s.preferred_name || s.first_name} {s.last_name ?? ""}{" "}
              <span className="font-normal text-muted">
                · {curriculumName(s.curriculum_id)} · {s.grade_text ?? "Grade not set"}
              </span>
            </p>
            <p className="text-muted">
              Subjects: {s.subjects.length ? s.subjects.map((x) => x.subject_name).join(", ") : "none yet"}
              {s.learning_needs_restricted ? " · Learning-needs note (restricted)" : ""}
            </p>
            {can(me, "crm.students.manage") ? (
              <div className="mt-1 flex gap-2">
                <Input
                  className="min-w-0 flex-1"
                  aria-label={`Add subject for ${s.first_name}`}
                  placeholder="Add subject"
                  value={subject[s.id] ?? ""}
                  onChange={(e) => setSubject({ ...subject, [s.id]: e.target.value })}
                />
                <Button variant="secondary" disabled={!subject[s.id]} onClick={() => addSubject.mutate(s.id)}>
                  Add
                </Button>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
      <ErrorNote error={add.error ?? addSubject.error} />
      {can(me, "crm.students.manage") ? (
        <form
          className="mt-3 grid gap-2 sm:grid-cols-4"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate();
          }}
        >
          <Input aria-label="Student first name" placeholder="First name" required value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
          <Select aria-label="Curriculum" value={form.curriculum_code} onChange={(e) => setForm({ ...form, curriculum_code: e.target.value })}>
            <option value="">Curriculum…</option>
            {(curricula.data ?? []).map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </Select>
          <Input aria-label="Grade" placeholder="Grade / year" value={form.grade_text} onChange={(e) => setForm({ ...form, grade_text: e.target.value })} />
          <Button type="submit" variant="secondary">Add student</Button>
        </form>
      ) : null}
    </Card>
  );
}

function Opportunities({ accountId }: { accountId: string }) {
  const stages = useStages();
  const currencies = useCurrencies();
  const opportunities = useQuery({
    queryKey: ["opportunities", "account", accountId],
    queryFn: () => api<Schemas["OpportunityOut"][]>(`/pipeline/opportunities${qs({ account_id: accountId })}`),
  });
  const minorUnits = (code: string) => currencies.data?.find((c) => c.code === code)?.minor_units ?? 2;
  return (
    <Card title="Opportunities" actions={<Link href="/pipeline" className="text-sm text-accent">Pipeline</Link>}>
      {(opportunities.data ?? []).length === 0 ? <Empty>No opportunities.</Empty> : null}
      <ul className="divide-y divide-border text-sm">
        {(opportunities.data ?? []).map((o) => (
          <li key={o.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span>{o.title}</span>
            <span className="flex items-center gap-2">
              {o.budget_amount_minor !== null && o.budget_currency ? (
                <span className="tabular text-muted">Budget {formatMoney(o.budget_amount_minor, o.budget_currency, minorUnits(o.budget_currency))}</span>
              ) : null}
              <Badge tone={o.stage_type === "lost" ? "danger" : o.stage_type === "won" ? "success" : "accent"}>
                {stages.data?.find((s) => s.key === o.stage_key)?.name ?? o.stage_key}
              </Badge>
              {o.sla_breached ? <Badge tone="warning">Past SLA</Badge> : null}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Notes({ accountId }: { accountId: string }) {
  const queryClient = useQueryClient();
  const { data: me } = useMe();
  const notes = useQuery({ queryKey: ["notes", accountId], queryFn: () => api<Schemas["NoteOut"][]>(`/crm/accounts/${accountId}/notes`) });
  const [body, setBody] = useState("");
  const [visibility, setVisibility] = useState<"team" | "private">("team");
  const add = useMutation({
    mutationFn: () => api(`/crm/accounts/${accountId}/notes`, { json: { body, visibility } }),
    onSuccess: async () => {
      setBody("");
      await queryClient.invalidateQueries({ queryKey: ["notes", accountId] });
    },
  });
  return (
    <Card title="Notes">
      {can(me, "crm.notes.write") ? (
        <form
          className="mb-3 space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate();
          }}
        >
          <Textarea aria-label="New note" placeholder="Add a note (notes cannot be edited later)" value={body} onChange={(e) => setBody(e.target.value)} />
          <div className="flex items-center gap-2">
            <Select aria-label="Note visibility" value={visibility} onChange={(e) => setVisibility(e.target.value as "team" | "private")}>
              <option value="team">Visible to the team</option>
              <option value="private">Private (only me)</option>
            </Select>
            <Button type="submit" disabled={!body.trim() || add.isPending}>Add note</Button>
          </div>
          <ErrorNote error={add.error} />
        </form>
      ) : null}
      {(notes.data ?? []).length === 0 ? <Empty>No notes.</Empty> : null}
      <ul className="space-y-3">
        {(notes.data ?? []).map((n) => (
          <li key={n.id} className="rounded-md bg-surface p-3 text-sm">
            <p className="whitespace-pre-wrap">{n.body}</p>
            <p className="mt-1 text-xs text-muted">
              {formatDateTime(n.created_at, me?.timezone)} {n.visibility === "private" ? "· Private" : ""}
            </p>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Tasks({ accountId }: { accountId: string }) {
  const queryClient = useQueryClient();
  const { data: me } = useMe();
  const tasks = useQuery({
    queryKey: ["tasks", "account", accountId],
    queryFn: () => api<Schemas["TaskOut"][]>(`/tasks${qs({ assignee: "any", status: "open", account_id: accountId })}`),
    enabled: can(me, "crm.tasks.manage"),
  });
  const [title, setTitle] = useState("");
  const add = useMutation({
    mutationFn: () => api("/tasks", { json: { title, account_id: accountId } }),
    onSuccess: async () => {
      setTitle("");
      await queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
  if (!can(me, "crm.tasks.manage")) return null;
  return (
    <Card title="Open tasks">
      <form
        className="mb-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate();
        }}
      >
        <Input aria-label="New task" placeholder="New task" className="min-w-0 flex-1" value={title} onChange={(e) => setTitle(e.target.value)} />
        <Button type="submit" variant="secondary" disabled={!title.trim()}>Add</Button>
      </form>
      <ErrorNote error={add.error} />
      {(tasks.data ?? []).length === 0 ? <Empty>No open tasks.</Empty> : null}
      <ul className="space-y-1 text-sm">
        {(tasks.data ?? []).map((t) => (
          <li key={t.id} className="flex justify-between gap-2">
            <span>{t.title}</span>
            <span className="text-xs text-muted">{t.due_at ? formatDateTime(t.due_at, me?.timezone) : "No due date"}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Tags({ accountId }: { accountId: string }) {
  const queryClient = useQueryClient();
  const { data: me } = useMe();
  const all = useQuery({ queryKey: ["tags"], queryFn: () => api<Schemas["TagOut"][]>("/crm/tags") });
  const mine = useQuery({ queryKey: ["tags", accountId], queryFn: () => api<Schemas["TagOut"][]>(`/crm/accounts/${accountId}/tags`) });
  const [choice, setChoice] = useState("");
  const apply = useMutation({
    mutationFn: () => api(`/crm/accounts/${accountId}/tags/${choice}`, { method: "PUT" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tags", accountId] }),
  });
  return (
    <Card title="Tags">
      <div className="mb-2 flex flex-wrap gap-1">
        {(mine.data ?? []).length === 0 ? <span className="text-sm text-muted">No tags</span> : null}
        {(mine.data ?? []).map((t) => (
          <Badge key={t.id} tone="primary">{t.name}</Badge>
        ))}
      </div>
      {can(me, "crm.accounts.update") && (all.data ?? []).length > 0 ? (
        <div className="flex gap-2">
          <Select aria-label="Tag" value={choice} onChange={(e) => setChoice(e.target.value)}>
            <option value="">Add tag…</option>
            {(all.data ?? []).map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </Select>
          <Button variant="secondary" disabled={!choice} onClick={() => apply.mutate()}>Apply</Button>
        </div>
      ) : null}
    </Card>
  );
}

function Timeline({ accountId, timezone }: { accountId: string; timezone?: string }) {
  const timeline = useQuery({
    queryKey: ["timeline", accountId],
    queryFn: () => api<Schemas["ActivityOut"][]>(`/crm/accounts/${accountId}/timeline`),
    refetchInterval: 15_000,
  });
  return (
    <Card title="Timeline">
      <p className="mb-2 text-xs text-muted">Updated by the background worker, usually within seconds.</p>
      {(timeline.data ?? []).length === 0 ? <Empty>Nothing yet.</Empty> : null}
      <ol className="space-y-3">
        {(timeline.data ?? []).map((a) => (
          <li key={a.id} className="border-l-2 border-primary-soft pl-3 text-sm">
            <p className="font-medium">{a.title}</p>
            {a.body ? <p className="text-muted">{a.body}</p> : null}
            <p className="text-xs text-muted">{formatDateTime(a.occurred_at, timezone)}</p>
          </li>
        ))}
      </ol>
    </Card>
  );
}

function Pricing({ accountId, marketConfirmed }: { accountId: string; marketConfirmed: boolean }) {
  const { data: me } = useMe();
  const queryClient = useQueryClient();
  const tiers = useQuery({
    queryKey: ["pricing-tiers", accountId],
    queryFn: () => api<Schemas["TierChoicesOut"]>(`/accounts/${accountId}/pricing/tiers`),
  });
  const [showOptions, setShowOptions] = useState(false);
  const options = useQuery({
    queryKey: ["pricing-options", accountId],
    queryFn: () => api<Schemas["OptionsOut"]>(`/accounts/${accountId}/pricing/options`),
    enabled: showOptions,
    retry: false,
  });
  const [choosing, setChoosing] = useState<Schemas["TierChoiceOut"] | null>(null);
  const [bookId, setBookId] = useState("");
  const [reason, setReason] = useState("");
  const select = useMutation({
    mutationFn: () => api(`/accounts/${accountId}/pricing/tiers`, { json: { price_book_id: bookId, reason } }),
    onSuccess: () => {
      setChoosing(null);
      setReason("");
      void queryClient.invalidateQueries({ queryKey: ["pricing-tiers", accountId] });
      void queryClient.invalidateQueries({ queryKey: ["pricing-options", accountId] });
    },
  });
  const refusal = options.error instanceof ApiError ? options.error : null;

  return (
    <Card title="Pricing">
      {!marketConfirmed ? (
        <p className="text-sm text-muted">Confirm the pricing market first. Currency, phone number and curriculum never decide it.</p>
      ) : null}
      {tiers.data?.choices.map((choice) => (
        <div key={choice.plan_type} className="mb-3 text-sm">
          <p className="font-medium">{humanize(choice.plan_type)} tier / schedule</p>
          {choice.current ? (
            <p>
              <Badge tone="accent">{choice.current.tier_label ?? choice.current.price_book_code}</Badge>{" "}
              <span className="text-muted">chosen {formatDateTime(choice.current.selected_at, me?.timezone)}: {choice.current.reason}</span>
            </p>
          ) : (
            <p className="text-warning">Not chosen yet: a person decides which applies to this customer.</p>
          )}
          {can(me, "pricing.tier.select") ? (
            <Button
              variant="ghost"
              onClick={() => {
                setChoosing(choice);
                setBookId(choice.current?.price_book_id ?? "");
              }}
            >
              {choice.current ? "Change" : "Choose"}
            </Button>
          ) : null}
        </div>
      ))}
      {marketConfirmed && can(me, "pricing.options.read") ? (
        <div className="space-y-2">
          <Button variant="secondary" onClick={() => setShowOptions(true)}>
            Show package options
          </Button>
          {options.isFetching ? <Loading /> : null}
          {refusal ? (
            <div role="status" className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-warning">
              <p className="font-medium">No figures can be offered: {refusal.detail}</p>
              <p className="mt-1 text-xs">Tell the customer: &ldquo;{String(refusal.body.customer_safe_message ?? "")}&rdquo;</p>
              <p className="mt-1 text-xs opacity-75">Code: {refusal.code}</p>
            </div>
          ) : (
            <ErrorNote error={options.error} />
          )}
          {options.data ? (
            <ul className="space-y-1 text-sm" aria-label="Package options">
              {options.data.options.map((o) => (
                <li key={o.option_ref}>
                  <div className="flex justify-between gap-2">
                    <span>
                      {o.display_name} {o.is_special ? <Badge tone="accent">Special (confidential)</Badge> : null}
                    </span>
                    <span className="tabular font-medium">{o.package_total_display}</span>
                  </div>
                  {o.promotions.map((p) => (
                    <div key={p.code} className="ml-3 text-xs text-success">
                      Promotion {p.code}: {p.promotional_total_display ?? `${p.bonus_units} bonus hour(s)`} until{" "}
                      {formatDateTime(p.ends_at, me?.timezone)} (separate from the list price)
                    </div>
                  ))}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      {marketConfirmed && can(me, "pricing.special.view") ? <SpecialPricing accountId={accountId} /> : null}
      <Modal open={choosing !== null} title="Choose the tier for this customer" onClose={() => setChoosing(null)}>
        {choosing ? (
          <form
            className="flex flex-col gap-4"
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              select.mutate();
            }}
          >
            <p className="text-sm text-muted">
              Both options are valid in this market. Mixt has not set a rule for choosing (Q-PRC-02), so a person decides. Never mention the
              other option to the customer.
            </p>
            <Field label="Tier / schedule">
              {(fid) => (
                <Select id={fid} value={bookId} onChange={(e) => setBookId(e.target.value)} required>
                  <option value="">Choose…</option>
                  {choosing.books.map((b) => (
                    <option key={b.price_book_id} value={b.price_book_id}>
                      {b.tier_label ?? b.code}
                      {b.has_active_pricing ? "" : " (no active pricing yet)"}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Why this applies to this customer">
              {(fid) => <Textarea id={fid} value={reason} onChange={(e) => setReason(e.target.value)} required />}
            </Field>
            <ErrorNote error={select.error} />
            <Button type="submit" disabled={select.isPending}>
              Save choice
            </Button>
          </form>
        ) : null}
      </Modal>
    </Card>
  );
}

function SpecialPricing({ accountId }: { accountId: string }) {
  const { data: me } = useMe();
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: ["pricing-special", accountId],
    queryFn: () => api<Schemas["SpecialOut"][]>(`/accounts/${accountId}/pricing/special`),
  });
  const [requesting, setRequesting] = useState(false);
  const books = useQuery({
    queryKey: ["pricing-special-books", accountId],
    queryFn: () => api<Schemas["SpecialBookOut"][]>(`/accounts/${accountId}/pricing/special/books`),
    enabled: requesting,
  });
  const [bookId, setBookId] = useState("");
  const [reason, setReason] = useState("");
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["pricing-special", accountId] });
    void queryClient.invalidateQueries({ queryKey: ["pricing-options", accountId] });
  };
  const request = useMutation({
    mutationFn: () => api(`/accounts/${accountId}/pricing/special`, { json: { price_book_id: bookId, reason } }),
    onSuccess: () => {
      setRequesting(false);
      refresh();
    },
  });
  const act = useMutation({
    mutationFn: ({ id, path, json }: { id: string; path: string; json?: unknown }) => api(`/pricing/special/${id}/${path}`, { method: "POST", json }),
    onSuccess: refresh,
  });
  return (
    <div className="mt-4 border-t border-border pt-3 text-sm">
      <p className="font-medium">Confidential pricing</p>
      {list.data?.length === 0 ? <p className="text-muted">None.</p> : null}
      <ul className="space-y-2">
        {list.data?.map((s) => (
          <li key={s.id}>
            {s.price_book_code} <Badge tone={s.status === "active" ? "success" : "neutral"}>{humanize(s.status)}</Badge>
            <div className="text-xs text-muted">{s.reason}</div>
            {s.status === "pending_approval" && can(me, "pricing.special.approve") ? (
              <span className="space-x-2">
                <Button variant="ghost" onClick={() => act.mutate({ id: s.id, path: "approve" })}>
                  Approve
                </Button>
                <Button variant="ghost" onClick={() => act.mutate({ id: s.id, path: "reject", json: { reason: "Not approved" } })}>
                  Reject
                </Button>
              </span>
            ) : null}
            {s.status === "active" && can(me, "pricing.special.approve") ? (
              <Button variant="ghost" onClick={() => act.mutate({ id: s.id, path: "revoke", json: { reason: "Withdrawn" } })}>
                Revoke
              </Button>
            ) : null}
          </li>
        ))}
      </ul>
      <ErrorNote error={act.error} />
      {can(me, "pricing.special.request") ? (
        <Button variant="ghost" onClick={() => setRequesting(true)}>
          Request special pricing
        </Button>
      ) : null}
      <Modal open={requesting} title="Request special pricing" onClose={() => setRequesting(false)}>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            request.mutate();
          }}
        >
          <p className="text-sm text-muted">
            Only restricted price books confirmed for this customer&apos;s market can be used. Someone else must approve it, and it stays
            confidential to this customer.
          </p>
          <Field label="Price book">
            {(fid) => (
              <Select id={fid} value={bookId} onChange={(e) => setBookId(e.target.value)} required>
                <option value="">{books.data?.length === 0 ? "No restricted price books for this market" : "Choose…"}</option>
                {books.data?.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.code}: {b.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Why this customer">{(fid) => <Textarea id={fid} value={reason} onChange={(e) => setReason(e.target.value)} required />}</Field>
          <ErrorNote error={request.error} />
          <Button type="submit" disabled={request.isPending}>
            Request
          </Button>
        </form>
      </Modal>
    </div>
  );
}

function Quotations({ accountId }: { accountId: string }) {
  const { data: me } = useMe();
  const list = useQuery({
    queryKey: ["quotations", accountId],
    queryFn: () => api<Schemas["QuotationSummaryOut"][]>(`/accounts/${accountId}/quotations`),
  });
  const opportunities = useQuery({
    queryKey: ["opportunities", "account", accountId],
    queryFn: () => api<Schemas["OpportunityOut"][]>(`/pipeline/opportunities${qs({ account_id: accountId })}`),
  });
  const [creating, setCreating] = useState(false);
  const [opportunityId, setOpportunityId] = useState("");
  const create = useMutation({
    mutationFn: () => api<Schemas["QuotationOut"]>("/quotations", { json: { account_id: accountId, opportunity_id: opportunityId } }),
    onSuccess: (q) => window.location.assign(`/quotations/${q.id}`),
  });
  return (
    <Card
      title="Quotations"
      actions={
        can(me, "quotations.manage") ? (
          <Button variant="ghost" onClick={() => setCreating(true)}>
            New quotation
          </Button>
        ) : null
      }
    >
      {(list.data ?? []).length === 0 ? <Empty>No quotations.</Empty> : null}
      <ul className="divide-y divide-border text-sm">
        {(list.data ?? []).map((q) => (
          <li key={q.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <Link href={`/quotations/${q.id}`} className="text-accent">
              {q.quote_number} rev {q.revision_no}
            </Link>
            <span className="flex items-center gap-2">
              <span className="tabular">{q.total_display ?? ""}</span>
              <Badge tone={q.status === "accepted" ? "success" : q.status === "issued" ? "accent" : "neutral"}>{humanize(q.status)}</Badge>
            </span>
          </li>
        ))}
      </ul>
      <Modal open={creating} title="New quotation" onClose={() => setCreating(false)}>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <Field label="For opportunity">
            {(fid) => (
              <Select id={fid} value={opportunityId} onChange={(e) => setOpportunityId(e.target.value)} required>
                <option value="">Choose…</option>
                {opportunities.data?.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.title}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <ErrorNote error={create.error} />
          <Button type="submit" disabled={create.isPending}>
            Create draft
          </Button>
        </form>
      </Modal>
    </Card>
  );
}

function Conversations({ accountId }: { accountId: string }) {
  const { data: me } = useMe();
  const list = useQuery({
    queryKey: ["inbox", "account", accountId],
    queryFn: () => api<Schemas["ConversationOut"][]>(`/crm/accounts/${accountId}/conversations`),
  });
  return (
    <Card title="Conversations" actions={<Link href="/inbox" className="text-sm text-accent">Inbox</Link>}>
      {list.isLoading ? <Loading /> : null}
      <ErrorNote error={list.error} />
      {(list.data ?? []).length === 0 && !list.isLoading ? <Empty>No conversations linked to this household.</Empty> : null}
      <ul className="divide-y divide-border">
        {(list.data ?? []).map((c) => (
          <li key={c.id} className="flex items-center justify-between gap-2 py-2 text-sm">
            <Link href={`/inbox?c=${c.id}`} className="text-accent">
              {channelLabel(c.channel)} · {c.contact_name ?? c.customer_name ?? c.customer_handle}
            </Link>
            <span className="flex items-center gap-2 text-xs text-muted">
              {c.unread_count > 0 ? <Badge tone="primary">{c.unread_count} unread</Badge> : null}
              {formatDateTime(c.last_activity_at, me?.timezone)}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

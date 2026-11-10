"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Badge, Button, Empty, ErrorNote, Field, Input, Loading, Modal, PageHeader, Select, Table, Td, Textarea } from "@/components/ui";
import { api, qs, type Schemas } from "@/lib/api";
import { formatDateTime, humanize } from "@/lib/format";
import { useCurricula } from "@/lib/queries";
import { can, useMe } from "@/lib/session";

const STATUSES = ["", "new_account", "matched", "out_of_market", "spam", "rejected"];

const statusTone = (status: string) =>
  status === "out_of_market" ? "warning" : status === "spam" || status === "rejected" ? "danger" : status === "matched" ? "accent" : "success";

export default function LeadsPage() {
  const { data: me } = useMe();
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState(false);
  const leads = useQuery({
    queryKey: ["leads", status],
    queryFn: () => api<Schemas["LeadOut"][]>(`/leads${qs({ status, limit: 100 })}`),
  });

  return (
    <>
      <PageHeader
        title="Leads"
        description="Every enquiry is kept as received. New enquiries create a household and an opportunity; repeat enquiries link to the existing household."
        actions={
          <>
            {can(me, "leads.import") ? (
              <Link href="/leads/import" className="rounded-md border border-border px-3 py-2 text-sm">
                Import spreadsheet
              </Link>
            ) : null}
            {can(me, "leads.create") ? <Button onClick={() => setOpen(true)}>New lead</Button> : null}
          </>
        }
      />
      <div className="mb-4 flex items-end gap-3">
        <Field label="Status">
          {(id) => (
            <Select id={id} value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s ? humanize(s) : "All"}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      {leads.isLoading ? <Loading /> : null}
      <ErrorNote error={leads.error} />
      {leads.data && leads.data.length === 0 ? <Empty>No leads match.</Empty> : null}
      {leads.data && leads.data.length > 0 ? (
        <Table label="Leads" head={["Name", "Country", "Status", "Household", "Received"]}>
          {leads.data.map((lead) => (
            <tr key={lead.id}>
              <Td>{lead.submitted_name ?? "—"}</Td>
              <Td>{lead.submitted_country ?? "—"}</Td>
              <Td>
                <Badge tone={statusTone(lead.status)}>{humanize(lead.status)}</Badge>
                {lead.status_reason ? <p className="mt-1 text-xs text-muted">{lead.status_reason}</p> : null}
              </Td>
              <Td>
                {lead.account_id ? (
                  <Link href={`/customers/${lead.account_id}`} className="text-accent hover:underline">
                    Open household
                  </Link>
                ) : lead.linked_to_hidden_household ? (
                  <span className="text-xs text-muted">Linked to a household owned by a colleague (they were notified)</span>
                ) : (
                  "—"
                )}
              </Td>
              <Td className="whitespace-nowrap">{formatDateTime(lead.received_at, me?.timezone)}</Td>
            </tr>
          ))}
        </Table>
      ) : null}
      <Modal open={open} title="New lead" onClose={() => setOpen(false)}>
        <NewLeadForm onDone={() => setOpen(false)} />
      </Modal>
    </>
  );
}

function NewLeadForm({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const curricula = useCurricula();
  const sources = useQuery({ queryKey: ["lead-sources"], queryFn: () => api<Schemas["SourceOut"][]>("/leads/sources") });
  const [form, setForm] = useState({
    source: "manual", guardian_first_name: "", guardian_last_name: "", email: "", phone: "", country: "",
    student_first_name: "", student_curriculum: "", student_grade: "", message: "",
  });
  const [result, setResult] = useState<Schemas["IntakeOut"] | null>(null);
  const mutation = useMutation({
    mutationFn: () => {
      const body = Object.fromEntries(Object.entries(form).filter(([, v]) => v !== ""));
      return api<Schemas["IntakeOut"]>("/leads", { json: body });
    },
    onSuccess: async (data) => {
      setResult(data);
      await queryClient.invalidateQueries({ queryKey: ["leads"] });
    },
  });
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  if (result) {
    return (
      <div className="space-y-3 text-sm">
        <p>
          Lead saved as <Badge tone={statusTone(result.status)}>{humanize(result.status)}</Badge>
        </p>
        {result.status === "out_of_market" ? <p className="text-warning">This country is not one of Mixt&apos;s markets. A manager will review it; no opportunity was created.</p> : null}
        {result.duplicate_candidates > 0 ? <p>A household with a similar name exists; a manager can review possible duplicates.</p> : null}
        <div className="flex gap-2">
          {result.account_id ? (
            <Link href={`/customers/${result.account_id}`} className="rounded-md bg-primary px-3 py-2 text-white">
              Open household
            </Link>
          ) : null}
          <Button variant="secondary" onClick={onDone}>
            Close
          </Button>
        </div>
      </div>
    );
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    mutation.mutate();
  }

  return (
    <form onSubmit={submit} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <Field label="Source">
        {(id) => (
          <Select id={id} value={form.source} onChange={set("source")}>
            {(sources.data ?? []).filter((s) => s.manual_entry_allowed).map((s) => (
              <option key={s.code} value={s.code}>
                {s.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label="Country (ISO code)" hint="Where the family lives, e.g. AE, GB, SA. Never sets pricing.">
        {(id) => <Input id={id} maxLength={2} value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value.toUpperCase() })} />}
      </Field>
      <Field label="Parent / guardian first name">{(id) => <Input id={id} required value={form.guardian_first_name} onChange={set("guardian_first_name")} />}</Field>
      <Field label="Last name">{(id) => <Input id={id} value={form.guardian_last_name} onChange={set("guardian_last_name")} />}</Field>
      <Field label="Phone / WhatsApp" hint="With country code, e.g. +971 50 123 4567">{(id) => <Input id={id} type="tel" value={form.phone} onChange={set("phone")} />}</Field>
      <Field label="Email">{(id) => <Input id={id} type="email" value={form.email} onChange={set("email")} />}</Field>
      <Field label="Student first name">{(id) => <Input id={id} value={form.student_first_name} onChange={set("student_first_name")} />}</Field>
      <Field label="Curriculum">
        {(id) => (
          <Select id={id} value={form.student_curriculum} onChange={set("student_curriculum")}>
            <option value="">Not known yet</option>
            {(curricula.data ?? []).map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label="Grade / year">{(id) => <Input id={id} value={form.student_grade} onChange={set("student_grade")} />}</Field>
      <div className="sm:col-span-2">
        <Field label="Message / notes from the enquiry">{(id) => <Textarea id={id} value={form.message} onChange={set("message")} />}</Field>
      </div>
      <div className="sm:col-span-2 space-y-3">
        <ErrorNote error={mutation.error} />
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Saving…" : "Save lead"}
        </Button>
      </div>
    </form>
  );
}

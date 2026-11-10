"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Badge, Button, Card, Empty, ErrorNote, Field, Input, Loading, Modal, PageHeader, Select, Table, Td, Textarea } from "@/components/ui";
import { api, type Schemas } from "@/lib/api";
import { formatDateTime, humanize } from "@/lib/format";
import { can, useMe } from "@/lib/session";

type Quote = Schemas["QuotationOut"];

export default function QuotationPage() {
  const { id } = useParams<{ id: string }>();
  const { data: me } = useMe();
  const queryClient = useQueryClient();
  const quote = useQuery({ queryKey: ["quotation", id], queryFn: () => api<Quote>(`/quotations/${id}`) });
  const refresh = (q?: Quote) => {
    if (q) queryClient.setQueryData(["quotation", id], q);
    void queryClient.invalidateQueries({ queryKey: ["quotation", id] });
    void queryClient.invalidateQueries({ queryKey: ["quotation-inbox"] });
  };
  const act = useMutation({
    mutationFn: ({ path, json, method }: { path: string; json?: unknown; method?: "POST" | "PATCH" | "DELETE" }) =>
      api<Quote>(`/quotations/${id}${path}`, { method: method ?? "POST", json }),
    onSuccess: (q) => refresh(q),
  });
  const [dialog, setDialog] = useState<null | "approve" | "sendBack" | "issue" | "outcome" | "cancel">(null);

  if (quote.isLoading) return <Loading />;
  if (quote.error || !quote.data) return <ErrorNote error={quote.error} />;
  const q = quote.data;
  const draft = q.status === "draft";

  return (
    <>
      <PageHeader
        title={`Quotation ${q.quote_number} rev ${q.revision_no}`}
        description={q.status_reason ?? undefined}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={q.status === "approved" || q.status === "accepted" ? "success" : q.status === "issued" ? "accent" : "warning"}>{humanize(q.status)}</Badge>
            <Link href={`/customers/${q.account_id}`} className="text-sm text-accent">
              Customer
            </Link>
          </div>
        }
      />
      <div className="grid gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          <Card title="Lines">
            {q.lines.length === 0 ? <Empty>No lines yet. Add a package below.</Empty> : null}
            {q.lines.length > 0 ? (
              <Table label="Quotation lines" head={["Package", "List price", "Promotion", "Discount", "Total", ""]}>
                {q.lines.map((line) => (
                  <tr key={line.id}>
                    <Td>
                      {line.display_name} {line.special_pricing ? <Badge tone="accent">Special</Badge> : null}
                      <div className="text-xs text-muted">
                        {line.price_book_code} v{line.price_book_version_no}
                        {line.tier_label ? ` · ${line.tier_label}` : ""}
                      </div>
                    </Td>
                    <Td className="tabular whitespace-nowrap">{line.list_total_display}</Td>
                    <Td className="text-xs">
                      {line.promotion_code ? `${line.promotion_code}${line.bonus_units ? ` (+${line.bonus_units} h)` : ` (−${(line.promotion_discount_minor / 100).toLocaleString("en-GB")})`}` : ""}
                    </Td>
                    <Td className="tabular">{line.discount_minor ? `−${(line.discount_minor / 100).toLocaleString("en-GB")}` : ""}</Td>
                    <Td className="tabular whitespace-nowrap font-medium">{line.final_total_display}</Td>
                    <Td>
                      {draft ? (
                        <Button variant="ghost" aria-label={`Remove ${line.display_name}`} onClick={() => act.mutate({ path: `/lines/${line.id}`, method: "DELETE" })}>
                          Remove
                        </Button>
                      ) : null}
                    </Td>
                  </tr>
                ))}
              </Table>
            ) : null}
            <p className="mt-3 text-right text-sm">
              Total: <span className="tabular text-base font-semibold">{q.total_display ?? "—"}</span>
            </p>
            {draft && can(me, "quotations.manage") ? <AddLine quote={q} onAdded={refresh} /> : null}
          </Card>
          {q.checks.length > 0 ? (
            <Card title="Before it can go further">
              <ul className="list-disc pl-5 text-sm text-warning" aria-label="Quotation checks">
                {q.checks.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </Card>
          ) : null}
        </div>
        <div className="space-y-6">
          <Card title="Details">
            {draft ? <DraftDetails quote={q} onSaved={refresh} /> : <FrozenDetails quote={q} />}
          </Card>
          <Card title="Approvals">
            <p className="text-sm text-muted">
              Needed: {q.needs.sales ? "sales approval" : ""}
              {q.needs.sales && q.needs.pricing ? " and " : ""}
              {q.needs.pricing ? "pricing approval (discount)" : ""}
              {!q.needs.sales && !q.needs.pricing ? "worked out when submitted" : ""}
            </p>
            <ul className="mt-2 space-y-1 text-sm">
              {q.approvals.map((a) => (
                <li key={`${a.capacity}-${a.decided_at}`}>
                  {humanize(a.capacity)} approval {formatDateTime(a.decided_at, me?.timezone)}
                </li>
              ))}
            </ul>
            {q.outstanding.length > 0 ? <p className="mt-2 text-sm text-warning">Waiting for: {q.outstanding.join(", ")}</p> : null}
          </Card>
          <Card title="Actions">
            <div className="flex flex-col gap-2">
              {draft && can(me, "quotations.manage") ? <Button onClick={() => act.mutate({ path: "/submit" })}>Submit for approval</Button> : null}
              {q.status === "pending_approval" && (can(me, "quotations.approve") || can(me, "quotations.approve_discount")) ? (
                <>
                  <Button onClick={() => setDialog("approve")}>Approve</Button>
                  <Button variant="secondary" onClick={() => setDialog("sendBack")}>
                    Send back
                  </Button>
                </>
              ) : null}
              {q.snapshot_hash ? (
                <a className="text-sm text-accent" href={`/api/v1/quotations/${q.id}/pdf`}>
                  Download PDF
                </a>
              ) : null}
              {q.status === "approved" && can(me, "quotations.manage") ? <Button onClick={() => setDialog("issue")}>Issue to the customer</Button> : null}
              {q.status === "issued" && can(me, "quotations.manage") ? <Button onClick={() => setDialog("outcome")}>Record the customer&apos;s answer</Button> : null}
              {["pending_approval", "approved", "issued", "expired"].includes(q.status) && can(me, "quotations.manage") ? (
                <Button
                  variant="secondary"
                  onClick={() =>
                    api<Schemas["RevisionOut"]>(`/quotations/${q.id}/revise`, { method: "POST" }).then((r) => {
                      window.location.assign(`/quotations/${r.quotation.id}`);
                    })
                  }
                >
                  Create a revision
                </Button>
              ) : null}
              {["draft", "pending_approval", "approved", "issued"].includes(q.status) && can(me, "quotations.manage") ? (
                <Button variant="ghost" onClick={() => setDialog("cancel")}>
                  Cancel quotation
                </Button>
              ) : null}
              <ErrorNote error={act.error} />
            </div>
          </Card>
        </div>
      </div>
      <Modal open={dialog === "approve"} title="Approve quotation" onClose={() => setDialog(null)}>
        <ApproveForm quote={q} canPricing={can(me, "quotations.approve_discount")} onDone={(r) => { setDialog(null); refresh(r); }} />
      </Modal>
      <Modal open={dialog === "sendBack"} title="Send back to the preparer" onClose={() => setDialog(null)}>
        <ReasonForm label="What needs to change" onSubmit={(reason) => act.mutateAsync({ path: "/send-back", json: { reason } }).then(() => setDialog(null))} />
      </Modal>
      <Modal open={dialog === "cancel"} title="Cancel quotation" onClose={() => setDialog(null)}>
        <ReasonForm label="Reason" onSubmit={(reason) => act.mutateAsync({ path: "/cancel", json: { reason } }).then(() => setDialog(null))} />
      </Modal>
      <Modal open={dialog === "issue"} title="Issue to the customer" onClose={() => setDialog(null)}>
        <IssueForm quote={q} onDone={(r) => { setDialog(null); refresh(r); }} />
      </Modal>
      <Modal open={dialog === "outcome"} title="Customer's answer" onClose={() => setDialog(null)}>
        <OutcomeForm quote={q} onDone={(r) => { setDialog(null); refresh(r); }} />
      </Modal>
    </>
  );
}

function AddLine({ quote, onAdded }: { quote: Quote; onAdded: (q: Quote) => void }) {
  const options = useQuery({
    queryKey: ["pricing-options", quote.account_id],
    queryFn: () => api<Schemas["OptionsOut"]>(`/accounts/${quote.account_id}/pricing/options`),
    retry: false,
  });
  const [entry, setEntry] = useState("");
  const [promotion, setPromotion] = useState("");
  const [discount, setDiscount] = useState("");
  const [optionIndex, setOptionIndex] = useState(-1);
  const add = useMutation({
    mutationFn: () =>
      api<Quote>(`/quotations/${quote.id}/lines`, {
        json: { entry_id: entry, promotion_code: promotion || null, discount_minor: discount ? Math.round(Number(discount) * 100) : 0 },
      }),
    onSuccess: (q) => {
      setEntry("");
      setPromotion("");
      setDiscount("");
      onAdded(q);
    },
  });
  const chosen = optionIndex >= 0 ? options.data?.options[optionIndex] : undefined;
  if (options.error) return <ErrorNote error={options.error} />;
  return (
    <form
      className="mt-4 grid gap-3 border-t border-border pt-4 sm:grid-cols-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        add.mutate();
      }}
    >
      <Field label="Package">
        {(fid) => (
          <Select
            id={fid}
            value={String(optionIndex)}
            onChange={(e) => {
              const i = Number(e.target.value);
              setOptionIndex(i);
              setPromotion("");
              setEntry(i >= 0 ? (options.data?.options[i]?.entry_id ?? "") : "");
            }}
            required
          >
            <option value="-1">Choose…</option>
            {options.data?.options.map((o, i) => (
              <option key={o.option_ref} value={i}>
                {o.display_name}: {o.package_total_display}
                {o.is_special ? " (special)" : ""}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label="Promotion">
        {(fid) => (
          <Select id={fid} value={promotion} onChange={(e) => setPromotion(e.target.value)} disabled={!chosen || chosen.promotions.length === 0}>
            <option value="">None</option>
            {chosen?.promotions.map((p) => (
              <option key={p.code} value={p.code}>
                {p.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label="Discount (amount)" hint="Needs approval">
        {(fid) => <Input id={fid} inputMode="decimal" value={discount} onChange={(e) => setDiscount(e.target.value)} placeholder="0" />}
      </Field>
      <div className="flex items-end">
        <Button type="submit" disabled={!entry || add.isPending}>
          Add line
        </Button>
      </div>
      <div className="sm:col-span-4">
        <ErrorNote error={add.error} />
      </div>
    </form>
  );
}

function DraftDetails({ quote, onSaved }: { quote: Quote; onSaved: (q: Quote) => void }) {
  const [validUntil, setValidUntil] = useState(quote.valid_until ?? "");
  const [customerNote, setCustomerNote] = useState(quote.customer_note ?? "");
  const [internalNote, setInternalNote] = useState(quote.internal_note ?? "");
  const [discountReason, setDiscountReason] = useState(quote.discount_reason ?? "");
  const save = useMutation({
    mutationFn: () =>
      api<Quote>(`/quotations/${quote.id}`, {
        method: "PATCH",
        json: { valid_until: validUntil || null, customer_note: customerNote, internal_note: internalNote, discount_reason: discountReason },
      }),
    onSuccess: onSaved,
  });
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <Field label="Valid until" hint="No standard validity yet (Q-PRC-13): set it per quotation">
        {(fid) => <Input id={fid} type="date" value={validUntil} onChange={(e) => setValidUntil(e.target.value)} />}
      </Field>
      <Field label="Note to the customer">{(fid) => <Textarea id={fid} value={customerNote} onChange={(e) => setCustomerNote(e.target.value)} />}</Field>
      <Field label="Internal note">{(fid) => <Textarea id={fid} value={internalNote} onChange={(e) => setInternalNote(e.target.value)} />}</Field>
      {quote.discount_total_minor > 0 ? (
        <Field label="Reason for the discount">{(fid) => <Textarea id={fid} value={discountReason} onChange={(e) => setDiscountReason(e.target.value)} />}</Field>
      ) : null}
      <ErrorNote error={save.error} />
      <Button type="submit" variant="secondary" disabled={save.isPending}>
        Save details
      </Button>
    </form>
  );
}

function FrozenDetails({ quote }: { quote: Quote }) {
  return (
    <dl className="space-y-2 text-sm">
      <div>
        <dt className="text-muted">Valid until</dt>
        <dd>{quote.valid_until ?? "not set"}</dd>
      </div>
      {quote.customer_note ? (
        <div>
          <dt className="text-muted">Note to the customer</dt>
          <dd>{quote.customer_note}</dd>
        </div>
      ) : null}
      {quote.discount_reason ? (
        <div>
          <dt className="text-muted">Discount reason</dt>
          <dd>{quote.discount_reason}</dd>
        </div>
      ) : null}
      {quote.snapshot_hash ? (
        <div>
          <dt className="text-muted">Frozen as</dt>
          <dd className="font-mono text-xs">{quote.snapshot_hash.slice(0, 16)}</dd>
        </div>
      ) : null}
      {quote.outcome_note ? (
        <div>
          <dt className="text-muted">Customer&apos;s answer</dt>
          <dd>{quote.outcome_note}</dd>
        </div>
      ) : null}
    </dl>
  );
}

function ApproveForm({ quote, canPricing, onDone }: { quote: Quote; canPricing: boolean; onDone: (q: Quote) => void }) {
  const [capacity, setCapacity] = useState(quote.outstanding.includes("sales") ? "sales" : "pricing");
  const [validUntil, setValidUntil] = useState(quote.valid_until ?? "");
  const approve = useMutation({
    mutationFn: () => api<Quote>(`/quotations/${quote.id}/approve`, { json: { capacity, valid_until: validUntil || null } }),
    onSuccess: onDone,
  });
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        approve.mutate();
      }}
    >
      <Field label="Approve as">
        {(fid) => (
          <Select id={fid} value={capacity} onChange={(e) => setCapacity(e.target.value)}>
            {quote.outstanding.includes("sales") ? <option value="sales">Sales approval</option> : null}
            {quote.outstanding.includes("pricing") && canPricing ? <option value="pricing">Pricing approval (discount)</option> : null}
          </Select>
        )}
      </Field>
      <Field label="Valid until">{(fid) => <Input id={fid} type="date" value={validUntil} onChange={(e) => setValidUntil(e.target.value)} />}</Field>
      <ErrorNote error={approve.error} />
      <Button type="submit" disabled={approve.isPending}>
        Approve
      </Button>
    </form>
  );
}

function IssueForm({ quote, onDone }: { quote: Quote; onDone: (q: Quote) => void }) {
  const contacts = useQuery({ queryKey: ["contacts", quote.account_id], queryFn: () => api<Schemas["ContactOut"][]>(`/crm/accounts/${quote.account_id}/contacts`) });
  const [contact, setContact] = useState("");
  const issue = useMutation({ mutationFn: () => api<Quote>(`/quotations/${quote.id}/issue`, { json: { contact_id: contact } }), onSuccess: onDone });
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        issue.mutate();
      }}
    >
      <p className="text-sm text-muted">Download the PDF and send it to the customer yourself; messaging channels arrive in Phase 3.</p>
      <Field label="Sent to">
        {(fid) => (
          <Select id={fid} value={contact} onChange={(e) => setContact(e.target.value)} required>
            <option value="">Choose…</option>
            {contacts.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {[c.first_name, c.last_name].filter(Boolean).join(" ")} ({humanize(c.role)})
              </option>
            ))}
          </Select>
        )}
      </Field>
      <ErrorNote error={issue.error} />
      <Button type="submit" disabled={issue.isPending}>
        Mark as issued
      </Button>
    </form>
  );
}

function OutcomeForm({ quote, onDone }: { quote: Quote; onDone: (q: Quote) => void }) {
  const [outcome, setOutcome] = useState("accepted");
  const [note, setNote] = useState("");
  const [reconfirmed, setReconfirmed] = useState(false);
  const record = useMutation({
    mutationFn: () => api<Quote>(`/quotations/${quote.id}/outcome`, { json: { outcome, note, price_change_reconfirmed: reconfirmed } }),
    onSuccess: onDone,
  });
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        record.mutate();
      }}
    >
      <Field label="Answer">
        {(fid) => (
          <Select id={fid} value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            <option value="accepted">Accepted</option>
            <option value="declined">Declined</option>
          </Select>
        )}
      </Field>
      <Field label="How did they answer?">{(fid) => <Textarea id={fid} value={note} onChange={(e) => setNote(e.target.value)} required />}</Field>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={reconfirmed} onChange={(e) => setReconfirmed(e.target.checked)} />
        The price changed after issue and I confirm we still honour this quotation
      </label>
      <ErrorNote error={record.error} />
      <Button type="submit" disabled={record.isPending}>
        Save
      </Button>
    </form>
  );
}

function ReasonForm({ label, onSubmit }: { label: string; onSubmit: (reason: string) => Promise<unknown> }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        setError(null);
        onSubmit(reason).catch(setError);
      }}
    >
      <Field label={label}>{(fid) => <Textarea id={fid} value={reason} onChange={(e) => setReason(e.target.value)} required />}</Field>
      <ErrorNote error={error} />
      <Button type="submit">Confirm</Button>
    </form>
  );
}

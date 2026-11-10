"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { PricingTabs } from "@/components/pricing";
import { Badge, Button, Empty, ErrorNote, Field, Input, Loading, Modal, PageHeader, Select, Table, Td, Textarea } from "@/components/ui";
import { api, type Schemas } from "@/lib/api";
import { formatDateTime, humanize } from "@/lib/format";
import { can, useMe } from "@/lib/session";

function describe(p: Schemas["PromotionOut"]): string {
  const v = p.value as Record<string, unknown>;
  if (p.kind === "percent_off") return `${String(v.percent)} % off`;
  if (p.kind === "amount_off") return `${String(v.currency)} ${(Number(v.amount_minor) / 100).toLocaleString("en-GB")} off`;
  return `${String(v.units)} bonus hour(s)`;
}

export default function PromotionsPage() {
  const { data: me } = useMe();
  const queryClient = useQueryClient();
  const promotions = useQuery({ queryKey: ["promotions"], queryFn: () => api<Schemas["PromotionOut"][]>("/pricing/promotions") });
  const [creating, setCreating] = useState(false);
  const [cancelling, setCancelling] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["promotions"] });
  const action = useMutation({
    mutationFn: ({ id, path }: { id: string; path: string }) => api(`/pricing/promotions/${id}/${path}`, { method: "POST" }),
    onSuccess: refresh,
  });
  const cancel = useMutation({
    mutationFn: () => api(`/pricing/promotions/${cancelling}/cancel`, { json: { reason } }),
    onSuccess: () => {
      setCancelling(null);
      refresh();
    },
  });

  return (
    <>
      <PageHeader
        title="Promotions"
        description="Offers are kept separate from standard prices: they never change a price book and are shown next to the list price. Every promotion ends on a fixed date."
        actions={can(me, "pricing.promotions.manage") ? <Button onClick={() => setCreating(true)}>New promotion</Button> : null}
      />
      <PricingTabs current="/pricing/promotions" permissions={me?.permissions ?? []} />
      <p role="note" className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-warning">
        Promotions cannot be switched on until Mixt confirms its first promotion (setting <code>promotions.enabled</code>, Q-PRC-05). Drafts can be
        prepared and approved meanwhile.
      </p>
      <ErrorNote error={promotions.error ?? action.error} />
      {promotions.isLoading ? <Loading /> : null}
      {promotions.data && promotions.data.length === 0 ? <Empty>No promotions.</Empty> : null}
      {promotions.data && promotions.data.length > 0 ? (
        <Table label="Promotions" head={["Promotion", "Offer", "Runs", "Status", ""]}>
          {promotions.data.map((p) => (
            <tr key={p.id}>
              <Td>
                <span className="font-medium">{p.code}</span>
                <div className="text-xs text-muted">{p.description}</div>
              </Td>
              <Td>{describe(p)}</Td>
              <Td className="whitespace-nowrap text-xs">
                {formatDateTime(p.starts_at, me?.timezone)}
                <br />
                to {formatDateTime(p.ends_at, me?.timezone)}
              </Td>
              <Td>
                <Badge tone={p.status === "active" ? "success" : p.status === "cancelled" || p.status === "expired" ? "neutral" : "warning"}>{humanize(p.status)}</Badge>
                {p.activation_problems.length > 0 ? (
                  <ul className="mt-1 list-disc pl-4 text-xs text-warning">
                    {p.activation_problems.map((m) => (
                      <li key={m}>{m}</li>
                    ))}
                  </ul>
                ) : null}
              </Td>
              <Td className="space-x-2 whitespace-nowrap">
                {p.status === "draft" && can(me, "pricing.promotions.manage") ? (
                  <Button variant="secondary" onClick={() => action.mutate({ id: p.id, path: "submit" })}>
                    Submit
                  </Button>
                ) : null}
                {p.status === "in_review" && can(me, "pricing.promotions.approve") ? (
                  <Button variant="secondary" onClick={() => action.mutate({ id: p.id, path: "approve" })}>
                    Approve
                  </Button>
                ) : null}
                {p.status === "approved" && can(me, "pricing.promotions.approve") ? (
                  <Button onClick={() => action.mutate({ id: p.id, path: "activate" })}>Activate</Button>
                ) : null}
                {!["expired", "cancelled"].includes(p.status) && can(me, "pricing.promotions.approve") ? (
                  <Button variant="ghost" onClick={() => setCancelling(p.id)}>
                    Cancel
                  </Button>
                ) : null}
              </Td>
            </tr>
          ))}
        </Table>
      ) : null}
      <Modal open={creating} title="New promotion" onClose={() => setCreating(false)}>
        <PromotionForm
          onDone={() => {
            setCreating(false);
            refresh();
          }}
        />
      </Modal>
      <Modal open={cancelling !== null} title="Cancel promotion" onClose={() => setCancelling(null)}>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            cancel.mutate();
          }}
        >
          <Field label="Reason">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} required />}</Field>
          <ErrorNote error={cancel.error} />
          <Button type="submit" variant="danger">
            Cancel promotion
          </Button>
        </form>
      </Modal>
    </>
  );
}

function PromotionForm({ onDone }: { onDone: () => void }) {
  const books = useQuery({ queryKey: ["pricing-books"], queryFn: () => api<Schemas["BookOut"][]>("/pricing/books") });
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [terms, setTerms] = useState("");
  const [kind, setKind] = useState("bonus_units");
  const [amount, setAmount] = useState("");
  const [versionId, setVersionId] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [ref, setRef] = useState("");
  const book = books.data?.find((b) => b.latest_version.id === versionId);
  const create = useMutation({
    mutationFn: () => {
      const value =
        kind === "percent_off"
          ? { percent: amount }
          : kind === "amount_off"
            ? { amount_minor: Math.round(Number(amount) * 100), currency: book?.currency_code }
            : { units: Number(amount) };
      return api("/pricing/promotions", {
        json: {
          code,
          name,
          description,
          terms: terms || null,
          kind,
          value,
          starts_at: new Date(startsAt).toISOString(),
          ends_at: new Date(endsAt).toISOString(),
          targets: [{ price_book_version_id: versionId }],
          decision_ref: ref || null,
        },
      });
    },
    onSuccess: onDone,
  });
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <Field label="Code">{(id) => <Input id={id} value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} required />}</Field>
      <Field label="Name">{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} required />}</Field>
      <Field label="Description customers see">{(id) => <Textarea id={id} value={description} onChange={(e) => setDescription(e.target.value)} required />}</Field>
      <Field label="Terms">{(id) => <Textarea id={id} value={terms} onChange={(e) => setTerms(e.target.value)} />}</Field>
      <Field label="Applies to (price book version)">
        {(id) => (
          <Select id={id} value={versionId} onChange={(e) => setVersionId(e.target.value)} required>
            <option value="">Choose…</option>
            {books.data?.map((b) => (
              <option key={b.latest_version.id} value={b.latest_version.id}>
                {b.code} v{b.latest_version.version_no} ({b.latest_version.status})
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label="Offer">
        {(id) => (
          <Select id={id} value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="bonus_units">Bonus hours</option>
            <option value="amount_off">Amount off</option>
            <option value="percent_off">Percentage off</option>
          </Select>
        )}
      </Field>
      <Field label={kind === "bonus_units" ? "Bonus hours" : kind === "amount_off" ? `Amount off${book ? ` (${book.currency_code})` : ""}` : "Percent off"}>
        {(id) => <Input id={id} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} required />}
      </Field>
      <Field label="Starts">{(id) => <Input id={id} type="datetime-local" value={startsAt} onChange={(e) => setStartsAt(e.target.value)} required />}</Field>
      <Field label="Ends (required)">{(id) => <Input id={id} type="datetime-local" value={endsAt} onChange={(e) => setEndsAt(e.target.value)} required />}</Field>
      <Field label="Decision-log reference" hint="Needed before approval (Q-PRC-05)">
        {(id) => <Input id={id} value={ref} onChange={(e) => setRef(e.target.value)} />}
      </Field>
      <ErrorNote error={create.error} />
      <Button type="submit" disabled={create.isPending}>
        Save draft
      </Button>
    </form>
  );
}

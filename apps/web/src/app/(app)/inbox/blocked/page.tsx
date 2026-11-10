"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Badge, Button, Card, Empty, ErrorNote, Field, Input, Loading, Modal, PageHeader, Select, Table, Td, Textarea } from "@/components/ui";
import { api, qs, type Schemas } from "@/lib/api";
import { formatDateTime, humanize } from "@/lib/format";
import { useMe } from "@/lib/session";

type Entry = Schemas["SuppressionOut"];

export default function BlockedNumbersPage() {
  const { data: me } = useMe();
  const queryClient = useQueryClient();
  const [showLifted, setShowLifted] = useState(false);
  const list = useQuery({
    queryKey: ["suppressions", showLifted],
    queryFn: () => api<Entry[]>(`/messaging/suppressions${qs({ include_lifted: showLifted })}`),
  });
  const [adding, setAdding] = useState(false);
  const [lifting, setLifting] = useState<Entry | null>(null);
  const done = () => void queryClient.invalidateQueries({ queryKey: ["suppressions"] });

  return (
    <>
      <PageHeader
        title="Blocked numbers"
        description="Nothing is sent to a number or address on this list. Customers add themselves by replying with an opt-out word (e.g. STOP); a manager can add one after a complaint or legal request, and lift a block when the customer asks, with a reason."
        actions={<Button onClick={() => setAdding(true)}>Block a number or address</Button>}
      />
      <Card
        title="Blocks"
        actions={
          <label className="flex items-center gap-2 text-sm text-muted">
            <input type="checkbox" checked={showLifted} onChange={(e) => setShowLifted(e.target.checked)} /> Show lifted
          </label>
        }
      >
        {list.isLoading ? <Loading /> : null}
        <ErrorNote error={list.error} />
        {list.data && list.data.length === 0 ? <Empty>No blocked numbers.</Empty> : null}
        {list.data && list.data.length > 0 ? (
          <Table label="Blocked numbers" head={["Number or address", "Reason", "Source", "Since", ""]}>
            {list.data.map((e) => (
              <tr key={e.id}>
                <Td className="tabular">{e.value_masked}</Td>
                <Td>
                  <Badge tone={e.lifted_at ? "neutral" : "danger"}>{humanize(e.reason)}</Badge>
                  {e.note ? <p className="mt-1 text-xs text-muted">{e.note}</p> : null}
                </Td>
                <Td>{humanize(e.source)}</Td>
                <Td>
                  {formatDateTime(e.created_at, me?.timezone)}
                  {e.lifted_at ? <p className="text-xs text-muted">Lifted {formatDateTime(e.lifted_at, me?.timezone)}: {e.lift_reason}</p> : null}
                </Td>
                <Td>
                  {!e.lifted_at ? (
                    <Button variant="ghost" onClick={() => setLifting(e)}>
                      Allow messages again
                    </Button>
                  ) : null}
                </Td>
              </tr>
            ))}
          </Table>
        ) : null}
      </Card>
      <Modal open={adding} title="Block a number or address" onClose={() => setAdding(false)}>
        <AddForm onDone={() => { setAdding(false); done(); }} />
      </Modal>
      <Modal open={!!lifting} title="Allow messages again" onClose={() => setLifting(null)}>
        {lifting ? <LiftForm entry={lifting} onDone={() => { setLifting(null); done(); }} /> : null}
      </Modal>
    </>
  );
}

function AddForm({ onDone }: { onDone: () => void }) {
  const [kind, setKind] = useState<"phone" | "email">("phone");
  const [value, setValue] = useState("");
  const [reason, setReason] = useState<"manual" | "complaint" | "legal">("manual");
  const [note, setNote] = useState("");
  const add = useMutation({
    mutationFn: () => api<Entry>("/messaging/suppressions", { json: { kind, value, reason, note } }),
    onSuccess: onDone,
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    add.mutate();
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label="Type">
        {(id) => (
          <Select id={id} value={kind} onChange={(e) => setKind(e.target.value as "phone" | "email")}>
            <option value="phone">Phone / WhatsApp number</option>
            <option value="email">Email address</option>
          </Select>
        )}
      </Field>
      <Field label={kind === "phone" ? "Number (with country code, e.g. +974...)" : "Email address"}>
        {(id) => <Input id={id} value={value} onChange={(e) => setValue(e.target.value)} required />}
      </Field>
      <Field label="Reason">
        {(id) => (
          <Select id={id} value={reason} onChange={(e) => setReason(e.target.value as "manual" | "complaint" | "legal")}>
            <option value="manual">Customer asked</option>
            <option value="complaint">Complaint</option>
            <option value="legal">Legal request</option>
          </Select>
        )}
      </Field>
      <Field label="Note">{(id) => <Textarea id={id} value={note} onChange={(e) => setNote(e.target.value)} required />}</Field>
      <ErrorNote error={add.error} />
      <Button type="submit" disabled={add.isPending}>
        Block
      </Button>
    </form>
  );
}

function LiftForm({ entry, onDone }: { entry: Entry; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const lift = useMutation({
    mutationFn: () => api<Entry>(`/messaging/suppressions/${entry.id}/lift`, { json: { reason } }),
    onSuccess: onDone,
  });
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        lift.mutate();
      }}
    >
      <p className="text-sm text-muted">
        {entry.value_masked} will receive messages again. Marketing still needs the customer&apos;s consent.
      </p>
      <Field label="Why?">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} required />}</Field>
      <ErrorNote error={lift.error} />
      <Button type="submit" disabled={lift.isPending}>
        Allow messages
      </Button>
    </form>
  );
}

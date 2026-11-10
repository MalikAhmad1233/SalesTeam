"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { PricingBanners, statusTone } from "@/components/pricing";
import { Badge, Button, Card, Empty, ErrorNote, Field, Input, Loading, Modal, PageHeader, Select, Table, Td, Textarea } from "@/components/ui";
import { api, type Schemas } from "@/lib/api";
import { formatDate, formatDateTime, humanize } from "@/lib/format";
import { useMarkets } from "@/lib/queries";
import { can, useMe } from "@/lib/session";

type Version = Schemas["VersionDetailOut"];

export default function PriceBookPage() {
  const { id } = useParams<{ id: string }>();
  const status = useQuery({ queryKey: ["pricing-status"], queryFn: () => api<Schemas["PricingStatusOut"]>("/pricing/status") });
  const book = useQuery({ queryKey: ["pricing-book", id], queryFn: () => api<Schemas["BookDetailOut"]>(`/pricing/books/${id}`) });
  const [selected, setSelected] = useState<string | null>(null);

  if (book.isLoading) return <Loading />;
  if (book.error || !book.data) return <ErrorNote error={book.error ?? new Error("not found")} />;
  const b = book.data;
  const versionId = selected ?? b.versions[b.versions.length - 1]?.id;

  return (
    <>
      <PageHeader
        title={b.code}
        description={`${b.name} · ${humanize(b.plan_type)} plan · priced per ${b.unit_type}`}
        actions={
          <Link href="/pricing" className="text-sm text-accent">
            All price books
          </Link>
        }
      />
      <PricingBanners status={status.data} />
      <div className="grid gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">{versionId ? <VersionPanel versionId={versionId} bookId={b.id} /> : null}</div>
        <div className="space-y-6">
          <Card title="History">
            <ol className="space-y-3">
              {[...b.versions].reverse().map((v) => (
                <li key={v.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(v.id)}
                    aria-pressed={v.id === versionId}
                    className={`w-full rounded-md border px-3 py-2 text-left text-sm ${v.id === versionId ? "border-accent bg-accent-soft" : "border-border"}`}
                  >
                    <span className="font-medium">Version {v.version_no}</span>{" "}
                    <Badge tone={statusTone(v.status)}>{humanize(v.status)}</Badge>
                    <div className="mt-1 text-xs text-muted">
                      {humanize(v.change_type)} · received {formatDate(v.source_received_on)}
                      {v.status_reason ? ` · ${v.status_reason}` : ""}
                    </div>
                  </button>
                </li>
              ))}
            </ol>
          </Card>
          <Markets book={b} />
        </div>
      </div>
    </>
  );
}

function useVersionAction(versionId: string, bookId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ path, json }: { path: string; json?: unknown }) => api<Version>(`/pricing/versions/${versionId}/${path}`, { method: "POST", json }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["pricing-version", versionId] });
      void queryClient.invalidateQueries({ queryKey: ["pricing-book", bookId] });
      void queryClient.invalidateQueries({ queryKey: ["pricing-books"] });
      void queryClient.invalidateQueries({ queryKey: ["pricing-status"] });
    },
  });
}

function VersionPanel({ versionId, bookId }: { versionId: string; bookId: string }) {
  const { data: me } = useMe();
  const version = useQuery({ queryKey: ["pricing-version", versionId], queryFn: () => api<Version>(`/pricing/versions/${versionId}`) });
  const action = useVersionAction(versionId, bookId);
  const [dialog, setDialog] = useState<null | "figures" | "tax" | "reason-return" | "reason-reject" | "reason-retire" | "correction">(null);

  if (version.isLoading) return <Loading />;
  if (version.error || !version.data) return <ErrorNote error={version.error} />;
  const v = version.data;
  const editable = v.status === "draft" || v.status === "in_review";

  return (
    <>
      <Card
        title={`Version ${v.version_no}: ${humanize(v.status)}`}
        actions={
          <div className="flex flex-wrap gap-2">
            {v.status === "draft" && can(me, "pricing.version.submit") ? (
              <Button variant="secondary" onClick={() => action.mutate({ path: "submit" })}>
                Submit for review
              </Button>
            ) : null}
            {v.status === "in_review" && can(me, "pricing.version.approve") ? (
              <>
                <Button onClick={() => action.mutate({ path: "approve" })}>Approve</Button>
                <Button variant="secondary" onClick={() => setDialog("reason-return")}>
                  Send back
                </Button>
                <Button variant="danger" onClick={() => setDialog("reason-reject")}>
                  Reject
                </Button>
              </>
            ) : null}
            {v.status === "approved" && can(me, "pricing.version.activate") ? (
              <Button onClick={() => action.mutate({ path: "activate" })}>Activate</Button>
            ) : null}
            {v.status === "active" && can(me, "pricing.version.activate") ? (
              <Button variant="danger" onClick={() => setDialog("reason-retire")}>
                Retire
              </Button>
            ) : null}
          </div>
        }
      >
        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-muted">Source</dt>
            <dd>
              {v.source_document} (received {formatDate(v.source_received_on)})
            </dd>
          </div>
          <div>
            <dt className="text-muted">Figures</dt>
            <dd>
              {v.figures_confirmation === "confirmed" ? `Confirmed by Mixt (${v.figures_confirmation_ref})` : "Supplied, not yet confirmed"}
              {v.figures_locked ? " · locked" : ""}
            </dd>
          </div>
          <div>
            <dt className="text-muted">Unit</dt>
            <dd>
              {v.unit_type}, {v.session_minutes_per_unit} minutes {v.unit_definition_ref ? `(${v.unit_definition_ref})` : ""}
            </dd>
          </div>
          <div>
            <dt className="text-muted">Tax treatment</dt>
            <dd>{v.tax_treatment === "unknown" ? "Unknown (Q-PAY-04)" : `${humanize(v.tax_treatment)} (${v.tax_treatment_ref})`}</dd>
          </div>
          {v.change_summary ? (
            <div className="sm:col-span-2">
              <dt className="text-muted">Change summary</dt>
              <dd>{v.change_summary}</dd>
            </div>
          ) : null}
          {v.effective_from ? (
            <div>
              <dt className="text-muted">Effective</dt>
              <dd>
                {formatDateTime(v.effective_from)} {v.effective_to ? `to ${formatDateTime(v.effective_to)}` : "onwards"}
              </dd>
            </div>
          ) : null}
        </dl>
        <ErrorNote error={action.error} />
        {editable ? (
          <div className="mt-4 flex flex-wrap gap-2">
            {can(me, "pricing.version.confirm_figures") && v.figures_confirmation !== "confirmed" ? (
              <Button variant="secondary" onClick={() => setDialog("figures")}>
                Record Mixt&apos;s confirmation of the figures
              </Button>
            ) : null}
            {can(me, "pricing.version.tax") ? (
              <Button variant="secondary" onClick={() => setDialog("tax")}>
                Record tax treatment
              </Button>
            ) : null}
          </div>
        ) : null}
        {can(me, "pricing.version.correct") && !["superseded", "retired", "rejected"].includes(v.status) ? (
          <div className="mt-2">
            <Button variant="ghost" onClick={() => setDialog("correction")}>
              Load corrected figures as a new version
            </Button>
          </div>
        ) : null}
      </Card>

      <Card title="Packages (as supplied)">
        <Table label="Packages" head={["Package", "Quantity", "Package total", "Effective rate (derived, information only)"]}>
          {v.entries.map((e) => (
            <tr key={e.id}>
              <Td>{e.display_name}</Td>
              <Td className="tabular whitespace-nowrap">
                {Number(e.quantity)} {v.unit_type === "class" ? "classes" : "hours"}
              </Td>
              <Td className="tabular whitespace-nowrap font-medium">{e.package_total_display}</Td>
              <Td className="tabular text-muted">{e.derived_unit_rate_display}</Td>
            </tr>
          ))}
        </Table>
      </Card>

      <Card title={`Activation checklist ${v.gate_passes ? "(all passed)" : ""}`}>
        <ul className="space-y-2" aria-label="Activation checklist">
          {v.gate.map((g) => (
            <li key={g.code} className="flex gap-3 text-sm">
              <span aria-hidden="true" className={g.ok ? "text-success" : "text-danger"}>
                {g.ok ? "✓" : "✕"}
              </span>
              <div>
                <span className="font-medium">
                  {g.code} {g.title}
                </span>
                <span className="sr-only">{g.ok ? " passed" : " not passed"}</span>
                <div className="text-muted">{g.detail}</div>
                {!g.ok && g.questions.length > 0 ? <div className="text-xs text-warning">Waiting for: {g.questions.join(", ")}</div> : null}
              </div>
            </li>
          ))}
        </ul>
      </Card>

      <Card title="Benefits attached to this version">
        {v.benefits.length === 0 ? (
          <Empty>None attached. No benefit may be promised with this price.</Empty>
        ) : (
          <ul className="space-y-2 text-sm">
            {v.benefits.map((benefit) => (
              <BenefitRow key={benefit.id} benefit={benefit} canApprove={editable && can(me, "pricing.benefits.approve")} versionId={versionId} />
            ))}
          </ul>
        )}
      </Card>

      <Modal open={dialog === "figures"} title="Mixt's confirmation of the figures" onClose={() => setDialog(null)}>
        <DecisionForm
          noteLabel="What Mixt confirmed"
          onSubmit={(decision_ref, note) => action.mutateAsync({ path: "confirm-figures", json: { decision_ref, note } }).then(() => setDialog(null))}
        />
      </Modal>
      <Modal open={dialog === "tax"} title="Tax treatment" onClose={() => setDialog(null)}>
        <TaxForm onSubmit={(treatment, decision_ref) => action.mutateAsync({ path: "tax", json: { treatment, decision_ref } }).then(() => setDialog(null))} />
      </Modal>
      {(["return", "reject", "retire"] as const).map((kind) => (
        <Modal key={kind} open={dialog === `reason-${kind}`} title={{ return: "Send back for changes", reject: "Reject this version", retire: "Retire this version" }[kind]} onClose={() => setDialog(null)}>
          <ReasonForm onSubmit={(reason) => action.mutateAsync({ path: kind, json: { reason } }).then(() => setDialog(null))} />
        </Modal>
      ))}
      <Modal open={dialog === "correction"} title="Load corrected figures" onClose={() => setDialog(null)}>
        <CorrectionForm version={v} bookId={bookId} onDone={() => setDialog(null)} />
      </Modal>
    </>
  );
}

function BenefitRow({ benefit, canApprove, versionId }: { benefit: Schemas["BenefitOut"]; canApprove: boolean; versionId: string }) {
  const queryClient = useQueryClient();
  const approve = useMutation({
    mutationFn: () => api(`/pricing/benefits/${benefit.id}/approve`, { method: "POST" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["pricing-version", versionId] }),
  });
  return (
    <li className="flex items-center justify-between gap-3">
      <span>
        {benefit.customer_facing_text} <Badge tone={benefit.status === "approved" ? "success" : "warning"}>{humanize(benefit.status)}</Badge>
      </span>
      {canApprove && benefit.status !== "approved" ? (
        <Button variant="ghost" onClick={() => approve.mutate()}>
          Approve
        </Button>
      ) : null}
    </li>
  );
}

function useFormRunner() {
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function run(task: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await task();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return { error, busy, run };
}

function DecisionForm({ noteLabel, onSubmit }: { noteLabel: string; onSubmit: (ref: string, note: string) => Promise<unknown> }) {
  const [ref, setRef] = useState("");
  const [note, setNote] = useState("");
  const { error, busy, run } = useFormRunner();
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        void run(() => onSubmit(ref, note));
      }}
    >
      <p className="text-sm text-muted">Record Mixt&apos;s decision in the decision log first; then enter its reference here.</p>
      <Field label="Decision-log reference" hint="For example BD-034">
        {(id) => <Input id={id} value={ref} onChange={(e) => setRef(e.target.value)} required />}
      </Field>
      <Field label={noteLabel}>{(id) => <Textarea id={id} value={note} onChange={(e) => setNote(e.target.value)} required />}</Field>
      <ErrorNote error={error} />
      <Button type="submit" disabled={busy}>
        Save
      </Button>
    </form>
  );
}

function TaxForm({ onSubmit }: { onSubmit: (treatment: string, ref: string) => Promise<unknown> }) {
  const [treatment, setTreatment] = useState("inclusive");
  const [ref, setRef] = useState("");
  const { error, busy, run } = useFormRunner();
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        void run(() => onSubmit(treatment, ref));
      }}
    >
      <Field label="Tax treatment">
        {(id) => (
          <Select id={id} value={treatment} onChange={(e) => setTreatment(e.target.value)}>
            <option value="inclusive">Prices include tax</option>
            <option value="exclusive">Tax is added to prices</option>
            <option value="not_applicable">No tax applies</option>
          </Select>
        )}
      </Field>
      <Field label="Decision-log reference" hint="For example BD-034 (Q-PAY-04)">
        {(id) => <Input id={id} value={ref} onChange={(e) => setRef(e.target.value)} required />}
      </Field>
      <ErrorNote error={error} />
      <Button type="submit" disabled={busy}>
        Save
      </Button>
    </form>
  );
}

function ReasonForm({ onSubmit }: { onSubmit: (reason: string) => Promise<unknown> }) {
  const [reason, setReason] = useState("");
  const { error, busy, run } = useFormRunner();
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        void run(() => onSubmit(reason));
      }}
    >
      <Field label="Reason">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} required />}</Field>
      <ErrorNote error={error} />
      <Button type="submit" disabled={busy}>
        Confirm
      </Button>
    </form>
  );
}

function CorrectionForm({ version, bookId, onDone }: { version: Version; bookId: string; onDone: () => void }) {
  const queryClient = useQueryClient();
  const unitWord = version.unit_type === "class" ? "classes" : "h";
  const [rows, setRows] = useState(
    version.entries.map((e) => `${Number(e.quantity)}, ${(e.package_total_minor / 100).toFixed(2).replace(/\.00$/, "")}`).join("\n"),
  );
  const [source, setSource] = useState("");
  const [received, setReceived] = useState(new Date().toISOString().slice(0, 10));
  const [summary, setSummary] = useState("");
  const [result, setResult] = useState<Schemas["CorrectionOut"] | null>(null);
  const { error, busy, run } = useFormRunner();

  async function submit() {
    const entries = rows
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [quantity, total] = line.split(",").map((p) => p.trim());
        const q = Number(quantity);
        return {
          package_code: `${q}${version.unit_type === "class" ? "C" : "H"}`,
          display_name: version.unit_type === "class" ? `${q} classes` : `${q}${unitWord}`,
          quantity: String(quantity),
          package_total: String(total),
        };
      });
    const created = await api<Schemas["CorrectionOut"]>(`/pricing/versions/${version.id}/corrections`, {
      json: { source_document: source, source_received_on: received, change_summary: summary, entries },
    });
    setResult(created);
    void queryClient.invalidateQueries({ queryKey: ["pricing-book", bookId] });
    void queryClient.invalidateQueries({ queryKey: ["pricing-books"] });
  }

  if (result) {
    return (
      <div className="space-y-3 text-sm">
        <p>
          Version {result.version.version_no} created as a draft. Version {version.version_no} is kept unchanged in the history.
        </p>
        {result.anomalies.length > 0 ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-warning">
            <p className="font-medium">Please double-check (nothing was changed):</p>
            <ul className="mt-1 list-disc pl-5">
              {result.anomalies.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-muted">No anomalies found.</p>
        )}
        <Button onClick={onDone}>Close</Button>
      </div>
    );
  }
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        void run(submit);
      }}
    >
      <p className="text-sm text-muted">
        One package per line: quantity, package total in {version.currency_code} exactly as on the corrected sheet. The current figures
        are pre-filled; change only what the corrected sheet says.
      </p>
      <Field label="Packages">{(id) => <Textarea id={id} value={rows} onChange={(e) => setRows(e.target.value)} className="font-mono" required />}</Field>
      <Field label="Source document">{(id) => <Input id={id} value={source} onChange={(e) => setSource(e.target.value)} required />}</Field>
      <Field label="Received on">{(id) => <Input id={id} type="date" value={received} onChange={(e) => setReceived(e.target.value)} required />}</Field>
      <Field label="What was corrected and who supplied it">{(id) => <Textarea id={id} value={summary} onChange={(e) => setSummary(e.target.value)} required />}</Field>
      <ErrorNote error={error} />
      <Button type="submit" disabled={busy}>
        Create correction version
      </Button>
    </form>
  );
}

function Markets({ book }: { book: Schemas["BookDetailOut"] }) {
  const { data: me } = useMe();
  const queryClient = useQueryClient();
  const markets = useMarkets();
  const [assigning, setAssigning] = useState(false);
  const [relationshipFor, setRelationshipFor] = useState<string | null>(null);
  const [marketId, setMarketId] = useState("");
  const [ref, setRef] = useState("");
  const [note, setNote] = useState("");
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["pricing-book", book.id] });
    void queryClient.invalidateQueries({ queryKey: ["pricing-books"] });
    void queryClient.invalidateQueries({ queryKey: ["pricing-version"] });
  };
  const assign = useMutation({
    mutationFn: () => api(`/pricing/books/${book.id}/assignments`, { json: { market_id: marketId, decision_ref: ref, note } }),
    onSuccess: () => {
      setAssigning(false);
      refresh();
    },
  });
  const manage = can(me, "pricing.assignments.manage");
  return (
    <Card
      title="Markets"
      actions={
        manage ? (
          <Button variant="ghost" onClick={() => setAssigning(true)}>
            Assign to a market
          </Button>
        ) : null
      }
    >
      {book.assignments.length === 0 ? (
        <Empty>Not assigned to any market. Its market has not been confirmed by Mixt, so it cannot be offered anywhere.</Empty>
      ) : (
        <ul className="space-y-2 text-sm">
          {book.assignments.map((a) => (
            <li key={a.id}>
              <span className="font-medium">{a.market_name}</span> <Badge tone={a.status === "confirmed" ? "success" : "neutral"}>{humanize(a.status)}</Badge>
              <div className="text-xs text-muted">Decision: {a.decision_ref ?? "none"}</div>
              {a.requires_relationship_confirmation ? (
                <div className="text-xs">
                  {a.relationship_confirmed_ref ? (
                    `Relationship between schedules confirmed (${a.relationship_confirmed_ref})`
                  ) : (
                    <span className="text-warning">
                      Relationship between this market&apos;s schedules not confirmed (Q-PRC-03).{" "}
                      {manage ? (
                        <button type="button" className="text-accent underline" onClick={() => setRelationshipFor(a.id)}>
                          Record Mixt&apos;s decision
                        </button>
                      ) : null}
                    </span>
                  )}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      <Modal open={assigning} title="Assign to a market" onClose={() => setAssigning(false)}>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            assign.mutate();
          }}
        >
          <p className="text-sm text-muted">Only record a market Mixt has decided on. The currency never decides the market.</p>
          <Field label="Market">
            {(id) => (
              <Select id={id} value={marketId} onChange={(e) => setMarketId(e.target.value)} required>
                <option value="">Choose…</option>
                {markets.data?.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Decision-log reference">{(id) => <Input id={id} value={ref} onChange={(e) => setRef(e.target.value)} required />}</Field>
          <Field label="Note">{(id) => <Input id={id} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
          <ErrorNote error={assign.error} />
          <Button type="submit" disabled={assign.isPending}>
            Assign
          </Button>
        </form>
      </Modal>
      <Modal open={relationshipFor !== null} title="Relationship between the schedules" onClose={() => setRelationshipFor(null)}>
        <DecisionForm
          noteLabel="What Mixt decided"
          onSubmit={(decision_ref) =>
            api(`/pricing/assignments/${relationshipFor}/confirm-relationship`, { json: { decision_ref } }).then(() => {
              setRelationshipFor(null);
              refresh();
            })
          }
        />
      </Modal>
    </Card>
  );
}

"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { PricingTabs } from "@/components/pricing";
import { Badge, Button, Card, ErrorNote, Field, Input, PageHeader, Select, Table, Td, Textarea } from "@/components/ui";
import { api, type Schemas } from "@/lib/api";
import { useMe } from "@/lib/session";

type Batch = Schemas["PricingImportOut"];
type Diff = { is_new: boolean; compared_with?: string | null; added?: { quantity: string; total_minor: number }[]; removed?: { quantity: string; total_minor: number }[]; changed?: { quantity: string; from_minor: number; to_minor: number }[]; unchanged?: number };
type ReportBook = { code: string; name: string; currency: string; plan_type: string; unit_type: string; audience: string; tier_label: string | null; packages: number; diff: Diff; anomalies: string[] };

const major = (minor: number) => (minor / 100).toLocaleString("en-GB", { minimumFractionDigits: 0, maximumFractionDigits: 2 });

export default function PricingImportPage() {
  const { data: me } = useMe();
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [batch, setBatch] = useState<Batch | null>(null);
  const upload = useMutation({
    mutationFn: () => {
      const form = new FormData();
      if (file) form.append("file", file);
      return api<Batch>("/pricing/imports", { form });
    },
    onSuccess: setBatch,
  });
  const [changeType, setChangeType] = useState("price_change");
  const [source, setSource] = useState("");
  const [received, setReceived] = useState(new Date().toISOString().slice(0, 10));
  const [summary, setSummary] = useState("");
  const apply = useMutation({
    mutationFn: () =>
      api<Batch>(`/pricing/imports/${batch?.id}/apply`, {
        json: { change_type: changeType, source_document: source, source_received_on: received, change_summary: summary },
      }),
    onSuccess: setBatch,
  });
  const discard = useMutation({ mutationFn: () => api<Batch>(`/pricing/imports/${batch?.id}/discard`, { method: "POST" }), onSuccess: setBatch });
  const books = ((batch?.report as { books?: ReportBook[] } | undefined)?.books ?? []) as ReportBook[];

  return (
    <>
      <PageHeader
        title="Import a pricing sheet"
        description="Checks every row and shows what would change. Applying creates draft versions only: nothing is assigned to a market and nothing goes live."
      />
      <PricingTabs current="/pricing/import" permissions={me?.permissions ?? []} />
      <Card title="1. Upload">
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            upload.mutate();
          }}
        >
          <Field label="Pricing sheet (CSV)">
            {(id) => <Input id={id} type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />}
          </Field>
          <Button type="submit" disabled={!file || upload.isPending}>
            Check sheet
          </Button>
          <a className="text-sm text-accent" href="/api/v1/pricing/imports/template">
            Download the template
          </a>
        </form>
        <ErrorNote error={upload.error} />
      </Card>

      {batch ? (
        <div className="mt-6 space-y-6">
          <Card title={`2. Result: ${batch.filename}`} actions={<Badge tone={batch.status === "validated" ? "success" : batch.status === "applied" ? "accent" : "danger"}>{batch.status}</Badge>}>
            {batch.error_count > 0 ? (
              <>
                <p className="mb-3 text-sm text-danger">{batch.error_count} row(s) need fixing. Correct the sheet and upload it again.</p>
                <Table label="Rows with problems" head={["Row", "Problems"]}>
                  {batch.rows
                    .filter((r) => r.errors.length > 0)
                    .map((r) => (
                      <tr key={r.row_no}>
                        <Td>{r.row_no}</Td>
                        <Td>{r.errors.join("; ")}</Td>
                      </tr>
                    ))}
                </Table>
              </>
            ) : null}
            <div className="mt-4 space-y-4">
              {books.map((b) => (
                <section key={b.code} aria-label={`Changes to ${b.code}`} className="rounded-md border border-border p-3 text-sm">
                  <p className="font-medium">
                    {b.code} {b.diff.is_new ? <Badge tone="accent">New price book ({b.audience})</Badge> : <span className="text-muted">compared with {b.diff.compared_with}</span>}
                  </p>
                  <p className="text-muted">
                    {b.currency} · {b.plan_type} · per {b.unit_type} · {b.packages} package(s)
                  </p>
                  {!b.diff.is_new ? (
                    <ul className="mt-2 list-disc pl-5">
                      {b.diff.changed?.map((c) => (
                        <li key={`c${c.quantity}`}>
                          {c.quantity}: {b.currency} {major(c.from_minor)} → {b.currency} {major(c.to_minor)}
                        </li>
                      ))}
                      {b.diff.added?.map((a) => <li key={`a${a.quantity}`}>Added {a.quantity}: {b.currency} {major(a.total_minor)}</li>)}
                      {b.diff.removed?.map((r) => <li key={`r${r.quantity}`}>Not in this sheet: {r.quantity}</li>)}
                      <li>{b.diff.unchanged ?? 0} unchanged</li>
                    </ul>
                  ) : null}
                  {b.anomalies.length > 0 ? (
                    <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-warning">
                      <p className="font-medium">Please double-check (nothing is changed):</p>
                      <ul className="list-disc pl-5">
                        {b.anomalies.map((a) => (
                          <li key={a}>{a}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </section>
              ))}
            </div>
          </Card>

          {batch.status === "validated" ? (
            <Card title="3. Apply as draft versions">
              <form
                className="grid gap-4 sm:grid-cols-2"
                onSubmit={(e: FormEvent) => {
                  e.preventDefault();
                  apply.mutate();
                }}
              >
                <Field label="This sheet is">
                  {(id) => (
                    <Select id={id} value={changeType} onChange={(e) => setChangeType(e.target.value)}>
                      <option value="price_change">A new price (a new version alongside the current one)</option>
                      <option value="correction">A correction of the latest version (the original is kept)</option>
                    </Select>
                  )}
                </Field>
                <Field label="Received on">{(id) => <Input id={id} type="date" value={received} onChange={(e) => setReceived(e.target.value)} required />}</Field>
                <Field label="Source document">{(id) => <Input id={id} value={source} onChange={(e) => setSource(e.target.value)} required />}</Field>
                <Field label="What changed and who supplied it">{(id) => <Textarea id={id} value={summary} onChange={(e) => setSummary(e.target.value)} required />}</Field>
                <div className="flex gap-2 sm:col-span-2">
                  <Button type="submit" disabled={apply.isPending}>
                    Create draft versions
                  </Button>
                  <Button variant="secondary" onClick={() => discard.mutate()}>
                    Discard
                  </Button>
                </div>
                <div className="sm:col-span-2">
                  <ErrorNote error={apply.error ?? discard.error} />
                </div>
              </form>
            </Card>
          ) : null}
          {batch.status === "applied" ? (
            <Card title="Done">
              <p className="text-sm">
                {batch.applied_version_ids?.length ?? 0} draft version(s) created. Each still needs Mixt&apos;s confirmation, approval and the
                activation checklist before it can be used.
              </p>
              <Button variant="secondary" className="mt-3" onClick={() => router.push("/pricing")}>
                Back to price books
              </Button>
            </Card>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

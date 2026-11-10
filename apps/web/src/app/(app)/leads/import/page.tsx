"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Badge, Button, Card, ErrorNote, Field, Input, PageHeader, Table, Td } from "@/components/ui";
import { api, type Schemas } from "@/lib/api";

const COLUMNS =
  "household_name, guardian_first_name, guardian_last_name, email, phone, country, student_first_name, student_curriculum, student_grade, message, external_id";

export default function ImportPage() {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<Schemas["ImportOut"] | null>(null);

  const upload = useMutation({
    mutationFn: () => {
      const form = new FormData();
      if (file) form.append("file", file);
      return api<Schemas["ImportOut"]>("/leads/imports", { form });
    },
    onSuccess: setReport,
  });
  const finish = useMutation({
    mutationFn: (action: "commit" | "discard") => api<Schemas["ImportOut"]>(`/leads/imports/${report?.id}/${action}`, { method: "POST" }),
    onSuccess: async (data) => {
      setReport(data);
      await queryClient.invalidateQueries({ queryKey: ["leads"] });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    upload.mutate();
  }

  return (
    <>
      <PageHeader
        title="Import leads"
        description="Step 1 checks every row and creates nothing. Step 2 imports the valid rows. Imports never record marketing consent, and personal data is removed from the report afterwards."
      />
      <Card title="1. Upload a CSV file (UTF-8)">
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <Field label="File" hint={`Columns: ${COLUMNS}`}>
            {(id) => <Input id={id} type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />}
          </Field>
          <Button type="submit" disabled={!file || upload.isPending}>
            {upload.isPending ? "Checking…" : "Check file"}
          </Button>
        </form>
        <div className="mt-3">
          <ErrorNote error={upload.error} />
        </div>
      </Card>
      {report ? (
        <Card
          className="mt-6"
          title={`2. Review: ${report.valid_count} valid, ${report.error_count} with errors`}
          actions={
            report.status === "validated" ? (
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => finish.mutate("discard")}>
                  Discard
                </Button>
                <Button onClick={() => finish.mutate("commit")} disabled={report.valid_count === 0 || finish.isPending}>
                  Import {report.valid_count} rows
                </Button>
              </div>
            ) : (
              <Badge tone={report.status === "imported" ? "success" : "neutral"}>
                {report.status === "imported" ? `Imported ${report.imported_count}` : "Discarded"}
              </Badge>
            )
          }
        >
          <ErrorNote error={finish.error} />
          {report.note ? <p className="mb-3 text-xs text-muted">{report.note}</p> : null}
          <Table label="Import rows" head={["Row", "Result", "Details"]}>
            {report.rows.map((row) => (
              <tr key={String(row.row)}>
                <Td>{String(row.row)}</Td>
                <Td>{row.ok ? <Badge tone="success">OK</Badge> : <Badge tone="danger">Error</Badge>}</Td>
                <Td>{Array.isArray(row.errors) && row.errors.length ? row.errors.join("; ") : String(row.outcome ?? "")}</Td>
              </tr>
            ))}
          </Table>
        </Card>
      ) : null}
    </>
  );
}

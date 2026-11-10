"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { Badge, Card, Empty, ErrorNote, Loading, PageHeader, Table, Td } from "@/components/ui";
import { api, type Schemas } from "@/lib/api";
import { formatDate, humanize } from "@/lib/format";

export default function QuotationsPage() {
  const inbox = useQuery({ queryKey: ["quotation-inbox"], queryFn: () => api<Schemas["QuotationSummaryOut"][]>("/quotations/approvals") });
  return (
    <>
      <PageHeader
        title="Quotations"
        description="Quotations are built on a customer's page from the options that customer can be offered. Every quotation is approved by a person before it is issued, and an approved quotation never changes."
      />
      <Card title="Waiting for my approval">
        {inbox.isLoading ? <Loading /> : null}
        <ErrorNote error={inbox.error} />
        {inbox.data && inbox.data.length === 0 ? <Empty>Nothing is waiting for you.</Empty> : null}
        {inbox.data && inbox.data.length > 0 ? (
          <Table label="Waiting for my approval" head={["Quotation", "Total", "Valid until", "Status"]}>
            {inbox.data.map((q) => (
              <tr key={q.id}>
                <Td>
                  <Link className="font-medium text-accent" href={`/quotations/${q.id}`}>
                    {q.quote_number} rev {q.revision_no}
                  </Link>
                </Td>
                <Td className="tabular">{q.total_display}</Td>
                <Td>{q.valid_until ? formatDate(q.valid_until) : "not set"}</Td>
                <Td>
                  <Badge tone="warning">{humanize(q.status)}</Badge>
                </Td>
              </tr>
            ))}
          </Table>
        ) : null}
      </Card>
    </>
  );
}

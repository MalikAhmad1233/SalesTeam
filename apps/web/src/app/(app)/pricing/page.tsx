"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { Badge, Card, ErrorNote, Loading, PageHeader, Table, Td } from "@/components/ui";
import { PricingBanners, statusTone } from "@/components/pricing";
import { api, type Schemas } from "@/lib/api";
import { humanize } from "@/lib/format";

export default function PricingPage() {
  const status = useQuery({ queryKey: ["pricing-status"], queryFn: () => api<Schemas["PricingStatusOut"]>("/pricing/status") });
  const books = useQuery({ queryKey: ["pricing-books"], queryFn: () => api<Schemas["BookOut"][]>("/pricing/books") });
  const unpriced = status.data?.markets.filter((m) => m.books.length === 0) ?? [];

  return (
    <>
      <PageHeader
        title="Pricing"
        description="Price books as supplied by Mixt. Figures are never edited: a correction becomes a new version, and the original is kept."
      />
      <PricingBanners status={status.data} />
      {books.isLoading ? <Loading /> : null}
      <ErrorNote error={books.error ?? status.error} />
      {books.data ? (
        <Table label="Price books" head={["Price book", "Currency", "Plan", "Unit", "Markets", "Latest version", "Live"]}>
          {books.data.map((b) => (
            <tr key={b.id}>
              <Td>
                <Link href={`/pricing/${b.id}`} className="font-medium text-accent">
                  {b.code}
                </Link>
                <div className="text-xs text-muted">{b.name}</div>
              </Td>
              <Td>{b.currency_code}</Td>
              <Td>
                {humanize(b.plan_type)}
                {b.tier_label ? <div className="text-xs text-muted">{b.tier_label}</div> : null}
              </Td>
              <Td>{b.unit_type}</Td>
              <Td>
                {b.assignments.filter((a) => a.status === "confirmed").length === 0 ? (
                  <Badge tone="warning">No market (unconfirmed)</Badge>
                ) : (
                  b.assignments
                    .filter((a) => a.status === "confirmed")
                    .map((a) => (
                      <div key={a.id}>
                        {a.market_name}
                        {a.requires_relationship_confirmation && !a.relationship_confirmed_ref ? (
                          <span className="ml-1 text-xs text-warning">(schedule relationship open)</span>
                        ) : null}
                      </div>
                    ))
                )}
              </Td>
              <Td>
                v{b.latest_version.version_no} <Badge tone={statusTone(b.latest_version.status)}>{humanize(b.latest_version.status)}</Badge>
              </Td>
              <Td>{b.active_version_no ? <Badge tone="success">v{b.active_version_no} active</Badge> : <span className="text-muted">Not active</span>}</Td>
            </tr>
          ))}
        </Table>
      ) : null}
      {unpriced.length > 0 ? (
        <Card title="Markets without pricing" className="mt-6">
          <p className="text-sm text-muted">
            No pricing has been supplied for these markets. Customers there get no figures: the team is asked to follow up, and no other
            market&apos;s or currency&apos;s pricing is used instead.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {unpriced.map((m) => (
              <Badge key={m.market_id}>{m.name}</Badge>
            ))}
          </div>
        </Card>
      ) : null}
    </>
  );
}

"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Badge, Empty, ErrorNote, Field, Input, Loading, PageHeader, Select, Table, Td } from "@/components/ui";
import { api, qs, type Schemas } from "@/lib/api";
import { humanize } from "@/lib/format";
import { useMarkets, useUserNames } from "@/lib/queries";
import { can, useMe } from "@/lib/session";

const STAGES = ["", "lead", "prospect", "customer", "former_customer", "disqualified", "out_of_market"];

export default function CustomersPage() {
  const { data: me } = useMe();
  const ownerName = useUserNames(me);
  const markets = useMarkets();
  const [search, setSearch] = useState("");
  const [stage, setStage] = useState("");
  const accounts = useQuery({
    queryKey: ["accounts", search, stage],
    queryFn: () => api<Schemas["AccountOut"][]>(`/crm/accounts${qs({ search, lifecycle_stage: stage, limit: 100 })}`),
  });
  const marketName = (id: string | null) => markets.data?.find((m) => m.id === id)?.name;

  return (
    <>
      <PageHeader
        title="Customers"
        description="Households you can see: your own, your team's and the unassigned pool."
        actions={
          can(me, "crm.accounts.merge") ? (
            <Link href="/customers/duplicates" className="rounded-md border border-border px-3 py-2 text-sm">
              Review duplicates
            </Link>
          ) : null
        }
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Search">
          {(id) => <Input id={id} placeholder="Name or MX-number" value={search} onChange={(e) => setSearch(e.target.value)} />}
        </Field>
        <Field label="Lifecycle">
          {(id) => (
            <Select id={id} value={stage} onChange={(e) => setStage(e.target.value)}>
              {STAGES.map((s) => (
                <option key={s} value={s}>
                  {s ? humanize(s) : "All"}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      {accounts.isLoading ? <Loading /> : null}
      <ErrorNote error={accounts.error} />
      {accounts.data && accounts.data.length === 0 ? <Empty>No households match.</Empty> : null}
      {accounts.data && accounts.data.length > 0 ? (
        <Table label="Households" head={["Household", "Number", "Lifecycle", "Pricing market", "Owner"]}>
          {accounts.data.map((a) => (
            <tr key={a.id}>
              <Td>
                <Link href={`/customers/${a.id}`} className="font-medium text-accent hover:underline">
                  {a.display_name}
                </Link>
                {a.is_vip ? <span className="ml-2"><Badge tone="primary">VIP</Badge></span> : null}
              </Td>
              <Td className="tabular">{a.account_number}</Td>
              <Td>
                <Badge tone={a.lifecycle_stage === "out_of_market" ? "warning" : "neutral"}>{humanize(a.lifecycle_stage)}</Badge>
              </Td>
              <Td>{a.market_id ? marketName(a.market_id) : <span className="text-muted">Not confirmed</span>}</Td>
              <Td>{ownerName(a.owner_user_id)}</Td>
            </tr>
          ))}
        </Table>
      ) : null}
    </>
  );
}

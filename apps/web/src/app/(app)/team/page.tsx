"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Badge, Button, Card, ErrorNote, Field, Input, Loading, PageHeader, Select, Table, Td } from "@/components/ui";
import { api, type Schemas } from "@/lib/api";
import { formatDateTime, humanize } from "@/lib/format";
import { useMarkets } from "@/lib/queries";
import { can, useMe } from "@/lib/session";

export default function TeamPage() {
  const { data: me } = useMe();
  const queryClient = useQueryClient();
  const markets = useMarkets();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<Schemas["UserOut"][]>("/users") });
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => api<Schemas["RoleOut"][]>("/roles") });
  const [form, setForm] = useState({ email: "", full_name: "", temporary_password: "", role: "sales_rep", market_id: "" });
  const create = useMutation({
    mutationFn: () =>
      api("/users", {
        json: {
          email: form.email, full_name: form.full_name, temporary_password: form.temporary_password,
          roles: [{ role: form.role, market_id: form.market_id || null }],
        },
      }),
    onSuccess: async () => {
      setForm({ email: "", full_name: "", temporary_password: "", role: "sales_rep", market_id: "" });
      await queryClient.invalidateQueries({ queryKey: ["users"] });
    },
  });
  const marketName = (id: string | null | undefined) => (id ? markets.data?.find((m) => m.id === id)?.name ?? "market" : "all markets");
  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }
  return (
    <>
      <PageHeader title="Team" description="Staff accounts and roles. New users get a temporary password and must set up two-step verification." />
      {users.isLoading ? <Loading /> : null}
      <ErrorNote error={users.error} />
      {users.data ? (
        <Table label="Users" head={["Name", "Email", "Roles", "Status", "Last sign-in"]}>
          {users.data.map((u) => (
            <tr key={u.id}>
              <Td>{u.full_name}</Td>
              <Td>{u.email}</Td>
              <Td>
                <div className="flex flex-wrap gap-1">
                  {u.roles.map((r) => (
                    <Badge key={`${r.role}-${r.market_id}`} tone="accent">
                      {humanize(r.role)} · {marketName(r.market_id)}
                    </Badge>
                  ))}
                </div>
              </Td>
              <Td><Badge tone={u.status === "active" ? "success" : "danger"}>{humanize(u.status)}</Badge></Td>
              <Td>{formatDateTime(u.last_login_at, me?.timezone)}</Td>
            </tr>
          ))}
        </Table>
      ) : null}
      {can(me, "users.manage") ? (
        <Card title="Add a user" className="mt-6">
          <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="Full name">{(id) => <Input id={id} required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />}</Field>
            <Field label="Email">{(id) => <Input id={id} type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />}</Field>
            <Field label="Temporary password" hint="At least 12 characters; share it securely.">
              {(id) => <Input id={id} type="password" minLength={12} required value={form.temporary_password} onChange={(e) => setForm({ ...form, temporary_password: e.target.value })} />}
            </Field>
            <Field label="Role">
              {(id) => (
                <Select id={id} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                  {(roles.data ?? []).map((r) => (
                    <option key={r.key} value={r.key}>{r.name}</option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Market scope">
              {(id) => (
                <Select id={id} value={form.market_id} onChange={(e) => setForm({ ...form, market_id: e.target.value })}>
                  <option value="">All markets</option>
                  {(markets.data ?? []).map((m) => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </Select>
              )}
            </Field>
            <div className="flex items-end"><Button type="submit">Create user</Button></div>
          </form>
          <div className="mt-3"><ErrorNote error={create.error} /></div>
        </Card>
      ) : null}
    </>
  );
}

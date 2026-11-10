"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Badge, Button, Card, Empty, ErrorNote, Field, Input, Loading, PageHeader, Select, Table, Td } from "@/components/ui";
import { api, qs, type Schemas } from "@/lib/api";
import { formatDateTime, humanize } from "@/lib/format";
import { useMe } from "@/lib/session";

type Task = Schemas["TaskOut"];

export default function TasksPage() {
  const { data: me } = useMe();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("open");
  const tasks = useQuery({ queryKey: ["tasks", "page", status], queryFn: () => api<Task[]>(`/tasks${qs({ assignee: "me", status })}`) });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["tasks"] });
  const transition = useMutation({
    mutationFn: ({ task, action }: { task: Task; action: string }) =>
      api(`/tasks/${task.id}/transition`, { json: { action }, version: task.version }),
    onSuccess: refresh,
  });
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const create = useMutation({
    mutationFn: () => api("/tasks", { json: { title, due_at: due ? new Date(due).toISOString() : undefined } }),
    onSuccess: async () => {
      setTitle("");
      setDue("");
      await refresh();
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }
  const overdue = (t: Task) => t.due_at && new Date(t.due_at) < new Date() && t.status !== "done";

  return (
    <>
      <PageHeader title="Tasks & follow-ups" description="Your tasks, including reminders created automatically (for example nurture revisits)." />
      <Card title="New task">
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <Field label="Title">{(id) => <Input id={id} required value={title} onChange={(e) => setTitle(e.target.value)} />}</Field>
          <Field label="Due">{(id) => <Input id={id} type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} />}</Field>
          <Button type="submit" disabled={!title.trim()}>Add task</Button>
        </form>
        <div className="mt-2"><ErrorNote error={create.error} /></div>
      </Card>
      <div className="my-4 flex items-end gap-3">
        <Field label="Show">
          {(id) => (
            <Select id={id} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="open">Open</option>
              <option value="done">Done</option>
              <option value="any">All</option>
            </Select>
          )}
        </Field>
      </div>
      {tasks.isLoading ? <Loading /> : null}
      <ErrorNote error={tasks.error ?? transition.error} />
      {tasks.data && tasks.data.length === 0 ? <Empty>Nothing here.</Empty> : null}
      {tasks.data && tasks.data.length > 0 ? (
        <Table label="Tasks" head={["Task", "Due", "Status", "Household", ""]}>
          {tasks.data.map((t) => (
            <tr key={t.id}>
              <Td>
                {t.title} {t.source === "system" ? <Badge>Automatic</Badge> : null}
              </Td>
              <Td className={overdue(t) ? "text-danger" : ""}>{t.due_at ? formatDateTime(t.due_at, me?.timezone) : "—"}</Td>
              <Td><Badge tone={t.status === "done" ? "success" : "neutral"}>{humanize(t.status)}</Badge></Td>
              <Td>{t.account_id ? <Link href={`/customers/${t.account_id}`} className="text-accent hover:underline">Open</Link> : "—"}</Td>
              <Td className="whitespace-nowrap">
                {t.status === "done" || t.status === "cancelled" ? (
                  <Button variant="ghost" onClick={() => transition.mutate({ task: t, action: "reopen" })}>Reopen</Button>
                ) : (
                  <Button variant="secondary" onClick={() => transition.mutate({ task: t, action: "complete" })}>Done</Button>
                )}
              </Td>
            </tr>
          ))}
        </Table>
      ) : null}
    </>
  );
}

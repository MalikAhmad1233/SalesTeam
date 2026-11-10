"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Badge, Button, ErrorNote, Field, Input, Loading, Modal, PageHeader, Select, Textarea } from "@/components/ui";
import { api, qs, type Schemas } from "@/lib/api";
import { useStages, useUserNames } from "@/lib/queries";
import { can, useMe } from "@/lib/session";

type Opp = Schemas["OpportunityOut"];

export default function PipelinePage() {
  const { data: me } = useMe();
  const ownerName = useUserNames(me);
  const stages = useStages();
  const [mineOnly, setMineOnly] = useState(false);
  const [moving, setMoving] = useState<Opp | null>(null);
  const opportunities = useQuery({
    queryKey: ["opportunities", "board", mineOnly],
    queryFn: () => api<Opp[]>(`/pipeline/opportunities${qs({ limit: 200, owner_user_id: mineOnly ? me?.id : undefined })}`),
  });
  const shown = (stages.data ?? []).filter((s) => s.type === "open" || (opportunities.data ?? []).some((o) => o.stage_key === s.key));

  return (
    <>
      <PageHeader
        title="Sales pipeline"
        description="Stages and their entry checks are proposed defaults until Mixt confirms them (Settings → Outstanding decisions)."
        actions={
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={mineOnly} onChange={(e) => setMineOnly(e.target.checked)} /> Only mine
          </label>
        }
      />
      {stages.isLoading || opportunities.isLoading ? <Loading /> : null}
      <ErrorNote error={opportunities.error} />
      <div className="flex gap-4 overflow-x-auto pb-4" role="list" aria-label="Pipeline stages">
        {shown.map((stage) => {
          const cards = (opportunities.data ?? []).filter((o) => o.stage_key === stage.key);
          return (
            <section key={stage.key} role="listitem" aria-label={stage.name} className="w-64 shrink-0 rounded-lg bg-surface p-3">
              <h2 className="mb-2 flex justify-between text-sm font-semibold">
                {stage.name} <span className="tabular text-muted">{cards.length}</span>
              </h2>
              <ul className="space-y-2">
                {cards.map((o) => (
                  <li key={o.id} className="rounded-md border border-border bg-white p-3 text-sm shadow-sm">
                    <Link href={`/customers/${o.account_id}`} className="font-medium text-ink hover:underline">
                      {o.title}
                    </Link>
                    <p className="mt-1 text-xs text-muted">{ownerName(o.owner_user_id)}</p>
                    <div className="mt-2 flex items-center justify-between">
                      {o.sla_breached ? <Badge tone="warning">Past SLA</Badge> : <span />}
                      {can(me, "crm.opportunities.manage") ? (
                        <Button variant="ghost" onClick={() => setMoving(o)}>
                          Move
                        </Button>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
      <Modal open={!!moving} title={`Move: ${moving?.title ?? ""}`} onClose={() => setMoving(null)}>
        {moving ? <MoveForm opportunity={moving} onDone={() => setMoving(null)} /> : null}
      </Modal>
    </>
  );
}

function MoveForm({ opportunity, onDone }: { opportunity: Opp; onDone: () => void }) {
  const queryClient = useQueryClient();
  const stages = useStages();
  const reasons = useQuery({ queryKey: ["lost-reasons"], queryFn: () => api<Schemas["SettingDetailOut"]>("/settings/crm.lost_reasons") });
  const [to, setTo] = useState("");
  const [note, setNote] = useState("");
  const [lostReason, setLostReason] = useState("");
  const [nurtureUntil, setNurtureUntil] = useState("");
  const target = stages.data?.find((s) => s.key === to);
  const mutation = useMutation({
    mutationFn: () =>
      api(`/pipeline/opportunities/${opportunity.id}/move`, {
        json: { to_stage: to, note: note || undefined, lost_reason: lostReason || undefined, nurture_until: nurtureUntil || undefined },
        version: opportunity.version,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      onDone();
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    mutation.mutate();
  }
  const reasonList = (reasons.data?.value as { code: string; name: string }[] | undefined) ?? [];
  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label="Move to">
        {(id) => (
          <Select id={id} required value={to} onChange={(e) => setTo(e.target.value)}>
            <option value="">Choose a stage…</option>
            {(stages.data ?? []).filter((s) => s.key !== opportunity.stage_key).map((s) => (
              <option key={s.key} value={s.key}>
                {s.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      {target && target.requires.length > 0 ? (
        <p className="text-xs text-muted">Needs: {target.requires.map((r) => r.replace(/_/g, " ")).join(", ")}</p>
      ) : null}
      {target?.requires.includes("lost_reason") ? (
        <Field label="Lost reason">
          {(id) => (
            <Select id={id} value={lostReason} onChange={(e) => setLostReason(e.target.value)}>
              <option value="">Choose…</option>
              {reasonList.map((r) => (
                <option key={r.code} value={r.code}>
                  {r.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
      ) : null}
      {target?.requires.includes("nurture_until") ? (
        <Field label="Revisit on">{(id) => <Input id={id} type="date" value={nurtureUntil} onChange={(e) => setNurtureUntil(e.target.value)} />}</Field>
      ) : null}
      <Field label="Note" hint="Required for some stages until trials, quotations and payments are built.">
        {(id) => <Textarea id={id} value={note} onChange={(e) => setNote(e.target.value)} />}
      </Field>
      <ErrorNote error={mutation.error} />
      <Button type="submit" disabled={!to || mutation.isPending}>
        Move
      </Button>
    </form>
  );
}

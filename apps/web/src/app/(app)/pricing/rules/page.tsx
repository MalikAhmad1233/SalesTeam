"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { PricingTabs } from "@/components/pricing";
import { Badge, Button, Card, Empty, ErrorNote, Field, Input, Loading, Modal, PageHeader, Select, Table, Td, Textarea } from "@/components/ui";
import { api, type Schemas } from "@/lib/api";
import { humanize } from "@/lib/format";
import { can, useMe } from "@/lib/session";

const EXAMPLES: Record<string, string> = {
  eligibility: JSON.stringify(
    { condition: { all: [{ fact: "account.is_new_customer", op: "eq", value: true }, { fact: "account.lead_source", op: "in", value: ["website_form"] }] } },
    null,
    2,
  ),
  minimum_purchase: JSON.stringify({ condition: null, min_quantity: 60 }, null, 2),
};

export default function PricingRulesPage() {
  const { data: me } = useMe();
  const queryClient = useQueryClient();
  const rules = useQuery({ queryKey: ["pricing-rules"], queryFn: () => api<Schemas["RuleOut"][]>("/pricing/rules") });
  const facts = useQuery({ queryKey: ["pricing-rule-facts"], queryFn: () => api<Schemas["FactOut"][]>("/pricing/rules/facts"), staleTime: Infinity });
  const [creating, setCreating] = useState(false);
  const [testing, setTesting] = useState<Schemas["RuleOut"] | null>(null);
  const action = useMutation({
    mutationFn: ({ id, path }: { id: string; path: string }) => api(`/pricing/rules/${id}/${path}`, { method: "POST" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["pricing-rules"] }),
  });

  return (
    <>
      <PageHeader
        title="Pricing rules"
        description="Who may be offered a price book or promotion, and minimum purchases. Mixt has not confirmed any rule yet (Q-PRC-04, Q-PRC-10): each rule needs a decision reference and a second person's approval."
        actions={can(me, "pricing.rules.manage") ? <Button onClick={() => setCreating(true)}>New rule</Button> : null}
      />
      <PricingTabs current="/pricing/rules" permissions={me?.permissions ?? []} />
      <ErrorNote error={rules.error ?? action.error} />
      {rules.isLoading ? <Loading /> : null}
      {rules.data && rules.data.length === 0 ? <Empty>No rules yet. Without rules, every listed package is offered to every customer in the market.</Empty> : null}
      {rules.data && rules.data.length > 0 ? (
        <Table label="Pricing rules" head={["Rule", "Kind", "Status", "Decision", ""]}>
          {rules.data.map((r) => (
            <tr key={r.id}>
              <Td>
                <span className="font-medium">
                  {r.code} v{r.rule_version}
                </span>
                <div className="text-xs text-muted">{r.name}</div>
                <pre className="mt-1 max-w-xl overflow-x-auto rounded bg-surface p-2 text-xs">{JSON.stringify(r.definition)}</pre>
              </Td>
              <Td>{humanize(r.kind)}</Td>
              <Td>
                <Badge tone={r.status === "approved" ? "success" : r.status === "retired" ? "neutral" : "warning"}>{humanize(r.status)}</Badge>
              </Td>
              <Td>{r.decision_ref ?? <span className="text-warning">none yet</span>}</Td>
              <Td className="space-x-2 whitespace-nowrap">
                <Button variant="ghost" onClick={() => setTesting(r)}>
                  Try it
                </Button>
                {r.status === "draft" && can(me, "pricing.rules.approve") ? (
                  <Button variant="secondary" onClick={() => action.mutate({ id: r.id, path: "approve" })}>
                    Approve
                  </Button>
                ) : null}
                {r.status === "approved" && can(me, "pricing.rules.approve") ? (
                  <Button variant="ghost" onClick={() => action.mutate({ id: r.id, path: "retire" })}>
                    Retire
                  </Button>
                ) : null}
              </Td>
            </tr>
          ))}
        </Table>
      ) : null}
      {facts.data ? (
        <Card title="Facts a rule can use" className="mt-6">
          <ul className="grid gap-1 text-sm sm:grid-cols-2">
            {facts.data.map((f) => (
              <li key={f.fact}>
                <code>{f.fact}</code> <span className="text-muted">({f.type}: {f.operators.join(", ")})</span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
      <Modal open={creating} title="New pricing rule" onClose={() => setCreating(false)}>
        <RuleForm onDone={() => setCreating(false)} />
      </Modal>
      <Modal open={testing !== null} title={`Try ${testing?.code ?? ""}`} onClose={() => setTesting(null)}>
        {testing ? <RuleTester rule={testing} /> : null}
      </Modal>
    </>
  );
}

function RuleForm({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [kind, setKind] = useState("eligibility");
  const [definition, setDefinition] = useState(EXAMPLES.eligibility ?? "");
  const [ref, setRef] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: (parsed: unknown) => api("/pricing/rules", { json: { code, name, kind, definition: parsed, decision_ref: ref || null } }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["pricing-rules"] });
      onDone();
    },
  });
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        try {
          setParseError(null);
          create.mutate(JSON.parse(definition));
        } catch {
          setParseError("The definition is not valid JSON.");
        }
      }}
    >
      <Field label="Code" hint="Capital letters, digits and hyphens. Reusing a code creates its next version.">
        {(id) => <Input id={id} value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} required />}
      </Field>
      <Field label="Name">{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} required />}</Field>
      <Field label="Kind">
        {(id) => (
          <Select
            id={id}
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setDefinition(EXAMPLES[e.target.value] ?? "");
            }}
          >
            <option value="eligibility">Eligibility</option>
            <option value="minimum_purchase">Minimum purchase</option>
          </Select>
        )}
      </Field>
      <Field label="Definition (JSON)">{(id) => <Textarea id={id} value={definition} onChange={(e) => setDefinition(e.target.value)} className="min-h-48 font-mono" />}</Field>
      <Field label="Decision-log reference" hint="Needed before it can be approved, e.g. BD-034">
        {(id) => <Input id={id} value={ref} onChange={(e) => setRef(e.target.value)} />}
      </Field>
      {parseError ? <p className="text-sm text-danger">{parseError}</p> : null}
      <ErrorNote error={create.error} />
      <Button type="submit" disabled={create.isPending}>
        Save draft
      </Button>
    </form>
  );
}

function RuleTester({ rule }: { rule: Schemas["RuleOut"] }) {
  const [facts, setFacts] = useState(
    JSON.stringify({ "account.market": "QA", "account.is_new_customer": true, "account.lead_source": "website_form", "students.count": 1, "today": new Date().toISOString().slice(0, 10) }, null, 2),
  );
  const run = useMutation({
    mutationFn: () => api<Schemas["RuleTestOut"]>(`/pricing/rules/${rule.id}/evaluate`, { json: { facts: JSON.parse(facts) } }),
  });
  return (
    <div className="flex flex-col gap-3">
      <Field label="Example customer facts (JSON)">{(id) => <Textarea id={id} value={facts} onChange={(e) => setFacts(e.target.value)} className="min-h-40 font-mono" />}</Field>
      <Button onClick={() => run.mutate()}>Evaluate</Button>
      <ErrorNote error={run.error} />
      {run.data ? (
        <div role="status" className="rounded-md border border-border p-3 text-sm">
          <p className="font-medium">{run.data.result ? "Applies to this customer" : "Does not apply to this customer"}</p>
          {run.data.min_quantity ? <p>Minimum purchase: {run.data.min_quantity}</p> : null}
          <pre className="mt-2 whitespace-pre-wrap text-xs text-muted">{run.data.trace.join("\n")}</pre>
        </div>
      ) : null}
    </div>
  );
}

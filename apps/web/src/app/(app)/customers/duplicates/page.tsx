"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";

import { Button, Empty, ErrorNote, Loading, PageHeader, Table, Td } from "@/components/ui";
import { api, type Schemas } from "@/lib/api";

function AccountName({ id }: { id: string }) {
  const account = useQuery({ queryKey: ["account", id], queryFn: () => api<Schemas["AccountOut"]>(`/crm/accounts/${id}`) });
  return (
    <Link href={`/customers/${id}`} className="text-accent hover:underline">
      {account.data ? `${account.data.display_name} (${account.data.account_number})` : "…"}
    </Link>
  );
}

export default function DuplicatesPage() {
  const queryClient = useQueryClient();
  const candidates = useQuery({ queryKey: ["duplicates"], queryFn: () => api<Schemas["DuplicateOut"][]>("/crm/duplicates") });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["duplicates"] });
  const dismiss = useMutation({ mutationFn: (id: string) => api(`/crm/duplicates/${id}/dismiss`, { method: "POST" }), onSuccess: refresh });
  const merge = useMutation({
    mutationFn: (c: Schemas["DuplicateOut"]) =>
      api("/crm/merges", { json: { survivor_account_id: c.candidate_account_id, merged_account_id: c.account_id } }),
    onSuccess: async () => {
      await refresh();
      await queryClient.invalidateQueries({ queryKey: ["accounts"] });
    },
  });

  return (
    <>
      <PageHeader
        title="Possible duplicates"
        description="Households with similar names in the same country. Merging moves everything into the older household and archives the newer one; this cannot be undone automatically."
      />
      <ErrorNote error={candidates.error ?? merge.error ?? dismiss.error} />
      {candidates.isLoading ? <Loading /> : null}
      {candidates.data && candidates.data.length === 0 ? <Empty>No open duplicate candidates.</Empty> : null}
      {candidates.data && candidates.data.length > 0 ? (
        <Table label="Duplicate candidates" head={["Newer household", "Possible match (kept)", "Similarity", ""]}>
          {candidates.data.map((c) => (
            <tr key={c.id}>
              <Td><AccountName id={c.account_id} /></Td>
              <Td><AccountName id={c.candidate_account_id} /></Td>
              <Td className="tabular">{c.score !== null ? `${Math.round(c.score * 100)}%` : "—"}</Td>
              <Td className="whitespace-nowrap">
                <div className="flex gap-2">
                  <Button variant="secondary" onClick={() => dismiss.mutate(c.id)}>Not a duplicate</Button>
                  <Button
                    onClick={() => {
                      if (window.confirm("Merge these households? This cannot be undone automatically.")) merge.mutate(c);
                    }}
                  >
                    Merge
                  </Button>
                </div>
              </Td>
            </tr>
          ))}
        </Table>
      ) : null}
    </>
  );
}

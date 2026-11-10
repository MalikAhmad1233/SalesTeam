"use client";

import { useQuery } from "@tanstack/react-query";

import { api, type Schemas } from "./api";
import { can, type Me } from "./session";

export function useStages() {
  return useQuery({ queryKey: ["stages"], queryFn: () => api<Schemas["StageOut"][]>("/pipeline/stages"), staleTime: 300_000 });
}

export function useMarkets() {
  return useQuery({ queryKey: ["markets"], queryFn: () => api<Schemas["MarketOut"][]>("/reference/markets"), staleTime: 3_600_000 });
}

export function useCurrencies() {
  return useQuery({
    queryKey: ["currencies"],
    queryFn: () => api<Schemas["CurrencyOut"][]>("/reference/currencies"),
    staleTime: 3_600_000,
  });
}

export function useCurricula() {
  return useQuery({ queryKey: ["curricula"], queryFn: () => api<Schemas["CurriculumOut"][]>("/reference/curricula"), staleTime: 3_600_000 });
}

/** Staff names, when the viewer may see the team list (otherwise only "you" is known). */
export function useUserNames(me: Me | undefined) {
  const query = useQuery({
    queryKey: ["users"],
    queryFn: () => api<Schemas["UserOut"][]>("/users"),
    enabled: can(me, "users.read"),
    staleTime: 300_000,
  });
  return (id: string | null | undefined): string => {
    if (!id) return "Unassigned";
    if (me && id === me.id) return "You";
    return query.data?.find((u) => u.id === id)?.full_name ?? "Colleague";
  };
}

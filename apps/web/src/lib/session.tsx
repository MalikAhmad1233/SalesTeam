"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { api, ApiError, type Schemas } from "./api";

export type Me = Schemas["MeOut"];

export function useMe() {
  return useQuery<Me, ApiError>({
    queryKey: ["me"],
    queryFn: () => api<Me>("/auth/me"),
    retry: false,
    staleTime: 60_000,
  });
}

export function can(me: Me | undefined, permission: string): boolean {
  return !!me && me.permissions.includes(permission);
}

/** Sends people to the right step: sign in, two-step set-up/verification or password change. */
export function useSessionGuard(): Me | undefined {
  const router = useRouter();
  const { data, error } = useMe();
  useEffect(() => {
    if (error && error.status === 401) router.replace("/login");
    if (data && data.mfa_state !== "verified") router.replace("/mfa");
    else if (data && data.must_change_password) router.replace("/password");
  }, [data, error, router]);
  return data && data.mfa_state === "verified" && !data.must_change_password ? data : undefined;
}

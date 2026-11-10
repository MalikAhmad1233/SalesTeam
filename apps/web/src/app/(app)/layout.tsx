"use client";

import type { ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { Loading } from "@/components/ui";
import { useSessionGuard } from "@/lib/session";

export default function SignedInLayout({ children }: { children: ReactNode }) {
  const me = useSessionGuard();
  if (!me) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loading label="Checking your session…" />
      </div>
    );
  }
  return <AppShell me={me}>{children}</AppShell>;
}

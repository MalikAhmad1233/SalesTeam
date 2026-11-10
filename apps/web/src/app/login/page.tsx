"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { Button, ErrorNote, Field, Input } from "@/components/ui";
import { api, type Schemas } from "@/lib/api";

// Codes sent back by /api/v1/auth/sso/callback (services/backend/mixt/api/routers/sso.py).
const SSO_ERRORS: Record<string, string> = {
  unavailable: "Single sign-on is not available right now. Sign in with your email and password.",
  cancelled: "Single sign-on was cancelled.",
  expired: "The sign-in took too long or was started in another browser. Please try again.",
  invalid: "Single sign-on could not be verified. Please try again, or contact your administrator.",
  no_account: "There is no Mixt AI staff account for that email address. Ask an administrator to create one.",
  disabled: "This account is not active. Contact your administrator.",
  domain: "That email address is not allowed to use single sign-on here.",
  rate_limited: "Too many sign-in attempts. Wait a few minutes and try again.",
};

function SsoNotice() {
  const code = useSearchParams().get("sso_error");
  if (!code) return null;
  return (
    <div role="alert" className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-danger">
      {SSO_ERRORS[code] ?? SSO_ERRORS.invalid}
    </div>
  );
}

function SsoButton() {
  const sso = useQuery({
    queryKey: ["sso"],
    queryFn: () => api<Schemas["SsoInfoOut"]>("/auth/sso"),
    staleTime: 300_000,
    retry: false,
  });
  if (!sso.data?.enabled) return null;
  return (
    <div className="mt-4 flex flex-col gap-3">
      <div className="flex items-center gap-3 text-xs text-muted" aria-hidden="true">
        <span className="h-px flex-1 bg-border" />
        or
        <span className="h-px flex-1 bg-border" />
      </div>
      {/* A full-page navigation: the API redirects to the provider and back. */}
      <a
        href="/api/v1/auth/sso/start"
        className="inline-flex items-center justify-center rounded-md border border-border bg-white px-3 py-2 text-sm font-medium text-ink hover:bg-surface"
      >
        Sign in with {sso.data.label}
      </a>
    </div>
  );
}

export default function LoginPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const session = await api<Schemas["SessionOut"]>("/auth/login", { json: { email, password } });
      queryClient.clear();
      if (session.mfa_state !== "verified") router.replace("/mfa");
      else if (session.must_change_password) router.replace("/password");
      else router.replace("/overview");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title="Sign in" subtitle="Staff access only. Two-step verification is required.">
      <Suspense fallback={null}>
        <SsoNotice />
      </Suspense>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field label="Email">
          {(id) => <Input id={id} type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />}
        </Field>
        <Field label="Password">
          {(id) => (
            <Input id={id} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          )}
        </Field>
        <ErrorNote error={error} />
        <Button type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
      <SsoButton />
    </AuthCard>
  );
}

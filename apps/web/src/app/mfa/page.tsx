"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import QRCode from "qrcode";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { Button, ErrorNote, Field, Input, Loading } from "@/components/ui";
import { api, ApiError, type Schemas } from "@/lib/api";
import { useMe } from "@/lib/session";

export default function MfaPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: me, error: meError } = useMe();
  const [setup, setSetup] = useState<Schemas["TotpSetupOut"] | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const started = useRef(false);

  useEffect(() => {
    if (meError instanceof ApiError && meError.status === 401) router.replace("/login");
    if (me?.mfa_state === "verified") router.replace(me.must_change_password ? "/password" : "/overview");
  }, [me, meError, router]);

  useEffect(() => {
    if (me?.mfa_state !== "enrollment_required" || started.current) return;
    started.current = true;
    api<Schemas["TotpSetupOut"]>("/auth/mfa/totp/setup", { method: "POST" })
      .then(async (result) => {
        setSetup(result);
        setQr(await QRCode.toDataURL(result.provisioning_uri, { margin: 1, width: 192 }));
      })
      .catch(setError);
  }, [me]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const path = me?.mfa_state === "enrollment_required" ? "/auth/mfa/totp/confirm" : "/auth/mfa/verify";
      const session = await api<Schemas["SessionOut"]>(path, { json: { code: code.replace(/\s/g, "") } });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      router.replace(session.must_change_password ? "/password" : "/overview");
    } catch (err) {
      setError(err);
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  if (!me) return <AuthCard title="Two-step verification"><Loading /></AuthCard>;
  const enrolling = me.mfa_state === "enrollment_required";

  return (
    <AuthCard
      title={enrolling ? "Set up two-step verification" : "Two-step verification"}
      subtitle={enrolling ? "Scan the code with an authenticator app, then enter the 6-digit code it shows." : "Enter the 6-digit code from your authenticator app."}
    >
      {enrolling ? (
        <div className="mb-4 flex flex-col items-center gap-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {qr ? <img src={qr} alt="QR code for your authenticator app" width={192} height={192} /> : <Loading label="Preparing…" />}
          {setup ? (
            <p className="text-center text-xs text-muted">
              Can&apos;t scan? Enter this key: <code data-testid="totp-secret" className="break-all font-mono text-ink">{setup.secret}</code>
            </p>
          ) : null}
        </div>
      ) : null}
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field label="6-digit code">
          {(id) => (
            <Input id={id} inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,8}" required value={code} onChange={(e) => setCode(e.target.value)} />
          )}
        </Field>
        <ErrorNote error={error} />
        <Button type="submit" disabled={busy || (enrolling && !setup)}>
          {busy ? "Checking…" : "Continue"}
        </Button>
      </form>
    </AuthCard>
  );
}

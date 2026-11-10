"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { Button, ErrorNote, Field, Input } from "@/components/ui";
import { api } from "@/lib/api";

export default function PasswordPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState<unknown>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api("/auth/password", { json: { current_password: current, new_password: next } });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      router.replace("/overview");
    } catch (err) {
      setError(err);
    }
  }

  return (
    <AuthCard title="Choose a new password" subtitle="At least 12 characters. Your temporary password stops working.">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field label="Current (temporary) password">
          {(id) => <Input id={id} type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />}
        </Field>
        <Field label="New password">
          {(id) => <Input id={id} type="password" autoComplete="new-password" minLength={12} required value={next} onChange={(e) => setNext(e.target.value)} />}
        </Field>
        <ErrorNote error={error} />
        <Button type="submit">Save password</Button>
      </form>
    </AuthCard>
  );
}

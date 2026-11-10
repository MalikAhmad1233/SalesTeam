"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

/**
 * Live inbox updates over Server-Sent Events. The server names conversations that changed; we
 * refetch them. EventSource reconnects by itself (the server ends each stream after ~1 minute),
 * and the lists also refetch on a slow timer in case a proxy buffers the stream.
 */
export function useInboxStream(enabled: boolean) {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;
    const source = new EventSource("/api/v1/inbox/stream", { withCredentials: true });
    const onChange = (event: MessageEvent<string>) => {
      try {
        const { id } = JSON.parse(event.data) as { id: string };
        void queryClient.invalidateQueries({ queryKey: ["inbox"] });
        void queryClient.invalidateQueries({ queryKey: ["conversation", id] });
        void queryClient.invalidateQueries({ queryKey: ["conversation-messages", id] });
      } catch {
        // ignore malformed events
      }
    };
    source.addEventListener("conversation", onChange as EventListener);
    return () => {
      source.removeEventListener("conversation", onChange as EventListener);
      source.close();
    };
  }, [enabled, queryClient]);
}

export const MESSAGE_STATUS: Record<string, { label: string; tone: "neutral" | "accent" | "success" | "warning" | "danger" }> = {
  queued: { label: "Queued", tone: "neutral" },
  sending: { label: "Sending", tone: "neutral" },
  sent: { label: "Sent", tone: "accent" },
  delivered: { label: "Delivered", tone: "accent" },
  read: { label: "Read", tone: "success" },
  failed: { label: "Not sent", tone: "danger" },
};

/** A fresh idempotency key, so a retried request never sends a message twice. */
export function newKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function windowText(expires: string | null | undefined, open: boolean): string {
  if (!expires) return "The customer has not written yet: only approved templates can be sent.";
  const until = new Date(expires);
  const time = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" }).format(until);
  return open
    ? `Reply window open until ${time}.`
    : `Reply window closed at ${time}: only approved templates can be sent.`;
}

export function renderTemplate(body: string, values: string[]): string {
  return body.replace(/\{\{\s*(\d+)\s*\}\}/g, (_, n: string) => values[Number(n) - 1] || `{{${n}}}`);
}

const CHANNELS: Record<string, string> = { whatsapp: "WhatsApp", email: "Email", web_form: "Website form" };

export function channelLabel(channel: string): string {
  return CHANNELS[channel] ?? channel;
}

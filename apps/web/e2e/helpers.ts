import { execSync } from "node:child_process";
import { createHmac } from "node:crypto";

import { E2E } from "../playwright.config";

/** RFC 6238 TOTP code (SHA-1, 30 s, 6 digits), as an authenticator app would show. */
export function totp(secretBase32: string, offsetSteps = 0): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const char of secretBase32.replace(/=+$/, "").toUpperCase()) {
    bits += alphabet.indexOf(char).toString(2).padStart(5, "0");
  }
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 1000 / 30) + offsetSteps));
  const hmac = createHmac("sha1", key).update(counter).digest();
  const offset = hmac[hmac.length - 1]! & 0x0f;
  const code = (hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return code.toString().padStart(6, "0");
}

/** Run the background worker once (delivers events to the timeline). A deployment has its own worker. */
export function runWorkerOnce(): string {
  if (process.env.E2E_BASE_URL) return "";
  return execSync("uv run python -m mixt.cli dispatch-once", { cwd: E2E.backendDir, env: process.env }).toString();
}

/** Where the API answers directly: provider webhooks and the public website form are not under /api. */
export const apiBase = process.env.E2E_BASE_URL ?? "http://localhost:8000";

/** The X-Hub-Signature-256 header Meta sends with a webhook body. */
export function metaSignature(appSecret: string, body: string): string {
  return `sha256=${createHmac("sha256", appSecret).update(body).digest("hex")}`;
}

/** A WhatsApp Cloud API webhook body with inbound messages and/or delivery statuses. */
export function whatsappWebhook(
  phoneNumberId: string,
  options: { from?: string; name?: string; text?: string; statuses?: { id: string; status: string }[] },
): string {
  const now = Math.floor(Date.now() / 1000).toString();
  const value: Record<string, unknown> = {
    messaging_product: "whatsapp",
    metadata: { display_phone_number: "97143123456", phone_number_id: phoneNumberId },
  };
  if (options.text && options.from) {
    value.contacts = [{ profile: { name: options.name ?? "Customer" }, wa_id: options.from }];
    value.messages = [{ from: options.from, id: `wamid.in-${Date.now()}`, timestamp: now, type: "text", text: { body: options.text } }];
  }
  if (options.statuses) {
    value.statuses = options.statuses.map((s) => ({ ...s, timestamp: now, recipient_id: options.from ?? "" }));
  }
  return JSON.stringify({ object: "whatsapp_business_account", entry: [{ id: "123456789012345", changes: [{ field: "messages", value }] }] });
}

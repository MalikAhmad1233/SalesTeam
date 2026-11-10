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

/** Run the background worker once (delivers events to the timeline). */
export function runWorkerOnce(): string {
  return execSync("uv run python -m mixt.cli dispatch-once", { cwd: E2E.backendDir, env: process.env }).toString();
}

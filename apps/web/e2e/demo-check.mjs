// Checks the one-command demo (infra/demo) the way a person would use it: open the printed address,
// sign in with the printed details, set up two-step verification, and open the main pages without
// a single browser error. Run by staging-ci after `infra/demo/demo.sh`; not part of the E2E suite.
//
//   node e2e/demo-check.mjs <url> <email> <password> [screenshot dir]
import { createHmac } from "node:crypto";

import { chromium } from "@playwright/test";

/** RFC 6238 TOTP code (SHA-1, 30 s, 6 digits), as an authenticator app would show. */
function totp(secretBase32) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const char of secretBase32.replace(/=+$/, "").toUpperCase()) {
    bits += alphabet.indexOf(char).toString(2).padStart(5, "0");
  }
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 1000 / 30)));
  const hmac = createHmac("sha1", key).update(counter).digest();
  const offset = hmac[hmac.length - 1] & 0x0f;
  return ((hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).toString().padStart(6, "0");
}

const [url, email, password, shots] = process.argv.slice(2);
if (!url || !email || !password) {
  console.error("usage: node e2e/demo-check.mjs <url> <email> <password> [screenshot dir]");
  process.exit(2);
}

const browser = await chromium.launch();
const page = await browser.newPage();
const problems = [];
page.on("pageerror", (error) => problems.push(`page error: ${error.message}`));
page.on("console", (message) => message.type() === "error" && problems.push(`console: ${message.text()}`));
try {
  const login = await page.goto(`${url}/login`);
  const csp = login?.headers()["content-security-policy"] ?? "";
  if (!csp.includes("'strict-dynamic'")) problems.push(`no nonce-based CSP on the login page: ${csp}`);
  if (csp.includes("upgrade-insecure-requests")) problems.push("CSP upgrades requests on a plain-HTTP demo");

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/mfa$/);
  const secret = ((await page.getByTestId("totp-secret").textContent()) ?? "").trim();
  await page.getByLabel("6-digit code").fill(totp(secret));
  await page.getByRole("button", { name: /Verify|Confirm|Continue/ }).click();
  await page.waitForURL((u) => !/^\/(mfa|login)/.test(u.pathname), { timeout: 15_000 });

  for (const [path, heading] of [
    ["/overview", "Overview"],
    ["/leads", "Leads"],
    ["/inbox", "Inbox"],
    ["/pricing", "Pricing"],
    ["/integrations", "Integrations"],
  ]) {
    await page.goto(`${url}${path}`);
    await page.getByRole("heading", { name: heading, exact: true }).first().waitFor({ timeout: 15_000 });
    if (shots) {
      await page.waitForTimeout(1_000); // let the cards load their data before the picture
      await page.screenshot({ path: `${shots}/demo${path.replace("/", "-")}.png` });
    }
  }
} catch (error) {
  problems.push(String(error));
  if (shots) await page.screenshot({ path: `${shots}/demo-failure.png` }).catch(() => {});
} finally {
  await browser.close();
}

if (problems.length) {
  console.error(`demo check failed:\n  ${problems.join("\n  ")}`);
  process.exit(1);
}
console.log("demo check passed: signed in with two-step verification, main pages open without errors");

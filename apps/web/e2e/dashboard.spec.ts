import { expect, test } from "@playwright/test";

import { E2E } from "../playwright.config";
import { runWorkerOnce, totp } from "./helpers";

// Set E2E_SCREENSHOTS=/some/dir to save screenshots of key screens (for reviews and release notes).
const shotsDir = process.env.E2E_SCREENSHOTS;

test("sign in with two-step verification, work a lead through the CRM, sign out", async ({ page }) => {
  const shot = async (name: string) => {
    if (shotsDir) await page.screenshot({ path: `${shotsDir}/${name}.png`, fullPage: true });
  };
  // Any Content-Security-Policy violation anywhere in the journey fails the test.
  const cspViolations: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" && /Content Security Policy|Content-Security-Policy/i.test(message.text())) {
      cspViolations.push(message.text());
    }
  });

  await test.step("protected pages send you to sign-in", async () => {
    await page.goto("/overview");
    await expect(page).toHaveURL(/\/login$/);
  });

  await test.step("pages carry a nonce-based Content-Security-Policy", async () => {
    const policy = async () => (await page.goto("/login"))?.headers()["content-security-policy"] ?? "";
    const first = await policy();
    const second = await policy();
    const scriptSrc = first.split(";").find((d) => d.trim().startsWith("script-src")) ?? "";
    expect(scriptSrc).toMatch(/'nonce-[A-Za-z0-9+/=]+'/);
    expect(scriptSrc).toContain("'strict-dynamic'");
    expect(scriptSrc).not.toContain("'unsafe-inline'");
    expect(scriptSrc).not.toContain("'unsafe-eval'");
    expect(first).toContain("frame-ancestors 'none'");
    expect(first).toContain("object-src 'none'");
    expect(first.match(/nonce-([^']+)/)?.[1]).not.toEqual(second.match(/nonce-([^']+)/)?.[1]); // fresh per request
    // Single sign-on is off until Mixt chooses a provider (auth.sso, Q-TECH-01): no button.
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
    await expect(page.getByRole("link", { name: /Sign in with/ })).toHaveCount(0);
  });

  await test.step("sign in and set up two-step verification", async () => {
    await page.getByLabel("Email").fill(E2E.ownerEmail);
    await page.getByLabel("Password").fill(E2E.ownerPassword);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/mfa$/);
    await expect(page.getByAltText("QR code for your authenticator app")).toBeVisible();
    await shot("01-two-step-setup");
    const secret = (await page.getByTestId("totp-secret").textContent()) ?? "";
    await page.getByLabel("6-digit code").fill(totp(secret.trim()));
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page).toHaveURL(/\/overview$/);
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
    await expect(page.getByTestId("current-user")).toHaveText("E2E Owner");
  });

  await test.step("future modules are shown as not yet available", async () => {
    await expect(page.getByTitle("Arrives in Phase 2").first()).toBeVisible();
  });

  await test.step("outstanding decisions are listed", async () => {
    await page.getByRole("link", { name: "Settings" }).click();
    await expect(page.getByRole("tab", { name: /Outstanding decisions \(\d+\)/ })).toBeVisible();
    await expect(page.getByText("pricing.tier_selection_mode")).toBeVisible();
    await expect(page.getByText("pricing.catalogue_complete")).toHaveCount(0); // confirmed (BD-017), not outstanding
    await shot("02-outstanding-decisions");
  });

  await test.step("enter a lead", async () => {
    await page.getByRole("link", { name: "Leads" }).click();
    await page.getByRole("button", { name: "New lead" }).click();
    const dialog = page.getByRole("dialog", { name: "New lead" });
    await dialog.getByLabel("Country (ISO code)").fill("AE");
    await dialog.getByLabel("Parent / guardian first name").fill("Mona");
    await dialog.getByLabel("Last name").fill("Haddad");
    await dialog.getByLabel("Phone / WhatsApp").fill("+971 50 123 4567");
    await dialog.getByLabel("Student first name").fill("Layla");
    await dialog.getByLabel("Curriculum").selectOption("BRITISH");
    await dialog.getByLabel("Grade / year").fill("Year 10");
    await dialog.getByRole("button", { name: "Save lead" }).click();
    await expect(dialog.getByText("New account")).toBeVisible();
    await dialog.getByRole("link", { name: "Open household" }).click();
    await expect(page.getByRole("heading", { name: "Mona Haddad" })).toBeVisible();
    await expect(page.getByText("Pricing market not confirmed")).toBeVisible();
  });

  await test.step("a person confirms the pricing market", async () => {
    await page.getByRole("button", { name: "Confirm market" }).click();
    const dialog = page.getByRole("dialog", { name: "Confirm pricing market" });
    await dialog.getByLabel("Market").selectOption({ label: "United Arab Emirates" });
    await dialog.getByLabel("How was it confirmed?").fill("Parent said they live in Dubai");
    await dialog.getByRole("button", { name: "Confirm" }).click();
    await expect(page.getByText("Pricing market: United Arab Emirates")).toBeVisible();
  });

  await test.step("add a note and see the timeline after the worker runs", async () => {
    await page.getByLabel("New note").fill("Prefers WhatsApp after 5pm");
    await page.getByRole("button", { name: "Add note" }).click();
    await expect(page.getByText("Prefers WhatsApp after 5pm")).toBeVisible();
    runWorkerOnce(); // locally; a deployment's own worker delivers the events within seconds
    await expect(async () => {
      await page.reload();
      await expect(page.getByText("Household created")).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 30_000 });
    await expect(page.getByText("Pricing market confirmed: United Arab Emirates")).toBeVisible();
    await shot("03-household");
  });

  await test.step("pipeline refuses to qualify an incomplete student profile", async () => {
    await page.getByRole("link", { name: "Sales Pipeline" }).click();
    const newColumn = page.getByRole("listitem", { name: "New" });
    await expect(newColumn.getByText("Mona Haddad: new enquiry")).toBeVisible();
    await newColumn.getByRole("button", { name: "Move" }).click();
    const dialog = page.getByRole("dialog", { name: /Move:/ });
    await dialog.getByLabel("Move to").selectOption("qualified");
    await dialog.getByRole("button", { name: "Move" }).click();
    await expect(dialog.getByRole("alert")).toContainText("Still needed:");
    await expect(dialog.getByRole("alert")).toContainText("at least one subject");
    await shot("04-pipeline-stage-check");
    await dialog.getByRole("button", { name: "Close" }).click();
  });

  await test.step("tasks: add and complete", async () => {
    await page.getByRole("link", { name: "Tasks & Follow-ups" }).click();
    await page.getByLabel("Title").fill("Call Mona about the trial");
    await page.getByRole("button", { name: "Add task" }).click();
    const row = page.getByRole("row", { name: /Call Mona about the trial/ });
    await expect(row).toBeVisible();
    await row.getByRole("button", { name: "Done" }).click();
    await expect(page.getByRole("row", { name: /Call Mona about the trial/ })).toHaveCount(0);
  });

  await test.step("a US enquiry is flagged out of market", async () => {
    await page.getByRole("link", { name: "Leads" }).click();
    await page.getByRole("button", { name: "New lead" }).click();
    const dialog = page.getByRole("dialog", { name: "New lead" });
    await dialog.getByLabel("Country (ISO code)").fill("US");
    await dialog.getByLabel("Parent / guardian first name").fill("Sam");
    await dialog.getByLabel("Phone / WhatsApp").fill("+1 202 555 0143");
    await dialog.getByRole("button", { name: "Save lead" }).click();
    await expect(dialog.getByText("not one of Mixt's markets")).toBeVisible();
    await dialog.getByRole("button", { name: "Close" }).last().click();
  });

  await test.step("sign out", async () => {
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);
    await page.goto("/customers");
    await expect(page).toHaveURL(/\/login$/);
  });

  expect(cspViolations).toEqual([]);
});

import { expect, test } from "@playwright/test";

import { E2E } from "../playwright.config";
import { apiBase, metaSignature, runWorkerOnce, totp, whatsappWebhook } from "./helpers";

// Set E2E_SCREENSHOTS=/some/dir to save screenshots of key screens (for reviews and release notes).
const shotsDir = process.env.E2E_SCREENSHOTS;
const deployed = Boolean(process.env.E2E_BASE_URL);
// Test values only. Locally the Graph API is a fake (e2e/fake-graph.mjs); against a deployment
// nothing is sent to customers (no reply is sent, and the number is a test value).
const WA = {
  phoneNumberId: "109876543210987",
  number: "+97143123456",
  appSecret: "e2e-app-secret-0123456789",
  verifyToken: "e2e-verify-token-0123456789",
  customer: "971521234567",
};

test("sign in with two-step verification, work a lead through the CRM, sign out", async ({ page }) => {
  const shot = async (name: string) => {
    if (shotsDir) await page.screenshot({ path: `${shotsDir}/${name}.png`, fullPage: true });
  };
  // Any Content-Security-Policy violation anywhere in the journey fails the test.
  const cspViolations: string[] = [];
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
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
    await expect(page.getByTitle("Arrives in Phase 4").first()).toBeVisible();
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

  await test.step("a person chooses the UAE tier; nothing can be quoted while pricing is inactive", async () => {
    const pricing = page.locator("section").filter({ has: page.getByRole("heading", { name: "Pricing", exact: true }) });
    await expect(pricing.getByText("Not chosen yet")).toBeVisible();
    await pricing.getByRole("button", { name: "Choose" }).click();
    const dialog = page.getByRole("dialog", { name: "Choose the tier for this customer" });
    await dialog.getByLabel("Tier / schedule").selectOption({ label: "Tier B (no active pricing yet)" });
    await dialog.getByLabel("Why this applies to this customer").fill("Agreed with the parent on the call");
    await dialog.getByRole("button", { name: "Save choice" }).click();
    await expect(pricing.getByText("Tier B", { exact: true })).toBeVisible();
    await pricing.getByRole("button", { name: "Show package options" }).click();
    await expect(pricing.getByRole("status").filter({ hasText: "No figures can be offered" })).toContainText(
      "NO_APPROVED_PRICING_FOR_MARKET",
    );
  });

  await test.step("pricing shows the supplied books, unchanged and not active", async () => {
    await page.getByRole("link", { name: "Pricing" }).click();
    await expect(page.getByRole("heading", { name: "Pricing", exact: true })).toBeVisible();
    await expect(page.getByRole("note").filter({ hasText: "No pricing is active" })).toBeVisible();
    await expect(page.getByRole("note").filter({ hasText: "Pricing catalogue incomplete" })).toBeVisible();
    await expect(page.getByRole("table", { name: "Price books" }).getByRole("row")).toHaveCount(14); // header + 13
    await expect(page.getByRole("row", { name: /USD-SCHEDULE-A/ })).toContainText("No market (unconfirmed)");
    await page.getByRole("link", { name: "UK-GBP-TIER-A" }).click();
    await expect(page.getByRole("table", { name: "Packages" })).toContainText("GBP 285");
    const checklist = page.getByRole("list", { name: "Activation checklist" });
    await expect(checklist).toContainText("G-05 Tax treatment set not passed");
    await expect(checklist).toContainText("Q-PAY-04");
    await shot("05-pricing-checklist");
    await page.goBack();
    await page.goBack();
  });

  await test.step("import a pricing sheet as drafts, write and try a rule, see promotions switched off", async () => {
    await page.getByRole("link", { name: "Pricing" }).first().click();
    const tabs = page.getByRole("navigation", { name: "Pricing sections" });
    await tabs.getByRole("link", { name: "Import sheet" }).click();
    await page.getByLabel("Pricing sheet (CSV)").setInputFiles({
      name: "family.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(
        "price_book_code,currency,plan_type,audience,unit_type,quantity,package_total\n" +
          "QA-QAR-FAMILY,QAR,standard,restricted,hour,30,1650\n" +
          "QA-QAR-FAMILY,QAR,standard,restricted,hour,60,3000\n",
      ),
    });
    await page.getByRole("button", { name: "Check sheet" }).click();
    await expect(page.getByRole("region", { name: "Changes to QA-QAR-FAMILY" })).toContainText("New price book (restricted)");
    await page.getByLabel("Source document").fill("Family sheet (E2E)");
    await page.getByLabel("What changed and who supplied it").fill("New family pricing for testing");
    await page.getByRole("button", { name: "Create draft versions" }).click();
    await expect(page.getByText("1 draft version(s) created")).toBeVisible();

    await tabs.getByRole("link", { name: "Rules" }).click();
    await page.getByRole("button", { name: "New rule" }).click();
    const ruleDialog = page.getByRole("dialog", { name: "New pricing rule" });
    await ruleDialog.getByLabel("Code").fill("NEW-CUSTOMERS");
    await ruleDialog.getByLabel("Name").fill("New customers from the website");
    await ruleDialog.getByRole("button", { name: "Save draft" }).click();
    const row = page.getByRole("row", { name: /NEW-CUSTOMERS v1/ });
    await expect(row).toContainText("Draft");
    await row.getByRole("button", { name: "Try it" }).click();
    const tester = page.getByRole("dialog", { name: "Try NEW-CUSTOMERS" });
    await tester.getByRole("button", { name: "Evaluate" }).click();
    await expect(tester.getByRole("status")).toContainText("Applies to this customer");
    await tester.getByRole("button", { name: "Close" }).click();

    await tabs.getByRole("link", { name: "Promotions" }).click();
    await expect(page.getByRole("note")).toContainText("promotions.enabled");
    await page.getByRole("link", { name: "Customers" }).click();
    await page.getByRole("link", { name: "Mona Haddad" }).click();
    await expect(page.getByRole("heading", { name: "Mona Haddad" })).toBeVisible();
  });

  await test.step("a quotation can be started, but no package can be quoted while pricing is inactive", async () => {
    const quotes = page.locator("section").filter({ has: page.getByRole("heading", { name: "Quotations", exact: true }) });
    await quotes.getByRole("button", { name: "New quotation" }).click();
    const dialog = page.getByRole("dialog", { name: "New quotation" });
    await dialog.getByLabel("For opportunity").selectOption({ label: "Mona Haddad: new enquiry" });
    await dialog.getByRole("button", { name: "Create draft" }).click();
    await expect(page.getByRole("heading", { name: /Quotation Q-\d{6} rev 1/ })).toBeVisible();
    await expect(page.getByText("No lines yet")).toBeVisible();
    await expect(page.getByRole("alert").filter({ hasText: "no active, approved pricing" })).toBeVisible();
    await page.getByRole("button", { name: "Cancel quotation" }).click();
    const cancel = page.getByRole("dialog", { name: "Cancel quotation" });
    await cancel.getByLabel("Reason").fill("Waiting for Mixt to confirm pricing");
    await cancel.getByRole("button", { name: "Confirm" }).click();
    await expect(page.getByText("Cancelled", { exact: true })).toBeVisible();
    await page.getByRole("link", { name: "Quotations" }).click();
    await expect(page.getByText("Nothing is waiting for you.")).toBeVisible();
    await page.getByRole("link", { name: "Customers" }).click();
    await page.getByRole("link", { name: "Mona Haddad" }).click();
  });

  await test.step("add a note and see the timeline after the worker runs", async () => {
    await page.getByLabel("New note").fill("Prefers WhatsApp after 5pm");
    await page.getByRole("button", { name: "Add note" }).click();
    await expect(page.getByText("Prefers WhatsApp after 5pm")).toBeVisible();
    runWorkerOnce(); // locally; a deployment's own worker delivers the events within seconds
    await expect(async () => {
      await page.reload();
      // A deployment's worker delivers timeline events every few seconds, possibly in separate passes.
      await expect(page.getByText("Household created")).toBeVisible({ timeout: 2_000 });
      await expect(page.getByText("Pricing market confirmed: United Arab Emirates")).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 30_000 });
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
    // Wait until the Tasks page has loaded its list, so the form below is the Tasks form.
    await expect(page).toHaveURL(/\/tasks$/);
    await expect(page.getByRole("table", { name: "Tasks" }).or(page.getByText("Nothing here."))).toBeVisible();
    await page.getByLabel("Title").fill("Call Mona about the trial");
    const saved = page.waitForResponse((r) => r.url().endsWith("/api/v1/tasks") && r.request().method() === "POST");
    await page.getByRole("button", { name: "Add task" }).click();
    expect((await saved).status()).toBe(201);
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

  const csrf = async () => (await page.context().cookies()).find((c) => c.name === "mixt_csrf")?.value ?? "";
  const putSetting = async (key: string, value: unknown) => {
    const response = await page.request.put(`/api/v1/settings/${key}`, {
      data: { value, status: "safe_default" },
      headers: { "X-CSRF-Token": await csrf() },
    });
    expect(response.status(), await response.text()).toBe(200);
  };
  let webhookPath = "";
  const postWebhook = async (body: string) => {
    const response = await page.request.post(`${apiBase}${webhookPath}`, {
      data: body,
      headers: { "Content-Type": "application/json", "X-Hub-Signature-256": metaSignature(WA.appSecret, body) },
    });
    expect(response.status()).toBe(200);
    runWorkerOnce(); // locally; the API also processes it straight away, and a deployment has a worker
  };

  await test.step("connect WhatsApp: secrets are saved, Meta's handshake works, the number is switched on", async () => {
    await page.getByRole("link", { name: "Integrations" }).click();
    await expect(page.getByText("Nothing connected yet.")).toBeVisible();
    await page.getByRole("button", { name: "Connect WhatsApp" }).click();
    const dialog = page.getByRole("dialog", { name: "Connect a WhatsApp number" });
    await dialog.getByLabel("Graph API version").fill("v21.0");
    await dialog.getByLabel("WhatsApp Business Account ID").fill("123456789012345");
    await dialog.getByLabel("Phone number ID").fill(WA.phoneNumberId);
    await dialog.getByLabel("Phone number", { exact: true }).fill(WA.number);
    await dialog.getByLabel("System user access token").fill("EAAG-e2e-test-token-0123456789");
    await dialog.getByLabel("App secret").fill(WA.appSecret);
    await dialog.getByLabel("Webhook verify token").fill(WA.verifyToken);
    await dialog.getByRole("button", { name: "Save connection" }).click();
    await expect(page.getByText("Not switched on")).toBeVisible();
    await expect(page.getByText("EAAG-e2e-test-token")).toHaveCount(0); // secrets are never shown
    webhookPath = ((await page.getByTestId("webhook-url").textContent()) ?? "").match(/\/webhooks\/whatsapp\/[0-9a-f-]+/)?.[0] ?? "";
    expect(webhookPath).not.toBe("");
    const handshake = await page.request.get(
      `${apiBase}${webhookPath}?hub.mode=subscribe&hub.verify_token=${WA.verifyToken}&hub.challenge=e2e-challenge`,
    );
    expect(await handshake.text()).toBe("e2e-challenge");
    const forged = await page.request.post(`${apiBase}${webhookPath}`, {
      data: whatsappWebhook(WA.phoneNumberId, { from: WA.customer, text: "forged" }),
      headers: { "Content-Type": "application/json", "X-Hub-Signature-256": "sha256=00" },
    });
    expect(forged.status()).toBe(401);
    await putSetting("channels.whatsapp.numbers", [WA.number]);
    await page.reload();
    await expect(page.getByText("Switched on", { exact: true })).toBeVisible();
    if (!deployed) {
      await page.getByRole("button", { name: "Check connection" }).click();
      await expect(page.getByRole("status").filter({ hasText: "Connected." })).toBeVisible();
      await page.getByRole("button", { name: "Sync templates" }).click();
      await expect(page.getByText(/Templates: 1 new/)).toBeVisible();
      await page.getByRole("button", { name: "Approve for use" }).click();
      await expect(page.getByRole("button", { name: "Retire" })).toBeVisible();
    }
    await shot("05-integrations");
  });

  await test.step("a customer writes on WhatsApp; the message waits in the inbox until linked", async () => {
    await postWebhook(
      whatsappWebhook(WA.phoneNumberId, { from: WA.customer, name: "Layla Nasser", text: "Hello, do you offer IGCSE Physics tutoring?" }),
    );
    await page.getByRole("link", { name: "Inbox" }).click();
    await page.getByRole("tab", { name: "Not linked" }).click();
    await expect(async () => {
      await page.getByRole("tab", { name: "All" }).click();
      await page.getByRole("tab", { name: "Not linked" }).click();
      await expect(page.getByRole("button", { name: /Layla Nasser/ })).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 30_000 });
    await page.getByRole("button", { name: /Layla Nasser/ }).click();
    await expect(page.getByTestId("inbound-message")).toContainText("IGCSE Physics");
    await expect(page.getByText(/Reply window open until/)).toBeVisible();
  });

  await test.step("turn the conversation into a lead, leave a note for the team and reply", async () => {
    await page.getByRole("button", { name: "Create lead" }).click();
    const dialog = page.getByRole("dialog", { name: "Create a lead from this conversation" });
    await dialog.getByLabel("Country of residence").fill("AE");
    await dialog.getByLabel("Student first name").fill("Rami");
    await dialog.getByRole("button", { name: "Create lead" }).click();
    await expect(page.getByRole("complementary", { name: "Customer" }).getByRole("link", { name: "Layla Nasser" })).toBeVisible();
    await page.getByRole("tab", { name: "Internal note" }).click();
    await page.getByLabel("Internal note").fill("Asked about Physics; prefers calls after 5pm");
    await page.getByRole("button", { name: "Add note" }).click();
    await expect(page.getByTestId("internal-note").last()).toContainText("after 5pm");
    if (!deployed) {
      await page.getByRole("tab", { name: "Reply" }).click();
      await page.getByLabel("Reply").fill("Hello Layla, yes we do. When would suit you for a free trial lesson?");
      await page.getByRole("button", { name: "Send", exact: true }).click();
      await expect(page.getByTestId("outbound-message")).toContainText("free trial lesson");
      await expect(async () => {
        await page.reload();
        await expect(page.getByTestId("outbound-message")).toContainText("Sending", { timeout: 2_000 });
      }).toPass({ timeout: 30_000 });
      await postWebhook(whatsappWebhook(WA.phoneNumberId, { from: WA.customer, statuses: [{ id: "wamid.e2e1", status: "read" }] }));
      await expect(async () => {
        await page.reload();
        await expect(page.getByTestId("outbound-message")).toContainText("Read", { timeout: 2_000 });
      }).toPass({ timeout: 30_000 });
    }
    await shot("06-inbox");
    await page.getByRole("complementary", { name: "Customer" }).getByRole("link", { name: "Layla Nasser" }).click();
    await expect(page.getByRole("link", { name: /WhatsApp · Layla Nasser/ })).toBeVisible();
  });

  if (!deployed) {
    await test.step("email: connect a mailbox, receive a customer email, reply in the thread", async () => {
      // The local test servers have no TLS, which only local runs allow, so this mailbox is created
      // through the API; the form in the dashboard offers TLS and STARTTLS only.
      const created = await page.request.post("/api/v1/integrations/mailbox", {
        data: {
          display_name: "Mixt Sales",
          address: "sales@mixt.example",
          username: "sales@mixt.example",
          password: "app-password-1234",
          imap_host: "127.0.0.1",
          imap_port: 8143,
          imap_security: "none",
          smtp_host: "127.0.0.1",
          smtp_port: 8025,
          smtp_security: "none",
        },
        headers: { "X-CSRF-Token": await csrf() },
      });
      expect(created.status(), await created.text()).toBe(201);
      await putSetting("channels.email.provider", "imap_smtp");
      await putSetting("channels.email.mailboxes", ["sales@mixt.example"]);
      await page.getByRole("link", { name: "Integrations" }).click();
      const card = page.locator("section").filter({ hasText: "Mixt Sales · Email (IMAP/SMTP)" });
      await card.getByRole("button", { name: "Check connection" }).click();
      await expect(card.getByRole("status").filter({ hasText: "signed in to IMAP and SMTP" })).toBeVisible();
      await card.getByRole("button", { name: "Check for new mail now" }).click(); // first check: starts from now
      await expect(card.getByRole("status").filter({ hasText: "0 new message(s)" })).toBeVisible();
      const raw = [
        "From: Hana Saleh <hana.saleh@example.com>",
        "To: Mixt Sales <sales@mixt.example>",
        "Subject: Maths tutoring for Year 9",
        `Date: ${new Date().toUTCString()}`,
        "Message-ID: <e2e-email-1@example.com>",
        "Content-Type: text/plain; charset=utf-8",
        "",
        "Hello, my son needs help with Year 9 maths. Do you have evening slots?",
        "",
      ].join("\r\n");
      expect((await page.request.post("http://127.0.0.1:8144/inbox", { data: raw })).status()).toBe(200);
      await card.getByRole("button", { name: "Check for new mail now" }).click();
      await expect(card.getByRole("status").filter({ hasText: "1 new message(s)" })).toBeVisible();
      runWorkerOnce();
      await page.getByRole("link", { name: "Inbox" }).click();
      await page.getByRole("tab", { name: "Not linked" }).click();
      await expect(async () => {
        await page.getByRole("tab", { name: "All" }).click();
        await page.getByRole("tab", { name: "Not linked" }).click();
        await expect(page.getByRole("button", { name: /Hana Saleh/ })).toBeVisible({ timeout: 2_000 });
      }).toPass({ timeout: 30_000 });
      await page.getByRole("button", { name: /Hana Saleh/ }).click();
      await expect(page.getByText("Subject: Maths tutoring for Year 9")).toBeVisible();
      await expect(page.getByTestId("inbound-message").last()).toContainText("evening slots");
      await expect(page.getByRole("tab", { name: "Template" })).toHaveCount(0); // templates are WhatsApp only
      await page.getByLabel("Reply").fill("Hello Hana, yes: we have evening slots. Shall we book a free trial?");
      await page.getByRole("button", { name: "Send", exact: true }).click();
      await expect(async () => {
        await page.reload();
        await expect(page.getByTestId("outbound-message").last()).toContainText("Sent", { timeout: 2_000 });
      }).toPass({ timeout: 30_000 });
      const sent = (await (await page.request.get("http://127.0.0.1:8144/sent")).json()) as {
        to: string[];
        subject: string;
        in_reply_to: string;
      }[];
      expect(sent.at(-1)).toEqual({
        to: ["hana.saleh@example.com"],
        subject: "Re: Maths tutoring for Year 9",
        in_reply_to: "<e2e-email-1@example.com>",
      });
      await shot("07-email");
    });
  }

  await test.step("the website form is off until switched on; then an enquiry arrives as a lead", async () => {
    const form = {
      guardian_first_name: "Rana",
      guardian_last_name: "Haddad",
      email: "rana.haddad@example.com",
      country: "QA",
      message: "British curriculum, Year 9 maths",
      utm: { source: "e2e" },
    };
    expect((await page.request.post(`${apiBase}/public/v1/enquiries`, { data: form })).status()).toBe(404);
    await putSetting("web.enquiries.enabled", true);
    expect((await page.request.post(`${apiBase}/public/v1/enquiries`, { data: form })).status()).toBe(202);
    await putSetting("web.enquiries.enabled", false);
    await page.getByRole("link", { name: "Leads" }).click();
    await expect(page.getByRole("cell", { name: "Rana Haddad" })).toBeVisible();
  });

  await test.step("sign out", async () => {
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);
    await page.goto("/customers");
    await expect(page).toHaveURL(/\/login$/);
  });

  expect(cspViolations).toEqual([]);
  expect(pageErrors).toEqual([]);
});

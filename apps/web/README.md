# Mixt AI dashboard

Next.js 16 · React 19 · TypeScript (strict) · Tailwind CSS 4 · TanStack Query. Design direction: [docs/09](../../docs/09-dashboard-ux.md).

## What exists today (Phase 1c, hardened in 1d)

| Screen | What it does |
|--------|--------------|
| Sign in, two-step verification, password change | Email + password; "Sign in with Google/Microsoft" when single sign-on is switched on (`auth.sso`) with clear error messages; QR-code set-up for an authenticator app; code entry; forced change of a temporary password; rate-limit messages |
| Overview | My open and overdue tasks, open opportunities and SLA breaches, pipeline by stage, latest enquiries, number of outstanding decisions |
| Leads | List with status filter; new-lead form (country never sets pricing; out-of-market and duplicate outcomes explained); two-step spreadsheet import with per-row report |
| Customers | Search and lifecycle filter; household page with market confirmation (with a note), contacts with contact details and consent status, students and subjects, opportunities with budget in its currency, notes (team or private), tasks, tags, timeline |
| Duplicates | Review possible duplicate households; merge (with confirmation) or dismiss |
| Sales Pipeline | Board by stage; move with the stage's requirements shown, lost reason and revisit date; "Still needed" list when a move is refused |
| Tasks & Follow-ups | My tasks, add with due date, complete and reopen; automatic reminders marked |
| Team | Staff, roles with market scope, last sign-in; add users with a temporary password |
| Pricing (2a) | "Catalogue incomplete" and "No pricing is active" banners; all price books with markets and status; markets without pricing; per book: version history, packages exactly as supplied with the derived rate labelled, activation checklist with the open question behind each blocker, benefits, and actions by permission (record Mixt's confirmation or tax treatment with a decision reference, submit, approve, send back, reject, activate, retire, load a correction, assign a market, confirm the Ireland schedule relationship) |
| Pricing (2b) | Sections for price books, sheet import (template, per-row problems, comparison with the current version, anomaly notes, apply as drafts), rules (JSON editor with examples, approve, retire, tester with trace, list of usable facts) and promotions (draft, submit, approve, activate, cancel, with what still prevents activation); rules can be attached per market on a price book; unit definition confirmation |
| Quotations (2c) | Customer page: the customer's quotations and "New quotation" for an opportunity. Quotation page: lines from the offered packages (with promotion and discount), validity and notes, the checks still failing, submit, approve as sales or pricing, send back, PDF download, issue to a contact, the customer's answer (with price-change confirmation), revision and cancellation. Quotations menu: the approvals waiting for you |
| Customer pricing (2a) | On the household page: who chose which tier and why, choosing or changing it (with a reason), and the package options (special prices and promotion offers marked separately), or the reason none can be offered plus what to tell the customer; confidential pricing requests and approvals for people who may see them |
| Inbox (3a, 3b) | WhatsApp and email conversations: list (all, mine, unassigned, not linked; search; active or closed) with unread counts and live updates; the thread with delivery status, failures and "Send again"; reply (only inside the 24-hour window), template (with the reason each one cannot be sent now, variables and a preview) or internal note; link to a household (optionally saving the number on the contact) or create a lead; take or assign; close and reopen. Customer page: the household's conversations. Blocked numbers: add and lift blocks with a reason |
| Integrations (3a, 3b) | Connect a mailbox over IMAP/SMTP (TLS or STARTTLS), check it, "Check for new mail now", replace its app password. Connect WhatsApp (secrets are never shown again), webhook address and verification state, check connection, sync templates and approve them for use, replace a secret, disconnect, webhooks that failed with "Process again" |
| Settings | Outstanding decisions and all settings; change values with status and decision reference (permission-checked; dual-approval settings locked until Phase 2) |

**Security (1d):** every page gets a Content-Security-Policy with a fresh nonce (`src/proxy.ts`): no inline scripts without the nonce, no `eval` in production, no framing. Pages are therefore rendered per request. The image (`Dockerfile`) runs the standalone server as a non-root user.

Modules from later phases appear in the navigation, greyed out, with the phase they arrive in. Colours are placeholders until Mixt's brand assets arrive (Q-BRD-01).

## Run locally

Start the backend first (see [services/backend/README.md](../../services/backend/README.md)) on port 8000, plus the worker for the timeline. Then:

```bash
npm install
npm run dev
```

Open http://localhost:3000. Requests to `/api/v1/*` are proxied to the backend (`MIXT_API_ORIGIN`, default `http://localhost:8000`), so the API's HttpOnly session cookie works on the same origin.

## Checks (same as CI)

```bash
npm run typecheck
npm run build
npm run e2e
```

`npm run e2e` starts the real backend and dashboard and wipes the database in `E2E_DATABASE_URL` (default `postgresql+psycopg://postgres@localhost:5433/mixt_e2e`). It creates the application role `mixt_app_e2e` and migrates as the owner, so the API runs with data-only rights as in staging. It then creates an Owner and drives a browser through these steps:
* the nonce-based Content-Security-Policy check;
* sign-in and two-step set-up;
* leads, market confirmation, notes and the timeline;
* pipeline checks and tasks;
* a US enquiry;
* connecting WhatsApp (Meta's handshake, a forged webhook refused, the number switched on, templates synced and approved), a customer message arriving in the "Not linked" queue, a lead created from it, an internal note, a reply sent through a local fake Graph API (`e2e/fake-graph.mjs`; nothing is ever sent to Meta) and its read receipt;
* email: a mailbox on local IMAP and SMTP test servers (`services/backend/scripts/fake_mail_servers.py`) is checked, a customer email arrives in the "Not linked" queue with its subject, and the reply is sent in the customer's thread (`Re:` subject, `In-Reply-To`);
* the website form refusing enquiries until switched on, then an enquiry arriving as a lead;
* sign-out.

Any CSP violation or browser error fails the test. Set `E2E_SCREENSHOTS=<dir>` to save screenshots.

`E2E_BASE_URL=https://localhost npx playwright test` runs the same journey against a running deployment, such as the staging stack in `infra/staging`. In that mode there are no local servers and no database reset, the deployment's own worker delivers the timeline events, and the WhatsApp reply and email steps are skipped (a deployment talks to the real services).

When the API changes, regenerate the types (CI fails if they are out of date):

```bash
(cd ../../services/backend && uv run python scripts/export_openapi.py ../../apps/web/openapi.json)
npm run gen:api
```

# Mixt AI: AI Sales & CRM Platform for Mixt Academy

> **Project status: Phases 1 and 2 are code complete; Phase 3a (WhatsApp, unified inbox, website form) and 3b (email) are built.** No price is live until Mixt confirms the pricing data, and no channel is connected until Mixt's accounts exist. Architecture approved by Mixt on 2026-11-10 (BD-032).
> **Built so far:**
> * The backend: sign-in with mandatory two-step verification and optional single sign-on; roles and record-level access; a tamper-evident audit log; reference data with the US blocked; the settings register.
> * The CRM: lead intake and spreadsheet import, duplicate review and merge, the sales pipeline, tasks, notes, tags and the customer timeline.
> * The **dashboard** for all of the above.
> * Hardening: separate database roles, rate limiting, a nonce-based Content-Security-Policy, a staging stack with HTTPS, and encrypted backups with a restore check.
> * **Pricing (2a):** the 13 supplied price books are stored exactly as supplied and locked against changes, and **none is active**. The catalogue also has: the activation checklist (each blocker shown with the open question behind it), review and two-person approval, corrections as new versions, per-customer tier choice by a person, and the price-lookup engine that refuses with clear reasons.
> * **Pricing (2b):** pricing-sheet import (checked and compared, applied as drafts), eligibility and minimum-purchase rules with a tester, confidential per-customer pricing (two people, own market only), and promotions kept separate from list prices (switched off until Mixt confirms one).
> * **Quotations (2c):** built only from the customer's offered options; list price, promotion and discount shown separately; approved by people other than the preparer (any discount also needs a pricing approval); frozen with a fingerprint on approval; PDF made from the frozen version; issue, customer answer, revisions and expiry.
> * **Channels and inbox (3a):** the integration framework (encrypted secrets, signature-checked webhooks stored once, retries, dead letters and replay); the WhatsApp Cloud API adapter, tested against a fake Graph API and **not yet connected** (24-hour window, templates approved by Meta and by Mixt, consent checks, opt-out words and a suppression list); the unified inbox (matching to households, a "Not linked" queue, assignment, notes, lead creation, live updates); the website enquiry form (off until the consent wording is approved).
> * **Email (3b):** Mixt uses neither Google Workspace nor Microsoft 365 (BD-034), so email works with any service over IMAP and SMTP: read-only checks for new mail, replies in the customer's thread, bounces and opt-out replies block the address, spoofed senders are never linked to a customer. **Not yet connected** (Mixt's mailbox details are needed, Q-COM-03).
>
> 324 backend tests run against a real PostgreSQL database as the least-privileged application role. A browser end-to-end test drives the real stack, and CI starts the full staging stack on every push and checks it over HTTPS.
> Details: [services/backend/README.md](services/backend/README.md), [apps/web/README.md](apps/web/README.md), [operations runbook](docs/14-operations-runbook.md).
> **Not built yet:** file storage for WhatsApp media and email attachments (Phase 3c), AI agents (Phase 4) and everything in later phases. A permanently hosted staging server needs a server or cloud account from Mixt. Real customer data waits for Q-CMP-01, Q-CMP-02 and Q-TECH-04.
> A feature counts as implemented only when working code and passing tests exist for it.

## Try it

* **In your browser, with nothing to install:** on GitHub, click **Code**, then **Codespaces**, then **Create codespace**. The dashboard opens by itself when it's ready, and the sign-in details appear in the terminal.
* **On your own computer:** run `infra/demo/demo.sh`, then open <http://localhost:3000>. If Docker is missing on Kali, Debian or Ubuntu, the script offers to install it.

Both are demos for synthetic data only. Details are in [infra/demo/README.md](infra/demo/README.md).

Mixt AI is an AI sales system being built for Mixt Academy, an international online 1:1 tutoring company.
It will cover the whole customer journey: lead capture, qualification, AI-assisted sales conversations,
tutor matching, trials, pricing, quotations, payments, enrolment, retention, renewals and referrals.
All of it runs on **one central CRM database**, with **people in control** of every important action.

## Document index

| # | Document | What it covers |
|---|----------|----------------|
| 00 | [Requirements analysis](docs/00-requirements-analysis.md) | Confirmed facts vs. assumptions, functional and non-functional requirements, risks |
| 01 | [System architecture](docs/01-architecture.md) | Principles, components, technology stack, main flows, deployment, key decisions |
| 02 | [Database schema](docs/02-database-schema.md) | Conventions, ERD, table-by-table design for every domain |
| 03 | [AI agent architecture](docs/03-ai-agent-architecture.md) | Agent runtime, memory, tools, permissions, approvals, guardrails, the 14 agents |
| 04 | [Pricing engine](docs/04-pricing-engine.md) | Price books, versions, tiers, promotions, how a price is chosen, validation, quotations |
| 05 | [Pricing data register](docs/05-pricing-data-register.md) | Pricing data supplied so far, as given, with derived rates and points to check. **Not active** |
| 06 | [CRM structure](docs/06-crm-structure.md) | Household/student model, lifecycle, pipeline stages, retention and referrals |
| 07 | [External integrations](docs/07-integrations.md) | WhatsApp Cloud API, Gmail, Microsoft 365, Meta Lead Ads, Instagram, web forms and chat, payments, calendars |
| 08 | [Security and privacy](docs/08-security-privacy.md) | Login, roles, encryption, webhooks, audit, backups, data protection, children's data |
| 09 | [Dashboard and UX](docs/09-dashboard-ux.md) | Navigation, modules, design system direction |
| 10 | [Implementation roadmap](docs/10-roadmap.md) | Phases, deliverables, exit criteria, critical-path external lead times |
| 11 | [Open questions](docs/11-open-questions.md) | Remaining missing business information, with the phase each question blocks and the safe default meanwhile |
| 12 | [Decision log](docs/12-decision-log.md) | Every business and architecture decision with date, status (CONFIRMED / OPEN / PROPOSED) and source |
| 13 | [Configurable settings](docs/13-configurable-settings.md) | Safe-default settings for outstanding decisions, so the architecture is not blocked |
| 14 | [Operations runbook](docs/14-operations-runbook.md) | Deploying staging, releases, secrets and rotation, backups, restore checks, recovery, rate limits, single sign-on set-up |

## Non-negotiable rules (apply to every phase)

1. **Mixt operates in 13 markets** (UAE, Qatar, Kuwait, Saudi Arabia, Oman, Bahrain, Malaysia, Hong Kong, Singapore, Indonesia, South Korea, UK, Ireland). **The United States is not a target market**: never a target, acquisition or operating market.
   USD price schedules exist, but their market assignment is **unconfirmed**; **USD is never associated with the US**. Currency, phone prefix and curriculum never decide a customer's market.
2. **No invented pricing.** The system never makes up prices or package durations, never infers pricing for a country that has none, never uses currency conversion to produce an official price, and never mixes one market's pricing with another's.
3. **Tiers are never selected automatically.** UK and UAE each have two valid tiers and Ireland two separate schedules; a person with the right permission selects one per customer until Mixt defines a rule.
4. **The pricing database is incomplete** (more sheets are being collected). No pricing tier, schedule or promotion is active until it passes the activation gate (see [04](docs/04-pricing-engine.md#5-lifecycle-and-the-activation-gate)). Supplied figures are never silently changed; corrections become new versions and originals are preserved. Promotional terms stay separate from standard pricing.
5. **People approve important actions by default.** AI prepares; a person approves.
6. **One customer's confidential pricing or data is never shown to another customer.**
7. **No feature is described as implemented unless working code and tests exist.**
8. **Open business decisions never block the architecture and are never guessed.** Each has a safe default setting until Mixt answers it (see [13](docs/13-configurable-settings.md)). Confirmed curricula are Irish, SABIS, American and British; IB is not included unless separately approved.

## Technology (approved)

Next.js + React + TypeScript + Tailwind CSS · Python + FastAPI · PostgreSQL 17 (CI also on 16) (+ pgvector later) · Redis + Celery workers ·
Claude API and OpenAI API behind interchangeable model adapters · Docker · Alembic migrations · GitHub Actions CI.

## Repository layout

```
docs/                 architecture, decisions, open questions (start with docs/12-decision-log.md)
apps/web/             Next.js dashboard (Phase 1c, hardened in 1d): see its README
services/backend/     FastAPI backend (Phases 1a, 1b, 1d): see its README to run and test it
infra/demo/           one-command demo (demo.sh), also used by GitHub Codespaces (.devcontainer/)
infra/compose.yaml    local PostgreSQL, Redis, API and worker for development
infra/staging/        staging stack: Caddy (TLS), API, worker, dashboard, PostgreSQL roles, Redis, backups (docs/14)
infra/backup/         encrypted backup and restore image
.github/workflows/    backend-ci: lint, strict types, tests on PostgreSQL 16 and 17 with Redis, dependency audit, Docker build
                      web-ci: type check, build, API-type drift check, browser end-to-end test
                      staging-ci: full stack from the Dockerfiles, browser journey over HTTPS, smoke test, backup, restore check;
                                  the one-command demo started and signed in to like a person would
                      images: publishes container images to GitHub Container Registry (main branch)
```

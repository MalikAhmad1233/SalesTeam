# 10: Implementation Roadmap

Status: **APPROVED 2026-11-10** (BD-032) · **Phases 0 to 2 code complete; Phase 3a (WhatsApp, unified inbox, website form) done 2026-11-10; Phase 3b (email) waits for Q-COM-03.** Nothing customer-facing is switched on until Mixt's accounts and confirmations are in place.

## Approach

- **Data correctness before automation.** CRM and pricing are built and tested before any AI talks to customers.
- **People in the loop before autonomy.** Channels launch with human-only messaging, then AI drafts with approval, then gradual autonomy.
- **Each phase ships usable software** to the Mixt team and ends with explicit exit criteria.
- **Definition of done** (every phase): working code, automated tests passing in CI, migrations, documentation updated, security review of new surfaces, and a demo to Mixt. Nothing is reported as implemented without this.
- **Effort sizing** is relative (S/M/L/XL). Calendar estimates depend on team size and the answers in [11](11-open-questions.md) (Q-TEAM-05), so none are given yet.

## Phase overview

```mermaid
flowchart LR
  P0[Phase 0<br/>Discovery & data<br/>confirmation] --> P1[Phase 1<br/>Foundation & core CRM]
  P1 --> P2[Phase 2<br/>Pricing engine &<br/>quotations]
  P1 --> P3[Phase 3<br/>Channels & unified inbox]
  P2 --> P4[Phase 4<br/>AI core + Sales Agent<br/>draft mode]
  P3 --> P4
  P4 --> P5[Phase 5<br/>Tutors, matching,<br/>trials & scheduling]
  P4 --> P6[Phase 6<br/>Payments, enrolment<br/>& hours ledger]
  P5 --> P7[Phase 7<br/>Retention, renewals,<br/>referrals, more lead sources]
  P6 --> P7
  P7 --> P8[Phase 8<br/>Analytics, Manager Agent,<br/>hardening, autonomy]
```

Phases 2 and 3 can run in parallel after Phase 1. Phases 5 and 6 can run in parallel after Phase 4.

---

## Phase 0: Discovery and business-data confirmation: **complete (2026-11-10)**

| Deliverables | Status |
|--------------|--------|
| Requirements analysis, architecture, schema, agent design, pricing design, CRM design, integrations, security, UX direction, roadmap, open questions | **Drafted in this repository: awaiting approval** |
| Pricing data register (supplied figures, verified by script against the brief) | Drafted; **incomplete and not active** |
| First round of business confirmations applied (markets, US exclusion, USD rule, curricula, 1:1 model, class = 1 hour, UK/UAE tiers, Ireland schedules, Malaysia correction, HK plans, catalogue incomplete) | **Done (v0.2, 2026-11-09)**: see [decision log](12-decision-log.md) |
| Configurable settings register with safe defaults for open decisions | **Drafted**: [13](13-configurable-settings.md) |
| Answers to remaining questions | Waiting for Mixt; only 3 questions block Phase 1 production use ([11 §2](11-open-questions.md#2-questions-that-block-phase-1)) |
| External accounts started (Meta verification, WhatsApp numbers, email platform access, payment provider, cloud account, LLM provider terms) | Waiting for Mixt |
| Legal review kick-off (hosting region, consent wording, children's data, AI disclosure) | Waiting for Mixt |

**Exit criteria:** architecture **explicitly approved** by Mixt (BD-031): **met on 2026-11-10 (BD-032)**. Open business questions do **not** hold up the start of Phase 1: each has a safe default setting. Before Phase 1 is used with real customer data: hosting region (Q-CMP-02), legal/privacy sign-off (Q-CMP-01) and production cloud account (Q-TECH-04).

## Phase 1: Foundation and core CRM (L): **code complete**; waiting only for a hosted staging server and the real-data blockers

Delivered in four increments, each tested and pushed:

| Increment | Scope | Status |
|-----------|-------|--------|
| **1a** Backend foundation | Project set-up, CI, core utilities, migrations, sign-in with MFA, sessions, CSRF, roles with market scope, record-level access, hash-chained audit log, reference data (US blocked), settings register with Outstanding decisions, CRM households/contacts/contact points/consents/students/subjects/exams | **Done 2026-11-10**: 90 automated tests, 91.6% coverage; details in [services/backend/README.md](../services/backend/README.md) |
| **1b** Leads and pipeline | Lead intake (manual entry and two-step CSV import), duplicate review and merge, configurable pipeline stages with required checks, opportunities, tasks, notes, tags, customer timeline, outbox and scheduled-action worker, scheduling preferences API | **Done 2026-11-10**: 119 automated tests in total, 93% coverage; implementation notes IN-08 to IN-14 |
| **1c** Dashboard | Next.js shell, design system, sign-in and MFA screens, Leads, Customers (360 v1), Pipeline, Tasks, Team, Settings incl. Outstanding decisions | **Done 2026-11-10**: production build, browser end-to-end test against the real stack, typed API client checked in CI; implementation notes IN-15 to IN-19; details in [apps/web/README.md](../apps/web/README.md) |
| **1d** Hardening | Rate limiting (Redis), SSO option, nonce-based Content-Security-Policy, staging deployment, separate migration and application database roles, backups and restore check | **Done 2026-11-10**: 202 backend tests (93% coverage) run as the least-privileged application role; single sign-on tested against a fake provider with signed tokens; the staging stack ([infra/staging](../infra/staging)) is built from the real Dockerfiles and started on every push (`staging-ci`), which runs the browser journey over HTTPS, a security smoke test, an encrypted backup and a restore check; implementation notes IN-20 to IN-26; runbook [14](14-operations-runbook.md). **Not done:** a permanently hosted staging server. It needs a server or cloud account, which Mixt has to provide; staging may use a temporary account with synthetic data (Q-TECH-04). |

Original Phase 1 scope:


- Monorepo scaffolding; Docker compose; CI (lint, types, tests, migrations, import boundaries, secret/dependency scanning).
- Core platform: config, structured logging, tracing, error tracking, money and time-zone utilities, outbox + event dispatcher, scheduled actions, dead-letter handling.
- Identity: users, MFA, sessions, roles/permissions, record-level policy module, agent principals.
- Audit log with hash chain.
- Reference data: markets (US excluded at DB level), currencies, curricula, boards, qualifications, subjects.
- CRM: accounts, contacts, contact points, consents, students, subjects, exams, preferences, notes, tags, merge.
- Leads (manual + CSV import with consent evidence), pipeline and stages, opportunities, tasks, timeline.
- Dashboard shell with design system; Leads, Customers (360 v1), Pipeline, Tasks, Team, Settings screens.

**Exit criteria:** Mixt staff can log in with MFA, manage leads/households/students/opportunities/tasks with correct permissions; audit trail verified; ≥ 85% coverage on domain modules; staging deployed.

**Exit criteria status (2026-11-10):** sign-in with MFA, permissions, leads/households/students/opportunities/tasks and audit verification are met and tested; coverage is 93%. "Staging deployed" is met as a deployable stack that CI starts and checks on every push. A permanently running staging server is still to be set up, once a server or cloud account is available ([14 §2](14-operations-runbook.md#2-first-deployment-a-linux-server-with-docker)).

## Phase 2: Pricing engine and quotations (L): **code complete**; waiting for Mixt's confirmations before any price goes live

| Increment | Scope | Status |
|-----------|-------|--------|
| **2a** Catalogue, lifecycle, tiers, resolution | Price books, versions, entries, market assignments, benefits; the 13 supplied books loaded as **locked drafts**, figures unchanged; activation gate G-01 to G-09 with the open question behind each blocker; review, four-eyes and dual approval, activation, supersession, retirement; corrections as new versions with anomaly notes; per-customer tier selection by a person; deterministic resolution engine with the docs/04 error codes; pricing API; Pricing screens and the customer's pricing card | **Done 2026-11-10**: golden test of all 91 entries against an independent reading of docs/05; database guards (entries append-only, versions never deleted, activation requirements as constraints); property and market-isolation tests; implementation notes IN-27 to IN-32. **No pricing is active.** |
| **2b** Promotions, rules, special pricing, imports | Promotions (separate from list prices, mandatory end date), eligibility and minimum-purchase rules with a tester, confidential customer pricing assignments, spreadsheet import with diff | **Done 2026-11-10**: rule language with type checking and a tester; rules applied in price lookup; confidential pricing (two people, own market only, leakage tests); promotions as separate offers with expiry, test that no standard figure changes; CSV import with per-row checks, diff and anomaly notes, applied as drafts only. Implementation notes IN-33 to IN-37. **Nothing is switched on**: no rule, special price or promotion exists, and promotions stay off (Q-PRC-05). Discount authority moved to 2c, where discounts are used. |
| **2c** Quotations | Builder from resolved options, validation V-01 to V-09, discount authority and approvals, immutable snapshots, PDF, revisions | **Done 2026-11-10**: lines only from the customer's offered options; list price, promotion and discount kept as separate amounts; approvals by people other than the preparer (sales approval, plus pricing approval for any discount while the discount authority is empty); snapshot frozen with SHA-256 on approval and protected by the database; PDF made only from the snapshot (same snapshot, same bytes); issue to a contact of the customer; outcome recording with the price-change rule; revisions; expiry by the worker. Implementation notes IN-38 to IN-42. |


- Price books, versions, entries, market assignments, benefits, policies, rules, promotions, customer pricing assignments, discount authority.
- Activation gate; dual approval; history and diffs; spreadsheet import with anomaly detection.
- Deterministic resolution engine with error codes; pricing API.
- Quotations: builder from resolved options, approvals, immutable snapshots, PDF, revisions.
- Load the 13 supplied price books as **drafts**, figures unchanged; tier selection mode `manual` for UK, UAE and Ireland; Malaysia as version 1 (a corrected set, if supplied, as version 2).
- Per-market tier selection, correction versions, separate promotions, settings register and "Outstanding decisions" view.

**Exit criteria:** golden tests for all 91 supplied entries; property tests (no cross-market results, no restricted books without assignment, no conversion); activation gate tests; a test quotation round trip in staging; **Mixt's pricing owner signs off each book before it is activated**.

**Exit criteria status (2026-11-10):** golden tests for all 91 entries, property tests, activation-gate tests and a quotation round trip (create, approve, freeze, PDF, issue, accept) pass in CI. Staging runs the same code. **Open: Mixt's pricing owner has not signed off any book (G-01), so nothing is active.**

## Phase 3: Communication channels and unified inbox (L): **3a done**; 3b (email) waits for Mixt's choice of platform

| Increment | Scope | Status |
|-----------|-------|--------|
| **3a** Framework, WhatsApp, inbox, website form | Integration framework (connections, encrypted secrets, verified webhook store, retries with backoff, dead letters and replay); WhatsApp Cloud API (handshake, signatures, inbound, statuses, templates, 24-hour window, consent, opt-out and opt-in words, suppression list, error mapping); unified inbox (matching, "Not linked" queue, assignment, take-over, notes, lead creation, live updates); website enquiry form | **Done 2026-11-10**, built and tested against a fake Graph API (unit, API and end-to-end tests: signatures valid, invalid and tampered; redelivered webhooks stored once; failures replayed from the dead-letter queue). Implementation notes IN-43 to IN-48. **Not connected**: connecting needs Mixt's Meta business account, a registered number and templates (EXT-01 to EXT-03). Not in 3a: downloading media files (needs private object storage), quiet hours and frequency caps (no automated or bulk sending exists yet; every message is sent by a person), and a separate ingress process (webhooks are served by the API on their own path and can move behind it later). |
| **3b** Email, media storage | Email adapter (Gmail **or** Microsoft 365), media download to private storage with malware scanning | Waiting for Q-COM-03 (which platform) and Q-COM-05 (sending domain). |


- Integration framework: connections, encrypted credentials, ingress service, webhook verification, raw event store, retries, DLQ UI.
- WhatsApp Cloud API: inbound/outbound, templates, 24-hour window, media, statuses, opt-in/opt-out, quiet hours, frequency caps.
- Email adapter (Gmail **or** Microsoft 365, whichever Mixt uses): inbound sync, send, threading, bounces, unsubscribe.
- Website enquiry form endpoint (bot protection, consent capture).
- Unified inbox (human-only messaging at this stage), assignment, takeover, SSE live updates.

**Exit criteria:** end-to-end tests with WhatsApp **test numbers** and test mailboxes; webhook signature tests (valid/invalid/replayed); no lost messages under simulated outages (replay from DLQ); Mixt team using the inbox in staging.

**Exit criteria status (2026-11-10):** webhook signature tests (valid, invalid, tampered, redelivered) and replay from the dead-letter queue pass; the end-to-end test drives the inbox against a fake Graph API. **Open:** tests with Meta's WhatsApp test numbers once Mixt's account exists; email (3b); the Mixt team using the inbox in staging.

## Phase 4: AI core and Sales Agent in draft mode (XL)

- Model Gateway with Claude and OpenAI adapters, profiles, fallback, cost tracking.
- Agent runtime: router, context builder (single-account scope), tool registry, Action Policy Engine, approval inbox, guardrails (price, claims, confidentiality, market, channel, safety, promise), escalations, kill switches, circuit breakers, run logs.
- Knowledge base with approval and pgvector retrieval; first content from Mixt (curricula, FAQs, objection library, policies).
- Agents: **AI Sales Agent** (draft mode), **Lead Qualification**, **Follow-up**, **Pricing** (tool wrapper), **WhatsApp Communication** and **Email Outreach** (channel logic).
- Evaluation harness, scenario suites, red-team set, CI gate.
- Shadow mode (L0) → draft & approve (L1) rollout.

**Exit criteria:** eval suite passes all hard checks (no unlisted prices, correct escalation for unpriced markets like Kuwait, no USD-as-US, no leakage, injection resistance); ≥ 2 weeks of L1 use with acceptance metrics reported; zero guardrail escapes.

## Phase 5: Tutors, matching, trials and scheduling (L)

- Tutor profiles, capabilities, languages, compliance checks, availability, capacity.
- Tutor Matching Agent (filters + scoring + rationale) with coordinator approval.
- Scheduling Agent: slot finding across time zones, calendar integration, video links, reminders, reschedules, no-shows, trial outcomes.

**Exit criteria:** property tests for slot finding (no double booking, respects availability and time zones incl. DST changes in UK/Ireland); coordinator approval flow in production.

## Phase 6: Payments, enrolment and hours ledger (L)

- Payment provider integration (chosen in Phase 0), invoices, payment links, webhook verification, manual bank-transfer confirmation.
- Payment Tracking Agent (reminders in draft mode).
- Student registration and package activation; hours ledger; expiry, pause/resume and family sharing driven by package policies; lesson-consumption feed (native or import).

**Exit criteria:** ledger invariants tested; reconciliation tests for partial/over/duplicate payments; currency mismatch blocked; finance sign-off.

## Phase 7: Retention, renewals, referrals and more lead sources (M–L)

- Retention Agent: health scores, low-balance/expiry alerts, renewal opportunities, check-ins, win-back.
- Referral programmes, codes, attribution, reward approval.
- Facebook/Instagram Lead Ads; Instagram DMs (if in scope); website chat widget; Lead Generation and Lead Research agents; Negotiation Agent.

**Exit criteria:** renewal opportunities created correctly in tests and pilot; Lead Ads reconciliation proven (no missed leads); chat widget passes security review.

## Phase 8: Analytics, Sales Manager Agent, hardening and autonomy (M–L)

- Reports module and metric definitions; Sales Manager Agent (digests, SLA monitoring, QA sampling, anomaly alerts).
- Performance and load tests; external penetration test; DR restore drill; privacy workflows (DSAR, retention jobs) complete.
- Autonomy reviews: promote specific low-risk action types to L2 where metrics justify it, with management sign-off.

**Exit criteria:** pen-test findings fixed; restore drill within RTO; documented autonomy decisions.

---

## Critical path and external lead times

| Item | Needed by | Risk if late |
|------|-----------|--------------|
| Meta business verification + WhatsApp number + templates | Phase 3 | WhatsApp channel blocked |
| Email platform admin access (Google/Microsoft) | Phase 3 | Email channel blocked |
| Pricing confirmations (tiers, eligibility, tax, USD market assignment, Ireland schedules) | Phase 2 exit | Pricing stays inactive → AI cannot quote |
| Hosting region / legal advice | Before any real customer data (Phase 1 production) | Re-platforming risk |
| Knowledge content (curricula explanations, FAQs, objection library, tone guide) | Phase 4 | AI quality |
| Payment provider merchant account | Phase 6 | Payments tracking only manual |
| Meta App Review for Lead Ads | Phase 7 | Lead Ads intake blocked |

## Suggested team (to confirm: Q-TEAM-05)

Tech lead / architect · 2 backend engineers (Python) · 1 frontend engineer (Next.js) · 1 AI engineer (agents, evals) · part-time DevOps/security · product owner from Mixt (decisions, content, acceptance) · Mixt pricing owner and sales lead as reviewers.

# 12: Decision Log

Every business decision and architecture decision, with date, status and source. **This log is the reference**: where another document disagrees with it, this log wins and the other document gets corrected.

## Status values

| Status | Meaning |
|--------|---------|
| **CONFIRMED** | Confirmed by Mixt Academy. Quoted from the source as closely as possible. |
| **OPEN** | Not yet answered. Tracked as a question in [11-open-questions](11-open-questions.md). Until it is answered, the system uses a **safe default setting** ([13-configurable-settings](13-configurable-settings.md)), never a guessed answer. |
| **PROPOSED** | Architecture or design decision awaiting Mixt's approval. |
| **APPROVED** | Architecture decision approved by Mixt (none yet). |
| **SUPERSEDED** | Replaced by a later entry (kept for history). |

## Sources

| Ref | Source | Date |
|-----|--------|------|
| S1 | Project initialisation brief ("PROJECT INITIALIZATION – MIXT AI") | 2026-11-09 |
| S2 | Mixt clarification: "confirmed business information" items 1–12 and documentation instructions | 2026-11-09 |
| S3 | Mixt approval of the architecture ("Approved") | 2026-11-10 |
| S4 | Mixt instruction to continue with Phase 1d and to proceed without asking for permission at each step | 2026-11-10 |

Where a decision is partly confirmed, the confirmed part is logged here as **CONFIRMED** and the remaining unknown is a separate **OPEN** question.

---

## A. Business decisions

| ID | Date | Decision | Status | Source | Open remainder | Docs |
|----|------|----------|--------|--------|----------------|------|
| BD-001 | 2026-11-09 | Company: **Mixt Academy**, international online tutoring. | CONFIRMED | S1 | — | 00 |
| BD-002 | 2026-11-09 | Service model: **personalised 1:1 online tutoring**. | CONFIRMED | S1, S2 #5 | Whether any other format exists (e.g. group classes): Q-BIZ-02 | 00, 06 |
| BD-003 | 2026-11-09 | Services: academic support; exam preparation; past-paper practice; curriculum-specific tutoring; long-term academic improvement. | CONFIRMED | S1 | — | 00 |
| BD-004 | 2026-11-09 | Mixt **operates in 13 markets**: United Arab Emirates, Qatar, Kuwait, Saudi Arabia, Oman, Bahrain, Malaysia, Hong Kong, Singapore, Indonesia, South Korea, United Kingdom, Ireland. | CONFIRMED | S1, S2 #1 | Which markets go live on Mixt AI first: Q-MKT-06 | 00, 02, 04 |
| BD-005 | 2026-11-09 | **The United States is NOT a target market.** Never a target, customer-acquisition or operating market. | CONFIRMED | S1, S2 #2 | Handling of unsolicited enquiries from non-target countries: Q-MKT-02 | All |
| BD-006 | 2026-11-09 | **USD pricing schedules exist; their market assignment is unconfirmed. USD is never associated with the US market.** | CONFIRMED | S1, S2 #3 | Which market(s) USD applies to: Q-MKT-01 | 04, 05 |
| BD-007 | 2026-11-09 | Four confirmed curriculum categories: **Irish, SABIS, American, British**. | CONFIRMED | S1, S2 #4 | Grade structures: Q-ACA-03 | 00, 02, 06 |
| BD-008 | 2026-11-09 | **IB is not on the confirmed curriculum list** and is not added unless separately approved. | CONFIRMED | S2 | Whether IB or other programmes will ever be offered: Q-ACA-04 | 00, 02, 13 |
| BD-009 | 2026-11-09 | British curriculum includes Cambridge, Pearson Edexcel, AQA, OCR, IGCSE, GCSE, AS and A-Levels. | CONFIRMED | S1 | Which board × qualification combinations are taught: Q-ACA-02 | 00, 02 |
| BD-010 | 2026-11-09 | Supplied figures are **package totals**; hourly rates and package totals are **separate fields**. | CONFIRMED | S1 | Whether per-hour rates are official advertised rates: Q-PRC-08 | 04, 05 |
| BD-011 | 2026-11-09 | **One class = one hour** for the supplied class-based pricing schedules, unless a package-specific exception is confirmed later. | CONFIRMED | S1, S2 #6 | — (closes former Q-PRC-07) | 04, 05 |
| BD-012 | 2026-11-09 | **UK has two separate, valid pricing tiers** (Tier A and Tier B). | CONFIRMED | S2 #7 | How a customer is placed on a tier: Q-PRC-02. **Neither tier is active.** | 04, 05 |
| BD-013 | 2026-11-09 | **UAE has two separate, valid pricing tiers** (Tier A and Tier B). | CONFIRMED | S2 #8 | How a customer is placed on a tier: Q-PRC-02. **Neither tier is active.** | 04, 05 |
| BD-014 | 2026-11-09 | **Ireland has two separate pricing schedules** (Schedule A and Schedule B), kept separate. | CONFIRMED | S1, S2 #9 | Their relationship and eligibility: Q-PRC-03. **Neither schedule is active.** | 04, 05 |
| BD-015 | 2026-11-09 | **Malaysia package totals have been mathematically corrected.** | CONFIRMED | S2 #10 | Whether the MYR figures held in the register (received 2026-11-09) **are** the corrected totals, or a further corrected set is to be supplied: Q-PRC-21 | 05 |
| BD-016 | 2026-11-09 | **Hong Kong has separate Standard and Premium plans.** | CONFIRMED | S1, S2 #11 | Minimum purchase / Standard above 40h: Q-PRC-10 | 04, 05 |
| BD-017 | 2026-11-09 | **Additional pricing sheets are still being collected. The pricing database remains marked INCOMPLETE.** | CONFIRMED | S1, S2 #12 | Which sheets and when: Q-PRC-01 | 04, 05, 13 |
| BD-018 | 2026-11-09 | Supplied pricing figures are **never silently changed**; **all original schedules are preserved**; corrections are recorded as new versions with the original kept. | CONFIRMED | S2 | — | 02, 04, 05 |
| BD-019 | 2026-11-09 | Never invent prices or durations; never assume pricing for a country without it; never use converted currency values as official prices; never mix one country's pricing with another's; never select a special pricing tier automatically. | CONFIRMED | S1 | — | 04 |
| BD-020 | 2026-11-09 | **Unconfirmed pricing tiers, pricing and promotional rules are not activated.** | CONFIRMED | S1, S2 | — | 04, 05 |
| BD-021 | 2026-11-09 | **Promotional terms are kept separate from standard pricing.** | CONFIRMED | S2 | Promotion details: Q-PRC-05 | 02, 04 |
| BD-022 | 2026-11-09 | Benefits and policies are stored separately by package, country and plan; never applied to another country without administrator approval. | CONFIRMED | S1 | Which packages the supplied benefits apply to: Q-PKG-01, Q-PKG-03 | 04, 05 |
| BD-023 | 2026-11-09 | Every quotation records the exact price, currency, tier and package version used. | CONFIRMED | S1 | — | 04 |
| BD-024 | 2026-11-09 | One customer's confidential pricing is never disclosed to another customer. | CONFIRMED | S1 | — | 03, 04 |
| BD-025 | 2026-11-09 | One centralised CRM shared by all modules and agents; no separate customer databases. | CONFIRMED | S1 | — | 01, 02 |
| BD-026 | 2026-11-09 | Several students can sit under one parent account. | CONFIRMED | S1 | Multiple guardians / split households: Q-CRM-02 | 06 |
| BD-027 | 2026-11-09 | Default AI mode: **AI prepares suggestions; a person approves important actions.** Approval levels are configurable. | CONFIRMED | S1 | Any exceptions at launch: Q-AI-02 | 03, 13 |
| BD-028 | 2026-11-09 | Integrations use official APIs and secure credentials, with webhooks, status tracking, retries and audit logs. | CONFIRMED | S1 | — | 07 |
| BD-029 | 2026-11-09 | Preferred stack: Next.js, React, TypeScript, Tailwind CSS; Python, FastAPI; PostgreSQL; Redis + background workers; Claude API and OpenAI API via model adapters; Docker, environment variables, migrations. | CONFIRMED (preference) | S1 | — | 01 |
| BD-030 | 2026-11-09 | Outstanding business decisions are handled with **configurable settings**; the architecture is not blocked by operational unknowns. | CONFIRMED | S2 | — | 13 |
| BD-031 | 2026-11-09 | **No full implementation until Mixt explicitly approves the architecture.** | CONFIRMED (satisfied by BD-032) | S1, S2 | — | 10 |
| BD-032 | 2026-11-10 | **The architecture (docs 00–13, v0.2) is approved. Implementation starts with Phase 1.** Open business questions stay OPEN and keep their safe defaults. | CONFIRMED | S3 | — | All |
| BD-033 | 2026-11-10 | **Implementation proceeds through the roadmap without asking for approval at each step.** This does not cover business decisions: open questions stay OPEN with their safe defaults, and the non-negotiable rules (no invented pricing, no US market, human approval by default) are unchanged. | CONFIRMED | S4 | — | 10 |

## B. Architecture decisions

Proposed 2026-11-09; **APPROVED 2026-11-10** (BD-032). ADR-01 to ADR-10 are described in [01 §13](01-architecture.md#13-key-architecture-decisions-summary).

| ID | Decision | Status | Implements |
|----|----------|--------|-----------|
| ADR-01 | Modular monolith + separate worker processes | APPROVED | BD-025, BD-029 |
| ADR-02 | PostgreSQL as the single system of record, incl. job intent | APPROVED | BD-025 |
| ADR-03 | Deterministic pricing engine; LLMs may only call it | APPROVED | BD-019 |
| ADR-04 | Action Policy Engine between agents and side effects | APPROVED | BD-027 |
| ADR-05 | Agents interact only through CRM, events and typed tools | APPROVED | BD-025 |
| ADR-06 | Celery + Redis transport; PostgreSQL outbox and scheduled actions | APPROVED | BD-028 |
| ADR-07 | Synchronous ORM sessions in domain services | APPROVED | — |
| ADR-08 | pgvector inside PostgreSQL for knowledge retrieval | APPROVED | — |
| ADR-09 | Money as integer minor units + ISO currency code | APPROVED | BD-019 |
| ADR-10 | Immutable price-book versions; quotations snapshot what they used | APPROVED | BD-018, BD-023 |
| ADR-11 | **Configurable settings register** with safe defaults for every outstanding business decision; settings carry `safe_default` / `confirmed` status and a decision-log reference ([13](13-configurable-settings.md)) | APPROVED | BD-030 |
| ADR-12 | **Tier/schedule selection mode per market**, default `manual`: a person with permission picks the tier or schedule for each customer, with a reason. The engine refuses (`TIER_DECISION_REQUIRED`) until that happens. AI never selects. Applies to UK, UAE and Ireland. | APPROVED | BD-012, BD-013, BD-014, BD-019 |
| ADR-13 | **Pricing market is confirmed by staff.** Currency, phone prefix and curriculum are **never** used to decide a customer's market (USD ≠ US; American curriculum ≠ US; British curriculum ≠ UK pricing; Irish curriculum ≠ Ireland pricing). | APPROVED | BD-005, BD-006 |
| ADR-14 | **Corrections are new versions** (`change_type = correction`, `supersedes_version_id`); original versions stay readable in pricing history and are never overwritten. | APPROVED | BD-015, BD-018 |
| ADR-15 | **Promotions never modify standard entries.** They live only as separate promotion records or separately labelled promotional price books; quotations show list price and promotion as separate items; promotions are globally disabled until the first promotion is confirmed. | APPROVED | BD-020, BD-021 |
| ADR-16 | **Safe-default principle:** while a decision is OPEN the system takes the most restrictive safe path (escalate to a person, show no figure, send nothing automatically), never a guessed business value. | APPROVED | BD-019, BD-030 |

## C. Implementation notes

Choices made while building (Phase 1a: IN-01 to IN-07; Phase 1b: IN-08 to IN-14; Phase 1c: IN-15 to IN-19), within the approved architecture. None of them changes a business decision.

| ID | Date | Note | Why |
|----|------|------|-----|
| IN-01 | 2026-11-10 | Setting **definitions** (schema, safe default, permission, open question) live in code (`settings/registry.py`); only **values** are stored in `system_settings`. Doc 02 originally showed a `setting_definitions` table. | Definitions belong with the code that interprets them; a test keeps code and docs/13 in sync. |
| IN-02 | 2026-11-10 | New setting `crm.unassigned_pool_visible_to_reps` (safe default `true`, Q-TEAM-02). | Who sees unassigned accounts is a business choice, so it is a setting rather than hard-coded. |
| IN-03 | 2026-11-10 | The audit hash chain is computed by a database trigger and serialised with an advisory lock held until commit. | Every write path is covered, including ones that bypass the app. Fine at expected volume; can move to a background chainer if writes grow a lot. |
| IN-04 | 2026-11-10 | CI tests on PostgreSQL 16 and 17. | Local development uses 16; production target is 17+. |
| IN-05 | 2026-11-10 | A contact point that already exists on another household is flagged as a "possible duplicate" without revealing which household. | Customer data isolation: reps must not learn about accounts they cannot see. |
| IN-06 | 2026-11-10 | Accounts living outside the 13 operating markets (including the US) are flagged `out_of_market` automatically for a person to review; the pricing market itself is only ever set by a person. | Implements BD-005 and ADR-13 with the safe default `markets.out_of_market_handling = human_review`. |
| IN-07 | 2026-11-10 | Sales reps hold neither read nor write access to restricted learning-needs notes; Sales Managers and Tutor Coordinators do. | Data minimisation for children's sensitive data; adjustable through roles (Q-TEAM-02). |
| IN-08 | 2026-11-10 | Pipeline stages and lost reasons are **settings** (`crm.pipeline_stages`, with the checks each stage requires; `crm.lost_reasons`), not separate tables. `crm.stage_required_fields` is merged into `crm.pipeline_stages`. Only the new-business pipeline exists; renewal and upsell pipelines arrive with retention (Phase 7). | One mechanism for every outstanding decision (ADR-11); a stage or reason still in use cannot be removed. |
| IN-09 | 2026-11-10 | Until trials, quotations and payments exist, moving into those stages needs a written note. A household becomes `prospect` when an opportunity reaches Qualified; `customer` is still only set by payments (Phase 6). | No invented evidence; lifecycle stays truthful. |
| IN-10 | 2026-11-10 | Lead intake matches existing households by phone or email (phone and WhatsApp numbers count as the same). Similar household names in the same country (trigram similarity ≥ 0.6) become duplicate candidates for a person to merge or dismiss. A merge moves contacts, students, opportunities, tasks, notes, tags, timeline and leads, archives the merged household and keeps a snapshot; undoing a merge is not automated. | Implements docs/06 §3 with a person deciding every merge. |
| IN-11 | 2026-11-10 | Spreadsheet import is two steps (validate, then commit). Imports never record marketing consent (Q-CMP-10 safe default). Personal data is removed from the import report once it is committed or discarded. Only managers and admins can import. | Consent must have evidence; data minimisation. |
| IN-12 | 2026-11-10 | Background work (event delivery, scheduled reminders) runs in a simple polling worker: `python -m mixt.cli worker`. The timeline updates when the worker runs, normally within seconds. Celery queues (ADR-06) are introduced when external channels start sending (Phase 3). | Nothing is lost if the worker is down: events wait in the database outbox. |
| IN-13 | 2026-11-10 | Notes cannot be edited or deleted (corrections are new notes). Private notes are visible only to their author, also on the timeline; note text is never copied into the timeline. | Trustworthy record; privacy between colleagues. |
| IN-14 | 2026-11-10 | Sales reps can enter leads and manage opportunities, tasks and notes. Importing, merging, reviewing out-of-market leads and creating campaigns or tags are manager/admin permissions. | Keeps bulk and destructive actions with managers; adjustable through roles (Q-TEAM-02). |
| IN-15 | 2026-11-10 | The dashboard calls the API on the same origin: Next.js proxies `/api/v1/*` to FastAPI, so the session cookie stays HttpOnly and there are no cross-origin requests. Security headers and a Content-Security-Policy are set by Next.js; the policy still allows inline scripts (needed by Next.js), and a nonce-based policy is planned for 1d (**done: IN-24**). | Simplest secure set-up for cookie sessions. |
| IN-16 | 2026-11-10 | The dashboard's API types are generated from the backend's OpenAPI schema; CI fails if they are out of date. | Front end and back end cannot drift apart silently. |
| IN-17 | 2026-11-10 | Modules from later phases are visible in the navigation, greyed out, with the phase they arrive in. | Shows the plan honestly; nothing pretends to work. |
| IN-18 | 2026-11-10 | Brand colours are the placeholder tokens from docs/09 (Q-BRD-01). The Inter font is used only if installed on the device; no font is downloaded from external services. | No guessed branding; no third-party requests from the dashboard. |
| IN-19 | 2026-11-10 | Browser end-to-end tests run the real backend, database and dashboard; the background worker is run once inside the test where the timeline is checked. | Tests the actual system, not mocks. |
| IN-20 | 2026-11-10 | **Three database roles.** The schema owner runs migrations (`mixt.cli migrate`, under an advisory lock) and then resets the application role's grants: SELECT/INSERT/UPDATE/DELETE on tables, no DDL or TRUNCATE, read-only `alembic_version`, and only SELECT/INSERT on append-only tables (found from their `reject_modification()` triggers). A read-only role takes backups. In staging/production the API and worker refuse to start with an over-privileged role or a schema behind the code. The whole test suite and the browser test run as the application role. | The append-only audit log is now protected twice (privileges and triggers); a compromised API cannot change the schema or erase history. |
| IN-21 | 2026-11-10 | **Rate limiting** uses GCRA (one value per key; burst of N, then N per period). It runs in Redis through an atomic Lua script that uses Redis's clock, or in memory locally. Limits apply per client address, per signed-in user, per account and per address for sign-in, per session for two-step codes, per user for password changes and imports, and per address for single sign-on. Keys are hashed (no personal data in Redis). If Redis is down, requests are let through and an error is logged. `X-Forwarded-For` is only believed from `MIXT_TRUSTED_PROXIES`. | Account lockout still protects sign-in during a Redis outage; taking the whole CRM down would be worse. Trusting forwarded addresses only from the proxy prevents address spoofing in limits and audit entries. |
| IN-22 | 2026-11-10 | **Backups:** `pg_dump` every 6 h by the read-only role, encrypted with age to a public key (the private key is kept off the server), with a manifest (schema revision, row counts, last audit entry and hash) and checksums; 14-day retention, newest 3 always kept, optional off-site copy command. **Restore check:** restore into a separate empty PostgreSQL and verify schema, tables, integrity triggers, the full audit hash chain, the manifest's last audit entry and the US exclusion. | Proves backups are usable, not just present. Six-hourly dumps do not meet the proposed RPO ≤ 15 min (Q-TECH-03): production needs managed point-in-time recovery or WAL archiving in addition (runbook §5). |
| IN-23 | 2026-11-10 | **Single sign-on** is OpenID Connect (authorization code with PKCE, state and nonce). ID tokens must be RS256-signed by the provider's published keys and are checked for issuer, audience, expiry and `azp`. It signs in existing active staff only: the first sign-in links the account by email, and after that only the provider's stable subject is used. Microsoft accounts are accepted only from a configured tenant id. Two-step codes are still required unless the new setting `auth.sso_satisfies_mfa` (safe default `false`, Q-TECH-01) is on **and** the provider reports a multi-factor sign-in. Off unless `auth.sso` selects a provider and its client credentials are configured. | No self-registration and no role changes through single sign-on; avoids the known "matching email from another organisation" weakness; Mixt keeps control of whether provider MFA is trusted. |
| IN-24 | 2026-11-10 | **Content-Security-Policy with a fresh nonce per request** (Next.js proxy): `script-src 'self' 'nonce-…' 'strict-dynamic'`, style nonce, `object-src 'none'`, `frame-ancestors 'none'`; no `unsafe-inline` or `unsafe-eval` in production. All pages are rendered per request so they carry the nonce. The browser test fails on any CSP violation. | Blocks injected scripts (XSS) even if one slipped through output escaping. |
| IN-25 | 2026-11-10 | **Staging stack** (`infra/staging`, Docker Compose): Caddy for TLS (Let's Encrypt or an internal CA), HSTS and request size limits; API, worker, dashboard, PostgreSQL 17, Redis and backups. Containers have read-only filesystems, no capabilities and `no-new-privileges`. The database network has no internet access. `migrate` runs before the API and worker and has no encryption keys. CI (`staging-ci`) builds it from the real Dockerfiles and checks it from the outside on every push. Images are published to GitHub Container Registry from the main branch (`images`). | Provider-neutral while the cloud provider is open (Q-TECH-04): it runs on any Linux server with Docker and moves to managed services later without code changes. |
| IN-26 | 2026-11-10 | Deployed environments do not publish the OpenAPI schema or API docs. Readiness reports database, schema revision and rate-limit store. The worker stops cleanly on SIGTERM and writes a heartbeat for its health check. The API process no longer applies uvicorn's own proxy-header handling (IN-21 does it). | Smaller attack surface; health checks reflect whether the service can do useful work. |

## D. Change history

| Date | Version | Change | Source |
|------|---------|--------|--------|
| 2026-11-09 | 0.1 | Phase 0 documentation drafted (docs 00–11). | S1 |
| 2026-11-09 | 0.2 | Clarification S2 applied: BD-002, BD-004 to BD-008, BD-011 to BD-018, BD-020, BD-021, BD-030, BD-031 recorded or re-confirmed; former Q-PRC-07 closed; Q-PRC-21 added (Malaysia correction); tier selection mode (ADR-12), market rule (ADR-13), correction versioning (ADR-14), promotion separation (ADR-15), safe defaults (ADR-16) and the settings register (doc 13) added; open questions re-classified by the phase they block. | S2 |
| 2026-11-09 | 0.2 | **US-market audit:** every document was searched for any association of the US with a market (incl. "US", "United States", "America", "US$", "$" amounts, "+1" phone prefix). **No document assigned, targeted or assumed a US market**: the US appears only as an excluded country, and "American" only as a curriculum name. To prevent any future inference, explicit rules were added: currency, curriculum and phone prefix never decide a market (ADR-13); a database trigger blocks a US market (DB-01); automated tests are listed in [04 §18](04-pricing-engine.md#18-tests-phase-2-exit-criteria). | S2 |
| 2026-11-09 | 0.2 | **Pricing figures unchanged.** The register was re-checked by script after the update: 13 books and 91 entries, identical to the brief. | S2 |
| 2026-11-10 | 0.3 | Architecture approved (BD-032); ADR-01 to ADR-16 marked APPROVED. Phase 1a (backend foundation) implemented with tests; implementation notes IN-01 to IN-07 added. | S3 |
| 2026-11-10 | 0.4 | Phase 1b (leads, pipeline, tasks, notes, tags, timeline, outbox, scheduled actions) implemented with tests; implementation notes IN-08 to IN-14; settings `crm.pipeline_stages` (now including stage checks) and `crm.lost_reasons` added to docs/13. | S3 |
| 2026-11-10 | 0.5 | Phase 1c (dashboard) implemented: sign-in and two-step screens, Overview, Leads and import, Customers and household page, Duplicates, Pipeline, Tasks, Team, Settings with Outstanding decisions; browser end-to-end test; implementation notes IN-15 to IN-19. | S3 |
| 2026-11-10 | 0.6 | Phase 1d (hardening) implemented on Mixt's instruction S4 (BD-033): database roles, rate limiting, single sign-on option, nonce-based CSP, staging stack, encrypted backups and restore check; implementation notes IN-20 to IN-26; setting `auth.sso_satisfies_mfa` added to docs/13; operations runbook (doc 14) added. | S4 |

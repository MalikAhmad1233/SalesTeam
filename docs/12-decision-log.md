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
| BD-031 | 2026-11-09 | **No full implementation until Mixt explicitly approves the architecture.** | CONFIRMED | S1, S2 | — | 10 |

## B. Architecture decisions

All **PROPOSED** (dated 2026-11-09), awaiting approval. ADR-01 to ADR-10 are described in [01 §13](01-architecture.md#13-key-architecture-decisions-summary).

| ID | Decision | Status | Implements |
|----|----------|--------|-----------|
| ADR-01 | Modular monolith + separate worker processes | PROPOSED | BD-025, BD-029 |
| ADR-02 | PostgreSQL as the single system of record, incl. job intent | PROPOSED | BD-025 |
| ADR-03 | Deterministic pricing engine; LLMs may only call it | PROPOSED | BD-019 |
| ADR-04 | Action Policy Engine between agents and side effects | PROPOSED | BD-027 |
| ADR-05 | Agents interact only through CRM, events and typed tools | PROPOSED | BD-025 |
| ADR-06 | Celery + Redis transport; PostgreSQL outbox and scheduled actions | PROPOSED | BD-028 |
| ADR-07 | Synchronous ORM sessions in domain services | PROPOSED | — |
| ADR-08 | pgvector inside PostgreSQL for knowledge retrieval | PROPOSED | — |
| ADR-09 | Money as integer minor units + ISO currency code | PROPOSED | BD-019 |
| ADR-10 | Immutable price-book versions; quotations snapshot what they used | PROPOSED | BD-018, BD-023 |
| ADR-11 | **Configurable settings register** with safe defaults for every outstanding business decision; settings carry `safe_default` / `confirmed` status and a decision-log reference ([13](13-configurable-settings.md)) | PROPOSED | BD-030 |
| ADR-12 | **Tier/schedule selection mode per market**, default `manual`: a person with permission picks the tier or schedule for each customer, with a reason. The engine refuses (`TIER_DECISION_REQUIRED`) until that happens. AI never selects. Applies to UK, UAE and Ireland. | PROPOSED | BD-012, BD-013, BD-014, BD-019 |
| ADR-13 | **Pricing market is confirmed by staff.** Currency, phone prefix and curriculum are **never** used to decide a customer's market (USD ≠ US; American curriculum ≠ US; British curriculum ≠ UK pricing; Irish curriculum ≠ Ireland pricing). | PROPOSED | BD-005, BD-006 |
| ADR-14 | **Corrections are new versions** (`change_type = correction`, `supersedes_version_id`); original versions stay readable in pricing history and are never overwritten. | PROPOSED | BD-015, BD-018 |
| ADR-15 | **Promotions never modify standard entries.** They live only as separate promotion records or separately labelled promotional price books; quotations show list price and promotion as separate items; promotions are globally disabled until the first promotion is confirmed. | PROPOSED | BD-020, BD-021 |
| ADR-16 | **Safe-default principle:** while a decision is OPEN the system takes the most restrictive safe path (escalate to a person, show no figure, send nothing automatically), never a guessed business value. | PROPOSED | BD-019, BD-030 |

## C. Change history

| Date | Version | Change | Source |
|------|---------|--------|--------|
| 2026-11-09 | 0.1 | Phase 0 documentation drafted (docs 00–11). | S1 |
| 2026-11-09 | 0.2 | Clarification S2 applied: BD-002, BD-004 to BD-008, BD-011 to BD-018, BD-020, BD-021, BD-030, BD-031 recorded or re-confirmed; former Q-PRC-07 closed; Q-PRC-21 added (Malaysia correction); tier selection mode (ADR-12), market rule (ADR-13), correction versioning (ADR-14), promotion separation (ADR-15), safe defaults (ADR-16) and the settings register (doc 13) added; open questions re-classified by the phase they block. | S2 |
| 2026-11-09 | 0.2 | **US-market audit:** every document was searched for any association of the US with a market (incl. "US", "United States", "America", "US$", "$" amounts, "+1" phone prefix). **No document assigned, targeted or assumed a US market**: the US appears only as an excluded country, and "American" only as a curriculum name. To prevent any future inference, explicit rules were added: currency, curriculum and phone prefix never decide a market (ADR-13); a database trigger blocks a US market (DB-01); automated tests are listed in [04 §18](04-pricing-engine.md#18-tests-phase-2-exit-criteria). | S2 |
| 2026-11-09 | 0.2 | **Pricing figures unchanged.** The register was re-checked by script after the update: 13 books and 91 entries, identical to the brief. | S2 |

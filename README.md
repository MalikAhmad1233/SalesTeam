# Mixt AI: AI Sales & CRM Platform for Mixt Academy

> **Project status: Phase 0, product discovery and business-data collection** · Documentation v0.2 (2026-11-09): first round of Mixt confirmations applied.
> This repository contains **design documents only**. **No application code has been written.**
> Nothing described here is implemented. A feature counts as implemented only when working code and passing tests exist for it.
> Full implementation starts **only after the architecture is approved** by Mixt Academy.

Mixt AI is a planned AI sales system for Mixt Academy, an international online 1:1 tutoring company.
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

## Proposed technology (subject to approval)

Next.js + React + TypeScript + Tailwind CSS · Python + FastAPI · PostgreSQL (+ pgvector) · Redis + Celery workers ·
Claude API and OpenAI API behind interchangeable model adapters · Docker · Alembic migrations · GitHub Actions CI.

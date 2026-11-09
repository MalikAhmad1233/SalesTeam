# Mixt AI: AI Sales & CRM Platform for Mixt Academy

> **Project status: Phase 0, product discovery and business-data collection.**
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
| 11 | [Open questions](docs/11-open-questions.md) | Structured list of missing business information, ranked by what it blocks |

## Non-negotiable rules (apply to every phase)

1. **The United States is not a market.** It is never a target, acquisition or operating country. USD price schedules are *currency records* whose market assignment is **unconfirmed**.
2. **No invented pricing.** The system never makes up prices or package durations, never infers pricing for a country that has none, never uses currency conversion to produce an official price, and never mixes one market's pricing with another's.
3. **Special pricing tiers are never selected automatically.** A person with the right permission assigns them.
4. **The pricing database is not complete**, and no supplied pricing or promotion is active until it has been confirmed and approved through the activation gate (see [04](docs/04-pricing-engine.md#5-lifecycle-and-the-activation-gate)).
5. **People approve important actions by default.** AI prepares; a person approves.
6. **One customer's confidential pricing or data is never shown to another customer.**
7. **No feature is described as implemented unless working code and tests exist.**

## Proposed technology (subject to approval)

Next.js + React + TypeScript + Tailwind CSS · Python + FastAPI · PostgreSQL (+ pgvector) · Redis + Celery workers ·
Claude API and OpenAI API behind interchangeable model adapters · Docker · Alembic migrations · GitHub Actions CI.

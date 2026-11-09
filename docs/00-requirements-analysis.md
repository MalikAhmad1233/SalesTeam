# 00: Requirements Analysis

Status: **Draft for approval** · Phase 0 · v0.2 (2026-11-09) · Sources: project brief (S1) and Mixt clarification (S2), both 2026-11-09. Every confirmed item cites its entry in the [decision log](12-decision-log.md).

## 1. How information is labelled

| Label | Meaning |
|-------|---------|
| **CONFIRMED** | Stated by Mixt Academy (S1 or S2) and recorded in the decision log with a `BD-` number. |
| **OPEN** | Not yet answered. Tracked as a question in [11-open-questions](11-open-questions.md). A safe default setting applies meanwhile ([13](13-configurable-settings.md)); nothing is guessed. |
| **DERIVED** | Calculated from confirmed data (e.g. package total ÷ hours). For information only, **never official**. |
| **ASSUMPTION** | A working design assumption. Must be checked; the impact if it is wrong is given. |
| **PROPOSAL** | An architecture or product recommendation awaiting approval (`ADR-` numbers in the decision log). |

---

## 2. Confirmed business information

### 2.1 Company and services: CONFIRMED
- Company: **Mixt Academy**, international online tutoring (BD-001).
- Service model: **personalised 1:1 online tutoring** (BD-002, re-confirmed in S2). Whether any other format exists is OPEN (Q-BIZ-02).
- Services: academic support; exam preparation; past-paper practice; curriculum-specific tutoring; long-term academic improvement (BD-003).

### 2.2 Curricula: CONFIRMED
Four confirmed curriculum categories (BD-007):

| Category | Detail supplied |
|----------|-----------------|
| Irish Curriculum | No sub-levels supplied (grade structure OPEN: Q-ACA-03) |
| SABIS Curriculum | No sub-levels supplied (OPEN: Q-ACA-03) |
| American Curriculum | No sub-levels supplied (OPEN: Q-ACA-03) |
| British Curriculum | Exam boards: Cambridge, Pearson Edexcel, AQA, OCR. Qualifications: IGCSE, GCSE, AS Level, A Level (BD-009) |

- **IB is not on the confirmed list** and is not added unless separately approved (BD-008). Adding any curriculum needs Owner approval and a decision-log entry (setting `crm.curricula`).
- Design note (PROPOSAL): exam board and qualification are stored as separate dimensions, so "Cambridge IGCSE", "Edexcel A Level" and "AQA GCSE" can each be represented. Which combinations Mixt teaches is OPEN (Q-ACA-02).
- **A curriculum never indicates a market.** The American curriculum is taught to students in Mixt's markets and says nothing about the US; a British-curriculum student in Dubai is a UAE customer (ADR-13).

### 2.3 Markets: CONFIRMED
**Mixt Academy operates in 13 markets** (BD-004): United Arab Emirates, Qatar, Kuwait, Saudi Arabia, Oman, Bahrain, Malaysia, Hong Kong, Singapore, Indonesia, South Korea, United Kingdom, Ireland.

- **The United States is NOT a target market** (BD-005): never a target, customer-acquisition or operating market. The database refuses to create a US market (DB-01).
- **USD pricing schedules exist, but their market assignment is unconfirmed. USD is never associated with the US market** (BD-006). Which market(s) USD applies to is OPEN (Q-MKT-01).
- A customer's pricing market is confirmed by staff; **currency, phone prefix (e.g. +1) and curriculum never decide a market** (ADR-13, PROPOSED). The exact basis (residence, school country, billing address) is OPEN (Q-MKT-04).
- Which markets move onto Mixt AI first is OPEN (Q-MKT-06).

### 2.4 Pricing: figures CONFIRMED, catalogue INCOMPLETE, nothing active
13 price schedules (91 package entries) supplied: UK GBP Tier A/B, USD Schedule A/B, UAE AED Tier A/B, Saudi SAR, Qatar QAR, Malaysia MYR, Ireland EUR Schedule A/B, Hong Kong HKD Standard/Premium. Full transcription, unchanged, in [05-pricing-data-register](05-pricing-data-register.md).

| Confirmed rule | Decision |
|----------------|----------|
| Figures are **package totals**; hourly rates and package totals are **separate fields**. | BD-010 |
| **One class = one hour** for the supplied class-based schedules, unless a package-specific exception is confirmed later. | BD-011 |
| **UK has two separate, valid pricing tiers** (Tier A, Tier B). | BD-012 |
| **UAE has two separate, valid pricing tiers** (Tier A, Tier B). | BD-013 |
| **Ireland has two separate pricing schedules** (A, B); their relationship is OPEN (Q-PRC-03). | BD-014 |
| **Malaysia package totals have been mathematically corrected.** Whether the register's figures (received 2026-11-09) are the corrected set is OPEN (Q-PRC-21). | BD-015 |
| **Hong Kong has separate Standard and Premium plans.** | BD-016 |
| **Additional pricing sheets are still being collected; the pricing database stays marked INCOMPLETE.** | BD-017 |
| Supplied figures are never silently changed; **original schedules are preserved**; corrections become new versions. | BD-018 |
| No invented prices or durations; no assumed country pricing; no currency conversion as official price; no mixing countries; no automatic special-tier selection. | BD-019 |
| **Unconfirmed pricing tiers, pricing and promotional rules are not activated.** | BD-020 |
| **Promotional terms are kept separate from standard pricing.** | BD-021 |
| Every quotation records the exact price, currency, tier and package version; confidential pricing is never disclosed to another customer. | BD-023, BD-024 |
| New pricing sheets can be added **without code changes**. | S1 |

- **How customers are placed on UK/UAE tiers is OPEN** (Q-PRC-02). Until then a person selects the tier per customer (`tier_selection_mode = manual`, ADR-12); the AI never selects.
- Markets with **no pricing supplied**: Kuwait, Oman, Bahrain, Singapore, Indonesia, South Korea. The system treats them as having **no approved pricing** and escalates to a person (Q-MKT-03).
- **No price book is active.** Remaining activation blockers: [11 §3](11-open-questions.md#3-questions-that-block-pricing-activation-p2-activate).

### 2.5 Benefits and policies: CONFIRMED as supplied, scope OPEN
| Scope stated in brief | Items |
|-----------------------|-------|
| "General package benefits supplied so far" (which packages they apply to: OPEN, Q-PKG-01) | Past papers and curated study resources · Dedicated academic support · Flexible scheduling · No expiry on purchased hours *in applicable packages* · Multiple subjects across grades · Sharing hours with siblings/family |
| Ireland packages (which schedule(s): OPEN, Q-PKG-03) | 18-month validity · Pause and resume · Recorded sessions · Fortnightly progress reports · Parent check-in calls · Dedicated WhatsApp coordinator · Irish-curriculum-trained tutors · Advertised first-paid-session refund **or** free tutor swap guarantee |
| Hong Kong Standard | No expiry · Up to four subjects · Family sharing · Flexible scheduling |
| Hong Kong Premium | Recorded sessions · Unlimited subjects across grades · No expiry · Bi-monthly parent-teacher consultations · Bi-weekly progress reports · Academic support team · Teacher chat access |

Rule (CONFIRMED, BD-022): benefits and policies are stored **separately by package, country and plan**, and are **never applied from one country to another without administrator approval**.

> To resolve (Q-PKG-02): "no expiry on purchased hours" vs Ireland's "18-month validity". The design treats both as package-specific policies, so both can exist; which applies where is OPEN.

### 2.6 Platform scope: CONFIRMED
- Capabilities: lead generation, lead research, qualification, AI sales conversations, WhatsApp automation, email automation, CRM, tutor matching, trial scheduling, pricing recommendations, negotiation assistance, quotations, payment tracking, student registration, follow-ups, retention, renewals, referrals, sales analytics.
- **All modules share one central CRM database**; no agent has its own customer store (BD-025). Several students under one parent account (BD-026).
- 14 specialised agents (see [03](03-ai-agent-architecture.md)), each with defined responsibilities, controlled permissions, CRM access, conversation memory, activity logging, error handling and human escalation.
- **Default autonomy mode:** AI prepares suggestions; **a person approves important actions**; approval levels configurable (BD-027).
- Integrations: WhatsApp Business Cloud API, Gmail, Microsoft 365, Facebook Lead Ads, Instagram lead sources, website enquiry forms, website chat, all through **official APIs** with secure credentials, webhook processing, message status tracking, retries and audit logs (BD-028).
- Dashboard modules (17): Overview, Leads, Customers, Conversations, AI Agents, Sales Pipeline, Tutors, Scheduling, Pricing, Quotations, Payments, Follow-ups, Retention, Reports, Team, Integrations, Settings.
- Brand direction: pink/magenta and blue accents; white and light neutral backgrounds; modern typography; responsive.
- Security: secure login, role-based permissions (admin and representative levels at minimum), encrypted credentials, API rate limiting, input validation, secure webhooks, audit trails, backups, privacy controls, customer data isolation.
- Preferred stack (BD-029): Next.js/React/TypeScript/Tailwind · Python/FastAPI · PostgreSQL · Redis + background workers · Claude API and OpenAI API via modular adapters · Docker, environment variables, migrations.
- Outstanding business decisions are handled with **configurable settings**, so the architecture is not blocked (BD-030). **No full implementation until the architecture is explicitly approved** (BD-031).

---

## 3. Design assumptions (must be checked)

| ID | Assumption | Status (v0.2) | Impact if wrong | Question |
|----|-----------|---------------|-----------------|----------|
| A-01 | One company, one brand: Mixt Academy (single-tenant system). | ASSUMPTION | Multi-brand or franchise use would need a tenant layer. | Q-BIZ-01 |
| A-02 | The buyer is usually a **parent/guardian**; most students are **minors**. | ASSUMPTION (system treats all students as minors meanwhile) | Consent design, safeguarding, who the AI talks to. | Q-CMP-03, Q-AI-05 |
| A-03 | One parent account can hold several students; one student may have more than one guardian contact. | Several students: **CONFIRMED** (BD-026). Several guardians: ASSUMPTION | Small schema change. | Q-CRM-02 |
| A-04 | Lessons are **1:1, online, 60 minutes**. | 1:1 online: **CONFIRMED** (BD-002). 1 class = 60 min for class-based schedules: **CONFIRMED** (BD-011). Other lesson lengths: ASSUMPTION (60 only) | Hours ledger and scheduling durations. | Q-SCH-03 |
| A-05 | Packages are **prepaid**; hours are drawn down as lessons are delivered. | ASSUMPTION | Payment and ledger design. | Q-PAY-02 |
| A-06 | Lessons are delivered on an **external video platform**. | ASSUMPTION | Scheduling integration. | Q-SCH-01 |
| A-07 | Tutor records and lesson data live outside any system Mixt AI can read today. | ASSUMPTION | Migration effort. | Q-TUT-01, Q-DAT-01 |
| A-08 | The sales team is small (fewer than 50 internal users) and works mainly in English. | ASSUMPTION | Sizing, dashboard language. | Q-TEAM-01 |
| A-09 | Customers may write in several languages (e.g. Arabic, Malay, Indonesian, Chinese, Korean). | ASSUMPTION (AI replies in English only meanwhile) | AI reply languages, staff review. | Q-AI-03 |
| A-10 | Unsolicited enquiries from outside the 13 markets (including US residents) can still arrive (e.g. via ads or referrals). They are flagged out-of-market for a person to review and are never targeted; **the US is never added as a market** (BD-005). | Handling: OPEN (safe default `human_review`) | Out-of-market wording. | Q-MKT-02 |
| A-11 | One shared WhatsApp Business number serves all markets. | ASSUMPTION | Several channel accounts (already supported). | Q-COM-01 |
| A-12 | Prices are **final consumer prices**; tax treatment unknown. | ASSUMPTION (tax `unknown` blocks activation) | Quotation and invoice totals. | Q-PAY-04 |
| A-13 | Hosting is in one cloud region chosen for data-protection reasons. | ASSUMPTION | Possibly several regions. | Q-CMP-02 |

---

## 4. Functional requirements

Priority: **MVP** = needed for the first production release used by the sales team; **P2/P3** = later phases (see [10-roadmap](10-roadmap.md)).

| ID | Area | Requirement | Priority |
|----|------|-------------|----------|
| FR-01 | Identity | Staff log in with MFA; role-based and record-level access control. | MVP |
| FR-02 | Audit | Every create/update/delete, approval, AI action and outbound message is written to an append-only audit trail. | MVP |
| FR-03 | CRM | Household accounts, contacts (guardians, students), several students per account, academic profiles, preferences, owner assignment. | MVP |
| FR-04 | CRM | Lead intake from any source with attribution, duplicate detection and merge. | MVP |
| FR-05 | CRM | Configurable sales pipeline with stage history, lost reasons, required fields per stage. | MVP |
| FR-06 | CRM | Unified customer timeline: messages, calls, notes, tasks, quotations, trials, payments. | MVP |
| FR-07 | Pricing | Versioned price books per market, currency, plan and tier, with entries, benefits, policies, promotions and customer-specific pricing. | MVP |
| FR-08 | Pricing | Admin pricing module: create/edit/version/approve/activate/deactivate; history; import from spreadsheet. | MVP |
| FR-09 | Pricing | Deterministic price resolution that refuses when no confirmed pricing exists. | MVP |
| FR-10 | Quotations | Create, approve, issue (PDF + message), revise and track quotations with an immutable pricing snapshot. | MVP |
| FR-11 | Approvals | Configurable approval policies per action type, role, market and amount; approval inbox. | MVP |
| FR-12 | Messaging | WhatsApp Cloud API send/receive, templates, 24-hour window rules, status tracking, opt-in/opt-out. | MVP |
| FR-13 | Messaging | Email send/receive via Gmail **or** Microsoft 365 (whichever Mixt uses), threading, bounces, unsubscribe. | MVP |
| FR-14 | Messaging | Unified inbox with assignment, human takeover, AI draft review. | MVP |
| FR-15 | Lead sources | Website enquiry form endpoint (spam-protected, consent captured). | MVP |
| FR-16 | AI | Model gateway (Claude, OpenAI) with profiles, fallback, cost tracking. | MVP |
| FR-17 | AI | Agent runtime: tools, permissions, memory, guardrails, escalation, kill switches, run logs. | MVP |
| FR-18 | AI | AI Sales Agent in draft mode (people approve every outbound message). | MVP |
| FR-19 | AI | Lead Qualification and Follow-up agents (suggestions + tasks). | MVP |
| FR-20 | Knowledge | Admin-curated knowledge base (curricula, FAQs, objection library, policies) with versioning. | MVP |
| FR-21 | Follow-ups | Tasks, reminders, cadences with frequency caps, quiet hours and consent checks. | MVP |
| FR-22 | Tutors | Tutor profiles, subjects/boards/levels, languages, availability, capacity, safeguarding-check status. | P2 |
| FR-23 | Matching | Tutor matching with hard filters + scoring + rationale; coordinator confirms. | P2 |
| FR-24 | Scheduling | Trial scheduling across time zones, calendar sync, video links, reminders, no-show handling. | P2 |
| FR-25 | Payments | Invoices, payment links (provider TBC), payment status via provider webhooks, manual reconciliation, reminders. | P2 |
| FR-26 | Enrolment | Student registration, package purchase, hours ledger (credits/debits/expiry/pause/family sharing). | P2 |
| FR-27 | Retention | Health score, low-balance and expiry alerts, renewal opportunities, check-ins, win-back. | P3 |
| FR-28 | Referrals | Referral codes/links, attribution, reward tracking and approval. | P3 |
| FR-29 | Lead sources | Facebook/Instagram Lead Ads webhooks; Instagram messages (if in scope). | P2 |
| FR-30 | Lead sources | Website chat widget connected to the AI Sales Agent. | P3 |
| FR-31 | Research | Lead research briefs from lawful, public, non-personal sources (e.g. school curriculum). | P3 |
| FR-32 | Analytics | Funnel, conversion, response time, revenue by market/currency (never summed across currencies without a labelled reporting rate), agent performance. | P2/P3 |
| FR-33 | Sales Manager Agent | Pipeline digests, SLA monitoring, conversation QA scoring, anomaly detection. | P3 |
| FR-34 | Privacy | Consent records, data export (DSAR), erasure/anonymisation, retention schedules. | MVP (records) / P2 (workflows) |
| FR-35 | Settings | Configurable settings register with safe defaults for every outstanding business decision, and an "Outstanding decisions" view ([13](13-configurable-settings.md)). | MVP |
| FR-36 | Pricing | Per-market tier selection mode; manual per-customer tier selection by authorised staff, with reason (ADR-12). | MVP |
| FR-37 | Pricing | Correction versions that supersede, never overwrite, original figures; original schedules preserved in history (ADR-14). | MVP |

## 5. Non-functional requirements

| ID | Category | Requirement (PROPOSAL; targets to confirm in Q-TECH-03) |
|----|----------|--------------------------------------------------------|
| NFR-01 | Correctness | Pricing resolution is deterministic and fully covered by tests; every supplied price has a "golden" test. Zero tolerance for an unapproved price reaching a customer. |
| NFR-02 | Reliability | No loss of inbound messages or webhooks: raw events are stored before processing; processing is idempotent; failed jobs retry and then go to a dead-letter queue that people can see. |
| NFR-03 | Availability | Proposed target 99.5% monthly for the API and webhook intake; webhook intake keeps running even when AI providers are down. |
| NFR-04 | Latency | Webhook acknowledgement < 1 s (p95). AI draft ready < 30 s (p95) after the customer's last message (after debounce). |
| NFR-05 | Security | OWASP ASVS Level 2 as the baseline; MFA for all staff; secrets never in code or logs. |
| NFR-06 | Privacy | Data minimisation for minors; consent before marketing; regional data-protection compliance (see [08](08-security-privacy.md)). |
| NFR-07 | Auditability | Every AI output that reaches a customer can be traced to: agent version, prompt version, model, input context, tools called, approver. |
| NFR-08 | Maintainability | Modular monolith with clear module boundaries; typed APIs; ≥ 85% backend line coverage on domain modules; migrations for every schema change. |
| NFR-09 | Scalability | Designed for at least 10⁵ contacts and 10⁷ messages on one PostgreSQL primary; workers scale horizontally. |
| NFR-10 | Recoverability | Point-in-time recovery; proposed RPO ≤ 15 min, RTO ≤ 4 h; restore tested quarterly. |
| NFR-11 | Configurability | Pricing, pipeline stages, approval policies, templates, knowledge and agent prompts are data, changed without redeploying. |
| NFR-12 | Internationalisation | Time-zone correct scheduling (IANA zones); per-currency formatting; UTF-8 throughout; customer messages may be right-to-left (Arabic). |

---

## 6. Main risks and mitigations

| Risk | Why it matters | Mitigation (PROPOSAL) |
|------|----------------|-----------------------|
| AI states a wrong or made-up price | Direct financial and reputational damage | LLMs never produce prices; prices come only from the pricing tool. An output "price guard" blocks any amount not in the customer's eligible, approved set. People approve by default. |
| AI promises a benefit or policy not offered in that market | Misleading-advertising and refund exposure | Benefits and policies are stored per price-book version; a "claims guard" checks statements against the customer's market and package. |
| One customer's data or pricing leaks into another's conversation | Confidentiality breach | Each agent run is limited to one account; tools refuse cross-account access; automated leakage tests. |
| Messaging-policy breach (WhatsApp, anti-spam laws) | Number blocked, fines | Opt-in records; 24-hour window enforcement; approved templates; frequency caps; quiet hours; suppression list. |
| Processing children's data | Higher legal duties across markets | Data minimisation; guardian as main contact; safeguarding escalation; legal review per market. |
| External approval delays (Meta business verification, WhatsApp templates, Google OAuth verification, Meta app review) | Can block go-live for weeks | Start these in Phase 0 (see roadmap critical path). |
| Over-automation harms the brand | Robotic or pushy conversations | Autonomy raised step by step, per message type, based on measured approval-without-edit rates. |
| Incomplete pricing data | Sales blocked in some markets | System escalates clearly ("no approved pricing for Kuwait"); never guesses. |
| Dependence on one AI vendor | Outage or price change | Model gateway with Claude and OpenAI adapters and per-profile fallback. |

## 7. Out of scope for now
- Delivering lessons (video classroom, whiteboard, lesson recording storage) unless Mixt asks for it.
- Tutor payroll and payouts.
- Accounting ledger beyond invoices/payments (assumes an external accounting tool; see Q-PAY-06).
- Scraping personal data from social media or third-party sites (excluded on legal and ethical grounds).
- Any activity targeting the United States.

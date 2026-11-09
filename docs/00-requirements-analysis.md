# 00: Requirements Analysis

Status: **Draft for approval** · Phase 0 · Source: Mixt Academy project brief received 2026-11-09

## 1. How information is labelled

Every statement in these documents carries one of these labels, so the evidence behind it is clear:

| Label | Meaning |
|-------|---------|
| **CONFIRMED** | Stated by Mixt Academy in the project brief. |
| **DERIVED** | Calculated from confirmed data (e.g. package total ÷ hours). For information only, **never official**. |
| **ASSUMPTION** | A working design assumption. Must be checked; the impact if it is wrong is given. |
| **UNKNOWN** | Missing information. Each one maps to a question in [11-open-questions](11-open-questions.md). |
| **PROPOSAL** | An architecture or product recommendation awaiting approval. |

---

## 2. Confirmed business information

### 2.1 Company and services: CONFIRMED
- Company: **Mixt Academy**, international online tutoring.
- Services: personalised 1:1 online tutoring; academic support; exam preparation; past-paper practice; curriculum-specific tutoring; long-term academic improvement.

### 2.2 Curricula: CONFIRMED
| Category | Detail supplied |
|----------|-----------------|
| Irish Curriculum | No sub-levels supplied |
| SABIS Curriculum | No sub-levels supplied |
| American Curriculum | No sub-levels supplied |
| British Curriculum | Exam boards: Cambridge, Pearson Edexcel, AQA, OCR. Qualifications: IGCSE, GCSE, AS Level, A Level |

> Design note (PROPOSAL): the brief lists exam boards and qualifications together. The schema stores **exam board** and **qualification** as separate dimensions, so "Cambridge IGCSE", "Edexcel A Level" and "AQA GCSE" can each be represented. Which board/qualification combinations Mixt teaches is UNKNOWN (Q-ACA-02).

### 2.3 Markets: CONFIRMED
Target countries (13): United Arab Emirates, Qatar, Kuwait, Saudi Arabia, Oman, Bahrain, Malaysia, Hong Kong, Singapore, Indonesia, South Korea, United Kingdom, Ireland.

**Explicit exclusion: the United States is not a market.** It must never be a target market, acquisition market or operating country.
USD-denominated schedules are **currency records whose market assignment is unconfirmed**. A USD price never implies a US market.

### 2.4 Pricing: CONFIRMED figures, activation NOT confirmed
13 price schedules (91 package entries) supplied: UK GBP Tier A/B, USD Schedule A/B, UAE AED Tier A/B, Saudi SAR, Qatar QAR, Malaysia MYR, Ireland EUR Schedule A/B, Hong Kong HKD Standard/Premium. Full transcription in [05-pricing-data-register](05-pricing-data-register.md).

Confirmed rules about pricing:
- Figures are **package totals**. Hourly rates and package totals are **stored in separate fields**.
- A "class" in the original schedules is **one hour** unless a package policy says otherwise.
- The full pricing data is **still being collected**. The pricing database is **not complete**.
- The two Ireland schedules stay **separate**; eligibility for each and how they relate are **not confirmed**.
- Prohibited: inventing prices or durations; assuming pricing for countries that have none; using converted currency values as official prices; mixing countries' pricing; selecting a special tier automatically.
- Every quotation must record the exact price, currency, tier and package version used.
- Confidential pricing must never be disclosed to another customer.
- New pricing sheets must be addable **without code changes**.

Countries with **no pricing supplied**: Kuwait, Oman, Bahrain, Singapore, Indonesia, South Korea. The system must treat these as having **no approved pricing** and escalate to a person.

### 2.5 Benefits and policies: CONFIRMED as supplied, scope partly UNKNOWN
| Scope stated in brief | Items |
|-----------------------|-------|
| "General package benefits supplied so far" (which packages they apply to: UNKNOWN) | Past papers and curated study resources · Dedicated academic support · Flexible scheduling · No expiry on purchased hours *in applicable packages* · Multiple subjects across grades · Sharing hours with siblings/family |
| Ireland packages | 18-month validity · Pause and resume · Recorded sessions · Fortnightly progress reports · Parent check-in calls · Dedicated WhatsApp coordinator · Irish-curriculum-trained tutors · Advertised first-paid-session refund **or** free tutor swap guarantee |
| Hong Kong Standard | No expiry · Up to four subjects · Family sharing · Flexible scheduling |
| Hong Kong Premium | Recorded sessions · Unlimited subjects across grades · No expiry · Bi-monthly parent-teacher consultations · Bi-weekly progress reports · Academic support team · Teacher chat access |

Rule (CONFIRMED): benefits and policies are stored **separately by package, country and plan**, and are **never applied from one country to another without administrator approval**.

> Possible conflict to resolve (Q-PKG-02): "no expiry on purchased hours" vs Ireland's "18-month validity". The design treats them as package-specific policies, so both can exist. Which applies where still needs confirming.

### 2.6 Platform scope: CONFIRMED
- Capabilities: lead generation, lead research, qualification, AI sales conversations, WhatsApp automation, email automation, CRM, tutor matching, trial scheduling, pricing recommendations, negotiation assistance, quotations, payment tracking, student registration, follow-ups, retention, renewals, referrals, sales analytics.
- **All modules share one central CRM database.** No agent has its own separate customer store.
- 14 specialised agents (see [03](03-ai-agent-architecture.md)), each with defined responsibilities, controlled permissions, CRM access, conversation memory, activity logging, error handling and human escalation.
- **Default autonomy mode:** AI prepares suggestions; **a person approves important actions**. Approval levels are configurable.
- Integrations: WhatsApp Business Cloud API, Gmail, Microsoft 365, Facebook Lead Ads, Instagram lead sources, website enquiry forms, website chat, all through **official APIs** with secure credentials, webhook processing, message status tracking, retries and audit logs.
- Dashboard modules (17): Overview, Leads, Customers, Conversations, AI Agents, Sales Pipeline, Tutors, Scheduling, Pricing, Quotations, Payments, Follow-ups, Retention, Reports, Team, Integrations, Settings.
- Brand direction: pink/magenta and blue accents; white and light neutral backgrounds; modern typography; responsive.
- Security: secure login, role-based permissions (admin and representative levels at minimum), encrypted credentials, API rate limiting, input validation, secure webhooks, audit trails, backups, privacy controls, customer data isolation.
- Preferred stack: Next.js/React/TypeScript/Tailwind · Python/FastAPI · PostgreSQL · Redis + background workers · Claude API and OpenAI API via modular adapters · Docker, environment variables, migrations.

---

## 3. Design assumptions (must be checked)

| ID | Assumption | Impact if wrong | Question |
|----|-----------|-----------------|----------|
| A-01 | One company, one brand: Mixt Academy (single-tenant system). | Multi-brand or franchise use would need a tenant layer. | Q-BIZ-01 |
| A-02 | The buyer is usually a **parent/guardian**; most students are **minors**. | Changes consent design, safeguarding rules and who the AI talks to. | Q-CMP-03, Q-AI-05 |
| A-03 | One parent account can hold several students (CONFIRMED), and one student may have more than one guardian contact (ASSUMPTION). | Small schema change. | Q-CRM-02 |
| A-04 | All lessons are **1:1, online, 60 minutes** unless a policy says otherwise. | The hours ledger and scheduling durations would change. | Q-PRC-07, Q-SCH-03 |
| A-05 | Packages are **prepaid**; hours are drawn down as lessons are delivered. | The payment and ledger design would change for subscriptions or instalments. | Q-PAY-02 |
| A-06 | Lessons are delivered on an **external video platform** (e.g. Zoom, Google Meet, Teams). | The scheduling integration would change. | Q-SCH-01 |
| A-07 | Tutor records and lesson-delivery data currently live outside any system Mixt AI can read (spreadsheets or another tool). | Migration and integration effort. | Q-TUT-01, Q-DAT-01 |
| A-08 | The sales team is small (fewer than 50 internal users) and works mainly in English. | Sizing, dashboard language. | Q-TEAM-01 |
| A-09 | Customers may write in several languages (e.g. Arabic, Malay, Indonesian, Chinese, Korean). | Supported AI reply languages and staff review ability. | Q-AI-03 |
| A-10 | A US-resident enquiry can still arrive by accident (e.g. ads, referrals). It is **flagged as out-of-market for a person to review**, never targeted. | Handling rule needed. | Q-MKT-02 |
| A-11 | One shared WhatsApp Business number serves all markets. | Separate numbers would mean several channel accounts (already supported). | Q-COM-01 |
| A-12 | Prices are **final consumer prices**; tax treatment is not yet known. | Quotation and invoice totals would change. | Q-PAY-04 |
| A-13 | Hosting is in one cloud region chosen for data-protection reasons. | Data residency could require a different region or several regions. | Q-CMP-02 |

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

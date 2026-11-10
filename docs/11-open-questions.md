# 11: Open Questions and Missing Business Information

Status: **Updated 2026-11-09 (v0.2)** after Mixt's clarification. Decisions: [12-decision-log](12-decision-log.md). Safe defaults: [13-configurable-settings](13-configurable-settings.md).

Every question below is **OPEN** unless it appears in §1. Each open question has a **safe default** that applies until it is answered, so **no open question blocks starting development**. The "Needed by" column says when an answer is actually required:

| Label | Meaning |
|-------|---------|
| **P1-live** | Before Phase 1 is used in production with **real customer data** |
| **P2-activate** | Before the named price book(s) can be **activated** (quoted to customers) |
| **P1 … P8** | Before that phase's feature is switched on; the safe default applies until then |

---

## 1. Answered or narrowed in this update

| ID | Was asked | Now | Decision |
|----|-----------|-----|----------|
| Q-PRC-07 | Is an Ireland Schedule A "class" 60 minutes? | **CLOSED: CONFIRMED.** One class = one hour for the supplied class-based schedules, unless a package-specific exception is confirmed later. | BD-011 |
| Q-PRC-02 | What do UK/UAE Tier A and B mean, and how is a customer placed on each? | **Narrowed.** CONFIRMED: UK and UAE each have two separate, valid tiers. OPEN: how a customer is placed on a tier. | BD-012, BD-013 |
| Q-PRC-03 | How do Ireland Schedule A and B relate? | **Narrowed.** CONFIRMED: two separate schedules. OPEN: their relationship and eligibility. | BD-014 |
| Q-PRC-01 | Which further pricing sheets are coming? | **Narrowed.** CONFIRMED: more sheets are being collected; the database stays incomplete. OPEN: which and when. | BD-017 |
| Q-PRC-10 | HK minimums and plan boundaries | **Narrowed.** CONFIRMED: HK has separate Standard and Premium plans. OPEN: minimum purchase; whether Standard is sold above 40h. | BD-016 |
| Q-BIZ-02 | 1:1 only, or group classes too? | **Narrowed.** CONFIRMED: personalised 1:1 online tutoring. OPEN: whether any other format is offered. | BD-002 |
| Q-SCH-03 | Lesson lengths offered | **Narrowed.** CONFIRMED: class = 60 min for class-based schedules. OPEN: whether individual lessons can be other lengths. | BD-011 |
| Q-ACA-04 | Other programmes (IB etc.)? | **Unchanged: OPEN.** IB is **not** on the confirmed list and is not added unless separately approved. | BD-008 |
| Q-MKT-01 | Which markets use the USD schedules? | **Unchanged: OPEN.** Re-confirmed: assignment unconfirmed; USD never means US. | BD-006 |
| Q-PRC-21 | *(new)* Malaysia correction | **New: OPEN.** See §3. | BD-015 |

---

## 2. Questions that block Phase 1

**Starting Phase 1 development: no business question blocks it.** Only your architecture approval is needed (BD-031). Everything else in Phase 1 has a safe default.

**Using Phase 1 in production with real customer data (P1-live):**

| ID | Question | Why it genuinely blocks | Until answered |
|----|----------|-------------------------|----------------|
| Q-CMP-02 | **Hosting region** and data-residency / cross-border transfer requirements (especially Saudi Arabia, UAE, Indonesia). | Where real customer and student data may legally be stored; moving it later is costly. | `infra.region` unset: development and staging use synthetic data only |
| Q-CMP-01 | Mixt's legal/data-protection contact; existing **privacy notice and terms**; approved **consent wording** for forms and messages. | Real personal data (including children's) must not be collected without an approved notice and consent wording. | No real data collected |
| Q-TECH-04 | **Cloud provider** preference or existing account where production runs. | Production infrastructure has to be created in Mixt's account. | Staging can run in a temporary account with synthetic data |

**Set-up information needed at Phase 1 go-live** (facts, not decisions; no design impact):
- Q-TEAM-01: staff list, roles, markets and languages per person (to create accounts and permissions).
- Q-DAT-01: where today's leads/customers/students/tutors are held, and roughly how many. Needed only if existing records are to be imported at go-live.

---

## 3. Questions that block pricing activation (P2-activate)

Phase 2 can be **built** without these. No price book can be **activated** until its blockers are answered (BD-020).

| ID | Question | Books blocked |
|----|----------|---------------|
| Q-PAY-04 | Are prices **VAT/GST-inclusive** where tax applies? Where is Mixt tax-registered? | **All** |
| Q-PRC-09 | Do prices vary by **curriculum, level (e.g. A Level vs GCSE), subject, exam board or tutor seniority**? | **All** |
| Q-PRC-20 | Who are Mixt's **pricing approvers** (one or two people per activation)? | **All** |
| Q-PRC-14 | UK Tier A: confirm **100h = £1,000** (80h = £960). | UK Tier A |
| Q-PRC-15 | UAE Tier A and Tier B are **identical at 100h/150h/200h** (AED 4,900 / 6,600 / 7,600). Intended? | UAE Tier A, UAE Tier B |
| Q-PRC-16 | Identical figures across books: SAR = AED Tier B; QAR = AED Tier A; USD Schedule A 150h/200h = UK Tier B 150h/200h; Ireland Schedule B 20/30/50/100h = USD Schedule A. Intended? | Saudi, Qatar, UAE A/B, UK Tier B, USD A, Ireland B |
| Q-PRC-21 | **Malaysia:** you confirmed the totals have been mathematically corrected. Are the MYR figures in the register (15h RM 1,170 … 200h RM 9,000, received 2026-11-09) **the corrected totals**? If a further corrected set exists, please send it: it will be loaded as version 2, and the current figures kept as version 1. | Malaysia |
| Q-PRC-03 | **Ireland:** how do Schedule A and Schedule B relate? Are both offered to new customers today, and to whom? | Ireland A, Ireland B |
| Q-MKT-01 | Which market(s) do **USD Schedule A and B** apply to? (Never the US.) | USD A, USD B |

Not activation blockers, because a safe default covers them: Q-PRC-02 (UK/UAE tier placement: a person selects the tier per customer), Q-MKT-04 (market basis: staff confirm), Q-PRC-06 (no plan label shown), Q-PKG-* (no benefit is claimed until it is attached and approved).

---

## 4. All open questions by area

### A. Pricing (Q-PRC)

| ID | Open question | Why it matters | Needed by | Until answered |
|----|---------------|----------------|-----------|----------------|
| Q-PRC-01 | Which further pricing sheets are coming (markets, currencies, plans, promotions), and when? | Completes the catalogue. | P2 | `pricing.catalogue_complete = false` |
| Q-PRC-02 | **UK and UAE:** how is a customer placed on Tier A or Tier B (new vs existing, lead source, campaign, date of enquiry, negotiation)? | Lets the engine choose without a person each time. | P4 | `tier_selection_mode = manual` |
| Q-PRC-03 | **Ireland:** relationship between Schedule A and B; eligibility for each. | See §3. | P2-activate (IE) | Ireland stays inactive |
| Q-PRC-04 | General eligibility rules (new customers, existing, referrals, siblings, campaigns)? | Eligibility rules. | P2 | No rules |
| Q-PRC-05 | Which supplied schedules (if any) are **promotional**? For each promotion: what changes, dates, eligibility, stacking. | Promotions stay separate from standard pricing (BD-021). | P2 | `promotions.enabled = false` |
| Q-PRC-06 | Saudi, Qatar, Malaysia: one schedule each? Should a plan name ("Standard") be shown? Are other tiers/plans coming? | Customer-facing labels; completeness. | P2 | No plan label shown |
| Q-PRC-08 | Are the whole-number per-hour rates behind the totals (e.g. £285 ÷ 15h = £19/h) **official advertised rates**? | Separate hourly-rate field (BD-010). | P2 | `customer_rate_display = totals_only` |
| Q-PRC-09 | Do prices vary by curriculum, level, subject, exam board or tutor seniority? | See §3. | P2-activate (all) | All inactive |
| Q-PRC-10 | **Hong Kong:** minimum purchase per plan? Can Standard be bought above 40h? | Minimum rules (none assumed). | P2 | Only listed packages |
| Q-PRC-11 | Discount authority per role and market; dual-approval threshold. | Negotiation approvals. | P2 | Any discount needs SM + PM |
| Q-PRC-12 | Rounding rule for percentage discounts per currency. | Discount maths. | P2 | Percentage discounts disabled |
| Q-PRC-13 | Standard quotation validity; are issued quotes honoured after a price change? | Quotation rules. | P2 | Expiry set per quote; reconfirm on price change |
| Q-PRC-14 | UK Tier A 100h = £1,000? | See §3. | P2-activate (UK A) | Inactive |
| Q-PRC-15 | UAE A/B identical at 100–200h intended? | See §3. | P2-activate (UAE) | Inactive |
| Q-PRC-16 | Identical figures across books intended? | See §3. | P2-activate | Inactive |
| Q-PRC-17 | Are any package rows missing (e.g. UK Tier A 150h/200h, UK Tier B 80h, HK Standard above 40h)? | Completeness; never invented. | P2 | Unlisted quantities → custom request |
| Q-PRC-18 | Can customers buy non-listed quantities (e.g. 25h)? Priced how, approved by whom? | Custom quotes. | P2 | `custom_quantities = disabled` |
| Q-PRC-19 | Several students: one shared package or one per student? Any sibling pricing? | Quotation structure. | P2 | Staff build multi-student quotes |
| Q-PRC-20 | Who approves pricing activation (one or two people)? | See §3. | P2-activate (all) | Dual approval required |
| Q-PRC-21 | Are the register's MYR figures the corrected totals? | See §3. | P2-activate (MY) | Inactive |

### B. Markets and currencies (Q-MKT)

| ID | Open question | Why it matters | Needed by | Until answered |
|----|---------------|----------------|-----------|----------------|
| Q-MKT-01 | Which market(s) do USD Schedule A and B apply to? (Never the US.) | See §3. | P2-activate (USD) | No market assignment |
| Q-MKT-02 | How should unsolicited enquiries from non-target countries (including US residents) be handled? | Out-of-market wording. | P3 | `human_review`, no AI sales reply |
| Q-MKT-03 | Is pricing coming for **Kuwait, Oman, Bahrain, Singapore, Indonesia, South Korea**? What may customers there be told meanwhile? | Sales in those markets. | P2 / P4 | No figures; escalate with holding message |
| Q-MKT-04 | How is a customer's pricing market decided (residence, school country, billing address)? Expatriates or families moving? | Price resolution step 1. | P2 | Staff confirm; currency/phone/curriculum never used |
| Q-MKT-05 | Can a customer pay in a currency other than their market's? | Payments (no conversion). | P6 | Not allowed |
| Q-MKT-06 | Which markets move onto Mixt AI first? | Rollout, templates, languages. | P3 | `mixt_ai_rollout = off` |
| Q-MKT-07 | Working days and acceptable contact hours per market. | Quiet hours, SLAs. | P3 | Automated sends disabled |

### C. Packages, benefits and policies (Q-PKG)

| ID | Open question | Why it matters | Needed by | Until answered |
|----|---------------|----------------|-----------|----------------|
| Q-PKG-01 | Which packages/markets do the **general benefits** apply to? | No cross-market application (BD-022). | P2 | No benefit claimed |
| Q-PKG-02 | Which packages have no expiry and which have validity periods (Ireland 18 months)? What applies where nothing is stated? | Expiry, claims. | P2 / P6 | No expiry claim; staff answer |
| Q-PKG-03 | Do the Ireland policies apply to Schedule A, B or both? | Benefits per version. | P2 | Not attached |
| Q-PKG-04 | HK Premium: "bi-monthly" = twice a month or every two months? "Bi-weekly" = twice a week or every two weeks? | Exact wording. | P2 | Wording not shown |
| Q-PKG-05 | Exact terms of Ireland's first-paid-session refund / free tutor swap guarantee. | Policy text; refunds are always handled by a person. | P2 | Not stated by AI |
| Q-PKG-06 | Family sharing: which packages, how many students, same household only? | Ledger rules. | P6 | Sharing off |
| Q-PKG-07 | Pause/resume (Ireland): maximum length, frequency, effect on 18-month validity. | Ledger/expiry. | P6 | Staff handle manually |
| Q-PKG-08 | HK Standard "up to four subjects": per student or per account? | Enforcement. | P6 | Not enforced; not claimed |
| Q-PKG-09 | Cancellation, late-cancellation and no-show rules. | Ledger deductions. | P6 | No automatic deductions |
| Q-PKG-10 | General refund policy for unused hours, per market. | Refund workflow, AI answers. | P6 | Escalate to a person |

### D. Academic offering (Q-ACA)

| ID | Open question | Why it matters | Needed by | Until answered |
|----|---------------|----------------|-----------|----------------|
| Q-ACA-01 | Subjects offered per curriculum and level. | Qualification, matching, AI answers. | P4 | AI does not claim; escalates |
| Q-ACA-02 | Which exam board × qualification combinations are taught? | AI must not offer what isn't taught. | P4 | Not claimed |
| Q-ACA-03 | Grade/year structure per curriculum (Irish, SABIS, American, British). | Controlled grade lists. | P1 (nice to have) | Free-text grade |
| Q-ACA-04 | Will IB or other programmes ever be offered? (IB is **not** on the confirmed list: BD-008.) | Scope. | Later | Not offered |
| Q-ACA-05 | Exam session calendars per board. | Package-size guidance, retention. | P4 | Not used |

### E. Sales process (Q-SAL)

| ID | Open question | Why it matters | Needed by | Until answered |
|----|---------------|----------------|-----------|----------------|
| Q-SAL-01 | Current sales process step by step; volumes and conversion rates. | Pipeline set-up; baselines. | P1 (nice to have) | Proposed default stages |
| Q-SAL-02 | Free trial policy: always? length? one per student/subject? all markets? | Pipeline, scheduling. | P5 | Staff-only trials |
| Q-SAL-03 | What makes a lead qualified or disqualified? | Scoring rules. | P4 | Proposed required fields |
| Q-SAL-04 | Approved positioning, objection responses, competitors per market. | Objection library. | P4 | AI escalates objections |
| Q-SAL-05 | Referral programme: rewards, eligibility. | Referrals. | P7 | Referrals off |
| Q-SAL-06 | Follow-up cadence: touches, intervals, when to stop. | Sequences. | P4 | Sequences off |
| Q-SAL-07 | Lead generation: inbound only, or outbound to schools/partners? Any lists, with what consent? | Lawful lead generation. | P7 | Inbound only |
| Q-SAL-08 | Renewal approach and incentives. | Retention. | P7 | Retention signals off |

### F. Tutors and scheduling (Q-TUT, Q-SCH)

| ID | Open question | Why it matters | Needed by | Until answered |
|----|---------------|----------------|-----------|----------------|
| Q-TUT-01 | Where is tutor data held; how many tutors; employment model? | Tutor module, migration. | P5 | — |
| Q-TUT-02 | Where are lessons scheduled/recorded today? Should Mixt AI hold lessons or import them? | Hours ledger source. | P6 | — |
| Q-TUT-03 | Tutor safeguarding/background-check requirements per market. | Matching filter. | P5 | Coordinator confirms every assignment |
| Q-TUT-04 | Matching priorities; can customers request tutors or tutor characteristics? | Matching weights. | P5 | Coordinator decides |
| Q-SCH-01 | Video platform and calendar system. | Scheduling integration. | P5 | Manual links |
| Q-SCH-02 | Who confirms trials; trial length; minimum notice. | Scheduling rules. | P5 | Staff-only |
| Q-SCH-03 | Can individual lessons be other than 60 minutes (e.g. 30/45/90)? | Scheduling and ledger. | P5 | `[60]` only |

### G. Payments and finance (Q-PAY)

| ID | Open question | Why it matters | Needed by | Until answered |
|----|---------------|----------------|-----------|----------------|
| Q-PAY-01 | Payment methods and providers per market. | Provider integration. | P6 | Manual finance confirmation |
| Q-PAY-02 | Full upfront, instalments or subscriptions? | Payment and ledger design. | P6 | One invoice per quotation |
| Q-PAY-03 | Which legal entity invoices which market? | Invoices, tax. | P6 | — |
| Q-PAY-04 | Prices VAT/GST-inclusive? Tax registrations? | See §3. | P2-activate (all) | All inactive |
| Q-PAY-05 | Invoice numbering and layout requirements. | Invoices. | P6 | — |
| Q-PAY-06 | Accounting software, if any. | Optional sync. | P6 | — |
| Q-PAY-07 | Overdue policy: reminders; when lessons pause. | Payment Tracking Agent. | P6 | Reminders off |

### H. Communication channels (Q-COM, Q-WEB)

These don't block Phase 1, but **Q-COM-01 and Q-COM-02 should be answered early**: Meta business verification and WhatsApp approvals take time.

| ID | Open question | Why it matters | Needed by | Until answered |
|----|---------------|----------------|-----------|----------------|
| Q-COM-01 | WhatsApp: one number for all markets or one per market? Which numbers exist? | Channel accounts, templates. | P3 | WhatsApp off |
| Q-COM-02 | How is WhatsApp used today (app, provider, API)? | Migration/coexistence plan. | P3 | — |
| Q-COM-03 | Google Workspace or Microsoft 365? Which mailboxes? | Email adapter. | P3 | Email off |
| Q-COM-04 | Instagram: lead ads, DMs, or both? | Integration scope. | P7 | Instagram off |
| Q-COM-05 | Sending domain(s); SPF/DKIM/DMARC status. | Deliverability. | P3 | — |
| Q-WEB-01 | Website platform/CMS; who can add forms/scripts. | Forms, chat widget. | P3 | — |
| Q-WEB-02 | Bot-protection preference. | Form security. | P3 | Proposed default chosen at build |

### I. AI behaviour (Q-AI)

| ID | Open question | Why it matters | Needed by | Until answered |
|----|---------------|----------------|-----------|----------------|
| Q-AI-01 | Brand voice and tone guide; assistant name; how it introduces itself. | Prompts. | P4 | Neutral professional tone |
| Q-AI-02 | Any exception at launch to "a person approves every outbound message" (e.g. live website-chat FAQs)? | Approval policy. | P4 | Approval for everything (BD-027) |
| Q-AI-03 | Which languages should the AI reply in; can staff review them? | Language support. | P4 | English only; others to a person |
| Q-AI-04 | Topics the AI must never discuss / always escalate. | Guardrails. | P4 | Proposed escalation list |
| Q-AI-05 | May the AI or staff message **students directly**? From what age, with whose consent? | Safeguarding, consent. | P3 | Guardians only |
| Q-AI-06 | LLM provider order; monthly AI budget. | Model profiles, cost. | P4 | Per-run limits only |
| Q-AI-07 | Existing content for the knowledge base (FAQs, scripts, curriculum explainers, policies). | Knowledge base. | P4 | — |

### J. Compliance and privacy (Q-CMP)

| ID | Open question | Why it matters | Needed by | Until answered |
|----|---------------|----------------|-----------|----------------|
| Q-CMP-01 | Legal/data-protection contact; privacy notice and terms; consent wording. | See §2. | **P1-live** | No real data collected |
| Q-CMP-02 | Hosting region; data residency / cross-border transfers. | See §2. | **P1-live** | Synthetic data only |
| Q-CMP-03 | Age range of students taught; are customers mainly parents of minors? | Children's-data duties. | P3 | All students treated as minors |
| Q-CMP-04 | Is full date of birth needed, or year only? | Minimisation. | Later | Year only |
| Q-CMP-05 | Should conversations disclose AI involvement? | Disclosure. | P4 | Disclosure on |
| Q-CMP-06 | Approval to process conversations with Anthropic/OpenAI; data-retention terms. | Provider contracts. | P4 | Customer data to LLMs blocked |
| Q-CMP-07 | Retention periods per data type. | Retention jobs. | P8 | No automatic deletion |
| Q-CMP-08 | Safeguarding policy and designated safeguarding lead. | Urgent escalation path. | P4 | Escalate to Owner |
| Q-CMP-09 | Session recordings (Ireland, HK Premium): consent, storage, retention, access. | Consent, storage. | P6 | Not handled by Mixt AI |
| Q-CMP-10 | Do existing contacts have WhatsApp/email marketing consent? | What may be imported and contacted. | P3 | Imported contacts get no marketing |

### K. Existing data (Q-DAT)

| ID | Open question | Why it matters | Needed by | Until answered |
|----|---------------|----------------|-----------|----------------|
| Q-DAT-01 | Where do current leads, customers, students and tutors live? Approximate counts? | Migration plan. | P1-live (only if importing at go-live) | Start empty; CSV import later |
| Q-DAT-02 | Anonymised sample conversations and leads. | AI evaluation scenarios. | P4 | Synthetic scenarios |
| Q-DAT-03 | Historical sales data. | Reporting baselines. | P8 | — |

### L. Team and operations (Q-TEAM)

| ID | Open question | Why it matters | Needed by | Until answered |
|----|---------------|----------------|-----------|----------------|
| Q-TEAM-01 | Staff list, roles, markets and languages per person. | Accounts, routing. | P1-live (set-up) | Manual assignment |
| Q-TEAM-02 | Confirm the role list and who approves what ([08 §3](08-security-privacy.md#3-authorisation)). | RBAC. | P1 | Proposed roles |
| Q-TEAM-03 | Target SLAs: speed-to-lead, escalation response, working hours. | SLA timers. | P3 | No SLA alerts |
| Q-TEAM-04 | Internal alert channel. | Notifications. | P4 | Dashboard + email |
| Q-TEAM-05 | Development team, budget, target dates. | Scheduling the roadmap. | Planning | — |

### M. Technical (Q-TECH)

| ID | Open question | Why it matters | Needed by | Until answered |
|----|---------------|----------------|-----------|----------------|
| Q-TECH-01 | Staff login via SSO (Google/Microsoft) or local accounts? And should the provider's own multi-factor sign-in replace Mixt's two-step code? | Auth. | P1 | Local accounts + MFA. Single sign-on for Google and Microsoft is **built and tested but off** (`auth.sso` = `off`, `auth.sso_satisfies_mfa` = `false`); switching it on needs only this answer and the client credentials ([14 §9](14-operations-runbook.md#9-single-sign-on-optional-off-until-mixt-decides-q-tech-01)) |
| Q-TECH-02 | Expected volumes (leads/month, conversations/day, active students). | Sizing. | P1 (nice to have) | Design sized for 10⁵ contacts |
| Q-TECH-03 | Accept proposed targets (99.5%, RPO ≤ 15 min, RTO ≤ 4 h)? | Infrastructure cost. | P1 (nice to have) | Proposed targets apply |
| Q-TECH-04 | Cloud provider / account for production. | See §2. | **P1-live** | Temporary staging only |
| Q-TECH-05 | Who operates the system after launch? | Runbooks, access. | P8 | — |

### N. Brand (Q-BRD)

| ID | Open question | Why it matters | Needed by | Until answered |
|----|---------------|----------------|-----------|----------------|
| Q-BRD-01 | Logo, brand colours (hex), fonts, guidelines. | Design system. | P1 (nice to have) | Placeholder tokens |
| Q-BRD-02 | Quotation/invoice layout; company details to print. | PDFs. | P2 | Plain layout |

### O. Business scope (Q-BIZ)

| ID | Open question | Why it matters | Needed by | Until answered |
|----|---------------|----------------|-----------|----------------|
| Q-BIZ-01 | One brand/legal entity, or several (now or planned)? | Single-tenant assumption A-01. | P1 (nice to have) | Single brand |
| Q-BIZ-02 | Besides 1:1 online tutoring (CONFIRMED), is any other format offered (e.g. group classes)? | Pricing/scheduling model. | Later | 1:1 only |
| Q-BIZ-03 | Will schools or institutions ever be customers? | Account types. | P7 | Households only |

### P. CRM data model (Q-CRM)

| ID | Open question | Why it matters | Needed by | Until answered |
|----|---------------|----------------|-----------|----------------|
| Q-CRM-01 | Which fields must be captured before a lead counts as qualified? | Stage requirements. | P1 (nice to have) | Proposed fields |
| Q-CRM-02 | Can a student have two guardian contacts (supported), and can separate households share a student? | Edge cases. | P1 (nice to have) | One household per student |

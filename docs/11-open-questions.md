# 11: Open Questions and Missing Business Information

Status: **Open** · Last updated 2026-11-09

**Priority:** **P0** blocks architecture sign-off, Phase 1–2, or any pricing activation · **P1** needed before the phase that uses it · **P2** can wait.
Answers can be given inline (e.g. "Q-PRC-02: …") in any order. Each answer will be recorded in the relevant document with the date and who confirmed it.

## Answer these first (top 12)

| # | ID | Question |
|---|----|----------|
| 1 | Q-PRC-02 | What do **Tier A and Tier B** mean (UK GBP, UAE AED), and how is a customer placed on each? |
| 2 | Q-MKT-01 | Which market(s) do **USD Schedule A and B** apply to? (Not the US.) |
| 3 | Q-PRC-03 | How do **Ireland Schedule A and B** relate, and who is eligible for each? |
| 4 | Q-MKT-04 | How is a customer's **pricing market** decided (residence, school country, billing address, phone)? |
| 5 | Q-PAY-04 | Are prices **inclusive of VAT/GST** where it applies, and which entity invoices which market? |
| 6 | Q-PRC-09 | Do prices vary by **curriculum, level, subject or tutor**? |
| 7 | Q-PRC-14–17 | The **double-check list** in [05 §3](05-pricing-data-register.md#3-points-to-double-check-before-activation) (identical figures across books, UK Tier A 100h, missing rows). |
| 8 | Q-MKT-03 | Pricing for **Kuwait, Oman, Bahrain, Singapore, Indonesia, South Korea**: coming, and what should be said meanwhile? |
| 9 | Q-AI-05 | May the AI or staff talk **directly to students** (minors)? From what age? |
| 10 | Q-CMP-02 | **Hosting region** and data-residency requirements (legal advice). |
| 11 | Q-COM-01/03 | **WhatsApp numbers** (one or per market) and **Google Workspace vs Microsoft 365**. |
| 12 | Q-DAT-01 | Where do current **leads, customers and tutor records** live today, and how many are there? |

---

## A. Pricing (Q-PRC)

| ID | Question | Why it matters | Blocks | Pri |
|----|----------|----------------|--------|-----|
| Q-PRC-01 | Which further pricing sheets are coming (markets, currencies, plans, promotions), and when? | Defines the remaining pricing scope; the database stays marked incomplete until then. | Phase 2 exit | P0 |
| Q-PRC-02 | What distinguishes **Tier A** from **Tier B** (UK GBP; UAE AED)? Is one the standard public price and the other special? What decides which tier a customer gets (new vs existing, source, campaign, negotiation, date of enquiry)? | Tiers can never be auto-selected; the system needs an explicit default or rule, or every UK/UAE quote becomes a manual decision. | Activation (UK, UAE) | P0 |
| Q-PRC-03 | **Ireland Schedule A vs B:** current vs legacy? Different customer groups? Different products? Can both be offered at once? | Kept separate per brief; the activation gate needs a rule to choose. | Activation (IE) | P0 |
| Q-PRC-04 | Are there general eligibility rules (new customers only, existing customers, referrals, siblings, campaigns)? | Eligibility rules configuration. | Phase 2 | P1 |
| Q-PRC-05 | Which supplied schedules (if any) are **promotional**? For each promotion: what changes, start/end dates, eligibility, stacking. | No promotion can be activated without these. | Promotions | P1 |
| Q-PRC-06 | Saudi SAR, Qatar QAR, Malaysia MYR: is there only one schedule per market? Are they "Standard"? Are Tier B or Premium versions coming? | Plan type and tier per book. | Activation (SA, QA, MY) | P0 |
| Q-PRC-07 | Ireland Schedule A is in **classes**: is a class 60 minutes? Are any lessons 30/45/90 minutes, and how do they count against package hours? | Unit definition and hours ledger. | Activation (IE), Phase 6 | P0 |
| Q-PRC-08 | All supplied totals divide into whole per-hour rates (e.g. £285/15h = £19/h). Are those **official advertised hourly rates** to store and show, or should customers only see package totals? | Separate hourly-rate field (P-03). | Phase 2 | P1 |
| Q-PRC-09 | Do prices vary by **curriculum, level (e.g. A Level vs GCSE), subject, exam board or tutor seniority**? | The current model assumes one price per package regardless of these; if not true, price books need extra dimensions. | Architecture | P0 |
| Q-PRC-10 | **Minimum purchases:** is there a minimum package per market/plan? In Hong Kong, are 60h+ packages only available as Premium, and can Standard be bought above 40h? | Minimum-purchase rules (none assumed). | Activation (HK) | P1 |
| Q-PRC-11 | **Discount authority:** who may approve discounts, up to what % or amount, per market? Above what level are two approvers needed? | Negotiation and quotation approvals. | Phase 2 | P1 |
| Q-PRC-12 | Rounding rule for discounted prices per currency (e.g. nearest whole unit). | Discount maths. | Phase 2 | P2 |
| Q-PRC-13 | How long is a quotation valid? If prices change, are issued quotations honoured until expiry? | Quotation validity. | Phase 2 | P1 |
| Q-PRC-14 | **UK Tier A:** please confirm 100h = **£1,000** (80h = £960, so the extra 20h cost £40). | Data check DC-01. | Activation (UK) | P0 |
| Q-PRC-15 | **UAE AED Tier A and B** are identical at 100h/150h/200h (4,900 / 6,600 / 7,600). Intended? | Data check DC-02. | Activation (AE) | P0 |
| Q-PRC-16 | Several books share identical numbers: SAR = AED Tier B; QAR = AED Tier A; USD Schedule A 150h/200h = UK Tier B 150h/200h; Ireland Schedule B 20/30/50/100h = USD Schedule A. Intended? | Data checks DC-03 to DC-06; rules out copy-paste errors. | Activation | P0 |
| Q-PRC-17 | Are any package rows missing (e.g. UK Tier A 150h/200h, UK Tier B 80h, HK Standard above 40h)? | Data check DC-07; the system never invents durations. | Activation | P0 |
| Q-PRC-18 | Can customers buy **non-listed quantities** (e.g. 25 hours)? If yes, how are they priced and who approves? | Custom quotation rules. | Phase 2 | P1 |
| Q-PRC-19 | **Several students:** one shared package, or one package per student? Any sibling pricing? | Quotation structure, family sharing. | Phase 2 | P1 |
| Q-PRC-20 | Who is Mixt's **pricing owner**, and should pricing activation require two approvers? | Activation gate G-07. | Phase 2 | P0 |

## B. Markets and currencies (Q-MKT)

| ID | Question | Why it matters | Blocks | Pri |
|----|----------|----------------|--------|-----|
| Q-MKT-01 | Which market(s) do **USD Schedule A** and **USD Schedule B** apply to? (e.g. some unpriced markets, international families, a specific channel.) The US is never one of them. | USD books cannot be assigned or activated without this. | Activation (USD) | P0 |
| Q-MKT-02 | How should enquiries from **non-target countries** (including US residents) be handled: polite decline, a person decides case by case, or something else? | Out-of-market workflow and AI wording. | Phase 1 | P1 |
| Q-MKT-03 | Is pricing coming for **Kuwait, Oman, Bahrain, Singapore, Indonesia, South Korea**? Until then, may the AI say "our team will confirm pricing for your country"? | Escalation wording; sales in those markets. | Phase 4 | P0 |
| Q-MKT-04 | How is a customer's **pricing market** decided: country of residence, the student's school country, billing address, phone country code? How are expatriates or families moving country handled? | Market confirmation is the first step of price resolution. | Phase 2 | P0 |
| Q-MKT-05 | Can a customer pay in a currency other than their market's currency? | Payment rules (no conversion inside the system). | Phase 6 | P1 |
| Q-MKT-06 | Launch order of markets. Which markets go live first? | Phasing, templates, languages. | Phase 3 | P1 |
| Q-MKT-07 | Working days, working hours and acceptable contact hours per market. | Quiet hours, SLAs, scheduling. | Phase 3 | P1 |

## C. Packages, benefits and policies (Q-PKG)

| ID | Question | Why it matters | Blocks | Pri |
|----|----------|----------------|--------|-----|
| Q-PKG-01 | Which packages/markets do the **general benefits** apply to (past papers, academic support, flexible scheduling, no expiry where applicable, multiple subjects, sibling sharing)? | Benefits are never applied across markets without approval. | Activation | P0 |
| Q-PKG-02 | **Expiry:** which packages have no expiry and which have validity periods (Ireland: 18 months)? What applies in markets where nothing is stated? | Package expiry and the claims guard. | Activation | P0 |
| Q-PKG-03 | Do the **Ireland policies** apply to Schedule A, Schedule B, or both? | Benefits per version. | Activation (IE) | P0 |
| Q-PKG-04 | HK Premium: does "**bi-monthly** consultations" mean twice a month or every two months? Does "**bi-weekly** reports" mean twice a week or every two weeks? | Exact customer-facing wording; avoids over-promising. | Activation (HK) | P1 |
| Q-PKG-05 | Exact terms of Ireland's **first-paid-session refund or free tutor swap guarantee**: conditions, time limit, who decides, how it is claimed. | Policy text; refund handling is always human. | Activation (IE) | P1 |
| Q-PKG-06 | **Family sharing:** which packages, how many students, same household only? | Ledger rules. | Phase 6 | P1 |
| Q-PKG-07 | **Pause/resume** (Ireland): maximum pause length, how often, notice needed, effect on the 18-month validity. | Ledger and expiry calculation. | Phase 6 | P1 |
| Q-PKG-08 | HK Standard "**up to four subjects**": per student or per account? | Policy enforcement. | Activation (HK) | P1 |
| Q-PKG-09 | Cancellation, late-cancellation and no-show rules: when are hours deducted? | Hours ledger. | Phase 6 | P1 |
| Q-PKG-10 | General **refund policy** for unused hours, by market. | Refund workflow, AI answers. | Phase 6 | P1 |

## D. Academic offering (Q-ACA)

| ID | Question | Why it matters | Blocks | Pri |
|----|----------|----------------|--------|-----|
| Q-ACA-01 | Subjects offered per curriculum and level. | Reference data, qualification, matching. | Phase 1 | P1 |
| Q-ACA-02 | Which **exam board × qualification** combinations are taught (e.g. Cambridge IGCSE, Edexcel IGCSE, AQA GCSE, OCR A Level)? | Reference data; the AI must not offer what isn't taught. | Phase 1 | P1 |
| Q-ACA-03 | Grade/year structure per curriculum: Irish (e.g. primary classes, Junior Cycle, Leaving Certificate?), SABIS levels, American grades and any AP/SAT preparation. | Grade reference data (nothing assumed). | Phase 1 | P1 |
| Q-ACA-04 | Any other programmes (e.g. IB, 11+, university admissions tests, language exams)? IB is not in the brief, so it is treated as **not offered**. | Scope of AI answers. | Phase 4 | P2 |
| Q-ACA-05 | Exam session calendars to load per board (for urgency and package-size recommendations). | Pricing recommendations, retention. | Phase 4 | P2 |

## E. Sales process (Q-SAL)

| ID | Question | Why it matters | Blocks | Pri |
|----|----------|----------------|--------|-----|
| Q-SAL-01 | Current sales process step by step, typical volumes and conversion rates. | Pipeline design, baselines. | Phase 1 | P0 |
| Q-SAL-02 | **Free trial policy:** always offered? Length? One per student/subject? All markets? | Pipeline, scheduling, AI wording. | Phase 4 | P1 |
| Q-SAL-03 | What makes a lead qualified or disqualified? | Qualification scoring rules. | Phase 4 | P1 |
| Q-SAL-04 | Approved positioning, objection responses and main competitors per market. | Objection library for the AI. | Phase 4 | P1 |
| Q-SAL-05 | **Referral programme:** rewards, eligibility, approval. | Referral module (none assumed). | Phase 7 | P2 |
| Q-SAL-06 | Follow-up cadence: number of touches, intervals, when to stop. | Sequences, frequency caps. | Phase 4 | P1 |
| Q-SAL-07 | **Lead generation scope:** inbound only, or also outbound to schools/partners (B2B)? Any purchased or partner lists, and with what consent? | Lead Generation Agent's lawful boundaries. | Phase 7 | P1 |
| Q-SAL-08 | Renewal approach: when to start (balance threshold), any renewal incentives? | Retention Agent. | Phase 7 | P2 |

## F. Tutors and scheduling (Q-TUT, Q-SCH)

| ID | Question | Why it matters | Blocks | Pri |
|----|----------|----------------|--------|-----|
| Q-TUT-01 | Where is tutor data held today; how many tutors; employment model? | Migration and tutor module. | Phase 5 | P1 |
| Q-TUT-02 | Where are lessons scheduled and recorded today (LMS or other tool)? Should Mixt AI become the lesson system, or import lesson data? | Hours ledger source. | Phase 6 | P1 |
| Q-TUT-03 | Tutor safeguarding/background-check requirements per market. | Matching hard filter. | Phase 5 | P1 |
| Q-TUT-04 | Matching priorities; may customers request specific tutors or tutor characteristics? | Matching weights. | Phase 5 | P2 |
| Q-SCH-01 | Video platform and calendar system used for lessons and trials. | Scheduling integration. | Phase 5 | P1 |
| Q-SCH-02 | Who confirms trial bookings, how long trials are, minimum notice. | Scheduling rules. | Phase 5 | P1 |
| Q-SCH-03 | Lesson lengths offered (60 minutes only?). | Scheduling and ledger. | Phase 5 | P0 |

## G. Payments and finance (Q-PAY)

| ID | Question | Why it matters | Blocks | Pri |
|----|----------|----------------|--------|-----|
| Q-PAY-01 | Payment methods and providers used today, per market. | Provider integration choice. | Phase 6 | P1 |
| Q-PAY-02 | Full upfront payment, instalments or subscriptions? | Payment and ledger design. | Phase 6 | P1 |
| Q-PAY-03 | Which legal entity invoices which market? | Invoices, tax, payment provider. | Phase 6 | P1 |
| Q-PAY-04 | **Tax:** are prices VAT/GST-inclusive where applicable? Where is Mixt tax-registered? Invoice requirements? | Activation gate G-05; quotation totals. | Activation | P0 |
| Q-PAY-05 | Invoice numbering and layout requirements. | Invoice generation. | Phase 6 | P2 |
| Q-PAY-06 | Accounting software used (if any). | Optional sync. | Phase 6 | P2 |
| Q-PAY-07 | Overdue policy: reminder schedule; when lessons pause. | Payment Tracking Agent. | Phase 6 | P2 |

## H. Communication channels (Q-COM, Q-WEB)

| ID | Question | Why it matters | Blocks | Pri |
|----|----------|----------------|--------|-----|
| Q-COM-01 | **WhatsApp numbers:** one for all markets or one per market? Which numbers exist today? | Channel accounts, templates. | Phase 3 | P0 |
| Q-COM-02 | How is WhatsApp used today (Business app on a phone, a provider/BSP, the API)? | Migration or coexistence plan. | Phase 3 | P0 |
| Q-COM-03 | **Google Workspace or Microsoft 365?** Which mailboxes should be connected? | Email adapter and auth. | Phase 3 | P0 |
| Q-COM-04 | **Instagram:** lead ads, direct messages, or both? | Integration scope. | Phase 7 | P1 |
| Q-COM-05 | Sending domain(s); SPF/DKIM/DMARC status. | Email deliverability. | Phase 3 | P1 |
| Q-WEB-01 | Website platform/CMS and who can add forms/scripts. | Forms and chat widget. | Phase 3 | P1 |
| Q-WEB-02 | Bot-protection preference (e.g. Cloudflare Turnstile, reCAPTCHA). | Form security. | Phase 3 | P2 |

## I. AI behaviour (Q-AI)

| ID | Question | Why it matters | Blocks | Pri |
|----|----------|----------------|--------|-----|
| Q-AI-01 | Brand voice and tone guide. Should the assistant have a name? How should it introduce itself? | Prompts, disclosure. | Phase 4 | P1 |
| Q-AI-02 | Confirm launch autonomy: **AI drafts, a person approves every outbound message.** Any exception at launch (e.g. website chat answering FAQs live)? | Approval policy defaults. | Phase 4 | P0 |
| Q-AI-03 | Which languages should the AI reply in, and can staff review messages in those languages? | Language support and approval. | Phase 4 | P1 |
| Q-AI-04 | Topics the AI must never discuss or must always pass to a person. | Guardrails and escalation. | Phase 4 | P1 |
| Q-AI-05 | May the AI or staff message **students directly**? From what age, with whose consent? | Safeguarding, consent, channel rules. | Phase 3 | P0 |
| Q-AI-06 | Preferred LLM provider order; monthly AI budget limit. | Model profiles, cost controls. | Phase 4 | P2 |
| Q-AI-07 | Existing content for the knowledge base: FAQs, scripts, curriculum explainers, policies, testimonials (with consent). | Knowledge base. | Phase 4 | P1 |

## J. Compliance and privacy (Q-CMP)

| ID | Question | Why it matters | Blocks | Pri |
|----|----------|----------------|--------|-----|
| Q-CMP-01 | Who is Mixt's legal/data-protection contact? Existing privacy policy and terms? | Legal review. | Phase 1 | P0 |
| Q-CMP-02 | **Hosting region** and data-residency or cross-border transfer requirements (especially Saudi Arabia, UAE, Indonesia). | Cloud region; possibly several regions. | Phase 1 (prod) | P0 |
| Q-CMP-03 | Confirm customers are mainly parents of minors; what age range do you teach? | Children's-data obligations. | Phase 1 | P0 |
| Q-CMP-04 | Is a student's full date of birth needed, or is year of birth enough? | Data minimisation. | Phase 1 | P2 |
| Q-CMP-05 | Should conversations state that an AI assistant is involved (legal requirement or brand choice)? | AI disclosure. | Phase 4 | P1 |
| Q-CMP-06 | Approval to process customer conversations with Anthropic and OpenAI; preferred data-retention terms. | Contracts with AI providers. | Phase 4 | P0 |
| Q-CMP-07 | Retention periods: lost leads, conversations, recordings, audit logs, financial records. | Retention jobs. | Phase 8 | P1 |
| Q-CMP-08 | Safeguarding policy and designated safeguarding lead for urgent escalations. | Safety escalation path. | Phase 4 | P1 |
| Q-CMP-09 | **Session recordings** (Ireland, HK Premium): consent process, storage location, retention, access. | Consent, storage design. | Phase 6 | P1 |
| Q-CMP-10 | Do existing leads/customers have consent for WhatsApp/email marketing? | What can be imported and contacted. | Phase 3 | P1 |

## K. Existing data (Q-DAT)

| ID | Question | Why it matters | Blocks | Pri |
|----|----------|----------------|--------|-----|
| Q-DAT-01 | Where do current leads, customers, students and tutors live (spreadsheets, a CRM, WhatsApp chats)? Approximate counts? | Migration plan. | Phase 1 | P0 |
| Q-DAT-02 | Can you share **anonymised** sample conversations and leads? | AI development and evaluation scenarios. | Phase 4 | P1 |
| Q-DAT-03 | Historical sales data for reporting baselines. | Analytics. | Phase 8 | P2 |

## L. Team and operations (Q-TEAM)

| ID | Question | Why it matters | Blocks | Pri |
|----|----------|----------------|--------|-----|
| Q-TEAM-01 | Team size, roles, markets per rep, languages spoken. | Roles, routing, sizing. | Phase 1 | P0 |
| Q-TEAM-02 | Confirm the role list and who approves what ([08 §3](08-security-privacy.md#3-authorisation)). | RBAC configuration. | Phase 1 | P1 |
| Q-TEAM-03 | Target SLAs: speed-to-lead, escalation response times, working hours. | SLA timers, Manager Agent. | Phase 3 | P1 |
| Q-TEAM-04 | Internal alert channel: email, Slack, Microsoft Teams, other? | Notifications. | Phase 4 | P2 |
| Q-TEAM-05 | Development team, budget and target dates. | Roadmap scheduling. | Approval | P0 |

## M. Technical (Q-TECH)

| ID | Question | Why it matters | Blocks | Pri |
|----|----------|----------------|--------|-----|
| Q-TECH-01 | Staff login via **SSO** (Google/Microsoft) or local accounts with MFA? | Auth design. | Phase 1 | P1 |
| Q-TECH-02 | Expected volumes: leads/month, conversations/day, active students. | Sizing. | Phase 1 | P1 |
| Q-TECH-03 | Accept the proposed targets (99.5% availability, RPO ≤ 15 min, RTO ≤ 4 h)? | Infrastructure cost and design. | Phase 1 | P2 |
| Q-TECH-04 | Cloud provider preference or existing accounts? | Infrastructure. | Phase 1 | P1 |
| Q-TECH-05 | Who operates the system after launch (in-house or vendor)? | Runbooks, access. | Phase 8 | P2 |

## N. Brand (Q-BRD)

| ID | Question | Why it matters | Blocks | Pri |
|----|----------|----------------|--------|-----|
| Q-BRD-01 | Logo, exact brand colours (hex), fonts, brand guidelines. | Design system (current tokens are placeholders). | Phase 1 | P1 |
| Q-BRD-02 | Quotation and invoice layout requirements; company details to print. | PDFs. | Phase 2 | P2 |

## O. Business scope (Q-BIZ)

| ID | Question | Why it matters | Blocks | Pri |
|----|----------|----------------|--------|-----|
| Q-BIZ-01 | One brand/legal entity, or several (now or planned)? | Single-tenant assumption A-01. | Architecture | P1 |
| Q-BIZ-02 | Only 1:1 tutoring, or group classes too? | Pricing and scheduling model. | Architecture | P2 |
| Q-BIZ-03 | Will schools or institutions ever be customers (B2B)? | Account types, pricing. | Phase 7 | P2 |

## P. CRM data model (Q-CRM)

| ID | Question | Why it matters | Blocks | Pri |
|----|----------|----------------|--------|-----|
| Q-CRM-01 | Which fields must be captured before a lead counts as qualified, and which are optional? | Stage entry requirements. | Phase 1 | P1 |
| Q-CRM-02 | Can a student have more than one guardian contact (e.g. both parents), and can parents in separate households share a student? | Household model edge cases. | Phase 1 | P1 |

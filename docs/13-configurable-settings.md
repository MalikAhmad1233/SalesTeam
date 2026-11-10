# 13: Configurable Settings Register

Status: **APPROVED 2026-11-10** · Implemented in Phase 1a (`services/backend/mixt/modules/settings`) · Implements ADR-11 and ADR-16 ([decision log](12-decision-log.md))

## 1. Why this exists

Many business decisions are still OPEN (see [11](11-open-questions.md)). The architecture must not wait for all of them (BD-030). Each outstanding decision is therefore a **setting** with a **safe default**:

- A safe default is **the most restrictive behaviour that still lets people work manually**: escalate to a person, show no figure, send nothing automatically.
- A safe default is **never a guessed business answer.** For example, there is no default quotation validity period: the approver types the expiry date on each quote until Mixt decides a standard.
- When Mixt answers a question, the setting changes to `confirmed`, with a reference to the decision-log entry. No code change is needed.

## 2. How settings work

| Aspect | Design |
|--------|--------|
| Storage | **Definitions live in code** (`services/backend/mixt/modules/settings/registry.py`): key, description, JSON schema, safe default, status, decision reference, who may change it, dual approval, open question. They sit next to the code that interprets them, and a test checks they match this document. **Values** that differ from the default, or that Mixt has confirmed, are stored in `system_settings` (key, scope, value, `status` = `safe_default` / `confirmed`, `decision_ref`, `version`); see [02 §15](02-database-schema.md#15-integrations-and-reliability). |
| Scopes | `global`, `market`, `price_book`, `price_book_version`, `channel`, `agent`, `role` |
| Validation | Every value is validated against its JSON schema; invalid values are refused. |
| Changes | Permission-checked; sensitive settings need two approvers; every change is audited with old/new value and decision reference. |
| Visibility | **Settings → Outstanding decisions** lists every setting still on `safe_default`, with its open question, so nothing is forgotten. |
| Caching | Read through a short-lived cache invalidated on change; agent runs record the setting versions they used. |

Who may change: **Owner** = Owner/Super Admin; **PM** = Pricing Manager; **SM** = Sales Manager; **Admin** = Admin (Operations); **Fin** = Finance.

## 3. Pricing and quotations

| Setting | Scope | Value now | Status | Other options | Question | Changed by |
|---------|-------|-----------|--------|---------------|----------|-----------|
| `pricing.catalogue_complete` | global | `false`: "Pricing data incomplete" banner in Pricing and Quotations | **confirmed** (BD-017) | `true` | Q-PRC-01 | Owner + PM |
| `pricing.market_basis` | global | `staff_confirmed`: a person confirms each account's pricing market from what the customer says (e.g. where they live). Currency, phone prefix and curriculum are never used (ADR-13). | safe_default | `rule_based` (an approved rule proposes; staff still confirm) | Q-MKT-04 | Owner |
| `pricing.tier_selection_mode` | market | `manual` for **UK, UAE, Ireland**: a person with `pricing.tier.select` picks the tier/schedule per customer, with a reason; until then the engine returns `TIER_DECISION_REQUIRED`; AI never selects (ADR-12) | safe_default | `market_default`, `rule_based` | Q-PRC-02, Q-PRC-03 | PM (dual) |
| `pricing.activation.dual_approval` | global | `true` | safe_default | `false` | Q-PRC-20 | Owner |
| `pricing.version.tax_treatment` | price_book_version | `unknown`: **version cannot be activated** | safe_default | `inclusive`, `exclusive`, `not_applicable` | Q-PAY-04 | PM + Fin |
| `pricing.version.minutes_per_unit` | price_book_version (+ per-package exception policy) | `60`, for hour-based and class-based books | **confirmed** for supplied class-based schedules (BD-011) | other values only via a confirmed package-specific exception | — | PM |
| `pricing.customer_rate_display` | global | `totals_only`: customers see package totals; the derived effective hourly rate is shown to staff only, labelled "derived" | safe_default | `totals_and_derived_rate`, `totals_and_official_rate` | Q-PRC-08 | PM |
| `pricing.plan_label_display` | price_book | Hong Kong: `Standard` / `Premium` (**confirmed**, BD-016). All other books: `none`, so no plan name is shown to customers | mixed | a confirmed plan label | Q-PRC-06 | PM |
| `pricing.custom_quantities` | global | `disabled`: only listed quantities can be quoted; any other quantity becomes a custom-quote request to a person | safe_default | `approval_required` with a pricing method | Q-PRC-18 | PM |
| `pricing.discounts.mode` | global | `amount_only_with_approval`: percentage discounts disabled (no rounding rule yet); any discount needs Sales Manager **and** Pricing Manager approval | safe_default | `percent_allowed` + rounding rule per currency | Q-PRC-11, Q-PRC-12 | Owner |
| `pricing.discount_authority` | role × market | empty: no single person can approve a discount alone | safe_default | limits per role/market | Q-PRC-11 | Owner |
| `pricing.minimum_purchase_rules` | market × plan | none | safe_default | rules | Q-PRC-10 | PM |
| `pricing.multi_student_quotes` | global | `staff_built`: AI drafts single-student options only; staff build multi-student quotations | safe_default | `ai_drafts_allowed` | Q-PRC-19 | PM |
| `pricing.unpriced_market_handling` | global | `escalate_no_figures`: no figure is given; AI drafts a holding message for a person to approve | safe_default | approved holding template sent automatically | Q-MKT-03 | SM |
| `quotations.validity` | global | `set_per_quote`: the approver must enter an expiry date on every quotation | safe_default | `fixed_days:N` | Q-PRC-13 | PM |
| `quotations.on_price_change` | global | `reconfirm_before_acceptance`: if a quote's price version is superseded, a person must confirm before the quote is accepted (the issued quote itself is never altered) | safe_default | `honour_until_expiry`, `expire_on_change` | Q-PRC-13 | PM |
| `promotions.enabled` | global | `false`: promotions can be drafted but not activated; promotions never modify standard entries (ADR-15) | safe_default | `true` | Q-PRC-05 | Owner + PM |
| `benefits.claims_mode` | price_book_version | `approved_only`: only benefits/policies attached **and approved** for that exact version can be shown or said; none are attached yet | safe_default | — | Q-PKG-01 to Q-PKG-10 | PM |

## 4. Markets, CRM and academic data

| Setting | Scope | Value now | Status | Other options | Question | Changed by |
|---------|-------|-----------|--------|---------------|----------|-----------|
| `markets.operating` | market | The 13 markets of BD-004 marked operating. US stored only as an excluded country. | **confirmed** (BD-004, BD-005) | add/remove market (excluded countries blocked) | — | Owner |
| `markets.mixt_ai_rollout` | market | `off` (which markets use Mixt AI first is a rollout choice) | safe_default | `crm_only`, `channels`, `ai_drafts` | Q-MKT-06 | Owner |
| `markets.out_of_market_handling` | global | `human_review`: enquiry flagged, no AI sales reply, no pricing, never added as a market | safe_default | `polite_decline_template` | Q-MKT-02 | SM |
| `markets.contact_hours`, `markets.working_days` | market | unset: **scheduled/automated sends disabled**; person-approved sends allowed | safe_default | hours/days per market | Q-MKT-07 | Admin |
| `crm.curricula` | global | Irish, SABIS, American, British (**confirmed**, BD-007). Adding one (e.g. IB) needs Owner approval and a decision-log entry (BD-008). | **confirmed** | — | Q-ACA-04 | Owner |
| `crm.grade_entry` | curriculum | `free_text` until grade lists are supplied | safe_default | `controlled_list` | Q-ACA-03 | Admin |
| `crm.offerings_unconfirmed` | global | board × qualification and subject combinations not marked "offered" → AI may not say Mixt teaches them; it escalates | safe_default | — | Q-ACA-01, Q-ACA-02 | Admin |
| `crm.student_birth_data` | global | `year_only` | safe_default | `full_date` | Q-CMP-04 | Owner |
| `crm.lead_assignment` | global | `manual` | safe_default | rules (market, language, workload) | Q-TEAM-01 | SM |
| `crm.unassigned_pool_visible_to_reps` | global | `true`: sales reps can see accounts with no owner yet | safe_default | `false` (only managers see the pool) | Q-TEAM-02 | SM |
| `crm.pipeline_stages` | global | The 12 proposed stages from [06 §4](06-crm-structure.md#4-sales-pipeline-default-new_business-pipeline-proposal), each with the checks needed to enter it (`owner`, `market_confirmed`, `student_profile`, `note`, `lost_reason`, `nurture_until`). Qualified = owner + confirmed market + a linked student with curriculum, grade and a subject. Trial, quotation and payment stages need a note until those modules exist. A stage that still holds opportunities cannot be removed. | safe_default | edited stages and checks | Q-SAL-01, Q-CRM-01, Q-SAL-03 | Admin |
| `crm.lost_reasons` | global | Generic proposed list: price, timing, chose another provider, no response, needs not covered, other. A reason still used by lost opportunities cannot be removed. | safe_default | edited list | Q-SAL-01 | Admin |

## 5. Channels and AI

| Setting | Scope | Value now | Status | Other options | Question | Changed by |
|---------|-------|-----------|--------|---------------|----------|-----------|
| `channels.email.provider` | global | unset (email channel off) | safe_default | `gmail`, `microsoft_graph` | Q-COM-03 | Admin |
| `channels.whatsapp.numbers` | market | none (WhatsApp channel off) | safe_default | number(s) per market or shared | Q-COM-01, Q-COM-02 | Admin |
| `channels.instagram` | global | `disabled` | safe_default | `lead_ads`, `dms`, `both` | Q-COM-04 | Admin |
| `messaging.student_direct_contact` | global | `disabled`: messages go to guardians only | safe_default | `enabled_from_age:N` | Q-AI-05 | Owner |
| `messaging.sequences_enabled` | global | `false` until cadence and contact hours are set | safe_default | `true` | Q-SAL-06, Q-MKT-07 | SM |
| `ai.enabled` | global / agent / channel / market | `false` | safe_default | `true` | Phase 4 | Owner |
| `ai.autonomy.customer_facing` | action × channel × market | `approval` for every customer-facing action | **confirmed** default (BD-027) | per [03 §8](03-ai-agent-architecture.md#8-action-policy-engine-and-approval-levels) | Q-AI-02 | Owner |
| `ai.customer_data_to_llm` | global | `blocked` until AI-provider data terms are approved | safe_default | `allowed` | Q-CMP-06 | Owner |
| `ai.reply_languages` | global | `[en]`: messages in other languages go to a person | safe_default | language list | Q-AI-03 | Admin |
| `ai.disclosure` | global | `on`: conversations state that an AI assistant helps the team | safe_default | `off` | Q-CMP-05 | Owner |
| `ai.webchat_live` | global | `false` | safe_default | `true` (approved-knowledge answers only) | Q-AI-02 | Owner |
| `ai.escalate_topics` | global | pricing outside the pricing tool, discounts, refunds, complaints, legal, safeguarding, health, out-of-market (proposed list) | safe_default | edited list | Q-AI-04 | Owner |
| `ai.monthly_budget` | global | unset (per-run limits still enforced) | safe_default | amount | Q-AI-06 | Owner |

## 6. Delivery, payments, retention (later phases)

| Setting | Scope | Value now | Status | Other options | Question | Changed by |
|---------|-------|-----------|--------|---------------|----------|-----------|
| `scheduling.trials` | global | `staff_only`: only staff propose trials | safe_default | `ai_propose` | Q-SAL-02, Q-SCH-02 | SM |
| `scheduling.lesson_lengths` | global | `[60]` | safe_default (60 min confirmed for class-based schedules: BD-011) | other lengths | Q-SCH-03 | Admin |
| `tutors.required_checks` | market | none listed: every assignment needs a coordinator to confirm Mixt's checks are complete | safe_default | check list per market | Q-TUT-03 | Admin |
| `payments.provider` | global | `none`: payments recorded manually and confirmed by Finance | safe_default | provider | Q-PAY-01 | Fin |
| `payments.structure` | global | `single_invoice_per_quotation` (instalments off) | safe_default | instalments | Q-PAY-02 | Fin |
| `payments.reminders` | global | `disabled` | safe_default | schedule | Q-PAY-07 | Fin |
| `ledger.cancellation_rules` | price_book_version | none: no automatic deductions; staff record adjustments | safe_default | rules | Q-PKG-09 | Admin |
| `retention.signals` | global | disabled until thresholds are set | safe_default | thresholds | Q-SAL-08 | SM |
| `referrals.enabled` | global | `false` | safe_default | `true` | Q-SAL-05 | Owner |

## 7. Platform

| Setting | Scope | Value now | Status | Other options | Question | Changed by |
|---------|-------|-----------|--------|---------------|----------|-----------|
| `auth.sso` | global | `off`: local accounts with mandatory MFA | safe_default | `google`, `microsoft` | Q-TECH-01 | Owner |
| `auth.sso_satisfies_mfa` | global | `false`: after single sign-on, staff still enter their authenticator code | safe_default | `true` (only when the provider reports multi-factor sign-in) | Q-TECH-01 | Owner |
| `infra.region` | deployment | unset: **production deployment with real customer data is blocked** | safe_default | region(s) | Q-CMP-02 | Owner |
| `privacy.retention` | global / data type | unset: nothing deleted automatically; erasure only via data-subject requests | safe_default | days + delete/anonymise | Q-CMP-07 | Owner |
| `notifications.internal_channel` | global | dashboard + email | safe_default | Slack, Teams | Q-TEAM-04 | Admin |

# 09: Dashboard and UX Direction

Status: **APPROVED 2026-11-10** (BD-032) · Visual design is provisional until Mixt's brand assets are received (Q-BRD-01).

## 1. Design principles

1. **Work queues first.** Reps open the app to *act*: approve drafts, answer escalations, follow up. The home screen puts "what needs me now" above vanity charts.
2. **Trust through transparency.** Every AI suggestion shows its sources, the pricing version it used, and why it was proposed; approving is one click, editing is inline.
3. **Money is never ambiguous.** Every amount shows its currency code; totals are never mixed across currencies.
4. **Time is local.** Times show in the viewer's time zone, with the customer's local time beside them ("Tue 16:00 Dubai · 13:00 London").
5. **Dense but calm.** Professional data tables, generous white space, restrained use of brand colour for emphasis and state.
6. **Accessible.** WCAG 2.2 AA contrast, full keyboard navigation, visible focus states, no meaning conveyed by colour alone.

## 2. Navigation

```
Sidebar (permission-aware)
├─ Overview
├─ Work
│  ├─ Conversations      (unified inbox: WhatsApp, email, chat, Instagram)
│  ├─ Leads
│  ├─ Customers
│  ├─ Sales Pipeline
│  ├─ Follow-ups
│  └─ Quotations
├─ Delivery
│  ├─ Tutors
│  └─ Scheduling
├─ Revenue
│  ├─ Pricing
│  ├─ Payments
│  └─ Retention
├─ Intelligence
│  ├─ AI Agents
│  └─ Reports
└─ Admin
   ├─ Team
   ├─ Integrations
   └─ Settings
Top bar: global search (people, students, phone, email, quote #) · approvals inbox (badge) · escalations (badge) · notifications · user menu
```

## 3. Modules: key screens

| Module | Key screens and functions |
|--------|---------------------------|
| **Overview** | My queue (drafts to approve, escalations, overdue follow-ups, trials today); pipeline snapshot by stage; speed-to-lead; this month's won/revenue **per currency**; AI health strip (agents on/off, guardrail blocks today). |
| **Leads** | Table with source, market, status, score, owner, age, SLA timer; saved views; duplicate review; out-of-market queue; bulk assign. |
| **Customers** | Household list; **Customer 360** page (see [06 §15](06-crm-structure.md#15-customer-360-screen-summary)). |
| **Conversations** | Three-pane inbox: list (filters: mine, unassigned, awaiting approval, escalated, channel, market) · thread (all channels for the household) · context panel (students, open opportunity, quotation, AI draft with "Approve / Edit / Reject / Take over"). WhatsApp window countdown; template picker when closed. |
| **AI Agents** | Agent list with on/off and kill switch, version, autonomy level per action; run log explorer (timeline of steps, tool calls, guardrails, approvals); evaluation results; cost and usage; approval-policy editor (admin). |
| **Sales Pipeline** | Kanban and table views per pipeline; stage-entry requirements shown when dragging; forecast by currency; lost-reason analysis. |
| **Tutors** | Directory with capabilities, languages, time zone, capacity, compliance status (restricted); availability editor; assignments. |
| **Scheduling** | Calendar (day/week) of trials and lessons across time zones; slot finder; reschedule/no-show handling. |
| **Pricing** | "Pricing data incomplete" banner while `pricing.catalogue_complete = false`; price books list (status badges: Draft / In review / Approved / Active / Superseded / Retired; "Unassigned market" flag for USD books); version editor with diff; **correction versions shown next to the originals**; activation-gate checklist showing each open blocker; market assignments; tier selection mode per market; benefits and policies per version; promotions in a **separate tab** from standard pricing; rules with tester; customer special pricing (restricted); import wizard; history. |
| **Quotations** | List with status and validity; builder (only from resolved options) with a **"Select tier" step** in UK/UAE/Ireland (person chooses, reason required); approval view with authority check; standard price and any promotion shown as separate lines; PDF preview; revision history. |
| **Payments** | Invoices, payments, overdue, manual-confirmation queue (finance), refunds; per-currency totals. |
| **Follow-ups** | My tasks; sequences (builder with approval); enrolments; frequency-cap and quiet-hour settings. |
| **Retention** | Health-score distribution; at-risk list with reasons; low-balance and expiring packages; renewals pipeline; referrals and rewards. |
| **Reports** | Funnel by source/market; conversion rates; speed-to-lead; rep performance; AI performance (draft acceptance, escalations, cost); revenue per currency; export with permission. |
| **Team** | Users, roles, teams, market scopes, discount authority, working hours. |
| **Integrations** | Connection cards (status, scopes, last success, token expiry); webhook log; dead-letter queue with replay; template status (WhatsApp). |
| **Settings** | **Outstanding decisions** (every setting still on a safe default, with its open question and decision-log link); markets, currencies, curricula/boards/qualifications/grades/subjects, pipelines, lost reasons, assignment rules, knowledge base, consent wording, retention policies, security settings. |

## 4. Visual design system (provisional tokens)

Brand direction from the brief: **pink/magenta and blue accents, white and light neutral backgrounds, modern typography.** Exact brand colours, logo and fonts are needed from Mixt (Q-BRD-01). Until then:

| Token | Provisional value | Use |
|-------|------------------|-----|
| `--color-primary` | Magenta `#C2185B` (placeholder) | Primary actions, active navigation, key highlights |
| `--color-primary-soft` | Pink `#FCE4EC` (placeholder) | Selected rows, soft badges |
| `--color-accent` | Blue `#1E63D6` (placeholder) | Links, secondary actions, charts series 2 |
| `--color-accent-soft` | `#E8F0FE` (placeholder) | Info backgrounds |
| `--color-bg` | `#FFFFFF` | Page background |
| `--color-surface` | `#F7F7FA` | Panels, table headers |
| `--color-border` | `#E4E4EA` | Dividers |
| `--color-text` | `#1A1A22` | Body text |
| `--color-text-muted` | `#5F6170` | Secondary text |
| Status colours | Success green, warning amber, danger red, info blue | Always paired with icon/label |

- **Typography:** a modern sans-serif such as *Inter* for UI (tabular numbers for money and tables); an Arabic-capable companion (e.g. *IBM Plex Sans Arabic* or *Noto Sans Arabic*) so Arabic customer messages display well in the inbox.
- **Charts:** a consistent palette derived from the brand tokens, checked for colour-blind safety; currency-aware axes.
- **Dark mode:** not in MVP unless requested.
- **Responsive:** full functionality on desktop; inbox, approvals, customer 360 and tasks usable on mobile for reps on the move.

## 5. Key interaction patterns

- **AI draft card:** draft text · detected language · sources (knowledge docs, pricing option refs) · guardrail results · "Approve & send", "Edit", "Reject (with reason)", "Take over conversation". Rejection reasons feed agent evaluation.
- **Approval card:** what will happen exactly (payload preview), who/what requested it, risk flags, authority check, expiry.
- **Money display component:** `amount + currency code`, derived hourly rates labelled "effective rate", never editable inline on issued quotes.
- **Pricing status badges:** visible everywhere a price appears (e.g. a draft price can be previewed internally but is watermarked "NOT ACTIVE").

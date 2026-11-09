# 07: External Integrations and API Requirements

Status: **PROPOSAL, awaiting approval** · No integration is implemented.

> Provider rules, permissions and prices change. Every point below will be checked against the provider's current official documentation when each integration is built, and Mixt's accounts must be set up by Mixt (we cannot create them on Mixt's behalf).

## 1. Shared integration framework

Every integration follows the same pattern:

| Concern | Design |
|---------|--------|
| Credentials | Stored encrypted (`integration_credentials`, envelope encryption with a KMS-held key); never shown in the UI or API after entry; rotation and expiry alerts. |
| Connection setup | OAuth flows (Google, Microsoft, Meta) run from the **Integrations** screen by an admin; the scopes granted are shown and recorded. |
| Inbound webhooks | Separate `ingress` service → **verify signature/authenticity first** → store raw event (`inbound_webhook_events`, unique on provider event ID) → `200` quickly → process asynchronously. Unverified requests are rejected and counted. |
| Outbound calls | Through the transactional outbox; idempotency keys; timeouts; retries with exponential backoff + jitter for retryable errors (429/5xx/network); circuit breaker per provider; **dead-letter** queue with replay in the UI. |
| Status tracking | Delivery/read/failure events update `messages.status` and `message_status_events`. |
| Rate limits | Respect provider limits via Redis token buckets per connection; back off on 429 using provider hints. |
| Audit | Connect/disconnect, scope changes, credential rotation, every outbound send and every webhook outcome are audited. |
| Testing | Recorded webhook fixtures for contract tests; provider test/sandbox accounts in staging; signature verification tests including tampered payloads. |
| Sync gaps | Periodic reconciliation jobs fetch anything missed during outages (e.g. Gmail history, Graph delta, Meta leads by form). |

---

## 2. WhatsApp Business Cloud API (Meta)

**Purpose:** main customer conversation channel; templates for business-initiated messages; status tracking.

| Item | Requirement |
|------|-------------|
| Mixt must provide | Meta Business portfolio with **business verification**; a WhatsApp Business Account (WABA); phone number(s) to register (one shared or one per market: Q-COM-01); approved display name; a Meta app connected to the WABA; a **system user** access token with the needed WhatsApp permissions. |
| API | Graph API endpoints for sending messages, managing templates and downloading media for a registered `phone_number_id`. |
| Webhooks | Verification handshake (`hub.mode`, `hub.verify_token`, `hub.challenge`) on subscribe; every POST verified with the `X-Hub-Signature-256` HMAC-SHA256 of the raw body using the app secret. Events: inbound messages, message statuses (sent, delivered, read, failed), template status changes, account/quality updates. |
| Messaging rules to enforce | **Customer-service window:** free-form messages only within 24 hours of the customer's last message; outside it, only **pre-approved templates**. Template categories (marketing, utility, authentication) are reviewed by Meta and priced differently by category and recipient country. **Opt-in** is required before business-initiated messages. Messaging limits and phone-number quality rating apply. |
| AI policy | Meta's WhatsApp Business terms restrict general-purpose AI assistants. Mixt's agent must stay a **business-specific assistant** for Mixt's own services; confirm against the current policy before launch. |
| Media | Media IDs/URLs from webhooks are temporary: download promptly, malware-scan, store in private object storage. |
| Failure handling | Map Meta error codes to retryable / non-retryable; e.g. window closed → convert to template proposal; recipient not on WhatsApp → mark contact point; rate limit → back off. |
| Existing number | If Mixt already uses the WhatsApp Business **app** on a number, migrating it or using Meta's coexistence option must be planned (Q-COM-02). |
| Lead time | Business verification, display-name and template approvals can take days to weeks: **start in Phase 0**. |

## 3. Email: Gmail API **or** Microsoft 365 (Graph)

Mixt uses one of these (Q-COM-03). Both adapters share one internal email interface; only one is needed at launch.

### 3.1 Gmail API (Google Workspace)
| Item | Requirement |
|------|-------------|
| Auth | OAuth 2.0. If Mixt's Google Cloud project is set as **Internal** to its Workspace domain, Google's external app verification is not needed. Reading mail uses **restricted** scopes; external apps using them need Google verification and a security assessment. Alternative for shared mailboxes: a service account with domain-wide delegation, approved by Mixt's Workspace admin. |
| Scopes (minimum) | Send + read/modify for the connected sales mailbox(es) only. |
| Inbound | `users.watch` → Cloud Pub/Sub push to our ingress (authenticated push); then `history.list` from the last `historyId`. **Watches expire**, so they are renewed daily by the scheduler. |
| Threading | Keep `threadId`, `Message-ID`, `In-Reply-To`, `References`. |
| Bounces | Parse delivery-status notifications → contact point `bounced` + suppression. |

### 3.2 Microsoft 365 (Microsoft Graph)
| Item | Requirement |
|------|-------------|
| Auth | Microsoft Entra ID app registration. Delegated permissions (per user) or application permissions **restricted to specific mailboxes** by Exchange Online application access policy / RBAC for applications. |
| Permissions (minimum) | Mail send + read/write for the connected mailbox(es). |
| Inbound | Graph **change notifications** subscriptions for mail: validation-token handshake, `clientState` secret checked on every notification, **subscriptions expire and must be renewed** (scheduler); delta queries to catch anything missed. |
| Threading | `conversationId`, `internetMessageId`, reply endpoints. |

### 3.3 Email deliverability (both)
SPF, DKIM and DMARC on Mixt's sending domain (Q-COM-05); one-click unsubscribe for marketing; bounce and complaint handling; sending caps for sequences.

## 4. Facebook Lead Ads (Meta)

| Item | Requirement |
|------|-------------|
| Mixt must provide | Facebook Page(s) and ad account; a Meta app with **App Review** approval for lead retrieval and page permissions; a Page access token from a user/system user with the right role on the Page. |
| Flow | Subscribe the app to the Page's `leadgen` webhook field → webhook gives `leadgen_id`, `form_id`, `ad_id` → fetch the lead's field data via Graph API → `leads.intake()`. |
| Security | `X-Hub-Signature-256` verification, as for WhatsApp. |
| Reliability | Leads can only be retrieved through the API for a limited period after submission; a reconciliation job regularly lists recent leads per form, so a missed webhook doesn't lose a lead. |
| Data | Store the form's consent/disclaimer text and custom questions (e.g. curriculum, grade) mapped to CRM fields via an admin-configured field mapping per form. |

## 5. Instagram lead sources (Meta)

Scope to confirm (Q-COM-04):
- **Instagram lead ads (instant forms):** delivered through the same Lead Ads mechanism as §4 on the linked Facebook Page. No separate integration.
- **Instagram Direct messages:** Meta's Instagram messaging API for a professional (business) account linked to Mixt's Meta setup; needs App Review for messaging permissions; standard messaging window rules apply (similar 24-hour logic). Treated as a conversation channel like WhatsApp.

## 6. Website enquiry forms

| Item | Requirement |
|------|-------------|
| Endpoint | `POST /public/v1/enquiries` on `ingress`, JSON schema validated, size-limited. |
| Abuse protection | Bot challenge (e.g. Cloudflare Turnstile or Google reCAPTCHA: Q-WEB-02), honeypot field, IP + fingerprint rate limits, disposable-email checks. |
| Consent | Separate, unticked checkboxes for marketing per channel; privacy notice link; the wording version is stored with the consent. |
| Attribution | Pass UTM parameters, landing page and referrer from the site. |
| Mixt must provide | Website platform/CMS details and who can add the form or script (Q-WEB-01). |

## 7. Website chat

| Item | Requirement |
|------|-------------|
| Widget | Small embeddable script served from Mixt AI (or a Mixt subdomain); branded; mobile-friendly; accessible. |
| Transport | Streaming responses over SSE/WebSocket to the `chat` service; anonymous session token; rate limits. |
| AI behaviour | The AI Sales Agent answers **live** only for low-risk content (approved knowledge, discovery questions). Anything needing approval (pricing quote, discounts) is collected and handed to a person, or the visitor is offered a WhatsApp/email follow-up, in line with the approval policy. Live chat therefore needs a defined autonomy level (Q-AI-02). |
| Identity | The visitor gives contact details → matched/created as a lead; the transcript joins the account timeline. |
| Disclosure | Clear statement that an AI assistant is answering and how to reach a person (Q-CMP-05). |

## 8. AI model providers

| Provider | Use | Requirement |
|----------|-----|-------------|
| Anthropic Claude API | Conversation, reasoning, extraction (per model profile) | Organisation API key held encrypted; usage limits; data-retention terms reviewed; zero-data-retention option requested where available (Q-CMP-06). |
| OpenAI API | Alternative/fallback; embeddings if chosen | Same requirements as above. |
| Embeddings | Knowledge-base retrieval | Provider chosen per profile; the embedding model is recorded per chunk so re-embedding is possible. |

## 9. Payments (provider to be decided: Q-PAY-01)

Payment **tracking** is in scope. Card data never touches Mixt AI.

| Option | Notes |
|--------|-------|
| Card/payment-link provider (e.g. Stripe, Checkout.com, or a regional gateway) | Hosted checkout or payment links; webhook events for success/failure/refund/dispute (signature-verified); multi-currency support must cover each market's currency **without converting prices**. Availability depends on where Mixt's legal entity is registered. |
| Local payment methods | Some markets favour local methods (e.g. mada in Saudi Arabia, KNET in Kuwait, BENEFIT in Bahrain, FPX in Malaysia, PayNow in Singapore, FPS in Hong Kong). Gateway choice should reflect the markets Mixt prioritises. |
| Bank transfer | Supported as `finance_confirmed` payments with uploaded evidence and approval. |
| Accounting | Optional later export/sync (e.g. Xero, QuickBooks, Zoho Books) if Mixt uses one (Q-PAY-06). |

## 10. Calendar and video (to be decided: Q-SCH-01)

| Need | Options |
|------|---------|
| Tutor availability and bookings | Google Calendar API or Microsoft Graph calendar (busy/free + event creation), or Mixt AI as the master calendar if tutors don't use a shared calendar |
| Trial/lesson video links | Zoom API, Google Meet (via Calendar conference data) or Microsoft Teams online meetings, whichever platform Mixt teaches on |
| Reminders | Through WhatsApp templates (utility) and email |

## 11. Optional / later

| Integration | Value |
|-------------|-------|
| Meta Conversions API | Send qualified/won events back to Meta to improve ad targeting (consent and policy review required) |
| Slack / Microsoft Teams | Internal alerts for urgent escalations and approvals |
| Existing LMS / scheduling system | Import lesson delivery → hours ledger (Q-TUT-02) |
| Telephony / call recording | Log calls into the timeline (only if Mixt uses calls) |
| SMS | Not requested; possible fallback for reminders |

## 12. What Mixt needs to start now (critical-path checklist)

| # | Item | Owner | Why now |
|---|------|-------|---------|
| EXT-01 | Meta Business portfolio + **business verification** | Mixt | Prerequisite for WhatsApp API and Lead Ads app review |
| EXT-02 | WhatsApp numbers decision + display name | Mixt | Approval lead time |
| EXT-03 | First WhatsApp templates (greeting/re-engagement, trial reminder, quotation follow-up, payment reminder) drafted and submitted | Mixt + us | Meta review lead time |
| EXT-04 | Confirm Google Workspace vs Microsoft 365; admin contact | Mixt | Determines the email adapter and auth model |
| EXT-05 | Sending domain SPF/DKIM/DMARC status | Mixt IT | Deliverability |
| EXT-06 | Meta app for Lead Ads + App Review submission | Us, under Mixt's business | Review lead time |
| EXT-07 | Payment provider choice and merchant account | Mixt finance | Underwriting lead time |
| EXT-08 | Cloud account and hosting region decision | Mixt + us (after legal advice) | Needed before any real data |
| EXT-09 | LLM provider organisation accounts + data-processing terms | Mixt | Contracts before customer data is processed |

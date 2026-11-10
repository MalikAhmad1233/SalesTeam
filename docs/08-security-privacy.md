# 08: Security, Privacy and Compliance

Status: **APPROVED 2026-11-10** (BD-032) · Not legal advice: the regulatory points below must be confirmed by Mixt's legal counsel for each market.

## 1. Security baseline

OWASP **ASVS Level 2** as the verification standard, with the OWASP Top 10 and the OWASP Top 10 for LLM applications covered in design reviews and tests.

## 2. Authentication

| Control | Design |
|---------|--------|
| Staff login | Either SSO through Mixt's identity provider (Google Workspace or Microsoft Entra ID via OIDC: Q-TECH-01) **or** email + password (Argon2id hashing) |
| MFA | **Required for all staff.** TOTP and WebAuthn/passkeys; SSO accounts follow the IdP's MFA policy |
| Sessions | Server-side sessions; httpOnly, Secure, SameSite=Lax cookies; idle timeout (proposed 30 min) and absolute timeout (proposed 12 h); rotation on login and privilege change; "sign out everywhere" |
| CSRF | Token on all state-changing requests |
| Brute force | Per-account and per-IP throttling; lockout with notification; breached-password check on set/change |
| Machine identities | Agents and integrations are **principals** with scoped permissions; no shared "god" service account |

## 3. Authorisation

### 3.1 Roles (PROPOSAL; final list in Q-TEAM-02)

| Role | Main permissions |
|------|-----------------|
| **Owner / Super Admin** | Everything, including security settings, kill switches and role management |
| **Admin (Operations)** | Users, integrations, templates, knowledge base, pipeline config, approval policies |
| **Pricing Manager** | Price books, versions, promotions, rules; approve/activate pricing (dual control) |
| **Sales Manager** | All accounts in their team(s)/markets; approvals within authority; reassignments; reports |
| **Sales Representative** | Own and pool accounts; conversations; draft/issue quotations within authority; approve AI drafts for own accounts |
| **Finance** | Invoices, payments, manual payment confirmation, refunds (with approval) |
| **Tutor Coordinator** | Tutors, availability, compliance checks, matching and assignment approvals, trials |
| **Analyst (read-only)** | Reports and dashboards; no personal data export unless granted |
| **Agent roles** | One per AI agent with only that agent's tool permissions (see [03](03-ai-agent-architecture.md)) |

### 3.2 Levels of control
- **Permission level:** granular keys (`quotation.issue`, `pricing.version.activate`, `payments.confirm_manual`, `pii.export`, …).
- **Record level:** reps see their own accounts and the pool; managers see their teams; roles can be scoped to markets. Enforced by one central policy module applied to **every** query and action (and tested), not scattered checks.
- **Field level:** restricted fields (special pricing, tutor pay rates, learning needs, compliance documents) need explicit permissions and are masked otherwise, including in exports and AI context.
- **Approval authority:** discount limits by role and market (pricing doc §12).
- **Separation of duties:** the person who submits a pricing version cannot be its only approver; whoever requests a refund cannot approve it.

## 4. Data protection in transit and at rest

| Layer | Control |
|-------|---------|
| Transit | TLS 1.2+ everywhere (TLS 1.3 preferred), HSTS; internal service traffic inside a private network |
| At rest | Managed database and storage encryption (AES-256) |
| Application-level encryption | Envelope encryption (AES-256-GCM data keys, wrapped by a KMS key) for: integration credentials, MFA secrets, learning-needs notes, tutor check references, LLM debug payloads |
| Secrets | Cloud secrets manager; injected as environment variables at runtime; **never committed**; secret scanning in CI; rotation runbook |
| Object storage | Private buckets; short-lived signed URLs; malware scanning of uploads |
| Backups | Encrypted; separate account/project; restricted access |

## 5. Application security controls

| Control | Design |
|---------|--------|
| Input validation | Pydantic v2 strict models for every API input; size limits; allow-lists for enums; file type and size checks on uploads |
| Output safety | React auto-escaping; strict Content Security Policy; sanitised HTML for email display (allow-list sanitiser) |
| SQL | SQLAlchemy parameterised queries only; no string-built SQL |
| Rate limiting | Redis token buckets: per IP on public endpoints (forms, chat, login), per user on the API, per connection for providers; WAF in front |
| Webhooks | Signature/authenticity verification (Meta `X-Hub-Signature-256`, Graph `clientState` + validation token, Pub/Sub authenticated push, payment-provider signatures); replay protection via unique event IDs and timestamp windows; reject before parsing large bodies |
| SSRF | Outbound HTTP only through an allow-listed client for integrations; the research agent's web access is limited to an allow-list and fetched through a sandboxed fetcher |
| Dependencies | Lock files; automated vulnerability scanning; pinned base images; SBOM generation |
| Containers | Non-root, read-only filesystem where possible, minimal images |
| Security testing | SAST and dependency scanning in CI; DAST against staging; external **penetration test before go-live** |

## 6. AI-specific security

| Risk | Control |
|------|---------|
| Prompt injection via customer messages, emails, forms, documents | Untrusted content is clearly delimited; the model cannot widen its permissions; tool scopes come from the run context; side effects go through the Action Policy Engine and guardrails |
| Data leakage across customers | Single-account run scope; tool-level enforcement; confidentiality guard; automated leakage tests |
| Made-up prices or policies | Price guard and claims guard; prices only from the pricing tool |
| Sensitive data sent to model providers | Minimisation; no payment data; restricted fields excluded unless needed and permitted; provider data-processing agreements |
| Excessive agency | Default human approval; kill switches; budgets; circuit breakers |
| Model or provider outage | Fallback profiles; safe failure with escalation |

## 7. Audit trail

- Append-only `audit_log` with **hash chaining** (each row includes the previous row's hash), monthly partitions, and `UPDATE`/`DELETE` revoked from the application role (implemented: IN-20).
- Logged: logins (success/failure), permission changes, every create/update/delete on business records (changed fields, sensitive values masked), approvals and rejections, AI proposals and their policy decisions, outbound messages, exports, pricing changes, integration changes, kill-switch use.
- A daily job verifies the hash chain and alerts on breaks. Logs are retained per policy (Q-CMP-07).

## 8. Backups and disaster recovery

| Item | Proposal (confirm in Q-TECH-03) |
|------|-------------------------------|
| Database | Managed point-in-time recovery (continuous WAL archiving), proposed **RPO ≤ 15 min**; daily snapshots kept 35 days; monthly kept 12 months |
| Object storage | Versioning + lifecycle rules; cross-region replication if permitted by data-residency decisions |
| Redis | Not a system of record; no business data lost if it fails |
| Recovery | Proposed **RTO ≤ 4 h**; documented runbook; **quarterly restore tests** into an isolated environment |
| Configuration | Infrastructure as code (Terraform) so environments can be rebuilt |

## 9. Privacy by design

### 9.1 Principles applied
- **Data minimisation:** collect only what selling and tutoring require; year of birth not full DOB; learning needs only if volunteered; no social-media profiling.
- **Purpose limitation:** consents per purpose; marketing separate from service messages.
- **Transparency:** privacy notice links in forms and chat; AI assistance disclosed where required.
- **Children:** the guardian is the main contact; direct communication with students only under a policy Mixt approves (Q-AI-05); safeguarding escalation path (Q-CMP-08).
- **Retention:** retention schedules per data type (e.g. lost leads, conversations, recordings), applied by scheduled jobs; legal holds override.
- **Individual rights:** access/export, rectification, erasure (anonymisation that keeps financial records where law requires), restriction and objection, tracked as `data_subject_requests` with due dates.
- **Customer data isolation:** record-level access for staff; single-account scope for AI; confidential pricing visible only to authorised roles and that customer.

### 9.2 Regulatory landscape to review with counsel

| Market | Main data-protection framework (to confirm applicability) |
|--------|-----------------------------------------------------------|
| United Kingdom | UK GDPR and Data Protection Act 2018; PECR for electronic marketing; ICO Children's Code (if services are likely to be used by children) |
| Ireland | EU GDPR; Irish ePrivacy rules for electronic marketing |
| United Arab Emirates | Federal Personal Data Protection Law (and free-zone regimes if Mixt is in one, e.g. DIFC/ADGM) |
| Saudi Arabia | Personal Data Protection Law (incl. cross-border transfer rules) |
| Qatar | Personal Data Privacy Protection Law |
| Kuwait | Data privacy regulation issued by the telecoms regulator (CITRA) |
| Oman | Personal Data Protection Law |
| Bahrain | Personal Data Protection Law |
| Malaysia | Personal Data Protection Act (as amended) |
| Singapore | Personal Data Protection Act, incl. Do Not Call provisions for marketing messages |
| Hong Kong | Personal Data (Privacy) Ordinance, incl. direct-marketing provisions |
| Indonesia | Personal Data Protection Law |
| South Korea | Personal Information Protection Act |

Design implications already included: consent records with evidence, purpose-specific consents, DSAR workflows, retention jobs, a data-transfer register (where data is stored and which processors receive it: cloud, LLM providers, Meta, email provider, payment provider), and a configurable hosting region.

**Decisions needed from counsel:** hosting region and cross-border transfer mechanisms (Q-CMP-02); lawful basis for each processing purpose; age thresholds for consent and for contacting students directly per market; whether AI disclosure is required; retention periods; whether session recordings (a supplied Ireland/HK Premium benefit) need extra consent (Q-CMP-09).

## 10. Incident response

- Severity levels, on-call contacts and runbooks (data breach, credential leak, AI misbehaviour, provider outage, WhatsApp number restriction).
- Breach notification timelines vary by law (e.g. 72 hours to the regulator under UK/EU GDPR); the runbook includes a per-market notification checklist from counsel.
- AI incident playbook: kill switch → identify affected conversations from run logs → correct with customers → root-cause fix → new eval case added.

## 11. What is implemented today (Phases 1a–1d)

The sections above are the design. This table lists only controls with working code **and** automated tests (rule 7). Everything else in this document is still planned.

| Area | Implemented control | Where it is tested |
|------|---------------------|--------------------|
| Sign-in | Argon2id passwords with policy; mandatory TOTP two-step verification with replay protection; lockout after repeated failures; temporary passwords that must be changed | `test_auth.py`, `test_more_paths.py` |
| Single sign-on (off by default) | OIDC code flow with PKCE, state, nonce; RS256 signature, issuer, audience, expiry, `azp` checks; existing active staff only; Microsoft single tenant; TOTP still required unless `auth.sso_satisfies_mfa` (IN-23) | `test_sso.py` (fake provider, real signed tokens) |
| Sessions and CSRF | HttpOnly/Secure/SameSite cookies, idle and absolute expiry, rotation after MFA, CSRF token on every state-changing request | `test_auth.py` |
| Rate limiting | Per address, per user, per account and per address for sign-in, per session for codes, per user for password changes and imports; Redis-backed in staging (IN-21) | `test_hardening.py`, `infra/staging/smoke.sh` |
| Client addresses | `X-Forwarded-For` only from the trusted proxy; a forged header is ignored | `test_hardening.py`, `smoke.sh` |
| Authorisation | Roles with market scope, record-level visibility, "grant only what you hold" | `test_admin.py`, `test_crm.py` |
| Database privileges | API and worker as a data-only role; append-only tables insert-only; refuses to start over-privileged in staging/production (IN-20) | `test_hardening.py`, `test_database.py`, E2E and `smoke.sh` |
| Audit | Append-only, hash-chained audit log (privileges **and** triggers); chain verification detects edited, removed and reordered rows | `test_database.py`, restore check |
| Encryption | AES-256-GCM field encryption with key rotation (MFA secrets, learning-needs notes, single sign-on state cookie) | `test_core.py`, `test_sso.py` |
| Browser | Nonce-based Content-Security-Policy, `frame-ancestors 'none'`, HSTS, `nosniff`, `no-referrer`, Permissions-Policy (IN-24) | E2E (`dashboard.spec.ts`), `smoke.sh` |
| Transport | TLS via Caddy, HTTP→HTTPS redirect, request size limits; API schema and docs hidden in deployed environments | `smoke.sh` |
| Containers | Non-root, read-only filesystems, no capabilities, `no-new-privileges`, database network without internet (IN-25) | `staging-ci` |
| Backups | Encrypted (age) six-hourly dumps by a read-only role; restore check verifies schema, triggers, the audit chain and the last audited entry (IN-22) | `test_hardening.py`, `staging-ci` |
| Dependencies | Locked dependencies; `pip-audit` in CI | `backend-ci` |
| Webhooks (3a) | Meta `X-Hub-Signature-256` HMAC checked with a constant-time comparison before anything is parsed or stored; failures counted; each delivery stored once (hash of the body); 1 MB body limit; per-connection rate limit; raw bodies cannot be edited or deleted (IN-43, IN-44) | `test_messaging.py` |
| Integration secrets (3a) | Encrypted with the field key ring, bound to connection and kind; never returned by the API; rotation audited; destroyed on disconnect | `test_messaging.py` |
| Messaging (3a) | Suppression list checked when a message is queued and again when it is sent; consent checked on the contact for every template; students not messaged directly by default; message content immutable; sends audited without their text (IN-45, IN-46) | `test_messaging.py` |
| Public form (3a) | Off by default; honeypot; optional Turnstile; per-address rate limit; strict schema (unknown fields refused); browsers only from listed origins (IN-48) | `test_web_enquiries.py` |

**Not yet implemented (planned):**
* WebAuthn/passkeys and a breached-password check.
* "Sign out everywhere" in the dashboard.
* A KMS for key wrapping (keys currently come from the environment).
* Managed point-in-time recovery (needed for RPO ≤ 15 min).
* A WAF, DAST and the external penetration test.
* Webhook verification for email providers (with Phase 3b).
* Malware scanning of uploads.

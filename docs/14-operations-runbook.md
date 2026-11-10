# 14: Operations Runbook

Status: **Phase 1d, 2026-11-10** · Applies to the staging stack in [`infra/staging`](../infra/staging). Production follows the same steps once the hosting region (Q-CMP-02), privacy sign-off (Q-CMP-01) and cloud account (Q-TECH-04) are settled. Until then **only synthetic data** may be loaded.

Everything described here is implemented, and CI runs it on every push (`staging-ci`): build, start, browser journey over HTTPS, security smoke test, backup and restore check.

## 1. What runs where

| Container | Purpose | Network | Database role |
|-----------|---------|---------|---------------|
| `caddy` | HTTPS front door (Let's Encrypt or internal CA), HTTP→HTTPS, HSTS, request size limits; `/api/*` to the API, everything else to the dashboard | public + frontend | — |
| `web` | Next.js dashboard (per-request CSP nonce) | frontend | — |
| `api` | FastAPI (2 processes by default) | frontend + backend | `mixt_app` (data only) |
| `worker` | Timeline events and scheduled reminders; heartbeat health check; stops cleanly on SIGTERM | backend | `mixt_app` |
| `migrate` | One-shot before `api`/`worker` start: schema upgrade under a lock, then re-grants. Has **no** encryption keys | backend | `mixt_owner` |
| `db` | PostgreSQL 17, data checksums, SCRAM passwords | backend | `postgres` (initialisation only) |
| `redis` | Rate-limit counters only (nothing persisted) | backend | — |
| `backup` | Encrypted `pg_dump` every 6 h, retention, optional off-site copy | backend | `mixt_readonly` |
| `restore-db` | Empty PostgreSQL for restore checks (profile `restore-check`, in memory) | backend | — |

The `backend` network has no internet access. Every service except the database runs with a read-only filesystem, no Linux capabilities (Caddy keeps only the one it needs to bind ports 80/443) and `no-new-privileges`.

The API **refuses to start** in staging/production if its database role can do more than read and write rows (superuser, owns tables, can create objects, can TRUNCATE, can change append-only tables) or if the schema is behind the code. `GET /api/v1/health/ready` reports `database`, `schema` and `rate_limit_store`.

## 2. First deployment (a Linux server with Docker)

1. A server with Docker Engine and the Compose plugin; a DNS name pointing at it; ports 80 and 443 open (80 only redirects and answers certificate checks).
2. Check out the repository on the server.
3. Generate secrets once:
   ```bash
   cd infra/staging
   ./generate-env.sh staging.mixt.example ops@mixt.example
   ```
   This writes `.env` (database passwords, Redis password, field-encryption key, backup public key) and `backup-identity.txt` (the private key that decrypts backups).
4. **Move `backup-identity.txt` off the server** into the password manager or secrets store, then delete it from the server. Whoever holds it can read every backup.
5. Start the stack:
   ```bash
   docker compose up -d --build --wait
   ```
6. Create the first Owner, then sign in and set up two-step verification:
   ```bash
   docker compose exec api python -m mixt.cli create-owner --email you@mixt.example --name "Your Name"
   ```
7. Run the smoke test: `./smoke.sh you@mixt.example` (it ends with `smoke test passed`).

## 3. Releasing a new version

```bash
git pull
docker compose up -d --build --wait
```

`migrate` runs first. `api` and `worker` only start if it succeeds. Migrations are forward-only. If a release must be undone after a migration, deploy the previous code together with a fix-forward migration, or restore a backup (§6). Images can also be pulled from GitHub Container Registry (workflow `images`, on the main branch). Set `MIXT_IMAGE_PREFIX=ghcr.io/<owner>/mixt` and `MIXT_IMAGE_TAG=<commit>` in `.env` and use `docker compose pull` in place of `--build`.

## 4. Secrets and rotation

| Secret | Used by | Rotation |
|--------|---------|----------|
| `MIXT_ENCRYPTION_KEYS` / `MIXT_ACTIVE_ENCRYPTION_KEY_ID` | API, worker | Add a new key to the JSON ring, switch the active id, redeploy. Old values stay readable; never remove a key while data encrypted with it exists |
| `MIXT_DB_APP_PASSWORD`, `MIXT_DB_READONLY_PASSWORD`, `MIXT_DB_OWNER_PASSWORD` | API/worker, backup, migrate | `docker compose exec db psql -U postgres -c "ALTER ROLE mixt_app PASSWORD '...'"`, update `.env`, `docker compose up -d` |
| `MIXT_REDIS_PASSWORD` | API, redis | Update `.env`, `docker compose up -d` (counters reset; harmless) |
| `BACKUP_AGE_RECIPIENT` + private key | backup / restore | Generate a new pair with `age-keygen`, update the recipient, keep the old private key as long as backups made with it are retained |
| Single sign-on client secrets | API | Rotate at the provider, update `.env`, `docker compose up -d` |
| WhatsApp access token, app secret, webhook verify token; Turnstile secret | API, worker (stored encrypted in the database, not in `.env`) | **Integrations → Replace a secret**. Change the verify token in the Meta app at the same time. Disconnecting destroys the stored secrets |

`.env` and `backup-identity.txt` are git-ignored. Never paste them into tickets or chat.

## 5. Backups

* Every 6 hours (`BACKUP_INTERVAL_SECONDS`), kept 14 days (`BACKUP_RETENTION_DAYS`), and the newest 3 are always kept.
* Taken with the **read-only** role, so a backup job can never change data.
* Encrypted with [age](https://age-encryption.org) to `BACKUP_AGE_RECIPIENT`; the server only holds the public key.
* Each backup has a manifest: schema revision, row counts, and the last audit-log entry and its hash. A restore can then prove it contains everything up to that moment.
* `BACKUP_UPLOAD_COMMAND` copies each backup off the server (e.g. `rclone copy` or `aws s3 cp` wrapped in a small script). **Set this before relying on backups.** A backup kept only on the same server does not survive losing the server. The destination depends on the hosting decision (Q-CMP-02, Q-TECH-04).
* Take one immediately: `docker compose exec backup backup.sh once`.

**Production gap (honest):** six-hourly logical dumps give a recovery point of up to 6 hours. The proposed target is RPO ≤ 15 min (Q-TECH-03). Production should use the cloud provider's managed point-in-time recovery, or WAL archiving, and keep these encrypted dumps as an independent second copy.

## 6. Restore check (monthly, and after any backup change)

```bash
cd infra/staging
BACKUP_AGE_IDENTITY_FILE=/path/to/backup-identity.txt ./restore-check.sh          # latest backup
BACKUP_AGE_IDENTITY_FILE=/path/to/backup-identity.txt ./restore-check.sh mixt-20261110T131152Z
```

The script starts a separate, empty PostgreSQL, checks the backup's checksums, decrypts it in memory and restores it. It then verifies:

| Check | Meaning |
|-------|---------|
| `schema_revision`, `schema_matches_manifest` | Restored schema is the one this build expects, and the one recorded at backup time |
| `tables_present` | Every table the code knows about exists |
| `integrity_triggers`, `append_only_tables` | US exclusion, audit-chain and append-only triggers came back |
| `audit_chain` | Every audit-log hash recomputes; no row edited, removed or reordered |
| `audit_tip_present` | The last audit entry recorded in the manifest is present with the same hash |
| `us_not_a_market` | The US is still excluded and is not a market (BD-005) |

It exits non-zero on any failure. Record the date, backup name and result in the operations log.

## 7. Recovering from a backup (real incident)

1. Stop writes: `docker compose stop api worker`.
2. Keep the damaged database for investigation: `docker compose stop db` and back up the `db-data` volume (or snapshot the disk).
3. Create an empty database for the restore. Either use a new `db-data` volume, which `db-init` initialises with the roles, or drop and recreate the `mixt` database as `postgres`.
4. Restore as the owner role, so that the restored objects belong to `mixt_owner`:
   ```bash
   set -a; source .env; set +a
   docker compose up -d --wait db
   docker compose run --rm -T --no-deps -e MIXT_DB_OWNER_PASSWORD backup sh -c \
     'cat > /tmp/identity && BACKUP_AGE_IDENTITY_FILE=/tmp/identity restore.sh latest "postgresql://mixt_owner:$MIXT_DB_OWNER_PASSWORD@db:5432/mixt"' \
     < /path/to/backup-identity.txt
   ```
5. Re-apply grants and start: `docker compose up -d --wait`, which runs `migrate` first.
6. Verify, then run `./smoke.sh` and sign in:
   ```bash
   docker compose run --rm --no-deps api python -m mixt.cli verify-restore \
     --database-url "postgresql+psycopg://mixt_owner:$MIXT_DB_OWNER_PASSWORD@db:5432/mixt"
   ```
7. Write up the incident (docs/08 §10), including the recovery point actually achieved.

## 8. Rate limits

Defaults are in `MIXT_RATE_*` (see `services/backend/.env.example`). A refused request gets HTTP 429 with `Retry-After`; the dashboard shows the message. Limits are counted per client address as reported by Caddy (`MIXT_TRUSTED_PROXIES` is Caddy's fixed address; any other `X-Forwarded-For` is ignored), per signed-in user, and per account or session for sign-in, two-step codes and password changes. If a whole office shares one address and hits `MIXT_RATE_API_PER_IP`, raise that value. Do not switch limits off; staging and production refuse to start without Redis or with limits off.

## 9. Single sign-on (optional; off until Mixt decides, Q-TECH-01)

1. Register an OAuth/OpenID Connect web application with the provider:
   * **Google Workspace**: Google Cloud console → APIs & Services → Credentials → OAuth client ID (Web application). Use an *Internal* consent screen.
   * **Microsoft Entra ID**: App registrations → New registration, single tenant. Create a client secret, and note the Directory (tenant) ID.
   * Redirect URI for both: `https://<MIXT_DOMAIN>/api/v1/auth/sso/callback`. Scopes: `openid email profile`.
2. Put the client id/secret (and, for Microsoft, the tenant id) into `.env` and run `docker compose up -d`. Optionally restrict sign-in to `MIXT_SSO_ALLOWED_DOMAINS='["mixt.example"]'`.
3. An Owner sets **Settings → `auth.sso`** to `google` or `microsoft`. The sign-in page then shows "Sign in with …".
4. Staff accounts must already exist; single sign-on never creates accounts or grants roles. The first sign-in links the account by email; after that the provider's stable id is used.
5. Two-step codes are still asked for after single sign-on. Only if Mixt switches on `auth.sso_satisfies_mfa` **and** the provider reports a multi-factor sign-in is the code skipped.

## 9a. WhatsApp (Cloud API)

Mixt does steps 1 and 2 in Meta's tools (EXT-01 to EXT-03 in [07 §12](07-integrations.md#12-what-mixt-needs-to-start-now-critical-path-checklist)); we can help, but cannot create Mixt's accounts.

1. In Meta Business Suite: business verification; a WhatsApp Business Account with the registered number and approved display name; a Meta app linked to it; a **system user** token with the WhatsApp messaging and management permissions.
2. Draft and submit the first templates in WhatsApp Manager (greeting, trial reminder, quotation follow-up, payment reminder).
3. In Mixt AI, an admin opens **Integrations → Connect WhatsApp** and enters the Graph API version the app uses, the WhatsApp Business Account id, the phone number id, the number, the token, the app secret and a long random verify token. Set `MIXT_PUBLIC_BASE_URL` so the screen shows the full webhook address.
4. In the Meta app's WhatsApp configuration, set the callback URL to that address (`https://<domain>/webhooks/whatsapp/<connection id>`) and the same verify token, then subscribe to the **messages** and **message_template_status_update** fields. "Webhook verified by Meta" turns to "yes".
5. **Check connection** (confirms the token and shows the verified name and quality rating), then **Sync templates** and approve the templates staff may use (people with `messaging.templates.approve`).
6. Switch the number on: **Settings → `channels.whatsapp.numbers`** (globally or for the markets that use it, Q-COM-01). Until then nothing is sent; inbound messages are stored.

Operating it:

* Failed webhooks show on the connection card with **Process again** (after the cause is fixed). Failed scheduled work also appears in the dead-letter list (`/api/v1/ops/dead-letters`).
* A connection in **error** (expired token, account restricted) stops sending; replace the token, then **Check connection**.
* Rejected webhooks (bad signature) are counted on the card. A rising count means a wrong app secret or someone probing the address.
* Customers who reply with an opt-out word are blocked automatically; managers see and lift blocks under **Inbox → Blocked numbers**.

## 9b. Website enquiry form

1. Once the privacy notice and consent wording are approved (Q-CMP-01), an Owner lists the wording version in `web.consent_wording_versions` and switches on `web.enquiries.enabled`.
2. Add the website's origin to `web.allowed_origins` if the browser posts the form directly; server-to-server posts need nothing.
3. The site posts JSON to `https://<domain>/public/v1/enquiries` with the fields in the API schema (`EnquiryIn`), an empty hidden `website` field (honeypot) and, if `web.bot_protection = turnstile`, the Turnstile token as `bot_token`. For Turnstile, create a connection of provider `website_forms` holding the Turnstile secret as `client_secret`.
4. Each address may post 5 enquiries per 10 minutes (`MIXT_RATE_ENQUIRY_PER_IP`).

## 10. Monitoring (minimum until an operations owner is named, Q-TECH-05)

* Uptime check on `https://<domain>/api/v1/health/ready` (expects HTTP 200).
* `docker compose ps`: all services `healthy`. The worker turns unhealthy if it has not polled for 60 s.
* Logs are JSON on stdout (`docker compose logs -f api`). Each request has an `X-Correlation-Id`; personal data is redacted.
* Alert on log events `rate_limit_backend_unavailable`, `startup_check`, `backup: FAILED`, `sso_refused` spikes and `webhook_rejected` spikes, and on any WhatsApp connection in **error**.
* Run `./smoke.sh` after every deployment.

## 11. Before any real customer data

All of these must be true:

1. Hosting region decided (Q-CMP-02, setting `infra.region`) and the stack running in that region's account (Q-TECH-04).
2. Privacy notice, terms and consent wording approved (Q-CMP-01).
3. Off-site backup copy configured (§5) and a restore check passed in the target environment.
4. Managed point-in-time recovery, or WAL archiving, enabled for the production database (§5).
5. External penetration test done (docs/08 §5).

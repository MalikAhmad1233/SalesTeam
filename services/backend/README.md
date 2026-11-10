# Mixt AI backend

Python 3.12+ · FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16/17. Architecture: [docs/01](../../docs/01-architecture.md).

## What exists today (Phase 1a)

Everything listed here has working code **and** automated tests (`tests/`), run against a real PostgreSQL database.

| Area | Implemented | Main tests |
|------|-------------|-----------|
| Core | Config validation, UUIDv7 ids, money (integer minor units, no currency mixing, no conversion), AES-256-GCM field encryption with key rotation, phone/email normalisation, time zones, JSON logging with personal-data redaction, RFC 9457 errors, correlation ids, security headers | `test_core.py`, `test_auth.py` |
| Identity | Argon2id passwords + policy, mandatory TOTP two-step verification with replay protection, session cookies (HttpOnly/Secure/SameSite) with idle + absolute expiry and rotation after MFA, CSRF tokens, lockout after repeated failures, temporary passwords that must be changed, roles with optional market scope, team leads, "can only grant what you hold" rule, owner bootstrap command | `test_auth.py`, `test_admin.py`, `test_more_paths.py` |
| Audit | Append-only audit log (database triggers block UPDATE/DELETE/TRUNCATE), SHA-256 hash chain computed in the database, verification endpoint that detects edited and removed rows | `test_database.py`, `test_admin.py` |
| Reference data | 13 confirmed markets (BD-004); the US stored only as an excluded country, and blocked as a market in the API **and** by database trigger (BD-005); ISO countries and currencies; the four confirmed curricula, no IB (BD-007/008); British boards and qualifications (BD-009); adding a market or curriculum needs a decision-log reference | `test_database.py`, `test_admin.py` |
| Settings register | 55 settings from docs/13 with JSON-schema validation, safe defaults, confirmed values with decision references, scoped values with fallback, "Outstanding decisions" endpoint, dual-approval settings locked until Phase 2, test that keeps code and docs/13 in sync | `test_admin.py` |
| CRM | Households, contacts (one primary), contact points (E.164/email normalisation, duplicate flag), append-only consent history with evidence, students (year of birth only, confirmed curricula, boards/qualifications checked against the curriculum, encrypted learning-needs notes visible only with permission), subjects, exams; record-level visibility (own, team, unassigned pool, market-scoped managers); optimistic locking with ETag/If-Match; pricing market set **only** by a person's confirmation, never inferred from currency, phone or curriculum (ADR-13); out-of-market flag for residents outside the 13 markets | `test_crm.py`, `test_more_paths.py` |
| Architecture | Module boundary checks; entry points register every table; models ↔ migrations identical | `test_architecture.py`, `test_entrypoints.py`, `test_database.py` |

**Not built yet:** leads, pipeline, tasks, timeline (1b); dashboard (1c); rate limiting, SSO, production deployment (1d); pricing, messaging, AI and everything in later phases.

## Run locally

```bash
cd services/backend
uv sync
cp .env.example .env   # then paste a generated key into MIXT_ENCRYPTION_KEYS
```

Start PostgreSQL (e.g. `docker compose -f infra/compose.yaml up -d db` from the repository root), then:

```bash
set -a; source .env; set +a
uv run alembic upgrade head
uv run python -m mixt.cli create-owner --email you@example.com --name "Your Name"
uv run uvicorn mixt.main:app --reload
```

API docs (local/test only): http://localhost:8000/api/docs

## Checks (same as CI)

```bash
uv run ruff check mixt tests migrations
uv run ruff format --check mixt tests migrations
uv run mypy mixt
MIXT_TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/mixt_test uv run pytest --cov=mixt --cov-fail-under=85
```

The test database is wiped and rebuilt from the migrations at the start of every run; point `MIXT_TEST_DATABASE_URL` at a database used only for tests. The migration test also creates and drops a database called `mixt_migration_check`.

## Layout

```
mixt/
  core/        config, db, ids, errors, crypto, money, timezones, normalize, logging, context
  modules/     identity, reference, settings, audit, crm  (models.py private; service.py public)
  api/         app factory, auth dependencies, routers (request/response schemas live with routers)
  cli.py       operational commands
migrations/    Alembic; 0001 includes integrity triggers and seed data (frozen in the migration)
tests/         pytest against real PostgreSQL
```

## Production notes

- Run migrations with a dedicated migration role; run the app with a role that has no DDL rights.
- `MIXT_ENCRYPTION_KEYS` must come from a secrets manager. Rotate by adding a key and switching `MIXT_ACTIVE_ENCRYPTION_KEY_ID`; old ciphertexts stay readable.
- Production with real customer data is blocked until the hosting region is decided (Q-CMP-02, setting `infra.region`).
- The audit hash chain serialises audit writes with a database advisory lock held until commit. That is fine at Mixt's expected volume; if write volume grows a lot, move chaining to a background job.

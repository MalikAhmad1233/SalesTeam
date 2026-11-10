# Mixt AI dashboard

Next.js 16 · React 19 · TypeScript (strict) · Tailwind CSS 4 · TanStack Query. Design direction: [docs/09](../../docs/09-dashboard-ux.md).

## What exists today (Phase 1c)

| Screen | What it does |
|--------|--------------|
| Sign in, two-step verification, password change | Email + password; QR-code set-up for an authenticator app; code entry; forced change of a temporary password |
| Overview | My open and overdue tasks, open opportunities and SLA breaches, pipeline by stage, latest enquiries, number of outstanding decisions |
| Leads | List with status filter; new-lead form (country never sets pricing; out-of-market and duplicate outcomes explained); two-step spreadsheet import with per-row report |
| Customers | Search and lifecycle filter; household page with market confirmation (with a note), contacts with contact details and consent status, students and subjects, opportunities with budget in its currency, notes (team or private), tasks, tags, timeline |
| Duplicates | Review possible duplicate households; merge (with confirmation) or dismiss |
| Sales Pipeline | Board by stage; move with the stage's requirements shown, lost reason and revisit date; "Still needed" list when a move is refused |
| Tasks & Follow-ups | My tasks, add with due date, complete and reopen; automatic reminders marked |
| Team | Staff, roles with market scope, last sign-in; add users with a temporary password |
| Settings | Outstanding decisions and all settings; change values with status and decision reference (permission-checked; dual-approval settings locked until Phase 2) |

Modules from later phases appear in the navigation, greyed out, with the phase they arrive in. Colours are placeholders until Mixt's brand assets arrive (Q-BRD-01).

## Run locally

Start the backend first (see [services/backend/README.md](../../services/backend/README.md)) on port 8000, plus the worker for the timeline. Then:

```bash
npm install
npm run dev
```

Open http://localhost:3000. Requests to `/api/v1/*` are proxied to the backend (`MIXT_API_ORIGIN`, default `http://localhost:8000`), so the API's HttpOnly session cookie works on the same origin.

## Checks (same as CI)

```bash
npm run typecheck
npm run build
npm run e2e
```

`npm run e2e` starts the real backend and dashboard, wipes and migrates the database in `E2E_DATABASE_URL` (default `postgresql+psycopg://postgres@localhost:5433/mixt_e2e`), creates an Owner and drives a browser through sign-in, two-step set-up, leads, market confirmation, notes, timeline, pipeline checks, tasks, a US enquiry and sign-out. Set `E2E_SCREENSHOTS=<dir>` to save screenshots.

When the API changes, regenerate the types (CI fails if they are out of date):

```bash
(cd ../../services/backend && uv run python scripts/export_openapi.py ../../apps/web/openapi.json)
npm run gen:api
```

import { defineConfig, devices } from "@playwright/test";

// End-to-end tests run the real stack: FastAPI on :8000 (real PostgreSQL) and Next.js on :3000.
// E2E_DATABASE_URL must point at a database used only for these tests (it is wiped first).
// The API runs as a least-privileged application role (no schema rights), like in staging; the
// migration step runs as the database owner and grants that role its rights.
const ownerUrl = process.env.E2E_DATABASE_URL ?? "postgresql+psycopg://postgres@localhost:5433/mixt_e2e";
export const E2E = {
  databaseUrl: ownerUrl,
  appRole: "mixt_app_e2e",
  appRolePassword: "mixt-app-e2e-only",
  appDatabaseUrl: ownerUrl.replace(/\/\/[^@/]*@/, "//mixt_app_e2e:mixt-app-e2e-only@"),
  backendDir: "../../services/backend",
  ownerEmail: "e2e.owner@example.com",
  ownerPassword: "E2e-owner-passphrase-2026",
};

const backendEnv = {
  MIXT_ENV: "local",
  MIXT_DATABASE_URL: E2E.appDatabaseUrl,
  MIXT_MIGRATION_DATABASE_URL: E2E.databaseUrl,
  MIXT_ENCRYPTION_KEYS: JSON.stringify({ e2e: "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA=" }),
  MIXT_ACTIVE_ENCRYPTION_KEY_ID: "e2e",
  MIXT_COOKIE_SECURE: "false",
  MIXT_LOG_JSON: "false",
  // WhatsApp calls go to a local fake Graph API (e2e/fake-graph.mjs), never to Meta.
  MIXT_WHATSAPP_GRAPH_BASE_URL: "http://127.0.0.1:8099",
};
Object.assign(process.env, backendEnv);

// E2E_BASE_URL runs the same journey against an already running deployment (e.g. the staging stack
// over HTTPS, infra/staging): no local servers, no database reset, and the deployment's own worker.
const deployed = process.env.E2E_BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  globalSetup: deployed ? undefined : "./e2e/global-setup.ts",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: deployed ?? "http://localhost:3000",
    ignoreHTTPSErrors: Boolean(deployed), // staging trials use Caddy's internal certificate authority
    trace: "off",
    deviceScaleFactor: process.env.E2E_SCREENSHOTS ? 2 : 1,
  },
  webServer: deployed ? undefined : [
    {
      command: "node e2e/fake-graph.mjs",
      url: "http://127.0.0.1:8099/health",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "uv run uvicorn mixt.main:app --port 8000",
      cwd: E2E.backendDir,
      url: "http://localhost:8000/api/v1/health",
      env: backendEnv,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "npx next start --port 3000",
      url: "http://localhost:3000/login",
      env: { MIXT_API_ORIGIN: "http://localhost:8000" },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});

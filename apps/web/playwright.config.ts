import { defineConfig, devices } from "@playwright/test";

// End-to-end tests run the real stack: FastAPI on :8000 (real PostgreSQL) and Next.js on :3000.
// E2E_DATABASE_URL must point at a database used only for these tests (it is wiped first).
export const E2E = {
  databaseUrl: process.env.E2E_DATABASE_URL ?? "postgresql+psycopg://postgres@localhost:5433/mixt_e2e",
  backendDir: "../../services/backend",
  ownerEmail: "e2e.owner@example.com",
  ownerPassword: "E2e-owner-passphrase-2026",
};

const backendEnv = {
  MIXT_ENV: "local",
  MIXT_DATABASE_URL: E2E.databaseUrl,
  MIXT_ENCRYPTION_KEYS: JSON.stringify({ e2e: "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA=" }),
  MIXT_ACTIVE_ENCRYPTION_KEY_ID: "e2e",
  MIXT_COOKIE_SECURE: "false",
  MIXT_LOG_JSON: "false",
};
Object.assign(process.env, backendEnv);

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  globalSetup: "./e2e/global-setup.ts",
  use: { ...devices["Desktop Chrome"], baseURL: "http://localhost:3000", trace: "off", deviceScaleFactor: process.env.E2E_SCREENSHOTS ? 2 : 1 },
  webServer: [
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

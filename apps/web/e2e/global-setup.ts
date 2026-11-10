import { execSync } from "node:child_process";

import { E2E } from "../playwright.config";

/** Fresh database: drop everything, run the real migrations, create the first Owner. */
export default function globalSetup(): void {
  const run = (command: string, extraEnv: Record<string, string> = {}) =>
    execSync(command, { cwd: E2E.backendDir, stdio: "inherit", env: { ...process.env, ...extraEnv } });
  run(
    `uv run python -c "from sqlalchemy import create_engine, text; e = create_engine('${E2E.databaseUrl}'); c = e.connect(); c.execute(text('DROP SCHEMA IF EXISTS public CASCADE')); c.execute(text('CREATE SCHEMA public')); c.commit()"`,
  );
  run("uv run alembic upgrade head");
  run(`uv run python -m mixt.cli create-owner --email ${E2E.ownerEmail} --name "E2E Owner"`, {
    MIXT_OWNER_PASSWORD: E2E.ownerPassword,
  });
}

import { execSync } from "node:child_process";

import { E2E } from "../playwright.config";

/**
 * Fresh database, set up the way staging is: drop everything, make sure the application role
 * exists, run the real migrations as the owner (which also grants the application role its
 * data-only rights), then create the first Owner account through the application role.
 */
export default function globalSetup(): void {
  const run = (command: string, extraEnv: Record<string, string> = {}) =>
    execSync(command, { cwd: E2E.backendDir, stdio: "inherit", env: { ...process.env, ...extraEnv } });
  // Passed on stdin, not on the command line, so the shell does not touch the SQL.
  const reset = [
    "from sqlalchemy import create_engine, text",
    `engine = create_engine(${JSON.stringify(E2E.databaseUrl)})`,
    "with engine.begin() as c:",
    "    c.execute(text('DROP SCHEMA IF EXISTS public CASCADE'))",
    "    c.execute(text('CREATE SCHEMA public'))",
    `    if not c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = '${E2E.appRole}'")).scalar():`,
    `        c.execute(text("CREATE ROLE ${E2E.appRole} LOGIN PASSWORD '${E2E.appRolePassword}'"))`,
  ].join("\n");
  execSync("uv run python -", { cwd: E2E.backendDir, stdio: ["pipe", "inherit", "inherit"], input: reset });
  run(`uv run python -m mixt.cli migrate --app-role ${E2E.appRole}`);
  run("uv run python -m mixt.cli check-db-role");
  run(`uv run python -m mixt.cli create-owner --email ${E2E.ownerEmail} --name "E2E Owner"`, {
    MIXT_OWNER_PASSWORD: E2E.ownerPassword,
  });
}

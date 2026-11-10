#!/bin/sh
# Runs once, when the database volume is first created (official postgres image entrypoint).
# Creates the three Mixt roles and the database. Passwords come from the environment (.env).
#   mixt_owner     owns the database and schema; used only by the `migrate` job
#   mixt_app       data access only (granted by `migrate` after each migration)
#   mixt_readonly  SELECT only; used by backups
set -eu
psql --no-psqlrc -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v owner_pw="$MIXT_DB_OWNER_PASSWORD" -v app_pw="$MIXT_DB_APP_PASSWORD" -v ro_pw="$MIXT_DB_READONLY_PASSWORD" <<'SQL'
CREATE ROLE mixt_owner LOGIN PASSWORD :'owner_pw';
CREATE ROLE mixt_app LOGIN PASSWORD :'app_pw' CONNECTION LIMIT 60;
CREATE ROLE mixt_readonly LOGIN PASSWORD :'ro_pw' CONNECTION LIMIT 5;
CREATE DATABASE mixt OWNER mixt_owner;
REVOKE ALL ON DATABASE mixt FROM PUBLIC;
GRANT CONNECT ON DATABASE mixt TO mixt_app, mixt_readonly;
SQL

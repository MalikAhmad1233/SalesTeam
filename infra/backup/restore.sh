#!/bin/sh
# Restore an encrypted backup into an EMPTY database (IN-22). Used by the restore check and for a
# real recovery.
#
#   restore.sh <backup stem or "latest"> <target database URL>
#
# BACKUP_AGE_IDENTITY_FILE: the private key file (never stored with the backups).
# Checks the checksums first; refuses to restore into a database that already has tables.
set -eu

: "${BACKUP_AGE_IDENTITY_FILE:?set BACKUP_AGE_IDENTITY_FILE to the private key file}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
which="${1:?usage: restore.sh <stem|latest> <target url>}"
target="${2:?usage: restore.sh <stem|latest> <target url>}"

if [ "$which" = "latest" ]; then
  dump="$(ls -1t "$BACKUP_DIR"/mixt-*.dump.age | head -n 1)"
  stem="$(basename "${dump%.dump.age}")"
else
  stem="$which"
fi
cd "$BACKUP_DIR"
sha256sum --check --quiet "$stem.sha256"
tables="$(psql "$target" --no-psqlrc --tuples-only --no-align -c "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")"
if [ "$tables" != "0" ]; then
  echo "restore: target database is not empty ($tables tables); refusing" >&2
  exit 1
fi
age --decrypt --identity "$BACKUP_AGE_IDENTITY_FILE" "$stem.dump.age" \
  | pg_restore --dbname="$target" --no-owner --no-acl --exit-on-error --single-transaction
echo "$stem"

#!/usr/bin/env bash
# Restore check (IN-22): restore a backup into a separate, empty PostgreSQL and verify it.
#
#   ./restore-check.sh [backup stem | latest]
#
# Needs the private key: BACKUP_AGE_IDENTITY_FILE (default ./backup-identity.txt). The key is
# streamed into the restore container's memory (tmpfs) and never written to a volume. Prints the
# verification report (JSON) and exits non-zero if any step or check fails. Run it at least monthly
# and after every change to the backup set-up; record the result in the operations log.
set -euo pipefail
cd "$(dirname "$0")"
which="${1:-latest}"
identity="${BACKUP_AGE_IDENTITY_FILE:-./backup-identity.txt}"
target="postgresql://postgres:restore-check-only@restore-db:5432/restore_check"

docker compose --profile restore-check up -d --wait restore-db
trap 'docker compose --profile restore-check rm -sf restore-db >/dev/null 2>&1' EXIT

output="$(docker compose run --rm -T --no-deps backup sh -c \
  'umask 077 && cat > /tmp/identity && BACKUP_AGE_IDENTITY_FILE=/tmp/identity restore.sh "$0" "$1"' \
  "$which" "$target" < "$identity")"
stem="$(printf '%s\n' "$output" | tail -n 1)"
case "$stem" in
  mixt-*) echo "restored $stem into the scratch database" >&2 ;;
  *) echo "restore failed: $output" >&2; exit 1 ;;
esac

manifest="$(docker compose run --rm -T --no-deps backup cat "/backups/$stem.manifest.json")"
printf '%s' "$manifest" | docker compose run --rm -T --no-deps api \
  python -m mixt.cli verify-restore --database-url "postgresql+psycopg://${target#postgresql://}" --manifest /dev/stdin

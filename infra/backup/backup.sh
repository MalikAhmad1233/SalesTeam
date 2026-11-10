#!/bin/sh
# Encrypted logical backups of the Mixt AI database (IN-22).
#
#   backup.sh once   take one backup now
#   backup.sh loop   take one every BACKUP_INTERVAL_SECONDS (default 6 h), forever
#
# Each backup is three files in BACKUP_DIR (default /backups):
#   mixt-<UTC time>.manifest.json  schema revision, row counts, last audit-log entry and hash
#                                  (written just before the dump; no personal data)
#   mixt-<UTC time>.dump.age       pg_dump custom format, encrypted to BACKUP_AGE_RECIPIENT
#   mixt-<UTC time>.sha256         checksums of both
#
# Runs as the read-only database role: a backup job can never change data. Only the public key is
# needed here; the private key that decrypts backups is kept elsewhere (see docs/14 runbook).
# Backups older than BACKUP_RETENTION_DAYS (default 14) are removed, but the newest
# BACKUP_KEEP_MIN (default 3) are always kept. BACKUP_UPLOAD_COMMAND, if set, is run with the
# three file paths as arguments to copy them off the server (e.g. to object storage).
set -eu

: "${PGHOST:?}" "${PGDATABASE:?}" "${PGUSER:?}" "${PGPASSWORD:?}" "${BACKUP_AGE_RECIPIENT:?}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_INTERVAL_SECONDS="${BACKUP_INTERVAL_SECONDS:-21600}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
BACKUP_KEEP_MIN="${BACKUP_KEEP_MIN:-3}"

log() { printf '%s backup: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

manifest_sql="
SELECT json_build_object(
  'taken_at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+00:00\"'),
  'schema_revision', (SELECT version_num FROM alembic_version),
  'tables', (
    SELECT json_object_agg(tablename, (xpath('/row/c/text()',
      query_to_xml(format('SELECT count(*) AS c FROM %I.%I', schemaname, tablename), false, true, '')))[1]::text::bigint
      ORDER BY tablename)
    FROM pg_tables WHERE schemaname = 'public'),
  'audit', (
    SELECT json_build_object(
      'rows', count(*),
      'last_chain_seq', max(chain_seq),
      'last_hash', (SELECT encode(row_hash, 'hex') FROM audit_log ORDER BY chain_seq DESC LIMIT 1))
    FROM audit_log)
)"

take_backup() {
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  base="$BACKUP_DIR/mixt-$stamp"
  umask 077
  psql --no-psqlrc --quiet --tuples-only --no-align -v ON_ERROR_STOP=1 -c "$manifest_sql" > "$base.manifest.json.tmp"
  pg_dump --format=custom --compress=6 --no-password | age --encrypt --recipient "$BACKUP_AGE_RECIPIENT" > "$base.dump.age.tmp"
  mv "$base.manifest.json.tmp" "$base.manifest.json"
  mv "$base.dump.age.tmp" "$base.dump.age"
  (cd "$BACKUP_DIR" && sha256sum "mixt-$stamp.manifest.json" "mixt-$stamp.dump.age" > "mixt-$stamp.sha256")
  log "written mixt-$stamp ($(wc -c < "$base.dump.age") bytes encrypted)"
  if [ -n "${BACKUP_UPLOAD_COMMAND:-}" ]; then
    # shellcheck disable=SC2086
    $BACKUP_UPLOAD_COMMAND "$base.manifest.json" "$base.dump.age" "$base.sha256"
    log "uploaded mixt-$stamp"
  fi
  prune
}

prune() {
  # Newest first; never remove the newest BACKUP_KEEP_MIN backups.
  ls -1t "$BACKUP_DIR"/mixt-*.dump.age 2>/dev/null | tail -n +"$((BACKUP_KEEP_MIN + 1))" | while read -r dump; do
    if [ -n "$(find "$dump" -mtime +"$BACKUP_RETENTION_DAYS")" ]; then
      stem="${dump%.dump.age}"
      rm -f "$stem.dump.age" "$stem.manifest.json" "$stem.sha256"
      log "removed $(basename "$stem") (older than $BACKUP_RETENTION_DAYS days)"
    fi
  done
  rm -f "$BACKUP_DIR"/*.tmp
}

case "${1:-once}" in
  once) take_backup ;;
  loop)
    log "every ${BACKUP_INTERVAL_SECONDS}s, keeping ${BACKUP_RETENTION_DAYS} days (at least ${BACKUP_KEEP_MIN})"
    until pg_isready --quiet; do sleep 2; done
    while true; do
      take_backup || log "FAILED (will retry at the next interval)"
      sleep "$BACKUP_INTERVAL_SECONDS" &
      wait $!
    done
    ;;
  *) echo "usage: backup.sh once|loop" >&2; exit 2 ;;
esac

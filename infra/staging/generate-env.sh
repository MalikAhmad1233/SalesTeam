#!/bin/sh
# Writes infra/staging/.env with fresh random secrets, and backup-identity.txt with the private key
# that decrypts backups. Run once per environment; never commit either file.
#
#   ./generate-env.sh <domain> <tls>
#     domain  public host name, e.g. staging.mixt.example (or "localhost" for a local trial)
#     tls     an email address for a real Let's Encrypt certificate, or "internal" (self-signed CA)
#
# Move backup-identity.txt OFF the server into the password manager / secrets store: whoever has it
# can read every backup. The server only needs the public key (BACKUP_AGE_RECIPIENT).
set -eu
cd "$(dirname "$0")"
domain="${1:?usage: generate-env.sh <domain> <email|internal>}"
tls="${2:?usage: generate-env.sh <domain> <email|internal>}"
if [ -e .env ]; then
  echo ".env already exists; refusing to overwrite secrets (move it away first)" >&2
  exit 1
fi
secret() { od -An -tx1 -N"${1:-24}" /dev/urandom | tr -d ' \n'; }
key32() { head -c 32 /dev/urandom | base64 | tr -d '\n'; }

if command -v age-keygen >/dev/null 2>&1; then
  age-keygen -o backup-identity.txt 2>/dev/null
else
  docker run --rm --entrypoint age-keygen "$(docker build -q ../backup)" > backup-identity.txt
fi
chmod 600 backup-identity.txt
recipient="$(grep -o 'age1[0-9a-z]*' backup-identity.txt | head -n 1)"
key_id="stg-$(date -u +%Y%m%d)"

umask 077
cat > .env <<ENV
# Generated $(date -u +%Y-%m-%dT%H:%M:%SZ) by generate-env.sh. Secrets: never commit, keep a copy in the secrets store.
MIXT_DOMAIN=$domain
MIXT_TLS=$tls
MIXT_DB_SUPERUSER_PASSWORD=$(secret)
MIXT_DB_OWNER_PASSWORD=$(secret)
MIXT_DB_APP_PASSWORD=$(secret)
MIXT_DB_READONLY_PASSWORD=$(secret)
MIXT_REDIS_PASSWORD=$(secret)
MIXT_ENCRYPTION_KEYS='{"$key_id":"$(key32)"}'
MIXT_ACTIVE_ENCRYPTION_KEY_ID=$key_id
BACKUP_AGE_RECIPIENT=$recipient
# Optional single sign-on client credentials (the provider is chosen in Settings: auth.sso)
MIXT_SSO_GOOGLE_CLIENT_ID=
MIXT_SSO_GOOGLE_CLIENT_SECRET=
MIXT_SSO_MICROSOFT_CLIENT_ID=
MIXT_SSO_MICROSOFT_CLIENT_SECRET=
MIXT_SSO_MICROSOFT_TENANT_ID=
ENV
echo "wrote .env and backup-identity.txt (move backup-identity.txt off this server)"

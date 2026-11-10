#!/usr/bin/env bash
# Staging smoke test (run after `docker compose up -d --wait` and creating the Owner account).
# Checks the security properties of the running stack from the outside, over HTTPS.
#   ./smoke.sh [owner email]
set -euo pipefail
cd "$(dirname "$0")"
set -a; source .env; set +a
base="https://$MIXT_DOMAIN"
owner="${1:-e2e.owner@example.com}"
curl_k() { curl --silent --show-error --insecure --resolve "$MIXT_DOMAIN:443:127.0.0.1" "$@"; }
pass() { printf 'ok    %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; exit 1; }

ready="$(curl_k "$base/api/v1/health/ready")"
[[ "$ready" == *'"status":"ready"'*'"rate_limit_store":"ok"'* ]] && pass "ready: $ready" || fail "not ready: $ready"

headers="$(curl_k -o /dev/null -D - "$base/login")"
grep -qi "^content-security-policy: .*script-src 'self' 'nonce-" <<<"$headers" && pass "nonce-based CSP on pages" || fail "no nonce CSP"
grep -qi "^content-security-policy: .*unsafe-inline" <<<"$headers" && fail "CSP allows unsafe-inline" || pass "no unsafe-inline"
grep -qi "^strict-transport-security: max-age=31536000" <<<"$headers" && pass "HSTS" || fail "no HSTS"
grep -qi "^server:" <<<"$headers" && fail "server header leaks" || pass "no Server header"

code="$(curl --silent -o /dev/null -w '%{http_code}' --resolve "$MIXT_DOMAIN:80:127.0.0.1" "http://$MIXT_DOMAIN/login")"
[[ "$code" == 308 || "$code" == 301 ]] && pass "http redirects to https ($code)" || fail "http answered $code"

code="$(curl_k -o /dev/null -w '%{http_code}' "$base/api/v1/openapi.json")"
[[ "$code" == 404 ]] && pass "API schema not published" || fail "openapi.json answered $code"
code="$(curl_k -o /dev/null -w '%{http_code}' "$base/api/docs")"
[[ "$code" == 404 ]] && pass "API docs not published" || fail "api/docs answered $code"

code="$(curl_k -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' --data-binary @<(head -c 400000 /dev/zero | tr '\0' 'a') "$base/api/v1/auth/login")"
[[ "$code" == 413 ]] && pass "oversized request bodies refused ($code)" || fail "large body answered $code"

docker compose exec -T api python -m mixt.cli check-db-role >/dev/null && pass "API database role has data access only" || fail "API role over-privileged"

# A forged X-Forwarded-For must not become the recorded client address.
curl_k -o /dev/null -H 'X-Forwarded-For: 6.6.6.6' -H 'Content-Type: application/json' \
  -d "{\"email\":\"$owner\",\"password\":\"not-the-password\"}" "$base/api/v1/auth/login"
recorded="$(docker compose exec -T db psql -U postgres -d mixt -tAc \
  "SELECT host(ip) FROM audit_log WHERE action = 'login_failed' ORDER BY chain_seq DESC LIMIT 1")"
[[ -n "$recorded" && "$recorded" != "6.6.6.6" ]] && pass "forged client address ignored (recorded $recorded)" || fail "recorded '$recorded'"

codes=""
for _ in $(seq 1 11); do
  codes+="$(curl_k -o /dev/null -w '%{http_code} ' -H 'Content-Type: application/json' \
    -d '{"email":"nobody-smoke@example.com","password":"x"}' "$base/api/v1/auth/login")"
done
[[ "$codes" == *"429 " ]] && pass "sign-in attempts rate-limited: $codes" || fail "no rate limit: $codes"

audit="$(docker compose exec -T api python -c "
from sqlalchemy.orm import Session
from mixt.core.db import get_engine
from mixt.modules.audit import service as audit
with Session(get_engine()) as s:
    r = audit.verify_chain(s)
    print(r.ok, r.rows_checked)")"
[[ "$audit" == True* ]] && pass "audit hash chain verifies ($audit)" || fail "audit chain: $audit"

docker compose stop worker >/dev/null
docker compose logs worker | grep -q "worker stopped" && pass "worker stops cleanly on SIGTERM" || fail "worker did not stop cleanly"
docker compose start worker >/dev/null
echo "smoke test passed"

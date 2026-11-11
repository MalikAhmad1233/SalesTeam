#!/bin/sh
# Mixt AI demo: the whole platform on this computer, with one command. Synthetic data only.
#
#   infra/demo/demo.sh          start it, then show the address and the demo sign-in
#                               (the first start builds everything: allow 5 to 10 minutes)
#   infra/demo/demo.sh info     show the address and the demo sign-in again
#   infra/demo/demo.sh stop     stop it (the demo data is kept for next time)
#   infra/demo/demo.sh reset    delete the demo and all its data (the next start is fresh)
#   infra/demo/demo.sh logs     follow what the servers are doing (Ctrl+C to leave)
#
# Needs Docker. If Docker is missing on Kali, Debian or Ubuntu, this script offers to install it
# (--yes installs without asking). --no-build starts the images from the last build as they are.
# MIXT_DEMO_PORT changes the port (default 3000).
#
# Not for real customer data: plain HTTP, no backups, "local" settings. infra/staging is the real
# stack (HTTPS, Redis, encrypted backups, restore checks); see docs/14-operations-runbook.md.
set -eu

SELF="$0"
cd "$(dirname "$0")"
PORT="${MIXT_DEMO_PORT:-3000}"
PROJECT="mixtdemo"
OWNER_EMAIL="owner@mixt-demo.example"
YES=0
BUILD=1
CMD=start
for arg in "$@"; do
  case "$arg" in
    --yes | -y) YES=1 ;;
    --no-build) BUILD=0 ;;
    start | info | stop | reset | logs) CMD=$arg ;;
    -h | --help | help) sed -n '2,16p' "$SELF" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
fail() { printf '\nerror: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
env_value() { sed -n "s/^$1=//p" .env 2>/dev/null | head -n 1; }

confirm() { # confirm "question": yes with --yes, or when the person answers yes
  [ "$YES" = 1 ] && return 0
  [ -t 0 ] || return 1
  printf '%s [Y/n] ' "$1"
  read -r answer || return 1
  case "$answer" in "" | y | Y | yes | Yes | YES) return 0 ;; *) return 1 ;; esac
}

apt_has() { [ -n "$(apt-cache policy "$1" 2>/dev/null | sed -n 's/^ *Candidate: *//p' | grep -v '(none)')" ]; }

apt_install_compose() {
  if apt_has docker-compose-v2; then sudo apt-get install -y docker-compose-v2; else sudo apt-get install -y docker-compose; fi
}

# ---- Docker -----------------------------------------------------------------------------------
SUDO=""
find_docker() {
  if ! have docker; then
    have apt-get || fail "Docker is not installed. Install Docker Engine with Compose (https://docs.docker.com/engine/install/), then run this again."
    confirm "Docker is not installed. Install it now with apt (asks for your sudo password)?" ||
      fail "Docker is needed. Install it with: sudo apt-get install -y docker.io docker-compose"
    sudo apt-get update
    sudo apt-get install -y docker.io
    if apt_has docker-buildx; then sudo apt-get install -y docker-buildx; fi
    if ! docker compose version >/dev/null 2>&1 && ! have docker-compose; then apt_install_compose; fi
  fi
  docker info >/dev/null 2>&1 && return 0
  # Either the Docker service is stopped, or this user may not use it without sudo yet.
  have sudo || fail "Docker is installed but not running. Start it, then run this again."
  if ! sudo docker info >/dev/null 2>&1 && have systemctl; then
    say "Starting the Docker service..."
    sudo systemctl enable --now docker >/dev/null 2>&1 || sudo systemctl start docker || true
    sleep 2
  fi
  docker info >/dev/null 2>&1 && return 0
  if sudo docker info >/dev/null 2>&1; then
    SUDO="sudo"
    say "(Using sudo for Docker. To stop needing it: sudo usermod -aG docker \"\$USER\", then sign out and back in.)"
    return 0
  fi
  fail "Docker is installed but not running. Start it with: sudo systemctl start docker"
}

COMPOSE=""
find_compose() {
  if $SUDO docker compose version >/dev/null 2>&1; then
    COMPOSE="$SUDO docker compose"
  elif have docker-compose; then
    COMPOSE="$SUDO docker-compose"
  elif have apt-get && confirm "Docker Compose is missing. Install it now with apt?"; then
    sudo apt-get update
    apt_install_compose
    if $SUDO docker compose version >/dev/null 2>&1; then COMPOSE="$SUDO docker compose"; else COMPOSE="$SUDO docker-compose"; fi
  else
    fail "Docker Compose is missing. Install it with: sudo apt-get install -y docker-compose"
  fi
}

compose() { $COMPOSE -p "$PROJECT" -f compose.yaml "$@"; }

# ---- secrets, readiness, sign-in --------------------------------------------------------------
secret() { od -An -tx1 -N"${1:-24}" /dev/urandom | tr -d ' \n'; }
key32() { head -c 32 /dev/urandom | base64 | tr -d '\n'; }

write_env() {
  if $SUDO docker volume inspect "${PROJECT}_demo-db" >/dev/null 2>&1; then
    fail "Demo data exists from an earlier run but its secrets (.env) are gone. Start over with: $SELF reset"
  fi
  owner_pw="Demo-$(secret 3)-$(secret 3)-$(secret 3)"
  umask 077
  cat >.env <<ENV
# Written by demo.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ): demo secrets for this computer only. Never commit.
MIXT_DB_SUPERUSER_PASSWORD=$(secret)
MIXT_DB_OWNER_PASSWORD=$(secret)
MIXT_DB_APP_PASSWORD=$(secret)
MIXT_DB_READONLY_PASSWORD=$(secret)
MIXT_ENCRYPTION_KEYS='{"demo":"$(key32)"}'
MIXT_ACTIVE_ENCRYPTION_KEY_ID=demo
MIXT_DEMO_OWNER_PASSWORD=$owner_pw
ENV
  umask 022
}

probe() { # probe URL: succeeds when it answers 200
  if have curl; then
    curl -fsS -o /dev/null --max-time 3 "$1" 2>/dev/null
  elif have wget; then
    wget -q -O /dev/null -T 3 "$1" 2>/dev/null
  else
    python3 -c "import sys,urllib.request; urllib.request.urlopen(sys.argv[1], timeout=3)" "$1" 2>/dev/null
  fi
}

ready_url="http://127.0.0.1:$PORT/api/v1/health/ready" # through the dashboard, so both must be up

wait_ready() {
  say "Waiting for Mixt AI to be ready..."
  i=0
  while ! probe "$ready_url"; do
    i=$((i + 1))
    if [ "$i" -ge 100 ]; then
      compose ps || true
      fail "Mixt AI did not become ready within 5 minutes. To see why: $SELF logs"
    fi
    sleep 3
  done
}

ensure_owner() {
  pw="$(env_value MIXT_DEMO_OWNER_PASSWORD)"
  if out=$(compose exec -T -e MIXT_OWNER_PASSWORD="$pw" api \
    python -m mixt.cli create-owner --email "$OWNER_EMAIL" --name "Demo Owner" 2>&1); then
    return 0
  fi
  case "$out" in *ALREADY_BOOTSTRAPPED*) return 0 ;; esac
  printf '%s\n' "$out" >&2
  fail "Could not create the demo Owner account."
}

demo_url() {
  if [ -n "${CODESPACE_NAME:-}" ] && [ -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]; then
    printf 'https://%s-%s.%s' "$CODESPACE_NAME" "$PORT" "$GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN"
  else
    printf 'http://localhost:%s' "$PORT"
  fi
}

show_info() {
  [ -f .env ] || fail "The demo has not been started yet. Start it with: $SELF"
  if probe "$ready_url"; then state="Mixt AI is running."; else state="Mixt AI is NOT running right now (start it with: $SELF)."; fi
  cat <<INFO

  ============================================================================
  $state

  Open:      $(demo_url)
  Email:     $OWNER_EMAIL
  Password:  $(env_value MIXT_DEMO_OWNER_PASSWORD)

  The first sign-in asks you to set up two-step verification: scan the QR code
  with an authenticator app on your phone (Google Authenticator, Microsoft
  Authenticator, Authy...) and type the 6-digit code it shows.

  Stop:        $SELF stop      (the demo data is kept)
  Start:       $SELF
  Start over:  $SELF reset
  Demo only: do not enter real customer details.
  ============================================================================

INFO
}

# ---- commands ---------------------------------------------------------------------------------
case "$CMD" in
  info)
    show_info
    ;;
  start)
    find_docker
    find_compose
    [ -f .env ] || write_env
    if [ "$BUILD" = 1 ]; then
      say "Building Mixt AI (the first time takes several minutes; later starts are quick)..."
      compose build
    fi
    say "Starting Mixt AI..."
    if ! compose up -d; then
      compose logs --tail 40 migrate api || true
      fail "Mixt AI did not start (details above). To see more: $SELF logs"
    fi
    wait_ready
    ensure_owner
    show_info
    ;;
  stop)
    find_docker
    find_compose
    compose stop
    say "Stopped. Your demo data is kept; start again with: $SELF"
    ;;
  logs)
    find_docker
    find_compose
    compose logs -f --tail 100
    ;;
  reset)
    find_docker
    find_compose
    confirm "Delete the demo and ALL its data?" || fail "Nothing deleted."
    compose down -v --remove-orphans
    rm -f .env
    say "Deleted. Start a fresh demo with: $SELF"
    ;;
esac

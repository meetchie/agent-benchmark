#!/usr/bin/env bash
# Run the live benchmark locally: the Python backend and the web UI, together.
#
#   make dev            needs ANTHROPIC_API_KEY (shell or .env)
#   make demo           DEMO_MODE=true: canned runs, no key, no browser
#
# Ctrl-C (or SIGTERM to this script) stops both servers.
#
# Settings. The backend loads .env itself (server/runtime_env.py) and so does Vite,
# so this script does not source it. It reads only the two values that decide which
# ports to use: BENCHMARK_API_URL (default http://127.0.0.1:8000, the URL Vite
# proxies to; the backend is started on that port) and BENCHMARK_WEB_PORT (default
# 5180). A value in your shell beats the one in .env.
#
# Processes. The script starts exactly two children, remembers their PIDs, and on
# exit stops those PIDs and their descendants by PID (found with `pgrep -P`),
# TERM first and KILL only for what is still alive after 10 s. It never matches
# processes by name.

set -u -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

API_PID=""
WEB_PID=""

say() { printf '%s\n' "$*"; }
die() { printf 'dev: %s\n' "$*" >&2; exit 1; }

# --- settings ---------------------------------------------------------------

# Value of NAME in $ROOT/.env: the last assignment, without quotes or a trailing comment.
dotenv_get() {
  [ -f "$ROOT/.env" ] || return 0
  sed -n -E "s/^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=(.*)$/\\2/p" "$ROOT/.env" \
    | tail -n 1 \
    | sed -E -e 's/^[[:space:]]+//' -e 's/[[:space:]]+$//' \
             -e 's/^"([^"]*)".*$/\1/' -e "s/^'([^']*)'.*\$/\\1/" \
             -e 's/[[:space:]]+#.*$//'
}

# NAME from the shell if it is set and not empty, else from .env, else the default.
setting() {
  local name=$1 default=$2 value
  eval "value=\${$name:-}"
  [ -n "$value" ] || value="$(dotenv_get "$name")"
  printf '%s' "${value:-$default}"
}

API_URL="$(setting BENCHMARK_API_URL http://127.0.0.1:8000)"
API_URL="${API_URL%/}"
WEB_PORT="$(setting BENCHMARK_WEB_PORT 5180)"

# http://host[:port] -> host and port
hostport="${API_URL#*://}"
hostport="${hostport%%/*}"
API_HOST="${hostport%%:*}"
case "$hostport" in
  *:*) API_PORT="${hostport##*:}" ;;
  *)   case "$API_URL" in https://*) API_PORT=443 ;; *) API_PORT=80 ;; esac ;;
esac

case "$WEB_PORT" in ''|*[!0-9]*) die "BENCHMARK_WEB_PORT=$WEB_PORT is not a port number." ;; esac
case "$API_PORT" in ''|*[!0-9]*) die "BENCHMARK_API_URL=$API_URL has no usable port." ;; esac

START_BACKEND=1
case "$API_HOST" in
  127.0.0.1|localhost) ;;
  *) START_BACKEND=0 ;;
esac

# --- process helpers --------------------------------------------------------

port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

descendants() {
  local child
  for child in $(pgrep -P "$1" 2>/dev/null); do
    printf '%s\n' "$child"
    descendants "$child"
  done
}

# Stop one PID and everything below it, by PID.
stop_tree() {
  local pid=$1 all p i alive
  [ -n "$pid" ] || return 0
  all="$pid $(descendants "$pid" | tr '\n' ' ')"
  kill -TERM $all 2>/dev/null
  for i in $(seq 1 50); do
    alive=0
    for p in $all; do kill -0 "$p" 2>/dev/null && alive=1; done
    [ "$alive" = 0 ] && return 0
    sleep 0.2
  done
  for p in $all; do kill -0 "$p" 2>/dev/null && kill -KILL "$p" 2>/dev/null; done
  return 0
}

cleanup() {
  trap '' INT TERM
  local pid
  for pid in "$WEB_PID" "$API_PID"; do stop_tree "$pid"; done
  WEB_PID=""
  API_PID=""
}

trap cleanup EXIT
trap 'say; say "Stopping."; exit 0' INT TERM

# Wait until URL answers. Returns 0 when it does, 2 when PID died first, 1 on timeout.
wait_for() {
  local url=$1 pid=$2 seconds=$3 i
  for ((i = 0; i < seconds * 5; i++)); do
    curl -fsS -o /dev/null --max-time 2 "$url" 2>/dev/null && return 0
    kill -0 "$pid" 2>/dev/null || return 2
    sleep 0.2
  done
  return 1
}

# --- preflight --------------------------------------------------------------

[ -x "$ROOT/web/node_modules/.bin/vite" ] || die "the web packages are not installed. Run 'make setup' first."
command -v uv >/dev/null 2>&1 || die "uv is not installed (https://docs.astral.sh/uv/)."
port_busy "$WEB_PORT" && die "port $WEB_PORT is already in use. Set BENCHMARK_WEB_PORT to a free port, or stop what is using it."
if [ "$START_BACKEND" = 1 ]; then
  port_busy "$API_PORT" && die "port $API_PORT is already in use. Set BENCHMARK_API_URL (for example http://127.0.0.1:8001) to use another, or stop what is using it."
fi

# --- backend ----------------------------------------------------------------

if [ "$START_BACKEND" = 1 ]; then
  say "Starting the backend on 127.0.0.1:$API_PORT ..."
  ( cd "$ROOT/server" && exec uv run uvicorn server:app --host 127.0.0.1 --port "$API_PORT" ) &
  API_PID=$!
  wait_for "http://127.0.0.1:$API_PORT/health" "$API_PID" 90
  case $? in
    0) ;;
    2) die "the backend exited before it was ready (the reason is printed above). Without a key, use 'make demo'." ;;
    *) die "the backend did not answer on http://127.0.0.1:$API_PORT/health within 90 s." ;;
  esac
  HEALTH="$(curl -fsS --max-time 2 "http://127.0.0.1:$API_PORT/health" 2>/dev/null || true)"
else
  say "BENCHMARK_API_URL is $API_URL, not this machine: not starting a backend."
  HEALTH=""
fi

# --- web UI -----------------------------------------------------------------

say "Starting the web UI on port $WEB_PORT ..."
( cd "$ROOT/web" && exec ./node_modules/.bin/vite ) &
WEB_PID=$!
wait_for "http://localhost:$WEB_PORT/" "$WEB_PID" 60
case $? in
  0) ;;
  2) die "the web UI exited before it was ready (the reason is printed above)." ;;
  *) die "the web UI did not answer on http://localhost:$WEB_PORT/ within 60 s." ;;
esac

# --- ready ------------------------------------------------------------------

case "$HEALTH" in
  *'"demo_mode":true'*) MODE="demo (canned runs and tasks: no key, no browser, no cost)" ;;
  '') MODE="backend at $API_URL" ;;
  *)  MODE="live (real runs with your API key; they cost money)" ;;
esac

say
say "  Web UI    http://localhost:$WEB_PORT      <- open this"
[ "$START_BACKEND" = 1 ] && say "  Backend   http://127.0.0.1:$API_PORT      (health: /health)"
say "  Mode      $MODE"
say
say "Press Ctrl-C to stop."

# Run until Ctrl-C, or until either server dies (then stop the other and fail).
while kill -0 "$WEB_PID" 2>/dev/null && { [ -z "$API_PID" ] || kill -0 "$API_PID" 2>/dev/null; }; do
  sleep 1
done
die "a server exited unexpectedly; stopping the other one."

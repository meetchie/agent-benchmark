#!/usr/bin/env bash
# Run the live benchmark locally: the Python backend and the web UI, together.
#
#   make dev            needs ANTHROPIC_API_KEY (shell or .env)
#   make demo           DEMO_MODE=true: canned runs, no key, no browser
#
# Ctrl-C (or SIGTERM or SIGHUP to this script) stops both servers.
#
# The backend and Vite load .env themselves. This script reads only the two values that pick ports:
# BENCHMARK_API_URL (default http://127.0.0.1:8000, the URL Vite proxies to and the port the backend
# starts on) and BENCHMARK_WEB_PORT (default 5180). A value in your shell beats .env.
#
# It starts exactly two children and stops them by PID, never by process name. The backend gets a
# process group of its own so a terminal Ctrl-C does not reach it directly, and has time to cancel
# its runs and save them before anything left in the group is killed.

set -u -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

API_PID=""
WEB_PID=""

say() { printf '%s\n' "$*"; }
die() { printf 'dev: %s\n' "$*" >&2; exit 1; }

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
[ "$WEB_PORT" -ge 1 ] && [ "$WEB_PORT" -le 65535 ] || die "BENCHMARK_WEB_PORT=$WEB_PORT is not a port number (1 to 65535)."
[ "$API_PORT" -ge 1 ] && [ "$API_PORT" -le 65535 ] || die "BENCHMARK_API_URL=$API_URL has no usable port (1 to 65535)."

START_BACKEND=1
case "$API_HOST" in
  127.0.0.1|localhost) ;;
  *) START_BACKEND=0 ;;
esac

# Is something listening on host $1, port $2?
listening_on() { (exec 3<>"/dev/tcp/$1/$2") 2>/dev/null; }

# The backend (uvicorn) binds 127.0.0.1 only.
api_port_busy() { listening_on 127.0.0.1 "$1"; }

# The web UI (Vite) binds 127.0.0.1 and ::1, so it needs both free: another server
# on either one would answer some of http://localhost:<port> and 127.0.0.1:<port>.
web_port_busy() { listening_on 127.0.0.1 "$1" || listening_on ::1 "$1"; }

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

# Seconds the backend gets to shut down (it cancels its runs and saves them) before
# what is left of its process group is stopped. The server waits at most 8 s for
# its runs, and uvicorn 3 s for requests still open.
BACKEND_GRACE_S=15

group_alive() { kill -0 -- "-$1" 2>/dev/null; }

# Stop the backend, whose process group is led by PID $1 (see "backend" below).
stop_backend() {
  local pid=$1 i
  [ -n "$pid" ] || return 0
  # uv forwards the TERM to the server; the server gets it directly too.
  kill -TERM "$pid" $(pgrep -P "$pid" 2>/dev/null) 2>/dev/null
  for ((i = 0; i < BACKEND_GRACE_S * 5; i++)); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.2
  done
  group_alive "$pid" || return 0
  kill -TERM -- "-$pid" 2>/dev/null
  for ((i = 0; i < 15; i++)); do
    group_alive "$pid" || return 0
    sleep 0.2
  done
  kill -KILL -- "-$pid" 2>/dev/null
  return 0
}

cleanup() {
  trap '' INT TERM HUP
  stop_tree "$WEB_PID"
  stop_backend "$API_PID"
  WEB_PID=""
  API_PID=""
}

trap cleanup EXIT
trap 'say; say "Stopping."; exit 0' INT TERM HUP

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

[ -x "$ROOT/web/node_modules/.bin/vite" ] || die "the web packages are not installed. Run 'make setup' first."
command -v uv >/dev/null 2>&1 || die "uv is not installed (https://docs.astral.sh/uv/)."
web_port_busy "$WEB_PORT" && die "port $WEB_PORT is already in use (on 127.0.0.1 or ::1). Set BENCHMARK_WEB_PORT to a free port, or stop what is using it."
if [ "$START_BACKEND" = 1 ]; then
  api_port_busy "$API_PORT" && die "port $API_PORT is already in use. Set BENCHMARK_API_URL (for example http://127.0.0.1:8001) to use another, or stop what is using it."
fi

if [ "$START_BACKEND" = 1 ]; then
  say "Starting the backend on 127.0.0.1:$API_PORT ..."
  # set -m: the backend gets a process group of its own (led by $API_PID), so a
  # terminal Ctrl-C reaches only this script, which then stops the backend in order
  # (stop_backend). Delivered straight to uvicorn, one Ctrl-C would arrive twice (the
  # terminal's and the copy `uv run` forwards), and uvicorn takes a second SIGINT as
  # "force quit" and skips the shutdown that stops the runs' browsers.
  set -m
  ( cd "$ROOT/server" && exec uv run uvicorn server:app --host 127.0.0.1 --port "$API_PORT" --timeout-graceful-shutdown 3 ) &
  API_PID=$!
  set +m
  wait_for "http://127.0.0.1:$API_PORT/health" "$API_PID" 90
  case $? in
    0) ;;
    2) die "the backend exited before it was ready (the reason is printed above)." ;;
    *) die "the backend did not answer on http://127.0.0.1:$API_PORT/health within 90 s." ;;
  esac
  HEALTH="$(curl -fsS --max-time 2 "http://127.0.0.1:$API_PORT/health" 2>/dev/null || true)"
else
  say "BENCHMARK_API_URL is $API_URL, not this machine: not starting a backend."
  HEALTH=""
fi

say "Starting the web UI on port $WEB_PORT ..."
( cd "$ROOT/web" && exec ./node_modules/.bin/vite ) &
WEB_PID=$!
wait_for "http://127.0.0.1:$WEB_PORT/" "$WEB_PID" 60
case $? in
  0) ;;
  2) die "the web UI exited before it was ready (the reason is printed above)." ;;
  *) die "the web UI did not answer on http://127.0.0.1:$WEB_PORT/ within 60 s." ;;
esac

case "$HEALTH" in
  *'"demo_mode":true'*) MODE="demo (canned runs and tasks: no key, no browser, no cost)" ;;
  '') MODE="backend at $API_URL" ;;
  *)  MODE="live (real runs with your API key; they cost money)" ;;
esac

say
say "  Web UI    http://localhost:$WEB_PORT      <- open this (127.0.0.1 works too)"
[ "$START_BACKEND" = 1 ] && say "  Backend   http://127.0.0.1:$API_PORT      (health: /health)"
say "  Mode      $MODE"
say
say "Press Ctrl-C to stop."

# Run until Ctrl-C, or until either server dies (then stop the other and fail).
while kill -0 "$WEB_PID" 2>/dev/null && { [ -z "$API_PID" ] || kill -0 "$API_PID" 2>/dev/null; }; do
  sleep 1
done
die "a server exited unexpectedly; stopping the other one."

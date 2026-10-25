#!/bin/sh
# Tests for scripts/setup-done.sh (the closing message of `make setup`) and for the
# Makefile's check of SUITES (`make test-scripts`). They need only make and sh.
# The "key" written into the throwaway .env files is a made-up word.

HERE=$(cd "$(dirname "$0")" && pwd -P)
ROOT=$(cd "$HERE/.." && pwd -P)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/scripts-test.XXXXXX") || exit 1
trap 'rm -rf "$TMP"' EXIT
pass=0
fail=0

ok()  { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); echo "FAIL: $1"; }

# Run a command the way a fresh shell would see it: no make flags from an outer make and
# no key from the caller's own environment. Output goes to $TMP/out, the status is in $?.
clean() {
  env -u MAKEFLAGS -u MAKELEVEL -u MFLAGS -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN "$@" > "$TMP/out" 2>&1
}
# contains <name> <text>: the last output has the text
contains() { if grep -qF -- "$2" "$TMP/out"; then ok; else bad "$1 (no '$2' in: $(cat "$TMP/out"))"; fi; }
lacks()    { if grep -qF -- "$2" "$TMP/out"; then bad "$1 (found '$2')"; else ok; fi; }
status()   { if [ "$2" -eq "$3" ]; then ok; else bad "$1 (exit $2, wanted $3)"; fi; }

# --- make setup's closing message -------------------------------------------
NEXT="Run 'make dev'."
BLANK="has no ANTHROPIC_API_KEY value yet"
ENVF="$TMP/env"

message() {   # message <env file contents>: what setup-done.sh says for a .env like that
  printf '%s\n' "$1" > "$ENVF"
  clean sh "$ROOT/scripts/setup-done.sh" "$ENVF"
  status "setup-done exits 0" $? 0
}

message "ANTHROPIC_API_KEY="                          ; contains "empty value" "$BLANK"
message 'ANTHROPIC_API_KEY=""'                        ; contains "empty double quotes" "$BLANK"
message "ANTHROPIC_API_KEY=''"                        ; contains "empty single quotes" "$BLANK"
message "ANTHROPIC_API_KEY=   # your key here"        ; contains "only a comment" "$BLANK"
message "OTHER=1"                                     ; contains "no such line" "$BLANK"
message "# ANTHROPIC_API_KEY=made-up-word"            ; contains "commented out" "$BLANK"
message "ANTHROPIC_API_KEY=made-up-word
ANTHROPIC_API_KEY="                                   ; contains "the last line wins" "$BLANK"

message "ANTHROPIC_API_KEY=made-up-word"              ; contains "a value" "$NEXT"; lacks "never prints the value" "made-up-word"
message 'export ANTHROPIC_API_KEY="made-up-word" # k'  ; contains "export, quotes and a comment" "$NEXT"; lacks "never prints a quoted value" "made-up-word"
message "ANTHROPIC_AUTH_TOKEN=made-up-word"           ; contains "a token in place of the key" "$NEXT"

printf 'ANTHROPIC_API_KEY=\n' > "$ENVF"
clean env ANTHROPIC_API_KEY=made-up-word sh "$ROOT/scripts/setup-done.sh" "$ENVF"
contains "a key in the shell counts" "$NEXT"; lacks "never prints the shell's value" "made-up-word"

clean sh "$ROOT/scripts/setup-done.sh" "$TMP/no-such-file"
contains "no .env yet" "cp .env.example .env"

# --- make test SUITES=... ----------------------------------------------------
clean make -C "$ROOT" test SUITES="nonesuch hooks"
status "an unknown suite fails" $? 2
contains "names the unknown suite" "Unknown test suite: nonesuch"
contains "lists the known ones" "Known suites: server cli web viewer hooks scripts"
lacks "runs nothing" "=== make test-"

clean make -C "$ROOT" test SUITES="server nonesuch other"
status "two unknown suites fail" $? 2
contains "names both" "Unknown test suite: nonesuch other"

clean make -C "$ROOT" test SUITES=""
status "no suite at all fails" $? 2
contains "says none was named" "No test suite named"

clean make -C "$ROOT" -n test SUITES="hooks"
status "a known suite is accepted" $? 0
contains "and is the one that runs" "test-hooks"

clean make -C "$ROOT" -n test
status "the default runs" $? 0
for suite in server cli web viewer hooks scripts; do contains "the default includes $suite" "$suite"; done

echo "scripts tests: $pass passed, $fail failed"
[ "$fail" -eq 0 ]

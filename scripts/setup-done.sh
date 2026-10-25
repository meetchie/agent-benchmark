#!/bin/sh
# The last lines of `make setup`: what to do next, depending on whether an API key is in place.
#
#   scripts/setup-done.sh [env file]     (default: .env in the repository root)
#
# Only whether a key has a value is tested. The value is never printed.

HERE=$(cd "$(dirname "$0")" && pwd -P)
ENV_FILE=${1:-$HERE/../.env}

# The last assignment of NAME in the env file, without quotes or a trailing comment
# (the same reading as dotenv_get in dev.sh).
env_file_value() {
  sed -n -E "s/^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=(.*)$/\\2/p" "$ENV_FILE" |
    tail -n 1 |
    sed -E -e 's/^[[:space:]]+//' \
           -e 's/^"([^"]*)".*$/\1/' -e "s/^'([^']*)'.*\$/\\1/" \
           -e 's/^#.*$//' -e 's/[[:space:]]+#.*$//' -e 's/[[:space:]]+$//'
}

# A key counts when the shell has it (the shell beats .env) or the env file gives it a value.
# ANTHROPIC_AUTH_TOKEN is accepted in place of ANTHROPIC_API_KEY.
has_key() {
  [ -n "${ANTHROPIC_API_KEY:-}" ] || [ -n "${ANTHROPIC_AUTH_TOKEN:-}" ] && return 0
  [ -f "$ENV_FILE" ] || return 1
  [ -n "$(env_file_value ANTHROPIC_API_KEY)" ] || [ -n "$(env_file_value ANTHROPIC_AUTH_TOKEN)" ]
}

if [ ! -f "$ENV_FILE" ]; then
  echo "Setup done. Next: 'cp .env.example .env' and put your key after ANTHROPIC_API_KEY=, then 'make dev'. ('make demo' runs without a key.)"
elif has_key; then
  echo "Setup done. Run 'make dev'."
else
  echo "Setup done. .env has no ANTHROPIC_API_KEY value yet: put your key after ANTHROPIC_API_KEY= in .env, then run 'make dev'. ('make demo' runs without a key.)"
fi

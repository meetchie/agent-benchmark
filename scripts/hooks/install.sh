#!/bin/sh
# Copy scripts/hooks/pre-commit to the checkout's hooks directory (`make setup` and
# `make install-hooks` run this). It never replaces anything and never changes git's
# configuration. It installs nothing, and says why, when:
#   - this folder is not the top of a git checkout (a download, or a folder inside another repo)
#   - a pre-commit hook already exists there
#   - core.hooksPath is set (hooks then live somewhere shared; that is not ours to write to)
# It always exits 0, so a hook that cannot be installed never fails `make setup`.

ROOT=$(cd "$(dirname "$0")/../.." && pwd -P) || exit 0
SRC="$ROOT/scripts/hooks/pre-commit"
say() { echo "pre-commit check: $*"; }

cd "$ROOT" || exit 0
[ -f "$SRC" ] || { say "scripts/hooks/pre-commit is missing, nothing installed."; exit 0; }
git rev-parse --git-dir >/dev/null 2>&1 || { say "this is not a git checkout, nothing installed."; exit 0; }
[ -z "$(git rev-parse --show-prefix)" ] || { say "this folder is inside another git repository, nothing installed."; exit 0; }
if [ -n "$(git config --get core.hooksPath)" ]; then
  say "core.hooksPath is set, so your hooks were left alone. To use the check, call scripts/hooks/pre-commit from your own pre-commit hook."
  exit 0
fi

dest=$(git rev-parse --git-path hooks/pre-commit)
case $dest in /*) ;; *) dest="$ROOT/$dest" ;; esac
if [ -e "$dest" ]; then
  say "a pre-commit hook already exists ($dest), left as it is."
  exit 0
fi
mkdir -p "$(dirname "$dest")" && cp "$SRC" "$dest" && chmod +x "$dest" \
  && say "installed ($dest). It refuses API keys and .env files." \
  || say "could not write $dest, nothing installed."
exit 0

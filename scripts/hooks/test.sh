#!/bin/sh
# Tests for scripts/hooks/pre-commit and scripts/hooks/install.sh (`make test-hooks`).
# Everything happens in throwaway repositories under a temp directory. The key-shaped
# strings are built here from pieces, so this file itself never looks like a key.

HERE=$(cd "$(dirname "$0")" && pwd -P)
ROOT=$(cd "$HERE/../.." && pwd -P)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/hooks-test.XXXXXX") || exit 1
trap 'rm -rf "$TMP"' EXIT
pass=0
fail=0

ok()  { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); echo "FAIL: $1"; }
# expect <exit code wanted> <name> <command...>
expect() {
  _want=$1; _label=$2; shift 2
  "$@" >/dev/null 2>&1
  _got=$?
  if [ "$_got" -eq "$_want" ]; then ok; else bad "$_label (exit $_got, wanted $_want)"; fi
}
rep() { printf "%${2}s" "" | tr ' ' "$1"; }   # rep <char> <count>

newrepo() {   # newrepo <dir>: an empty repository with its own identity
  mkdir -p "$1" && git -C "$1" init -q &&
    git -C "$1" config user.email t@example.invalid && git -C "$1" config user.name t
}
check() {     # check <repo>: run the hook on what is staged there
  (cd "$1" && sh "$ROOT/scripts/hooks/pre-commit")
}

# --- the hook ---------------------------------------------------------------
R="$TMP/hook"
newrepo "$R"
cd "$R" || exit 1

echo "hello" > notes.txt; git add notes.txt
expect 0 "a plain file passes" check "$R"

for key in \
  "sk-ant-$(rep a 30)" "sk-proj-$(rep b 30)" "sk-$(rep c 48)" "AKIA$(rep A 16)" "ASIA$(rep B 16)" \
  "ghp_$(rep d 36)" "gho_$(rep e 36)" "sk_live_$(rep f 24)" "bb_live_$(rep g 24)" \
  "$(rep - 5)BEGIN RSA PRIVATE KEY$(rep - 5)" "$(rep - 5)BEGIN PRIVATE KEY$(rep - 5)"; do
  echo "x = \"$key\"" > leak.txt; git add leak.txt
  expect 1 "refuses $(echo "$key" | cut -c1-12)" check "$R"
  git rm -q -f --cached leak.txt; rm -f leak.txt
done

echo "key = sk-ant-short" > short.txt; git add short.txt
expect 0 "a short sk-ant- word is not a key" check "$R"
git rm -q -f --cached short.txt; rm -f short.txt

echo "ANTHROPIC_API_KEY=" > .env.example; git add .env.example
expect 0 ".env.example passes" check "$R"
git rm -q -f --cached .env.example; rm -f .env.example

for name in .env .env.local sub/.env sub/.env.production; do
  mkdir -p "$(dirname "$name")"; echo "A=1" > "$name"; git add "$name"
  expect 1 "refuses $name" check "$R"
  git rm -q -f --cached "$name"; rm -f "$name"
done

echo "A=1" > .envrc; echo "A=1" > env.txt; git add .envrc env.txt
expect 0 ".envrc and env.txt are not .env files" check "$R"
git rm -q -f --cached .envrc env.txt; rm -f .envrc env.txt

# A key that is only removed, and a .env that is deleted, must not block the cleanup.
echo "x = \"sk-ant-$(rep a 30)\"" > old.txt; echo "A=1" > .env
git add -f old.txt .env; git commit -q -m "mistake"
git rm -q old.txt .env
expect 0 "deleting a committed key and .env passes" check "$R"
git commit -q -m "cleanup"

# --- the installer ----------------------------------------------------------
copy_tree() {   # the files install.sh needs, in a fresh folder
  mkdir -p "$1/scripts/hooks" &&
    cp "$ROOT/scripts/hooks/install.sh" "$ROOT/scripts/hooks/pre-commit" "$1/scripts/hooks/"
}
installed() { [ -x "$1/.git/hooks/pre-commit" ] && cmp -s "$1/.git/hooks/pre-commit" "$ROOT/scripts/hooks/pre-commit"; }

# a git checkout with no hook: installed, executable, identical
I="$TMP/install"; newrepo "$I"; copy_tree "$I"
expect 0 "installer exits 0" sh "$I/scripts/hooks/install.sh"
if installed "$I"; then ok; else bad "installer copies the hook"; fi
git -C "$I" config --get core.hooksPath >/dev/null 2>&1 && bad "installer must not set core.hooksPath" || ok

# a second run leaves an existing hook (here edited) alone
echo "# mine" >> "$I/.git/hooks/pre-commit"
sh "$I/scripts/hooks/install.sh" >/dev/null 2>&1
if tail -1 "$I/.git/hooks/pre-commit" | grep -q '^# mine$'; then ok; else bad "installer keeps an existing hook"; fi

# another tool's hook is never replaced
J="$TMP/other"; newrepo "$J"; copy_tree "$J"
printf '#!/bin/sh\necho theirs\n' > "$J/.git/hooks/pre-commit"
sh "$J/scripts/hooks/install.sh" >/dev/null 2>&1
if grep -q theirs "$J/.git/hooks/pre-commit"; then ok; else bad "installer keeps another pre-commit hook"; fi

# not a git checkout: nothing written, exit 0
N="$TMP/plain"; copy_tree "$N"
expect 0 "installer outside git exits 0" sh "$N/scripts/hooks/install.sh"
[ -e "$N/.git" ] && bad "installer must not create .git" || ok

# a folder inside another repository must not touch that repository's hooks
P="$TMP/parent"; newrepo "$P"; copy_tree "$P/inner"
sh "$P/inner/scripts/hooks/install.sh" >/dev/null 2>&1
[ -e "$P/.git/hooks/pre-commit" ] && bad "installer must not write into the parent repository" || ok

# core.hooksPath set: left alone
H="$TMP/hookspath"; newrepo "$H"; copy_tree "$H"; mkdir -p "$TMP/shared-hooks"
git -C "$H" config core.hooksPath "$TMP/shared-hooks"
sh "$H/scripts/hooks/install.sh" >/dev/null 2>&1
[ -e "$TMP/shared-hooks/pre-commit" ] || [ -e "$H/.git/hooks/pre-commit" ] && bad "installer must not write when core.hooksPath is set" || ok

# a linked worktree writes into the shared hooks directory of its repository
W="$TMP/main"; newrepo "$W"; copy_tree "$W"
git -C "$W" add -A && git -C "$W" commit -q -m init
git -C "$W" worktree add -q "$TMP/linked" -b linked
sh "$TMP/linked/scripts/hooks/install.sh" >/dev/null 2>&1
if installed "$W"; then ok; else bad "installer from a linked worktree"; fi

# the Makefile targets call the installer
M="$TMP/make"; newrepo "$M"; copy_tree "$M"; cp "$ROOT/Makefile" "$M/Makefile"
expect 0 "make install-hooks" make -C "$M" install-hooks
if installed "$M"; then ok; else bad "make install-hooks installs the hook"; fi

# the installed hook really blocks a commit
(cd "$M" && echo "k = sk-ant-$(rep z 30)" > secret.txt && git add secret.txt && git commit -q -m x >/dev/null 2>&1) && bad "an installed hook blocks a commit with a key" || ok

cd "$ROOT" || exit 1
echo "hooks: $pass checks passed, $fail failed"
[ "$fail" -eq 0 ]

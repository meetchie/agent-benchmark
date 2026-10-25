# agent-benchmark: set up, run and test everything from the repository root.
#
#   make setup    install everything (once), plus a pre-commit check against committed keys
#   make dev      backend + web UI, needs ANTHROPIC_API_KEY in .env
#   make demo     the same with canned runs, needs no key
#   make test     every test suite (all of them run, then the failures are listed);
#                 make test SUITES="server hooks" runs only those (unknown names are refused)
#
# Needs uv (https://docs.astral.sh/uv/), Node 20+ with npm, and make. uv fetches
# Python 3.11 itself. Run `make help` for the full list.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# arena shortcut:   make arena AGENT=BROWSERUSE SCENARIO=vhlistings_add_to_cart
# (both are required: an arena run costs money, so there are no defaults)
AGENT    ?=
SCENARIO ?=
# compare shortcut: make compare TASK=add-hair-towel [SITE=prose]
SITE ?= prose
TASK ?=
comma := ,

# The suites `make test` runs, in this order (each is also a target: make test-<suite>).
# make test SUITES="server hooks" runs only some of them; a name that is not in this
# list is refused.
KNOWN_SUITES := server cli web viewer hooks scripts
SUITES ?= $(KNOWN_SUITES)
export UNKNOWN_SUITES := $(filter-out $(KNOWN_SUITES),$(SUITES))

.PHONY: help setup install-hooks check-tools check-suites dev demo test $(addprefix test-,$(KNOWN_SUITES)) \
        arena arena-list analyze analyze-march check-task compare compare-tasks compare-tools viewer

help: ## list the targets
	@echo "agent-benchmark"
	@echo
	@awk -F':.*## ' '/^[a-zA-Z_-]+:.*## /{printf "  make %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo
	@echo "Variables: AGENT, SCENARIO (arena); SITE, TASK (compare); SUITES (test). Settings live in .env (see .env.example)."

check-tools:
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Install it from https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }
	@command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1 || { echo "Node.js 20 or newer with npm is not installed (web/.nvmrc says 22)." >&2; exit 1; }
	@node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)' || { echo "Node.js $$(node --version) is too old; 20 or newer is needed." >&2; exit 1; }

# The last step starts Chromium once (browser_env.py): on Linux it can be installed and
# still unable to run, for want of system libraries, and then nothing else would work.
setup: check-tools ## install the Python environment, Chromium, the npm packages and the pre-commit check
	cd server && uv sync
	cd server && uv run playwright install chromium
	cd web && npm ci --no-audit --no-fund
	cd viewer && npm ci --no-audit --no-fund
	@./scripts/hooks/install.sh
	@echo
	@cd server && uv run python browser_env.py || { echo; echo "Everything else is installed ('make demo' needs no browser). Fix Chromium, then run 'make setup' again."; exit 1; } >&2
	@./scripts/setup-done.sh

install-hooks: ## install the pre-commit check that refuses API keys and .env files (setup does this too)
	@./scripts/hooks/install.sh

dev: check-tools ## backend (127.0.0.1) and web UI together; Ctrl-C stops both
	@./scripts/dev.sh

demo: check-tools ## the same with canned runs: no API key, no browser
	@DEMO_MODE=true ./scripts/dev.sh

check-suites:
	@[ -n "$(strip $(SUITES))" ] || { echo "No test suite named. Known suites: $(KNOWN_SUITES)" >&2; exit 2; }
	@[ -z "$$UNKNOWN_SUITES" ] || { printf 'Unknown test suite: %s\nKnown suites: %s\n' "$$UNKNOWN_SUITES" "$(KNOWN_SUITES)" >&2; exit 2; }

test: check-suites check-tools ## every test suite (all run, failures listed at the end; offline, no key); SUITES="server hooks" picks some
	@passed=""; failed=""; \
	for suite in $(SUITES); do \
	  echo; echo "=== make test-$$suite"; \
	  if $(MAKE) --no-print-directory test-$$suite; then passed="$$passed $$suite"; else failed="$$failed $$suite"; fi; \
	done; \
	echo; echo "=== test summary"; \
	[ -z "$$passed" ] || echo "passed:$$passed"; \
	if [ -n "$$failed" ]; then echo "FAILED:$$failed" >&2; exit 1; fi

test-server: check-tools ## server tests (pytest)
	cd server && uv run pytest -q

test-cli: check-tools ## comparison CLI tests (pytest, run apart from the server's own suite)
	uv run --project server pytest cli -q

test-web: check-tools ## web tests (vitest) and a production build
	cd web && npm test && npm run build

test-viewer: check-tools ## viewer tests (vitest) and a production build
	cd viewer && npm test && npm run build

test-hooks: ## tests of the pre-commit check and its installer (needs git, no uv or node)
	sh scripts/hooks/test.sh

test-scripts: ## tests of the setup message and the SUITES and TASK checks (needs make and sh, no uv or node)
	sh scripts/test.sh

arena: check-tools ## one arena run, a real run that costs money: AGENT=RINDLER|BROWSERUSE SCENARIO=... (both required)
	@{ [ -n "$(AGENT)" ] && [ -n "$(SCENARIO)" ]; } || { echo "usage: make arena AGENT=<RINDLER|BROWSERUSE> SCENARIO=<scenario id>   ('make arena-list' lists them; this is a real run and costs money)" >&2; exit 2; }
	cd server && uv run python arena.py --agent "$(AGENT)" --scenario "$(SCENARIO)"

arena-list: check-tools ## list the arena's agents and scenarios
	cd server && uv run python arena.py --list-agents && uv run python arena.py --list-scenarios

analyze: check-tools ## table over the archived March logs and any new arena runs
	cd server && uv run python analyze_runs.py

analyze-march: check-tools ## the March 2026 headline: the 60 + 60 logs behind Rindler 59/60 vs BrowserUse 1/60
	cd server && uv run python analyze_runs.py --march-headline

# TASK must hold at least one id: "," or " , " would reach the CLI as no ids at all.
check-task:
	@test -n "$(strip $(subst $(comma), ,$(TASK)))" || { echo "usage: make compare TASK=<task id> [SITE=prose]   ('make compare-tasks' lists the ids; both arms run for real and cost money)" >&2; exit 2; }

compare: check-task check-tools ## prose.com CLI, both arms, real runs that cost money: TASK=add-hair-towel
	cli/bench.sh "$(SITE)" --task "$(TASK)"

compare-tasks: check-tools ## list the CLI's tasks (no key needed)
	cli/bench.sh "$(SITE)" --list-tasks

compare-tools: check-tools ## list the tools the mapping gives the Rindler arm (no key needed)
	cli/bench.sh "$(SITE)" --show-tools

viewer: check-tools ## browse the archived March 2026 arena logs
	@test -d viewer/node_modules || { echo "Run 'make setup' first." >&2; exit 1; }
	cd viewer && npm run dev

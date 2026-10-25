# agent-benchmark: set up, run and test everything from the repository root.
#
#   make setup    install everything (once)
#   make dev      backend + web UI, needs ANTHROPIC_API_KEY in .env
#   make demo     the same with canned runs, needs no key
#   make test     every test suite
#
# Needs uv (https://docs.astral.sh/uv/), Node 20+ with npm, and make. uv fetches
# Python 3.11 itself. Run `make help` for the full list.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# arena shortcut:   make arena AGENT=BROWSERUSE SCENARIO=vhlistings_add_to_cart
AGENT    ?= RINDLER
SCENARIO ?= vhlistings_product_attribute_search
# compare shortcut: make compare TASK=add-hair-towel [SITE=prose]
SITE ?= prose
TASK ?=

.PHONY: help setup check-tools dev demo test test-server test-cli test-web test-viewer \
        arena arena-list analyze compare compare-tasks compare-tools viewer

help: ## list the targets
	@echo "agent-benchmark"
	@echo
	@awk -F':.*## ' '/^[a-zA-Z_-]+:.*## /{printf "  make %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo
	@echo "Variables: AGENT, SCENARIO (arena); SITE, TASK (compare). Settings live in .env (see .env.example)."

check-tools:
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Install it from https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }
	@command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1 || { echo "Node.js 20 or newer with npm is not installed (web/.nvmrc says 22)." >&2; exit 1; }
	@node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)' || { echo "Node.js $$(node --version) is too old; 20 or newer is needed." >&2; exit 1; }

setup: check-tools ## install the Python environment, Chromium and the npm packages
	cd server && uv sync
	cd server && uv run playwright install chromium
	cd web && npm ci --no-audit --no-fund
	cd viewer && npm ci --no-audit --no-fund
	@echo
	@if [ -f .env ]; then echo "Setup done. Run 'make dev'."; else echo "Setup done. Next: 'cp .env.example .env' and put your key after ANTHROPIC_API_KEY=, then 'make dev'. ('make demo' runs without a key.)"; fi

dev: check-tools ## backend (127.0.0.1) and web UI together; Ctrl-C stops both
	@./scripts/dev.sh

demo: check-tools ## the same with canned runs: no API key, no browser
	@DEMO_MODE=true ./scripts/dev.sh

test: test-server test-cli test-web test-viewer ## every test suite (offline, no key needed)

test-server: check-tools ## server tests (pytest)
	cd server && uv run pytest -q

test-cli: check-tools ## comparison CLI tests (pytest, run apart from the server's own suite)
	uv run --project server pytest cli -q

test-web: check-tools ## web tests (vitest) and a production build
	cd web && npm test && npm run build

test-viewer: check-tools ## viewer tests (vitest) and a production build
	cd viewer && npm test && npm run build

arena: check-tools ## one arena run, a real run that costs money: AGENT=RINDLER|BROWSERUSE SCENARIO=...
	cd server && uv run python arena.py --agent "$(AGENT)" --scenario "$(SCENARIO)"

arena-list: check-tools ## list the arena's agents and scenarios
	cd server && uv run python arena.py --list-agents && uv run python arena.py --list-scenarios

analyze: check-tools ## table over the archived March logs and any new arena runs
	cd server && uv run python analyze_runs.py

compare: check-tools ## prose.com CLI, both arms, real runs that cost money: TASK=add-hair-towel
	@test -n "$(TASK)" || { echo "usage: make compare TASK=<task id> [SITE=prose]   ('make compare-tasks' lists the ids; both arms run for real and cost money)" >&2; exit 2; }
	cli/bench.sh "$(SITE)" --task "$(TASK)"

compare-tasks: check-tools ## list the CLI's tasks (no key needed)
	cli/bench.sh "$(SITE)" --list-tasks

compare-tools: check-tools ## list the tools the mapping gives the Rindler arm (no key needed)
	cli/bench.sh "$(SITE)" --show-tools

viewer: check-tools ## browse the archived March 2026 arena logs
	@test -d viewer/node_modules || { echo "Run 'make setup' first." >&2; exit 1; }
	cd viewer && npm run dev

# Rindler Arena

## What this is

Rindler Arena is a CLI-based telemetric agent testing environment that benchmarks browser automation AI agents against real-world web scenarios. It runs a suite of predefined tasks — spanning e-commerce, food delivery, travel, and tech — against multiple agent backends, then uses an LLM judge (GPT-4o-mini) to evaluate success. Results and full logs are written to `arena_logs/` for later analysis and comparison.

---

## Prerequisites

- Python 3.11
- [Playwright](https://playwright.dev/python/) with Chromium
- API keys for the agents you intend to run (see [Environment Variables](#environment-variables))

---

## Quick Start

```bash
cd packages/clean-room

python -m venv .venv
source .venv/bin/activate

pip install -e .

playwright install chromium

cp .env.example .env   # fill in the required keys

python arena.py --agent BROWSERUSE --scenario shipt_add_to_cart
```

---

## Environment Variables

Copy `.env.example` to `.env` and populate the values for the agents you need.

| Variable | Required for |
|---|---|
| `OPENAI_API_KEY` | All agents (LLM judge + BrowserUse/Steel reasoning) |
| `BROWSERBASE_API_KEY` | BrowserUse, Stagehand |
| `BROWSERBASE_PROJECT_ID` | BrowserUse, Stagehand |
| `BROWSERBASE_ORG_ID` | BrowserUse, Stagehand |
| `STEEL_API_KEY` | Steel |
| `SKYVERN_API_KEY` | Skyvern |

---

## CLI Usage

```bash
# Run a specific agent against a specific scenario
python arena.py --agent BROWSERUSE --scenario shipt_add_to_cart

# List all available agents
python arena.py --list-agents

# List all available scenarios
python arena.py --list-scenarios

# Run with a custom goal (overrides scenario default)
python arena.py --agent STEEL --scenario amazon_search --goal "Search for a standing desk under $300"

# Run Skyvern in no-wait mode (fire-and-forget, don't poll for result)
python arena.py --agent SKYVERN --scenario instacart_checkout --no-wait
```

---

## Supported Agents

| Agent key | Browser backend | LLM / SDK |
|---|---|---|
| `BROWSERUSE` | Browserbase (cloud) | GPT-4o via browser-use |
| `STEEL` | Steel (cloud) | GPT-4o via LangChain |
| `SKYVERN` | Skyvern cloud API | Skyvern-managed |
| `STAGEHAND` | Browserbase (cloud) | Stagehand SDK |

---

## Scenarios

The arena ships with 20 predefined scenarios across four categories:

- **E-commerce** — Amazon, Walmart, Target, Shipt, Instacart
- **Food delivery** — DoorDash, Uber Eats, Grubhub
- **Travel** — Expedia, Google Flights, Airbnb
- **Tech / misc** — GitHub, LinkedIn, and others

Scenario definitions (IDs, URLs, goals, and success criteria) live in [`scenarios/definitions.py`](scenarios/definitions.py).

---

## How It Works

1. The CLI resolves the requested agent and scenario.
2. The agent launches a browser session (local Playwright or a cloud provider) and attempts to complete the scenario goal.
3. On completion, a GPT-4o-mini judge reviews the agent's action trace and final page state to produce a pass/fail verdict with a confidence score.
4. Results and full logs are written to `arena_logs/<timestamp>/`.

---

## Known Issues

**`telemetric_logger.py` is missing.** Only a stale `.pyc` bytecode file exists in `__pycache__`. The source file must be restored before the package will work on a fresh checkout. Without it, any import of `telemetric_logger` will fail at runtime.

---

## Tech Stack

- Python 3.11
- [browser-use](https://github.com/browser-use/browser-use)
- [Playwright](https://playwright.dev/python/)
- [LangChain](https://python.langchain.com/)
- aiohttp

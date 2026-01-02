# Clean Room - Telemetric Agent Testing

This directory contains a clean-room implementation for testing and comparing different browser automation agents with unified telemetry tracking.

## Overview

The clean-room provides adapters for four browser automation frameworks:

| Agent | Provider | Description |
|-------|----------|-------------|
| **BROWSERUSE** | Browserbase | browser-use library with hook-based telemetry |
| **STEEL** | Steel.dev | LangChain orchestration with Playwright control |
| **SKYVERN** | Skyvern.com | Cloud AI service with polling telemetry |
| **STAGEHAND** | Browserbase | AI browser automation with natural language |

All agents share the unified `TelemetricWrapper` for consistent logging, cost tracking, and loop detection.

## Quick Start

```bash
# 1. Set up environment
cd clean-room
cp .env.example .env  # Then edit with your API keys

# 2. Check setup status
python setup_agents.py

# 3. Run the gauntlet test
python day2_gauntlet.py --lane BROWSERUSE
python day2_gauntlet.py --lane STEEL
python day2_gauntlet.py --lane SKYVERN
python day2_gauntlet.py --lane STAGEHAND
```

## Directory Structure

```
clean-room/
├── adapters/                    # Agent adapter implementations
│   ├── __init__.py              # Package exports
│   ├── browseruse_agent.py      # BrowserUse + Browserbase
│   ├── steel_agent.py           # Steel + LangChain
│   ├── skyvern_agent.py         # Skyvern cloud API
│   └── stagehand_agent.py       # Stagehand + Browserbase
├── gauntlet_logs/               # Run logs and telemetry output
├── day1_test.py                 # Basic browser-use test script
├── day2_gauntlet.py             # Unified agent test runner
├── check_skyvern_billing.py     # Skyvern billing/status checker
├── setup_agents.py              # Dependency checker script
├── close_sessions.py            # Browserbase session cleanup utility
├── telemetric_agent.py          # Backwards compatibility shim
├── SETUP.md                     # Detailed setup instructions
├── README.md                    # This file
├── pyproject.toml               # Python dependencies
└── .env                         # API keys (not in git)
```

## Environment Variables

Create a `.env` file with the following:

```bash
# Required for all agents
OPENAI_API_KEY=your_openai_api_key

# For BROWSERUSE and STAGEHAND
BROWSERBASE_API_KEY=your_browserbase_api_key
BROWSERBASE_PROJECT_ID=your_browserbase_project_id

# For STEEL
STEEL_API_KEY=your_steel_api_key

# For SKYVERN
SKYVERN_API_KEY=your_skyvern_api_key
```

## Running Tests

### Day 2 Gauntlet

The gauntlet runs a standardized test across all agents:

```bash
# Test specific agent
python day2_gauntlet.py --lane BROWSERUSE

# The test goal:
# 1. Navigate to shipt.com
# 2. Set delivery address
# 3. Search for "Organic Bananas"
# 4. Add first result to cart
```

### Skyvern (Cloud-Based)

Skyvern runs in the cloud and requires special handling since tasks can take 15-30+ minutes.

#### Fire-and-Forget Mode (Default)

```bash
python day2_gauntlet.py --lane SKYVERN
```

This submits the task and returns immediately with:
- Task ID and watch URL
- Commands to check status later

#### Wait Mode (Polls Until Complete)

```bash
python day2_gauntlet.py --lane SKYVERN --wait
```

Polls Skyvern every 5 seconds until completion or timeout.

#### Check Status & Billing Later

```bash
# Quick status check
python check_skyvern_billing.py <task_id> --status-only

# Full billing summary with step breakdown
python check_skyvern_billing.py <task_id>

# JSON output
python check_skyvern_billing.py <task_id> --json
```

#### Billing Information

Skyvern charges ~$0.05 per step. The billing tool fetches:
- All tasks belonging to a run
- Step count per task
- Estimated total cost

Example output:
```
============================================================
  SKYVERN RUN SUMMARY
============================================================
  Run ID:     tsk_v2_REDACTED
  Status:     completed

  BILLING BREAKDOWN
  --------------------------------------------------------
  Total tasks:  7
  Total steps:  27
  Cost/step:    $0.05

  💰 ESTIMATED COST: $1.35

  PER-TASK BREAKDOWN
  --------------------------------------------------------
   1. ✓ tsk_REDACTED...
      3 steps | $0.15 | completed
   ...
============================================================
```

### Day 1 Test (Basic)

Simple browser-use test for development:

```bash
python day1_test.py
```

## Telemetry Output

Each run produces:
- Console output with step-by-step progress
- Log file in `gauntlet_logs/` with full telemetry
- Token usage and cost breakdown

Example summary:
```
============================================================
  FINAL SUMMARY
============================================================
  Lane:        BROWSERUSE
  Run ID:      abc123...
  Trace ID:    def456...
  Duration:    45.32s
  Steps:       12
  Success:     True

  TOKEN BURN
  ----------
  Input:       15,432 tokens
  Output:      2,891 tokens
  Total:       18,323 tokens

  COST
  ----
  Total:       $0.1205
============================================================
```

## Utilities

### Check Setup

```bash
python setup_agents.py
```

### Close Browserbase Sessions

```bash
# List active sessions
python close_sessions.py

# Close all sessions
python close_sessions.py --close-all

# Close specific session
python close_sessions.py --close <session_id>
```

### Skyvern Billing Checker

Check billing and status for any Skyvern task (works retroactively):

```bash
# Full billing summary
python check_skyvern_billing.py tsk_v2_REDACTED

# Quick status only
python check_skyvern_billing.py tsk_v2_REDACTED --status-only

# JSON output for scripting
python check_skyvern_billing.py tsk_v2_REDACTED --json
```

You can also check by workflow run ID (wr_xxx format):
```bash
python check_skyvern_billing.py wr_REDACTED
```

## Documentation

- [SETUP.md](./SETUP.md) - Detailed setup instructions for each agent
- [steel-dev/steel-browser](https://github.com/steel-dev/steel-browser) - Steel reference
- [skyvern-ai/skyvern](https://github.com/skyvern-ai/skyvern) - Skyvern reference
- [browserbase/stagehand](https://github.com/browserbase/stagehand) - Stagehand reference

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   day2_gauntlet.py                       │
│                 (Unified Test Runner)                    │
└───────────────────────┬─────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
        ▼               ▼               ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│  BROWSERUSE   │ │    STEEL      │ │   SKYVERN     │
│   Adapter     │ │   Adapter     │ │   Adapter     │
└───────┬───────┘ └───────┬───────┘ └───────┬───────┘
        │               │               │
        ▼               ▼               ▼
┌─────────────────────────────────────────────────────────┐
│                 TelemetricWrapper                        │
│        (Unified logging, cost tracking, hashing)         │
└─────────────────────────────────────────────────────────┘
```

## License

Part of the Rindler-MVP project.


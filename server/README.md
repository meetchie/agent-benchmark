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
├── browser_use_logs/            # Run logs and telemetry output
├── day1_test.py                 # Basic browser-use test script
├── day2_gauntlet.py             # Unified agent test runner
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

### Day 1 Test (Basic)

Simple browser-use test for development:

```bash
python day1_test.py
```

## Telemetry Output

Each run produces:
- Console output with step-by-step progress
- Log file in `browser_use_logs/` with full telemetry
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


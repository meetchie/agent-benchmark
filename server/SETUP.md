# Agent Setup Guide

This guide explains how to set up each agent (BROWSERUSE, STEEL, SKYVERN, STAGEHAND) for the arena test runner.

## Prerequisites

All agents require:
- Python 3.11+
- Virtual environment activated (`.venv`)
- `OPENAI_API_KEY` - Required for all agents that use LLMs

## Environment Variables

Create a `.env` file in the `clean-room` directory with the following variables:

```bash
# Required for all agents
OPENAI_API_KEY=your_openai_api_key_here

# Required for BROWSERUSE agent
BROWSERBASE_API_KEY=your_browserbase_api_key_here
BROWSERBASE_PROJECT_ID=your_browserbase_project_id_here

# Required for SKYVERN agent
SKYVERN_API_KEY=your_skyvern_api_key_here

# Required for STEEL agent
STEEL_API_KEY=your_steel_api_key_here

# Required for STAGEHAND agent (uses Browserbase)
# BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID (same as above)
# OPENAI_API_KEY (same as above)
```

## Agent-Specific Setup

### 1. BROWSERUSE Agent

**Required:**
- `BROWSERBASE_API_KEY` - Get from [Browserbase](https://browserbase.com)
- `BROWSERBASE_PROJECT_ID` - Get from Browserbase dashboard
- `BROWSERBASE_ORG_ID` - Get from Browserbase dashboard URL (the org ID in your dashboard URL)
- `OPENAI_API_KEY` - For LLM calls

**Dependencies:**
- `browser-use` - Browser automation with AI
- `browserbase` - Cloud browser service

**Setup Steps:**
1. Sign up at [https://browserbase.com](https://browserbase.com)
2. Get your API key and Project ID from the dashboard
3. Add them to your `.env` file

**Usage:**
```bash
python arena.py --agent BROWSERUSE --scenario shipt_add_to_cart
```

### 2. STEEL Agent

**Required:**
- `STEEL_API_KEY` - Get from [Steel.dev](https://steel.dev)
- `OPENAI_API_KEY` - For LangChain LLM calls

**Dependencies:**
- `steel-sdk` - Steel SDK package
- `playwright` - Already included via other dependencies
- `langchain` and `langchain-openai` - Already in dependencies

**Setup Steps:**
1. Sign up at [https://steel.dev](https://steel.dev)
2. Get your API key from the dashboard
3. Install Steel SDK:
   ```bash
   pip install steel-sdk
   ```
   Or if using uv:
   ```bash
   uv pip install steel-sdk
   ```

4. Add `STEEL_API_KEY` to your `.env` file
5. Ensure `OPENAI_API_KEY` is set

**Usage:**
```bash
python arena.py --agent STEEL --scenario google_search
```

**Reference:** [github.com/steel-dev/steel-browser](https://github.com/steel-dev/steel-browser)

### 3. SKYVERN Agent

**Required:**
- `SKYVERN_API_KEY` - Get from [Skyvern](https://skyvern.com)

**Dependencies:**
- `requests` - For API calls (standard library)
- `aiohttp` - For async API calls

**Setup Steps:**
1. Sign up at [https://app.skyvern.com](https://app.skyvern.com)
2. Get your API key from the dashboard
3. Add `SKYVERN_API_KEY` to your `.env` file

**Usage:**
```bash
python arena.py --agent SKYVERN --scenario amazon_search
```

**Reference:** [github.com/skyvern-ai/skyvern](https://github.com/skyvern-ai/skyvern)

**Notes:**
- Skyvern is a cloud-based service - no local browser needed
- Uses polling to track task progress
- Supports structured data extraction

### 4. STAGEHAND Agent

**Required:**
- `BROWSERBASE_API_KEY` - Get from [Browserbase](https://browserbase.com)
- `BROWSERBASE_PROJECT_ID` - Get from Browserbase dashboard
- `OPENAI_API_KEY` - For AI-driven automation

**Dependencies:**
- Node.js 18+ - Required for running Stagehand
- `@browserbasehq/stagehand` - Stagehand npm package

**Setup Steps:**
1. Sign up at [https://browserbase.com](https://browserbase.com)
2. Get your API key and Project ID from the dashboard
3. Install Node.js dependencies in the `clean-room` directory:
   ```bash
   npm init -y
   npm install @browserbasehq/stagehand
   ```

4. Add Browserbase credentials and OpenAI key to your `.env` file

**Usage:**
```bash
python arena.py --agent STAGEHAND --scenario hacker_news_browse
```

**Reference:** [github.com/browserbase/stagehand](https://github.com/browserbase/stagehand)

**Notes:**
- Stagehand is a TypeScript/JavaScript library
- The Python adapter runs it via subprocess
- Provides `act()`, `extract()`, `observe()`, and `agent()` methods
- For full native integration, use the JavaScript SDK directly

## Quick Setup Checklist

- [ ] Create `.env` file in `clean-room/` directory
- [ ] Add `OPENAI_API_KEY` to `.env`
- [ ] For BROWSERUSE: Add `BROWSERBASE_API_KEY`, `BROWSERBASE_PROJECT_ID`, and `BROWSERBASE_ORG_ID`
- [ ] For STEEL: Add `STEEL_API_KEY` and install `steel-sdk`
- [ ] For SKYVERN: Add `SKYVERN_API_KEY` (no extra packages needed)
- [ ] For STAGEHAND: Same Browserbase keys + install Node.js dependencies

## Testing Your Setup

Test each agent individually:

```bash
# Test BROWSERUSE
python arena.py --agent BROWSERUSE --scenario shipt_add_to_cart

# Test STEEL
python arena.py --agent STEEL --scenario google_search

# Test SKYVERN
python arena.py --agent SKYVERN --scenario amazon_search

# Test STAGEHAND
python arena.py --agent STAGEHAND --scenario hacker_news_browse

# List all available scenarios
python arena.py --list-scenarios
```

## Troubleshooting

### "ModuleNotFoundError: No module named 'steel'"
- Install Steel: `pip install steel-sdk`

### "SKYVERN_API_KEY not found"
- Add the key to your `.env` file
- Get your API key from [Skyvern dashboard](https://app.skyvern.com)

### "STEEL_API_KEY not found"
- Add the key to your `.env` file
- Get your API key from [Steel.dev dashboard](https://app.steel.dev)

### "BROWSERBASE_API_KEY not found"
- Add the key to your `.env` file
- Get your API key from [Browserbase dashboard](https://browserbase.com)

### Stagehand Node.js issues
- Ensure Node.js 18+ is installed: `node --version`
- Install Stagehand: `npm install @browserbasehq/stagehand`
- Ensure you're in the `clean-room` directory

## API Key Sources

- **OpenAI**: [https://platform.openai.com/api-keys](https://platform.openai.com/api-keys)
- **Browserbase**: [https://www.browserbase.com](https://www.browserbase.com)
- **Steel**: [https://app.steel.dev](https://app.steel.dev)
- **Skyvern**: [https://app.skyvern.com](https://app.skyvern.com)

## Architecture Overview

| Agent | Browser Provider | AI Provider | Method |
|-------|-----------------|-------------|--------|
| BROWSERUSE | Browserbase | OpenAI | Hook-based telemetry |
| STEEL | Steel Cloud | OpenAI (LangChain) | Callback telemetry |
| SKYVERN | Skyvern Cloud | Skyvern's AI | Polling telemetry |
| STAGEHAND | Browserbase | OpenAI | Subprocess telemetry |

All agents share the unified `TelemetricWrapper` for consistent logging and cost tracking.

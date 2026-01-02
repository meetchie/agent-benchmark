# Quick Setup Guide for INDUCED, LAVAGUE, and STEEL Agents

## 🚀 Quick Start

Run the setup checker to see what you need:
```bash
python setup_agents.py
```

## 📋 Summary of Requirements

### All Agents Need:
- ✅ `OPENAI_API_KEY` - You already have this!

### INDUCED Agent
**What you need:**
- `INDUCED_API_KEY` - Get from [https://app.induced.ai](https://app.induced.ai)
- No additional Python packages (uses `requests` which is already installed)

**Setup:**
1. Sign up at [https://app.induced.ai](https://app.induced.ai)
2. Get your API key from the dashboard
3. Add to `.env`: `INDUCED_API_KEY=your_key_here`

**Test:**
```bash
python day2_gauntlet.py --lane INDUCED
```

### LAVAGUE Agent
**What you need:**
- `OPENAI_API_KEY` - You already have this!
- Install packages: `lavague-core` and `lavague-drivers-selenium`
- Chrome/Chromium browser installed on your system

**Setup:**
1. Install packages:
   ```bash
   pip install lavague-core lavague-drivers-selenium
   ```
   Or with uv:
   ```bash
   uv pip install lavague-core lavague-drivers-selenium
   ```
2. Ensure Chrome/Chromium is installed (for Selenium)

**Test:**
```bash
python day2_gauntlet.py --lane LAVAGUE
```

### STEEL Agent
**What you need:**
- `STEEL_API_KEY` - Get from [https://app.steel.dev](https://app.steel.dev)
- `OPENAI_API_KEY` - You already have this!
- Install package: `steel-sdk`

**Setup:**
1. Sign up at [https://app.steel.dev](https://app.steel.dev)
2. Get your API key from the dashboard
3. Install package:
   ```bash
   pip install steel-sdk
   ```
   Or with uv:
   ```bash
   uv pip install steel-sdk
   ```
4. Add to `.env`: `STEEL_API_KEY=your_key_here`

**Test:**
```bash
python day2_gauntlet.py --lane STEEL
```

## 📝 Your .env File

Your `.env` file in the `clean-room` directory should include:

```bash
# Already set up
OPENAI_API_KEY=your_openai_key
BROWSERBASE_API_KEY=your_browserbase_key
BROWSERBASE_PROJECT_ID=your_project_id

# Add these for INDUCED and STEEL
INDUCED_API_KEY=your_induced_key_here
STEEL_API_KEY=your_steel_key_here
```

## 🔍 Current Status

Based on the setup checker, you currently need:

1. **Install packages:**
   - `lavague-core` and `lavague-drivers-selenium` (for LAVAGUE)
   - `steel-sdk` (for STEEL)

2. **Get API keys:**
   - `INDUCED_API_KEY` from [https://app.induced.ai](https://app.induced.ai)
   - `STEEL_API_KEY` from [https://app.steel.dev](https://app.steel.dev)

## 📚 More Details

See `SETUP.md` for detailed documentation on each agent.


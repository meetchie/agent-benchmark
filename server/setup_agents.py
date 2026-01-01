#!/usr/bin/env python3
"""
Setup script to check and install dependencies for BROWSERUSE, STEEL, SKYVERN, and STAGEHAND agents.

This script will:
1. Check which packages are installed
2. Check which environment variables are set
3. Provide installation commands for missing packages
4. Guide you through getting API keys
"""

import os
import sys
import shutil
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    load_dotenv(env_path)
else:
    root_env_path = Path(__file__).parent.parent / '.env'
    if root_env_path.exists():
        load_dotenv(root_env_path)

def check_package(package_name, import_path):
    """Check if a package is installed."""
    try:
        __import__(import_path)
        return True
    except ImportError:
        return False

def check_env_var(var_name):
    """Check if an environment variable is set."""
    return bool(os.getenv(var_name))

def check_node():
    """Check if Node.js is installed."""
    return shutil.which("node") is not None

def check_npm_package(package_name):
    """Check if an npm package is installed locally."""
    node_modules_path = Path(__file__).parent / "node_modules" / package_name
    return node_modules_path.exists()

def main():
    print("=" * 60)
    print("  AGENT SETUP CHECKER")
    print("=" * 60)
    print()
    
    # Check Python packages
    print("📦 PYTHON PACKAGE STATUS")
    print("-" * 60)
    
    packages = {
        "browser-use": ("browser_use", "browser-use"),
        "browserbase": ("browserbase", "browserbase"),
        "steel": ("steel", "steel-sdk"),
        "requests": ("requests", "requests"),
        "aiohttp": ("aiohttp", "aiohttp"),
        "langchain": ("langchain", "langchain"),
        "langchain-openai": ("langchain_openai", "langchain-openai"),
        "playwright": ("playwright", "playwright"),
    }
    
    missing_packages = []
    for name, (import_path, install_name) in packages.items():
        installed = check_package(name, import_path)
        status = "✅" if installed else "❌"
        print(f"{status} {name:20} ({install_name})")
        if not installed:
            missing_packages.append(install_name)
    
    print()
    
    # Check Node.js for Stagehand
    print("🟢 NODE.JS STATUS (for STAGEHAND)")
    print("-" * 60)
    
    node_installed = check_node()
    print(f"{'✅' if node_installed else '❌'} Node.js installed")
    
    if node_installed:
        stagehand_installed = check_npm_package("@browserbasehq")
        print(f"{'✅' if stagehand_installed else '❌'} @browserbasehq/stagehand")
    else:
        stagehand_installed = False
        print("❌ @browserbasehq/stagehand (requires Node.js)")
    
    print()
    
    # Check environment variables
    print("🔑 ENVIRONMENT VARIABLES")
    print("-" * 60)
    
    env_vars = {
        "OPENAI_API_KEY": "Required for all LLM-based agents",
        "BROWSERBASE_API_KEY": "Required for BROWSERUSE and STAGEHAND",
        "BROWSERBASE_PROJECT_ID": "Required for BROWSERUSE and STAGEHAND",
        "STEEL_API_KEY": "Required for STEEL agent",
        "SKYVERN_API_KEY": "Required for SKYVERN agent",
    }
    
    missing_env = []
    for var_name, description in env_vars.items():
        set_var = check_env_var(var_name)
        status = "✅" if set_var else "❌"
        print(f"{status} {var_name:25} - {description}")
        if not set_var:
            missing_env.append(var_name)
    
    print()
    
    # Summary and instructions
    print("=" * 60)
    print("  SETUP INSTRUCTIONS")
    print("=" * 60)
    print()
    
    if missing_packages:
        print("📦 INSTALL MISSING PYTHON PACKAGES:")
        print("-" * 60)
        print("Run these commands in your virtual environment:")
        print()
        for pkg in missing_packages:
            print(f"  pip install {pkg}")
        print()
        print("Or if using uv:")
        print()
        for pkg in missing_packages:
            print(f"  uv pip install {pkg}")
        print()
    
    if not node_installed or not stagehand_installed:
        print("🟢 INSTALL NODE.JS DEPENDENCIES (for STAGEHAND):")
        print("-" * 60)
        if not node_installed:
            print("  1. Install Node.js 18+ from https://nodejs.org/")
        print("  2. In the clean-room directory, run:")
        print("     npm init -y")
        print("     npm install @browserbasehq/stagehand")
        print()
    
    if missing_env:
        print("🔑 SET UP MISSING API KEYS:")
        print("-" * 60)
        print("Add these to your .env file in the clean-room directory:")
        print()
        
        if "OPENAI_API_KEY" in missing_env:
            print("  # Get from: https://platform.openai.com/api-keys")
            print("  OPENAI_API_KEY=your_openai_api_key_here")
            print()
        
        if "BROWSERBASE_API_KEY" in missing_env or "BROWSERBASE_PROJECT_ID" in missing_env:
            print("  # Get from: https://www.browserbase.com")
            print("  BROWSERBASE_API_KEY=your_browserbase_api_key_here")
            print("  BROWSERBASE_PROJECT_ID=your_browserbase_project_id_here")
            print()
        
        if "STEEL_API_KEY" in missing_env:
            print("  # Get from: https://app.steel.dev")
            print("  STEEL_API_KEY=your_steel_api_key_here")
            print()
        
        if "SKYVERN_API_KEY" in missing_env:
            print("  # Get from: https://app.skyvern.com")
            print("  SKYVERN_API_KEY=your_skyvern_api_key_here")
            print()
    
    # Agent-specific requirements
    print("=" * 60)
    print("  AGENT-SPECIFIC REQUIREMENTS")
    print("=" * 60)
    print()
    
    # Map package names to import names for accurate checking
    package_import_map = {
        "browser-use": "browser_use",
        "browserbase": "browserbase",
        "steel-sdk": "steel",
        "playwright": "playwright",
        "langchain-openai": "langchain_openai",
        "aiohttp": "aiohttp",
    }
    
    agents = {
        "BROWSERUSE": {
            "packages": ["browser-use", "browserbase"],
            "env_vars": ["BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID", "OPENAI_API_KEY"],
            "notes": [
                "• Uses browser-use library with Browserbase cloud browsers",
                "• Session replays available at browserbase.com",
                "• Hook-based telemetry with step callbacks"
            ]
        },
        "STEEL": {
            "packages": ["steel-sdk", "playwright", "langchain-openai"],
            "env_vars": ["STEEL_API_KEY", "OPENAI_API_KEY"],
            "notes": [
                "• Uses Steel SDK for cloud browser sessions",
                "• LangChain orchestration with ChatOpenAI",
                "• Install: pip install steel-sdk",
                "• Reference: github.com/steel-dev/steel-browser"
            ]
        },
        "SKYVERN": {
            "packages": ["aiohttp"],
            "env_vars": ["SKYVERN_API_KEY"],
            "notes": [
                "• Cloud-based AI browser automation service",
                "• No local browser needed (fully hosted)",
                "• Polling-based telemetry",
                "• Reference: github.com/skyvern-ai/skyvern"
            ]
        },
        "STAGEHAND": {
            "packages": ["browserbase"],
            "env_vars": ["BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID", "OPENAI_API_KEY"],
            "notes": [
                "• TypeScript/JavaScript library (runs via Node.js subprocess)",
                "• Uses Browserbase for cloud browsers",
                "• Requires: npm install @browserbasehq/stagehand",
                "• Reference: github.com/browserbase/stagehand"
            ]
        }
    }
    
    for agent_name, requirements in agents.items():
        print(f"{agent_name} Agent:")
        print("-" * 60)
        
        # Check if ready using the import map
        packages_ok = all(
            check_package(pkg, package_import_map.get(pkg, pkg.replace("-", "_"))) 
            for pkg in requirements["packages"]
        )
        env_ok = all(check_env_var(var) for var in requirements["env_vars"])
        
        # Special check for Stagehand (needs Node.js)
        if agent_name == "STAGEHAND":
            packages_ok = packages_ok and node_installed and stagehand_installed
        
        if packages_ok and env_ok:
            print("  ✅ Ready to use!")
        else:
            if not packages_ok:
                print(f"  ❌ Missing packages or dependencies")
            if not env_ok:
                missing = [var for var in requirements["env_vars"] if not check_env_var(var)]
                print(f"  ❌ Missing env vars: {', '.join(missing)}")
        
        for note in requirements["notes"]:
            print(f"  {note}")
        print()
    
    # Final summary
    print("=" * 60)
    print("  QUICK START")
    print("=" * 60)
    print()
    print("Once everything is set up, test each agent:")
    print()
    print("  python day2_gauntlet.py --lane BROWSERUSE")
    print("  python day2_gauntlet.py --lane STEEL")
    print("  python day2_gauntlet.py --lane SKYVERN")
    print("  python day2_gauntlet.py --lane STAGEHAND")
    print()
    
    all_ready = (
        not missing_packages and 
        not missing_env and 
        node_installed and 
        stagehand_installed
    )
    
    if all_ready:
        print("🎉 All dependencies are installed and configured!")
        print("   You're ready to run all agents!")
    else:
        print("⚠️  Please install missing packages and set up API keys above.")
    
    print()

if __name__ == "__main__":
    main()

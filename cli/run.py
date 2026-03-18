"""
Rindler Benchmark CLI — Compare BrowserUse vs Rindler on commerce sites.

Usage: python run.py <site> [--model MODEL]
"""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import aiohttp
import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
MAPPINGS_DIR = SCRIPT_DIR / "mappings"
INSTRUCTIONS_DIR = SCRIPT_DIR / "instructions"
RESULTS_DIR = SCRIPT_DIR / "results"

SUPPORTED_MODELS = ["gpt-4o", "gpt-4o-mini", "claude-sonnet"]

COST_RATES = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "claude-sonnet": {"input": 3.00, "output": 15.00},
}

VALID_ACTIONS = {"click", "type", "navigate", "wait", "extract", "select"}

REQUIRED_TASK_FIELDS = {"id", "name", "goal", "start_url", "success_criteria"}

FAILURE_CATEGORIES = [
    "timeout", "wrong_action", "stuck_in_loop", "site_error",
    "auth_failure", "element_not_found", "navigation_failure",
    "max_steps_exceeded", "rate_limited", "unknown",
]

RINDLER_SYSTEM_PROMPT = """You are a commerce automation agent. You interact with shopping sites through Rindler's semantic tools — you do NOT have access to raw HTML, CSS selectors, or page elements.

Every tool response returns structured JSON with:
- "screen": which screen you're on (e.g., "landing", "search_results", "cart")
- "context": persistent state (cart contents, delivery address)
- "data": screen-specific information (product lists, cart items, etc.)
- "available_actions": actions valid on the current screen
- "global_actions": actions always available

RULES:
- Call start_session(url) first to begin. It returns a session_id you must pass to all subsequent calls.
- Only call actions listed in available_actions or global_actions.
- Item IDs for add_to_cart, view_product, etc. come from the data field.
- Do NOT try to construct URLs, CSS selectors, or reference page elements.

When you have completed the goal (or determined it cannot be completed),
call the "done" tool with {success: true/false, message: "explanation"}."""

DONE_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "success": {"type": "boolean", "description": "Whether the goal was accomplished"},
        "message": {"type": "string", "description": "Brief summary of what was accomplished or why it failed"},
    },
    "required": ["success", "message"],
}

MAX_RESULT_CHARS = 12000

# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def compute_cost(model: str, tokens_input: int, tokens_output: int) -> float:
    """Compute cost in USD for a given model and token counts."""
    rates = COST_RATES.get(model, COST_RATES["gpt-4o"])
    return (tokens_input / 1_000_000) * rates["input"] + (tokens_output / 1_000_000) * rates["output"]


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get_llm_for_browseruse(model: str):
    """Create a LangChain chat model for browser-use based on the model flag."""
    if model.startswith("gpt"):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model)
    elif model.startswith("claude"):
        from langchain_anthropic import ChatAnthropic
        model_map = {"claude-sonnet": "claude-sonnet-4-6"}
        return ChatAnthropic(model=model_map.get(model, model))
    else:
        raise ValueError(f"Unsupported model: {model}")


# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(
        description="Benchmark a commerce site: BrowserUse vs Rindler"
    )
    parser.add_argument("site", help="Site name (must match files in mappings/ and instructions/)")
    parser.add_argument(
        "--model", default="gpt-4o",
        choices=SUPPORTED_MODELS,
        help="LLM model for both agents (default: gpt-4o)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Validation functions
# ---------------------------------------------------------------------------


def validate_mapping(site: str) -> dict:
    """Load and validate the site mapping JSON."""
    path = MAPPINGS_DIR / f"{site}.json"
    if not path.exists():
        print(f"Error: Mapping file not found: {path}")
        print(f"Create {path} with the site's SiteConfig JSON.")
        sys.exit(1)

    with open(path) as f:
        try:
            mapping = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in {path}: {e}")
            sys.exit(1)

    # Validate required top-level fields
    for field in ("site_id", "domain", "screens", "actions"):
        if field not in mapping:
            print(f"Error: Mapping {path} missing required field: {field}")
            sys.exit(1)

    # Validate screens
    if not isinstance(mapping["screens"], dict) or not mapping["screens"]:
        print(f"Error: Mapping {path} must have at least one screen defined.")
        sys.exit(1)

    for screen_name, screen in mapping["screens"].items():
        if "url_pattern" not in screen:
            print(f"Error: Screen '{screen_name}' missing 'url_pattern'.")
            sys.exit(1)
        # Validate extraction.fields FieldSpec polymorphism
        extraction = screen.get("extraction", {})
        fields = extraction.get("fields", {})
        for field_name, field_val in fields.items():
            if isinstance(field_val, str):
                pass  # String shorthand is valid
            elif isinstance(field_val, dict) and "selector" in field_val:
                pass  # Full object form is valid
            else:
                print(f"Error: Screen '{screen_name}' field '{field_name}' must be a string selector or {{\"selector\": \"...\", \"invert\": bool}}.")
                sys.exit(1)

    # Validate actions
    if not isinstance(mapping["actions"], dict):
        print(f"Error: Mapping {path} 'actions' must be an object.")
        sys.exit(1)

    for action_name, action in mapping["actions"].items():
        if "steps" not in action or not isinstance(action["steps"], list):
            print(f"Error: Action '{action_name}' must have a 'steps' array.")
            sys.exit(1)
        for i, step in enumerate(action["steps"]):
            if "action" not in step:
                print(f"Error: Action '{action_name}' step {i} missing 'action' field.")
                sys.exit(1)
            if step["action"] not in VALID_ACTIONS:
                print(f"Error: Action '{action_name}' step {i} uses invalid action '{step['action']}'. Valid: {', '.join(sorted(VALID_ACTIONS))}")
                sys.exit(1)

    print(f"  Mapping validated: {len(mapping['screens'])} screens, {len(mapping['actions'])} actions")
    return mapping


def validate_instructions(site: str) -> dict:
    """Load and validate the site instructions YAML."""
    path = INSTRUCTIONS_DIR / f"{site}.yaml"
    if not path.exists():
        print(f"Error: Instructions file not found: {path}")
        print(f"Create {path} with the site's task instructions.")
        sys.exit(1)

    with open(path) as f:
        try:
            instructions = yaml.safe_load(f)
        except yaml.YAMLError as e:
            print(f"Error: Invalid YAML in {path}: {e}")
            sys.exit(1)

    if "tasks" not in instructions or not isinstance(instructions["tasks"], list):
        print(f"Error: Instructions {path} must have a 'tasks' array.")
        sys.exit(1)

    if not instructions["tasks"]:
        print(f"Error: Instructions {path} has no tasks defined.")
        sys.exit(1)

    for i, task in enumerate(instructions["tasks"]):
        missing = REQUIRED_TASK_FIELDS - set(task.keys())
        if missing:
            print(f"Error: Task {i} missing required fields: {', '.join(missing)}")
            sys.exit(1)
        # Set default max_steps
        if "max_steps" not in task:
            task["max_steps"] = 25

    print(f"  Instructions validated: {len(instructions['tasks'])} tasks")
    return instructions


def validate_api_keys(model: str):
    """Check that required API keys are set."""
    if model.startswith("gpt"):
        if not os.environ.get("OPENAI_API_KEY"):
            print("Error: OPENAI_API_KEY environment variable is required for gpt-* models.")
            sys.exit(1)
    elif model.startswith("claude"):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("Error: ANTHROPIC_API_KEY environment variable is required for claude-* models.")
            sys.exit(1)
    # Always need OPENAI_API_KEY for the judge (gpt-4o-mini)
    if not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY is required for the GPT-4o-mini judge, even when using claude-* models.")
        sys.exit(1)


def create_results_dir(site: str) -> Path:
    """Create a unique results directory for this benchmark run."""
    today = date.today().isoformat()
    base = RESULTS_DIR / f"{site}-{today}"
    results_path = base

    counter = 2
    while results_path.exists():
        results_path = RESULTS_DIR / f"{site}-{today}-{counter}"
        counter += 1

    results_path.mkdir(parents=True)
    (results_path / "browseruse" / "screenshots").mkdir(parents=True)
    (results_path / "rindler" / "screenshots").mkdir(parents=True)
    (results_path / "charts").mkdir(parents=True)

    print(f"  Results directory: {results_path}")
    return results_path


# ---------------------------------------------------------------------------
# LLMClient class
# ---------------------------------------------------------------------------


class LLMClient:
    """Provider-agnostic wrapper for LLM tool-calling APIs."""

    def __init__(self, model_name: str, system_prompt: str):
        self.model = model_name
        self.system_prompt = system_prompt

        if model_name.startswith("gpt"):
            self.provider = "openai"
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI()
        elif model_name.startswith("claude"):
            self.provider = "anthropic"
            from anthropic import AsyncAnthropic
            model_map = {"claude-sonnet": "claude-sonnet-4-6"}
            self.model = model_map.get(model_name, model_name)
            self._client = AsyncAnthropic()
        else:
            raise ValueError(f"Unknown model: {model_name}")

    async def call(self, messages: list, tools: list) -> dict:
        """Returns dict with keys: tool_name, tool_args, tool_call_id, text, tokens_input, tokens_output."""
        if self.provider == "openai":
            return await self._call_openai(messages, tools)
        else:
            return await self._call_anthropic(messages, tools)

    async def _call_openai(self, messages, tools):
        kwargs = {
            "model": self.model,
            "messages": [{"role": "system", "content": self.system_prompt}] + messages,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["parallel_tool_calls"] = False

        response = await self._client.chat.completions.create(**kwargs)
        msg = response.choices[0].message
        usage = response.usage

        if msg.tool_calls:
            tc = msg.tool_calls[0]
            return {
                "tool_name": tc.function.name,
                "tool_args": json.loads(tc.function.arguments),
                "tool_call_id": tc.id,
                "text": None,
                "tokens_input": usage.prompt_tokens,
                "tokens_output": usage.completion_tokens,
            }
        return {
            "tool_name": None, "tool_args": None, "tool_call_id": None,
            "text": msg.content,
            "tokens_input": usage.prompt_tokens,
            "tokens_output": usage.completion_tokens,
        }

    async def _call_anthropic(self, messages, tools):
        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "system": self.system_prompt,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = await self._client.messages.create(**kwargs)
        usage = response.usage

        for block in response.content:
            if block.type == "tool_use":
                return {
                    "tool_name": block.name,
                    "tool_args": block.input,
                    "tool_call_id": block.id,
                    "text": None,
                    "tokens_input": usage.input_tokens,
                    "tokens_output": usage.output_tokens,
                }

        text_parts = [b.text for b in response.content if b.type == "text"]
        return {
            "tool_name": None, "tool_args": None, "tool_call_id": None,
            "text": "\n".join(text_parts) if text_parts else None,
            "tokens_input": usage.input_tokens,
            "tokens_output": usage.output_tokens,
        }


# ---------------------------------------------------------------------------
# MCP tool bridge functions
# ---------------------------------------------------------------------------


def mcp_tools_to_llm_tools(mcp_tools: list, provider: str) -> list:
    """Convert MCP Tool objects to LLM provider format."""
    result = []
    for tool in mcp_tools:
        if provider == "openai":
            result.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema,
                },
            })
        else:
            result.append({
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            })
    return result


def inject_done_tool(tools: list, provider: str) -> list:
    """Append the synthetic 'done' tool to the tool list."""
    done_desc = (
        "Call this ONLY when you have fully completed every part of the goal. "
        "Do NOT call this if there are remaining items to add, quantities to update, "
        "or steps you haven't tried yet."
    )
    if provider == "openai":
        return tools + [{"type": "function", "function": {"name": "done", "description": done_desc, "parameters": DONE_TOOL_SCHEMA}}]
    else:
        return tools + [{"name": "done", "description": done_desc, "input_schema": DONE_TOOL_SCHEMA}]


def parse_tool_result(result) -> dict:
    """Extract JSON dict from MCP CallToolResult."""
    if getattr(result, "isError", False):
        text = result.content[0].text if result.content else "unknown error"
        return {"error": text}
    if not result.content:
        return {"error": "empty response"}
    text = result.content[0].text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": "non-JSON response", "raw": text[:500]}


# ---------------------------------------------------------------------------
# OAuth authentication
# ---------------------------------------------------------------------------


async def oauth_authenticate(server_url: str) -> str:
    """Run full OAuth 2.1 PKCE flow against the MCP server. Returns access token."""
    callback_port = find_free_port()

    async with aiohttp.ClientSession() as http:
        # Discover
        async with http.get(f"{server_url}/.well-known/oauth-protected-resource") as resp:
            if resp.status != 200:
                raise RuntimeError(f"OAuth discovery failed ({resp.status}). Is the server running at {server_url}?")
            resource_meta = await resp.json()

        as_url = resource_meta["authorization_servers"][0]
        async with http.get(f"{as_url}/.well-known/oauth-authorization-server") as resp:
            if resp.status != 200:
                raise RuntimeError(f"OAuth AS metadata fetch failed ({resp.status})")
            metadata = await resp.json()

        # Register
        async with http.post(metadata["registration_endpoint"], json={
            "client_name": "benchmark-rindler-agent",
            "redirect_uris": [f"http://127.0.0.1:{callback_port}/callback"],
            "grant_types": ["authorization_code"],
        }) as resp:
            data = await resp.json()
            if resp.status != 201:
                raise RuntimeError(f"Client registration failed ({resp.status}): {data}")
            client_id = data["client_id"]

        # Authorize with PKCE
        code_verifier = secrets.token_urlsafe(32)
        challenge_bytes = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(challenge_bytes).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)

        async with http.get(metadata["authorization_endpoint"], params={
            "client_id": client_id,
            "redirect_uri": f"http://127.0.0.1:{callback_port}/callback",
            "response_type": "code",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }, allow_redirects=False) as resp:
            if resp.status != 302:
                raise RuntimeError(f"Expected 302 from authorize, got {resp.status}")
            location = resp.headers.get("Location", "")
            parsed = urlparse(location)
            query = parse_qs(parsed.query)
            if query.get("state", [None])[0] != state:
                raise RuntimeError("OAuth state mismatch")
            auth_code = query["code"][0]

        # Exchange
        async with http.post(metadata["token_endpoint"], data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "code_verifier": code_verifier,
            "client_id": client_id,
        }) as resp:
            data = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f"Token exchange failed ({resp.status}): {data}")
            return data["access_token"]


# ---------------------------------------------------------------------------
# MCP server lifecycle
# ---------------------------------------------------------------------------


def start_mcp_server() -> subprocess.Popen:
    """Start the Go MCP server as a subprocess."""
    server_dir = SCRIPT_DIR.parent / "packages" / "mcp-server"
    if not (server_dir / "main.go").exists():
        print(f"Error: MCP server not found at {server_dir}")
        sys.exit(1)

    print(f"  Starting MCP server from {server_dir}...")
    proc = subprocess.Popen(
        ["go", "run", "main.go"],
        cwd=str(server_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc


def stop_mcp_server(proc: subprocess.Popen):
    """Stop the MCP server subprocess."""
    print("  Stopping MCP server...")
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    print("  MCP server stopped.")


async def wait_for_server(url: str, timeout: int = 30):
    """Poll the health endpoint until the server is ready."""
    print(f"  Waiting for MCP server at {url}...")
    start = time.monotonic()
    async with aiohttp.ClientSession() as session:
        while time.monotonic() - start < timeout:
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        print("  MCP server is ready.")
                        return
            except (aiohttp.ClientError, ConnectionError):
                pass
            await asyncio.sleep(1)
    raise RuntimeError(f"MCP server did not become ready within {timeout}s")


# ---------------------------------------------------------------------------
# BrowserUse runner
# ---------------------------------------------------------------------------


async def run_browseruse_task(task: dict, model: str, results_dir: Path, site: str) -> dict:
    """Run a single task through BrowserUse with local Playwright."""
    from browser_use import Agent

    task_id = task["id"]
    print(f"  Task: {task['name']} ({task_id})")
    print(f"  Goal: {task['goal'][:80]}...")

    llm = get_llm_for_browseruse(model)
    steps_log = []
    failure_screenshots = []
    current_step = {"index": 0}

    started_at = datetime.utcnow()

    async def on_step_start(agent):
        current_step["index"] += 1
        current_step["started_at"] = time.monotonic()
        current_step["start_ts"] = datetime.utcnow().isoformat() + "Z"

    async def on_step_end(agent):
        elapsed_ms = (time.monotonic() - current_step["started_at"]) * 1000
        step_num = current_step["index"]

        # Extract action info from history
        action_type = None
        action_args = {}
        observation = None
        try:
            if hasattr(agent.history, "model_actions") and agent.history.model_actions():
                latest = agent.history.model_actions()[-1]
                if isinstance(latest, dict):
                    action_type = list(latest.keys())[0] if latest else None
                    action_args = latest
            if hasattr(agent.history, "extracted_content"):
                extracted = agent.history.extracted_content()
                if extracted:
                    observation = extracted[-1] if isinstance(extracted, list) else str(extracted)
        except Exception:
            pass

        step_entry = {
            "step": step_num,
            "action": action_type,
            "action_args": action_args,
            "started_at": current_step["start_ts"],
            "duration_ms": round(elapsed_ms, 2),
            "tokens_input": 0,
            "tokens_output": 0,
            "cost_usd": 0.0,
            "observation": observation,
            "screenshot_path": None,
            "error": None,
        }
        steps_log.append(step_entry)
        print(f"    Step {step_num}: {action_type or 'N/A'} ({elapsed_ms:.0f}ms)")

    # Run the agent
    agent = Agent(task=task["goal"], llm=llm, max_steps=task["max_steps"], initial_actions=[{"open_url": task["start_url"]}])
    success = False
    error_msg = None

    try:
        history = await agent.run(
            on_step_start=on_step_start,
            on_step_end=on_step_end,
        )
        success = True

        # Extract token usage from history
        total_input = 0
        total_output = 0
        try:
            if history and hasattr(history, "usage") and history.usage:
                total_input = getattr(history.usage, "total_prompt_tokens", 0) or 0
                total_output = getattr(history.usage, "total_completion_tokens", 0) or 0
        except Exception:
            pass

        # Distribute tokens across steps
        if steps_log and (total_input or total_output):
            per_step_in = total_input // len(steps_log)
            per_step_out = total_output // len(steps_log)
            remainder_in = total_input % len(steps_log)
            remainder_out = total_output % len(steps_log)
            for i, s in enumerate(steps_log):
                s["tokens_input"] = per_step_in + (remainder_in if i == 0 else 0)
                s["tokens_output"] = per_step_out + (remainder_out if i == 0 else 0)
                s["cost_usd"] = compute_cost(model, s["tokens_input"], s["tokens_output"])

    except Exception as e:
        error_msg = str(e)
        print(f"    Error: {error_msg}")

        # Try to capture screenshot on failure
        try:
            if hasattr(agent, "browser") and agent.browser:
                contexts = agent.browser.contexts
                if contexts and contexts[0].pages:
                    page = contexts[0].pages[0]
                    screenshot_name = f"task-{task_id}-failure-step-{current_step['index']}.png"
                    screenshot_path = results_dir / "browseruse" / "screenshots" / screenshot_name
                    await page.screenshot(path=str(screenshot_path))
                    failure_screenshots.append(f"screenshots/{screenshot_name}")
                    if steps_log:
                        steps_log[-1]["screenshot_path"] = f"screenshots/{screenshot_name}"
                        steps_log[-1]["error"] = error_msg
        except Exception:
            pass

    finished_at = datetime.utcnow()
    duration_ms = (finished_at - started_at).total_seconds() * 1000

    total_tokens_in = sum(s["tokens_input"] for s in steps_log)
    total_tokens_out = sum(s["tokens_output"] for s in steps_log)
    total_cost = sum(s["cost_usd"] for s in steps_log)

    result = {
        "meta": {
            "task_id": task_id,
            "task_name": task["name"],
            "agent": "browseruse",
            "model": model,
            "site": site,
            "start_url": task["start_url"],
            "goal": task["goal"],
            "success_criteria": task["success_criteria"],
            "started_at": started_at.isoformat() + "Z",
            "finished_at": finished_at.isoformat() + "Z",
            "duration_ms": round(duration_ms, 2),
        },
        "result": {
            "success": success and error_msg is None,
            "verdict": None,  # Set by judge later
            "judge_reasoning": None,
            "failure_category": None,
        },
        "stats": {
            "total_steps": len(steps_log),
            "total_tokens_input": total_tokens_in,
            "total_tokens_output": total_tokens_out,
            "total_cost_usd": round(total_cost, 6),
            "avg_step_duration_ms": round(duration_ms / len(steps_log), 2) if steps_log else 0,
        },
        "steps": steps_log,
        "failure_screenshots": failure_screenshots,
    }

    # Save per-task log
    log_path = results_dir / "browseruse" / f"task-{task_id}.json"
    with open(log_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"    Saved: {log_path.name}")

    return result


# ---------------------------------------------------------------------------
# Rindler runner
# ---------------------------------------------------------------------------


async def run_rindler_task(task: dict, model: str, results_dir: Path, server_url: str, access_token: str, site: str) -> dict:
    """Run a single task through the Rindler MCP agent."""
    from mcp.client.sse import sse_client
    from mcp import ClientSession

    task_id = task["id"]
    print(f"  Task: {task['name']} ({task_id})")

    llm = LLMClient(model, RINDLER_SYSTEM_PROMPT)
    steps_log = []
    failure_screenshots = []
    started_at = datetime.utcnow()
    session_id = None
    cumulative_cost = 0.0

    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        async with sse_client(server_url + "/mcp/", headers=headers) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                mcp_tools = (await client.list_tools()).tools
                llm_tools = mcp_tools_to_llm_tools(mcp_tools, llm.provider)
                llm_tools = inject_done_tool(llm_tools, llm.provider)

                # Start session
                t0 = time.monotonic()
                raw_result = await client.call_tool("start_session", {"url": task["start_url"]})
                start_elapsed = time.monotonic() - t0
                parsed = parse_tool_result(raw_result)
                session_id = parsed.get("data", {}).get("session_id", "")

                # Build initial message
                content = (
                    f"Goal: {task['goal']}\n\n"
                    f"Session started. session_id: {session_id}\n"
                    f"Screen: {parsed.get('screen', 'unknown')}\n"
                    f"Available actions: {', '.join(parsed.get('available_actions', []))}\n"
                    f"Global actions: {', '.join(parsed.get('global_actions', []))}"
                )
                messages = [{"role": "user", "content": content}]

                # Record start_session step
                steps_log.append({
                    "step": 0,
                    "action": "start_session",
                    "action_args": {"url": task["start_url"]},
                    "started_at": started_at.isoformat() + "Z",
                    "duration_ms": round(start_elapsed * 1000, 2),
                    "tokens_input": 0, "tokens_output": 0, "cost_usd": 0.0,
                    "observation": f"screen={parsed.get('screen', 'unknown')}",
                    "screenshot_path": None, "error": parsed.get("error"),
                    "mcp_tool": "start_session",
                    "mcp_response_screen": parsed.get("screen"),
                    "mcp_available_actions": parsed.get("available_actions", []),
                    "mcp_response_size_bytes": len(json.dumps(parsed)),
                })

                max_steps = task["max_steps"]
                for step in range(max_steps):
                    step_num = step + 1
                    step_start = time.monotonic()
                    step_ts = datetime.utcnow().isoformat() + "Z"

                    llm_resp = await llm.call(messages, llm_tools)
                    cost = compute_cost(model, llm_resp["tokens_input"], llm_resp["tokens_output"])
                    cumulative_cost += cost

                    if llm_resp["tool_name"] == "done":
                        done_args = llm_resp["tool_args"] or {}
                        step_elapsed = (time.monotonic() - step_start) * 1000
                        steps_log.append({
                            "step": step_num, "action": "done", "action_args": done_args,
                            "started_at": step_ts, "duration_ms": round(step_elapsed, 2),
                            "tokens_input": llm_resp["tokens_input"],
                            "tokens_output": llm_resp["tokens_output"],
                            "cost_usd": round(cost, 6),
                            "observation": done_args.get("message", ""),
                            "screenshot_path": None, "error": None,
                            "mcp_tool": "done", "mcp_response_screen": None,
                            "mcp_available_actions": [], "mcp_response_size_bytes": 0,
                        })
                        icon = "pass" if done_args.get("success") else "fail"
                        print(f"    Step {step_num}: done ({icon}) — {done_args.get('message', '')[:60]}")
                        break

                    if llm_resp["tool_name"]:
                        tool_args = llm_resp["tool_args"] or {}
                        if session_id and "session_id" not in tool_args and llm_resp["tool_name"] != "start_session":
                            tool_args["session_id"] = session_id

                        t0 = time.monotonic()
                        raw_result = await client.call_tool(llm_resp["tool_name"], tool_args)
                        tool_elapsed = time.monotonic() - t0
                        parsed = parse_tool_result(raw_result)
                        step_elapsed = (time.monotonic() - step_start) * 1000

                        steps_log.append({
                            "step": step_num,
                            "action": llm_resp["tool_name"],
                            "action_args": {k: v for k, v in tool_args.items() if k != "session_id"},
                            "started_at": step_ts,
                            "duration_ms": round(step_elapsed, 2),
                            "tokens_input": llm_resp["tokens_input"],
                            "tokens_output": llm_resp["tokens_output"],
                            "cost_usd": round(cost, 6),
                            "observation": parsed.get("screen", str(parsed)[:200]),
                            "screenshot_path": None,
                            "error": parsed.get("error"),
                            "mcp_tool": llm_resp["tool_name"],
                            "mcp_response_screen": parsed.get("screen"),
                            "mcp_available_actions": parsed.get("available_actions", []),
                            "mcp_response_size_bytes": len(json.dumps(parsed, default=str)),
                        })

                        print(f"    Step {step_num}: {llm_resp['tool_name']} → {parsed.get('screen', '?')} ({step_elapsed:.0f}ms, ${cost:.4f})")

                        # Append tool exchange to messages
                        result_text = truncate(json.dumps(parsed, default=str), MAX_RESULT_CHARS)
                        if llm.provider == "openai":
                            messages.append({
                                "role": "assistant",
                                "tool_calls": [{"id": llm_resp["tool_call_id"], "type": "function",
                                    "function": {"name": llm_resp["tool_name"], "arguments": json.dumps(llm_resp["tool_args"])}}],
                            })
                            messages.append({"role": "tool", "tool_call_id": llm_resp["tool_call_id"], "content": result_text})
                        else:
                            messages.append({
                                "role": "assistant",
                                "content": [{"type": "tool_use", "id": llm_resp["tool_call_id"],
                                    "name": llm_resp["tool_name"], "input": llm_resp["tool_args"]}],
                            })
                            messages.append({
                                "role": "user",
                                "content": [{"type": "tool_result", "tool_use_id": llm_resp["tool_call_id"], "content": result_text}],
                            })
                    else:
                        # LLM returned text instead of tool call
                        step_elapsed = (time.monotonic() - step_start) * 1000
                        steps_log.append({
                            "step": step_num, "action": "thinking", "action_args": {},
                            "started_at": step_ts, "duration_ms": round(step_elapsed, 2),
                            "tokens_input": llm_resp["tokens_input"],
                            "tokens_output": llm_resp["tokens_output"],
                            "cost_usd": round(cost, 6),
                            "observation": (llm_resp["text"] or "")[:200],
                            "screenshot_path": None, "error": None,
                            "mcp_tool": None, "mcp_response_screen": None,
                            "mcp_available_actions": [], "mcp_response_size_bytes": 0,
                        })
                        messages.append({"role": "assistant", "content": llm_resp["text"]})
                        print(f"    Step {step_num}: [thinking] ({step_elapsed:.0f}ms)")

    except Exception as e:
        print(f"    Error: {e}")

    finished_at = datetime.utcnow()
    duration_ms = (finished_at - started_at).total_seconds() * 1000

    total_tokens_in = sum(s["tokens_input"] for s in steps_log)
    total_tokens_out = sum(s["tokens_output"] for s in steps_log)

    # Determine success from the last step
    agent_success = False
    if steps_log and steps_log[-1]["action"] == "done":
        agent_success = steps_log[-1]["action_args"].get("success", False)

    result = {
        "meta": {
            "task_id": task_id, "task_name": task["name"], "agent": "rindler",
            "model": model, "site": site,
            "start_url": task["start_url"], "goal": task["goal"],
            "success_criteria": task["success_criteria"],
            "started_at": started_at.isoformat() + "Z",
            "finished_at": finished_at.isoformat() + "Z",
            "duration_ms": round(duration_ms, 2),
        },
        "result": {
            "success": agent_success, "verdict": None,
            "judge_reasoning": None, "failure_category": None,
        },
        "stats": {
            "total_steps": len(steps_log),
            "total_tokens_input": total_tokens_in,
            "total_tokens_output": total_tokens_out,
            "total_cost_usd": round(cumulative_cost, 6),
            "avg_step_duration_ms": round(duration_ms / len(steps_log), 2) if steps_log else 0,
        },
        "steps": steps_log,
        "failure_screenshots": failure_screenshots,
    }

    log_path = results_dir / "rindler" / f"task-{task_id}.json"
    with open(log_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"    Saved: {log_path.name} (${cumulative_cost:.4f})")

    return result


async def run_rindler_phase(tasks: list, model: str, results_dir: Path, site: str) -> list:
    """Run all tasks through Rindler: start server, authenticate, run tasks, stop server."""
    server_url = "http://localhost:8080"

    proc = start_mcp_server()
    try:
        await wait_for_server(f"{server_url}/proxy/health")
        access_token = await oauth_authenticate(server_url)
        print(f"  Authenticated successfully.\n")

        results = []
        for task in tasks:
            result = await run_rindler_task(task, model, results_dir, server_url, access_token, site)
            results.append(result)
        return results
    finally:
        stop_mcp_server(proc)


# ---------------------------------------------------------------------------
# Judge
# ---------------------------------------------------------------------------


async def judge_task(task: dict, browseruse_result: dict, rindler_result: dict) -> tuple:
    """Use GPT-4o-mini to judge both agents' results. Returns updated (browseruse_result, rindler_result)."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI()

    for agent_name, result in [("browseruse", browseruse_result), ("rindler", rindler_result)]:
        # Build action trace summary for the judge
        trace_lines = []
        for s in result["steps"]:
            error_str = f" [ERROR: {s['error']}]" if s.get("error") else ""
            trace_lines.append(
                f"Step {s['step']}: {s['action']}({json.dumps(s.get('action_args', {}), default=str)[:100]}) "
                f"→ {s.get('observation', 'N/A')[:100]}{error_str}"
            )
        trace = "\n".join(trace_lines)

        prompt = f"""You are evaluating whether an AI agent successfully completed a task.

Task: {task['goal']}
Success Criteria: {task['success_criteria']}
Agent: {agent_name}
Agent reported success: {result['result']['success']}
Total steps: {result['stats']['total_steps']}

Action trace:
{trace}

Evaluate whether the agent met the success criteria. Respond with JSON only:
{{
  "verdict": "pass" or "fail",
  "reasoning": "brief explanation",
  "failure_category": null if pass, or one of: {json.dumps(FAILURE_CATEGORIES)}
}}"""

        for attempt in range(3):
            try:
                response = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                )
                judge_result = json.loads(response.choices[0].message.content)
                result["result"]["verdict"] = judge_result.get("verdict", "error")
                result["result"]["judge_reasoning"] = judge_result.get("reasoning", "")
                result["result"]["failure_category"] = judge_result.get("failure_category")
                print(f"  {agent_name}/{task['id']}: {judge_result['verdict']} — {judge_result.get('reasoning', '')[:60]}")
                break
            except Exception as e:
                if attempt == 2:
                    result["result"]["verdict"] = "error"
                    result["result"]["judge_reasoning"] = f"Judge failed after 3 attempts: {e}"
                    result["result"]["failure_category"] = "unknown"
                    print(f"  {agent_name}/{task['id']}: judge error — {e}")
                else:
                    await asyncio.sleep(2 ** attempt)

    return browseruse_result, rindler_result


# ---------------------------------------------------------------------------
# Summary generator
# ---------------------------------------------------------------------------


def generate_summary(site: str, domain: str, model: str, tasks: list,
                     browseruse_results: list, rindler_results: list, results_dir: Path):
    """Generate summary.json with aggregate statistics and comparisons."""

    def agent_stats(results: list) -> dict:
        passes = sum(1 for r in results if r["result"].get("verdict") == "pass")
        fails = len(results) - passes
        total_steps = sum(r["stats"]["total_steps"] for r in results)
        total_dur = sum(r["meta"]["duration_ms"] for r in results)
        total_cost = sum(r["stats"]["total_cost_usd"] for r in results)
        total_in = sum(r["stats"]["total_tokens_input"] for r in results)
        total_out = sum(r["stats"]["total_tokens_output"] for r in results)
        n = len(results)

        # Count failure categories
        fail_cats = {}
        for r in results:
            cat = r["result"].get("failure_category")
            if cat:
                fail_cats[cat] = fail_cats.get(cat, 0) + 1

        return {
            "pass": passes,
            "fail": fails,
            "success_rate": round(passes / n, 4) if n else 0,
            "total_steps": total_steps,
            "avg_steps_per_task": round(total_steps / n, 2) if n else 0,
            "total_duration_ms": round(total_dur, 2),
            "avg_duration_ms": round(total_dur / n, 2) if n else 0,
            "total_cost_usd": round(total_cost, 6),
            "avg_cost_per_task_usd": round(total_cost / n, 6) if n else 0,
            "total_tokens_input": total_in,
            "total_tokens_output": total_out,
            "failure_categories": fail_cats,
        }

    bu_stats = agent_stats(browseruse_results)
    ri_stats = agent_stats(rindler_results)

    # Per-task comparison
    per_task = []
    winner_by_task = {}
    for i, task in enumerate(tasks):
        bu = browseruse_results[i]
        ri = rindler_results[i]
        bu_v = bu["result"].get("verdict", "error")
        ri_v = ri["result"].get("verdict", "error")

        # Determine winner: pass > fail, then fewer steps, then lower cost
        if bu_v == "pass" and ri_v != "pass":
            winner = "browseruse"
        elif ri_v == "pass" and bu_v != "pass":
            winner = "rindler"
        elif bu["stats"]["total_steps"] != ri["stats"]["total_steps"]:
            winner = "browseruse" if bu["stats"]["total_steps"] < ri["stats"]["total_steps"] else "rindler"
        elif bu["stats"]["total_cost_usd"] != ri["stats"]["total_cost_usd"]:
            winner = "browseruse" if bu["stats"]["total_cost_usd"] < ri["stats"]["total_cost_usd"] else "rindler"
        else:
            winner = "tie"

        per_task.append({
            "task_id": task["id"],
            "browseruse": {
                "verdict": bu_v,
                "steps": bu["stats"]["total_steps"],
                "duration_ms": bu["meta"]["duration_ms"],
                "cost_usd": bu["stats"]["total_cost_usd"],
            },
            "rindler": {
                "verdict": ri_v,
                "steps": ri["stats"]["total_steps"],
                "duration_ms": ri["meta"]["duration_ms"],
                "cost_usd": ri["stats"]["total_cost_usd"],
            },
            "winner": winner,
        })
        winner_by_task[task["id"]] = winner

    # Comparison deltas (positive = Rindler better)
    comparison = {
        "success_rate_delta": round(ri_stats["success_rate"] - bu_stats["success_rate"], 4),
        "winner_by_task": winner_by_task,
    }
    if bu_stats["avg_steps_per_task"] > 0:
        comparison["avg_steps_reduction"] = round(
            1 - ri_stats["avg_steps_per_task"] / bu_stats["avg_steps_per_task"], 4
        )
    if bu_stats["avg_duration_ms"] > 0:
        comparison["avg_duration_reduction"] = round(
            1 - ri_stats["avg_duration_ms"] / bu_stats["avg_duration_ms"], 4
        )
    if bu_stats["avg_cost_per_task_usd"] > 0:
        comparison["avg_cost_reduction"] = round(
            1 - ri_stats["avg_cost_per_task_usd"] / bu_stats["avg_cost_per_task_usd"], 4
        )

    summary = {
        "benchmark": {
            "site": site,
            "domain": domain,
            "date": date.today().isoformat(),
            "model": model,
            "total_tasks": len(tasks),
        },
        "browseruse": bu_stats,
        "rindler": ri_stats,
        "comparison": comparison,
        "per_task": per_task,
    }

    summary_path = results_dir / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    # Print summary table
    print(f"\n{'=' * 60}")
    print(f"  SUMMARY")
    print(f"{'=' * 60}")
    print(f"  {'Metric':<25} {'BrowserUse':>12} {'Rindler':>12}")
    print(f"  {'-' * 49}")
    print(f"  {'Success Rate':<25} {bu_stats['success_rate']:>11.0%} {ri_stats['success_rate']:>11.0%}")
    print(f"  {'Avg Steps':<25} {bu_stats['avg_steps_per_task']:>12.1f} {ri_stats['avg_steps_per_task']:>12.1f}")
    print(f"  {'Avg Duration (s)':<25} {bu_stats['avg_duration_ms']/1000:>12.1f} {ri_stats['avg_duration_ms']/1000:>12.1f}")
    print(f"  {'Avg Cost ($)':<25} {bu_stats['avg_cost_per_task_usd']:>12.4f} {ri_stats['avg_cost_per_task_usd']:>12.4f}")
    print(f"  {'Total Cost ($)':<25} {bu_stats['total_cost_usd']:>12.4f} {ri_stats['total_cost_usd']:>12.4f}")
    print(f"{'=' * 60}")
    print(f"  Saved: {summary_path}")


# ---------------------------------------------------------------------------
# main() and entry point
# ---------------------------------------------------------------------------


async def main():
    args = parse_args()

    print(f"\n{'=' * 60}")
    print(f"  RINDLER BENCHMARK — {args.site}")
    print(f"{'=' * 60}")
    print(f"  Model: {args.model}")
    print(f"  Date:  {date.today().isoformat()}")
    print(f"{'=' * 60}\n")

    # Phase 0: Validate
    print("Validating inputs...")
    mapping = validate_mapping(args.site)
    instructions = validate_instructions(args.site)
    validate_api_keys(args.model)

    results_dir = create_results_dir(args.site)
    tasks = instructions["tasks"]

    print(f"\nReady to benchmark {len(tasks)} tasks.\n")

    # Phase 1: BrowserUse
    print(f"{'=' * 60}")
    print(f"  PHASE 1: BROWSERUSE")
    print(f"{'=' * 60}\n")
    browseruse_results = []
    for task in tasks:
        result = await run_browseruse_task(task, args.model, results_dir, args.site)
        browseruse_results.append(result)

    # Phase 2: Rindler
    print(f"\n{'=' * 60}")
    print(f"  PHASE 2: RINDLER")
    print(f"{'=' * 60}\n")
    rindler_results = await run_rindler_phase(tasks, args.model, results_dir, args.site)

    # Phase 3: Judge
    print(f"\n{'=' * 60}")
    print(f"  PHASE 3: JUDGE")
    print(f"{'=' * 60}\n")
    for i, task in enumerate(tasks):
        browseruse_results[i], rindler_results[i] = await judge_task(
            task, browseruse_results[i], rindler_results[i]
        )
        # Re-save with judge verdicts
        for agent_name, result in [("browseruse", browseruse_results[i]), ("rindler", rindler_results[i])]:
            log_path = results_dir / agent_name / f"task-{task['id']}.json"
            with open(log_path, "w") as f:
                json.dump(result, f, indent=2, default=str)

    # Phase 4: Summary
    print(f"\n{'=' * 60}")
    print(f"  PHASE 4: SUMMARY")
    print(f"{'=' * 60}\n")
    generate_summary(
        args.site, instructions["domain"], args.model,
        tasks, browseruse_results, rindler_results, results_dir,
    )

    print(f"\nBenchmark complete. Results: {results_dir}")
    print(f"Run ./benchmark/viz.sh {results_dir.relative_to(SCRIPT_DIR)}/ to generate charts.")


if __name__ == "__main__":
    asyncio.run(main())

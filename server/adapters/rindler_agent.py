"""
Rindler MCP Adapter - Connects to the Go MCP server over SSE for browser automation.

This module provides the RindlerTelemetricAgent which uses LLM tool-calling
to drive browser actions on the Go server, integrated with arena telemetry.
"""

import json
import os
import aiohttp
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from .base_agent import BaseAgent
except ImportError:
    BaseAgent = object  # Tests load this module directly; agent class won't be usable but other classes will import fine


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a commerce automation agent. You interact with shopping sites through Rindler's semantic tools — you do NOT have access to raw HTML, CSS selectors, or page elements.

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

MAX_TREE_CHARS = 8000
MAX_RESULT_CHARS = 12000

from constants import COST_RATES

# Maps semantic tool names to categories for cost analysis.
# Downstream scripts group by category to compare agents.
ACTION_CATEGORIES = {
    "update_address": "address",
    "search_products": "search",
    "add_to_cart": "cart_add",
    "remove_from_cart": "cart_remove",
    "update_quantity": "cart_update",
    "view_cart": "cart_view",
    "view_product": "product",
    "checkout": "checkout",
    "go_back": "navigation",
    "select_store": "navigation",
    "next_page": "navigation",
    "prev_page": "navigation",
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class LLMResponse:
    """Structured response from an LLM tool-calling API."""
    tool_name: Optional[str]
    tool_args: Optional[dict]
    tool_call_id: Optional[str]
    text: Optional[str]
    tokens_input: int
    tokens_output: int


# ---------------------------------------------------------------------------
# MCP Tool Bridge
# ---------------------------------------------------------------------------

class MCPToolBridge:
    """Converts between MCP tool schemas and LLM function definitions."""

    @staticmethod
    def mcp_tools_to_llm_tools(mcp_tools: list, provider: str) -> List[dict]:
        """Convert MCP Tool objects to LLM provider format.

        Args:
            mcp_tools: List of MCP Tool objects (with .name, .description, .inputSchema)
            provider: "openai" or "anthropic"
        """
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
            else:  # anthropic
                result.append({
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema,
                })
        return result

    @staticmethod
    def inject_done_tool(tools: List[dict], provider: str) -> List[dict]:
        """Append the synthetic 'done' tool to the tool list."""
        done_desc = (
            "Call this ONLY when you have fully completed every part of the goal. "
            "Do NOT call this if there are remaining items to add, quantities to update, "
            "or steps you haven't tried yet. If a tool returns an error, try an alternative "
            "approach (e.g. navigate to the cart first, then retry). Only report failure "
            "after exhausting all available actions."
        )
        if provider == "openai":
            tools = tools + [{
                "type": "function",
                "function": {
                    "name": "done",
                    "description": done_desc,
                    "parameters": DONE_TOOL_SCHEMA,
                },
            }]
        else:  # anthropic
            tools = tools + [{
                "name": "done",
                "description": done_desc,
                "input_schema": DONE_TOOL_SCHEMA,
            }]
        return tools



# ---------------------------------------------------------------------------
# CallToolResult parser
# ---------------------------------------------------------------------------

def parse_tool_result(result) -> dict:
    """Extract JSON dict from MCP CallToolResult.

    Handles isError flag and non-JSON responses gracefully so the LLM
    can attempt recovery instead of the agent crashing.
    """
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


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"


# ---------------------------------------------------------------------------
# LLM Client
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
            raise ValueError(f"Unknown model prefix: {model_name}. Use gpt-* or claude-*")

    async def call(self, messages: List[dict], tools: List[dict]) -> LLMResponse:
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
            return LLMResponse(
                tool_name=tc.function.name,
                tool_args=json.loads(tc.function.arguments),
                tool_call_id=tc.id,
                text=None,
                tokens_input=usage.prompt_tokens,
                tokens_output=usage.completion_tokens,
            )
        return LLMResponse(
            tool_name=None, tool_args=None, tool_call_id=None,
            text=msg.content,
            tokens_input=usage.prompt_tokens,
            tokens_output=usage.completion_tokens,
        )

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
                return LLMResponse(
                    tool_name=block.name,
                    tool_args=block.input,
                    tool_call_id=block.id,
                    text=None,
                    tokens_input=usage.input_tokens,
                    tokens_output=usage.output_tokens,
                )

        text_parts = [b.text for b in response.content if b.type == "text"]
        return LLMResponse(
            tool_name=None, tool_args=None, tool_call_id=None,
            text="\n".join(text_parts) if text_parts else None,
            tokens_input=usage.input_tokens,
            tokens_output=usage.output_tokens,
        )


# ---------------------------------------------------------------------------
# Rindler Telemetric Agent
# ---------------------------------------------------------------------------

class RindlerTelemetricAgent(BaseAgent):
    """
    MCP-based browser automation agent connecting to the Rindler Go server.
    Uses LLM tool-calling to drive browser actions over SSE.
    """

    def __init__(self, run_id: str, goal: str, lane: str = "RINDLER", **kwargs):
        super().__init__(run_id=run_id, goal=goal, lane=lane)
        self.server_url = os.environ.get("RINDLER_SERVER_URL", "http://localhost:8080")
        self.llm_name = kwargs.get("llm", "gpt-4o")
        self.max_steps = kwargs.get("max_steps", 25)
        self._token = None
        self._session_id = None
        self._code_verifier = None
        self._refresh_token = None
        self._callback_port = self._find_free_port()

    @staticmethod
    def _find_free_port() -> int:
        """Find a free port for the OAuth callback server."""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    async def _authenticate(self) -> str:
        """Run full OAuth 2.1 flow: discover → register → authorize → exchange."""
        print("  🔐 OAuth 2.1 authentication starting...")

        print("     ↳ Discovering OAuth endpoints...", end=" ", flush=True)
        metadata = await self._discover()
        print("✓")

        print("     ↳ Registering dynamic client...", end=" ", flush=True)
        client_id = await self._register(metadata["registration_endpoint"])
        print(f"✓ ({client_id[:12]}...)")

        print("     ↳ Authorizing (PKCE)...", end=" ", flush=True)
        auth_code = await self._authorize(
            metadata["authorization_endpoint"], client_id
        )
        print("✓")

        print("     ↳ Exchanging code for token...", end=" ", flush=True)
        access_token = await self._exchange(
            metadata["token_endpoint"], auth_code, client_id
        )
        print("✓")
        print("  🔐 Authentication complete.\n")
        return access_token

    async def _discover(self) -> dict:
        """Fetch OAuth metadata from well-known endpoints."""
        async with aiohttp.ClientSession() as http:
            async with http.get(
                f"{self.server_url}/.well-known/oauth-protected-resource"
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"OAuth discovery failed ({resp.status}). Is the Rindler server running at {self.server_url}?"
                    )
                resource_meta = await resp.json()

            as_url = resource_meta["authorization_servers"][0]
            async with http.get(
                f"{as_url}/.well-known/oauth-authorization-server"
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"OAuth AS metadata fetch failed ({resp.status}) from {as_url}"
                    )
                return await resp.json()

    async def _register(self, registration_endpoint: str) -> str:
        """Register as a dynamic OAuth client. Returns client_id."""
        async with aiohttp.ClientSession() as http:
            async with http.post(
                registration_endpoint,
                json={
                    "client_name": "arena-rindler-agent",
                    "redirect_uris": [f"http://127.0.0.1:{self._callback_port}/callback"],
                    "grant_types": ["authorization_code"],
                },
            ) as resp:
                data = await resp.json()
                if resp.status != 201:
                    error = data.get("error_description", data.get("error", str(data)))
                    raise RuntimeError(f"Client registration failed ({resp.status}): {error}")
                return data["client_id"]

    async def _authorize(self, authorization_endpoint: str, client_id: str) -> str:
        """Run authorization code flow with PKCE. Returns auth code via redirect interception."""
        import base64
        import hashlib
        import secrets
        from urllib.parse import urlparse, parse_qs

        self._code_verifier = secrets.token_urlsafe(32)
        challenge_bytes = hashlib.sha256(self._code_verifier.encode()).digest()
        code_challenge = (
            base64.urlsafe_b64encode(challenge_bytes).rstrip(b"=").decode()
        )

        state = secrets.token_urlsafe(16)

        params = {
            "client_id": client_id,
            "redirect_uri": f"http://127.0.0.1:{self._callback_port}/callback",
            "response_type": "code",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        async with aiohttp.ClientSession() as http:
            async with http.get(
                authorization_endpoint,
                params=params,
                allow_redirects=False,
            ) as resp:
                if resp.status != 302:
                    raise RuntimeError(
                        f"Expected 302 redirect from authorize, got {resp.status}"
                    )
                location = resp.headers.get("Location", "")
                parsed = urlparse(location)
                query = parse_qs(parsed.query)
                received_state = query.get("state", [None])[0]
                if received_state != state:
                    raise RuntimeError("OAuth state mismatch — possible CSRF")
                return query["code"][0]

    async def _exchange(self, token_endpoint: str, auth_code: str, client_id: str) -> str:
        """Exchange authorization code for access token."""
        async with aiohttp.ClientSession() as http:
            async with http.post(
                token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": auth_code,
                    "code_verifier": self._code_verifier,
                    "client_id": client_id,
                },
            ) as resp:
                data = await resp.json()
                if resp.status != 200:
                    error = data.get("error_description", data.get("error", str(data)))
                    raise RuntimeError(f"Token exchange failed ({resp.status}): {error}")
                self._refresh_token = data.get("refresh_token")
                self._code_verifier = None  # Clear after use
                return data["access_token"]

    def _build_initial_messages(self, provider: str, start_result: dict) -> list:
        session_id = start_result.get("data", {}).get("session_id", "")
        screen = start_result.get("screen", "unknown")
        context = json.dumps(start_result.get("context", {}), indent=2)
        available = start_result.get("available_actions") or []
        global_actions = start_result.get("global_actions") or []

        content = (
            f"Goal: {self.goal}\n\n"
            f"Session started. session_id: {session_id}\n"
            f"Screen: {screen}\n"
            f"Context: {context}\n"
            f"Available actions: {', '.join(available)}\n"
            f"Global actions: {', '.join(global_actions)}"
        )
        return [{"role": "user", "content": content}]

    def _append_tool_exchange(self, provider: str, messages: list, llm_resp: LLMResponse, parsed_result: dict) -> list:
        result_text = truncate(json.dumps(parsed_result), MAX_RESULT_CHARS)
        messages = list(messages)
        if provider == "openai":
            messages.append({
                "role": "assistant",
                "tool_calls": [{"id": llm_resp.tool_call_id, "type": "function",
                    "function": {"name": llm_resp.tool_name, "arguments": json.dumps(llm_resp.tool_args)}}],
            })
            messages.append({"role": "tool", "tool_call_id": llm_resp.tool_call_id, "content": result_text})
        else:
            messages.append({
                "role": "assistant",
                "content": [{"type": "tool_use", "id": llm_resp.tool_call_id,
                    "name": llm_resp.tool_name, "input": llm_resp.tool_args}],
            })
            messages.append({
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": llm_resp.tool_call_id, "content": result_text}],
            })
        return messages

    def _build_result(self, done_args: dict, steps: int) -> dict:
        return {
            "success": done_args.get("success", False),
            "message": done_args.get("message", ""),
            "steps": steps,
            "final_extraction": done_args.get("message", ""),
        }

    def _compute_cost(self, tokens_input: int, tokens_output: int) -> float:
        rates = COST_RATES.get(self.llm_name, COST_RATES["gpt-4o-mini"])
        return (tokens_input / 1_000_000) * rates["input"] + (tokens_output / 1_000_000) * rates["output"]

    async def _call_tool(self, client, tool_name: str, tool_args: dict) -> dict:
        """Call an MCP tool. Auth is at the SSE transport level."""
        raw = await client.call_tool(tool_name, tool_args)
        return parse_tool_result(raw)

    def _init_context_log(self, start_url: str):
        """Initialize the full context log file that captures everything fed to the agent."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "arena_logs")
        os.makedirs(log_dir, exist_ok=True)
        self._context_log_path = os.path.join(log_dir, f"context_{self.lane.lower()}_{timestamp}.log")
        with open(self._context_log_path, 'w') as f:
            f.write(f"{'=' * 80}\n")
            f.write(f"  RINDLER AGENT — FULL CONTEXT LOG\n")
            f.write(f"{'=' * 80}\n")
            f.write(f"  Timestamp:  {datetime.now().isoformat()}\n")
            f.write(f"  Run ID:     {self.run_id}\n")
            f.write(f"  Trace ID:   {self.trace_id}\n")
            f.write(f"  Goal:       {self.goal}\n")
            f.write(f"  Start URL:  {start_url}\n")
            f.write(f"  LLM:        {self.llm_name}\n")
            f.write(f"  Max Steps:  {self.max_steps}\n")
            f.write(f"{'=' * 80}\n\n")
            f.write(f"{'─' * 80}\n")
            f.write(f"  SYSTEM PROMPT (fed to LLM)\n")
            f.write(f"{'─' * 80}\n")
            f.write(SYSTEM_PROMPT)
            f.write(f"\n{'─' * 80}\n\n")
        print(f"  📝 Context log: {self._context_log_path}")

    def _log_context(self, header: str, content: str):
        """Append a section to the context log file."""
        if not hasattr(self, '_context_log_path'):
            return
        with open(self._context_log_path, 'a') as f:
            f.write(f"\n{'─' * 80}\n")
            f.write(f"  [{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {header}\n")
            f.write(f"{'─' * 80}\n")
            f.write(content)
            f.write("\n")

    def _print_terminal_state(self, parsed: dict, step_label: str = ""):
        """Print a detailed play-by-play of every terminal response phase."""
        prefix = f"    "

        # ── Phase 1: Screen Detection ──
        screen = parsed.get("screen", "")
        print(f"{prefix}┌─ SCREEN {'─' * 50}")
        if screen:
            print(f"{prefix}│  📍 Current screen: {screen}")
        else:
            print(f"{prefix}│  ⚠️  No screen detected")

        # ── Phase 2: Context Extractors (cart + address) ──
        ctx = parsed.get("context") or {}
        print(f"{prefix}├─ CONTEXT EXTRACTORS {'─' * 38}")
        if not ctx:
            print(f"{prefix}│  (empty — no persistent context returned)")
        else:
            cart = ctx.get("cart")
            address = ctx.get("address")
            store = ctx.get("store")
            store_slug = ctx.get("store_slug")

            if cart is not None:
                if isinstance(cart, dict):
                    items = cart.get("items", "?")
                    total = cart.get("total", "?")
                    print(f"{prefix}│  🛒 Cart: {items} items, total: {total}")
                else:
                    print(f"{prefix}│  🛒 Cart: {cart}")
            else:
                print(f"{prefix}│  🛒 Cart: (not extracted — extractor returned nothing)")

            if address is not None:
                addr_str = address if isinstance(address, str) else json.dumps(address)
                print(f"{prefix}│  📫 Address: {addr_str}")
            else:
                print(f"{prefix}│  📫 Address: (not extracted — extractor returned nothing)")

            if store:
                print(f"{prefix}│  🏪 Store: {store}" + (f" (slug: {store_slug})" if store_slug else ""))

            # Show any other context keys
            other_keys = [k for k in ctx if k not in ("cart", "address", "store", "store_slug")]
            for k in other_keys:
                print(f"{prefix}│  📎 {k}: {ctx[k]}")

        # ── Phase 3: Data Payload ──
        data = parsed.get("data")
        print(f"{prefix}├─ DATA PAYLOAD {'─' * 44}")
        if data and isinstance(data, dict):
            if "session_id" in data:
                print(f"{prefix}│  🔑 session_id: {data['session_id']}")

            products = data.get("products")
            if products and isinstance(products, list):
                print(f"{prefix}│  📋 {len(products)} products extracted:")
                for i, p in enumerate(products[:8]):
                    name = p.get("name", "?")
                    price = p.get("price", "")
                    size = p.get("size", "")
                    suffix = f" ({size})" if size else ""
                    print(f"{prefix}│     {i+1}. {name}{suffix} — {price}")
                if len(products) > 8:
                    print(f"{prefix}│     ... and {len(products) - 8} more")

            results = data.get("results")
            if results and isinstance(results, list):
                print(f"{prefix}│  📋 {len(results)} results:")
                for r in results[:5]:
                    name = r.get("name", "?")
                    price = r.get("price", "")
                    item_id = r.get("id", "")
                    print(f"{prefix}│     [{item_id}] {name} — {price}")
                if len(results) > 5:
                    print(f"{prefix}│     ... and {len(results) - 5} more")

            tree = data.get("accessibility_tree")
            if tree:
                tree_lines = tree.strip().split('\n')
                print(f"{prefix}│  🌳 Accessibility tree: {len(tree_lines)} lines, {len(tree)} chars")

            # Show any other data keys not already shown
            shown = {"session_id", "products", "results", "accessibility_tree"}
            for k in data:
                if k not in shown:
                    val = data[k]
                    val_str = json.dumps(val, default=str) if not isinstance(val, str) else val
                    if len(val_str) > 100:
                        val_str = val_str[:100] + "..."
                    print(f"{prefix}│  📎 {k}: {val_str}")
        elif data is not None:
            print(f"{prefix}│  Raw: {str(data)[:200]}")
        else:
            print(f"{prefix}│  (no data)")

        # ── Phase 4: Available Actions ──
        available = parsed.get("available_actions") or []
        global_actions = parsed.get("global_actions") or []
        print(f"{prefix}├─ AVAILABLE ACTIONS {'─' * 40}")
        if available:
            print(f"{prefix}│  Screen:  {', '.join(available)}")
        else:
            print(f"{prefix}│  Screen:  (none)")
        if global_actions:
            print(f"{prefix}│  Global:  {', '.join(global_actions)}")
        else:
            print(f"{prefix}│  Global:  (none)")

        # ── Phase 5: Errors ──
        error = parsed.get("error")
        if error:
            print(f"{prefix}├─ ERROR {'─' * 51}")
            if isinstance(error, dict):
                print(f"{prefix}│  ❌ [{error.get('code', '?')}] {error.get('message', '?')}")
            else:
                print(f"{prefix}│  ❌ {error}")

        print(f"{prefix}└{'─' * 59}")

    async def run(self, start_url=None, **kwargs):
        import time
        from mcp.client.sse import sse_client
        from mcp import ClientSession

        self.print_run_header(start_url)
        self._init_context_log(start_url)
        self._token = await self._authenticate()
        llm = LLMClient(self.llm_name, SYSTEM_PROMPT)
        print(f"  🤖 LLM: {llm.model} ({llm.provider})")

        headers = {"Authorization": f"Bearer {self._token}"}
        print(f"  🔌 Connecting to MCP server at {self.server_url}...", flush=True)
        try:
          async with sse_client(self.server_url + "/mcp/", headers=headers) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                mcp_tools = (await client.list_tools()).tools
                tool_names = [t.name for t in mcp_tools]
                print(f"  📦 {len(mcp_tools)} MCP tools: {', '.join(sorted(tool_names))}")
                llm_tools = MCPToolBridge.mcp_tools_to_llm_tools(mcp_tools, llm.provider)
                llm_tools = MCPToolBridge.inject_done_tool(llm_tools, llm.provider)

                # Log tool definitions to context log
                self._log_context("MCP TOOLS REGISTERED", json.dumps(
                    [{"name": t.name, "description": t.description} for t in mcp_tools],
                    indent=2
                ))

                cumulative_cost = 0.0

                # ── Phase: Start Session ──
                print(f"\n  {'═' * 60}")
                print(f"  ▶ PHASE: START SESSION → {start_url}")
                print(f"  {'═' * 60}", flush=True)
                t0 = time.monotonic()
                parsed = await self._call_tool(client, "start_session", {"url": start_url})
                elapsed = time.monotonic() - t0
                self._session_id = parsed.get("data", {}).get("session_id", "")
                screen = parsed.get("screen", "unknown")
                print(f"    session={self._session_id}  screen={screen}  ({elapsed:.1f}s)")
                if "error" in parsed:
                    print(f"    ⚠️  Error: {parsed['error']}")
                self._print_terminal_state(parsed, "start_session")

                # Log full start_session response to context log
                self._log_context("START_SESSION RESPONSE (full JSON)", json.dumps(parsed, indent=2, default=str))

                try:
                    messages = self._build_initial_messages(llm.provider, parsed)
                except Exception as e:
                    print(f"\n    ❌ Failed to build initial messages: {type(e).__name__}: {e}", flush=True)
                    import traceback
                    traceback.print_exc()
                    return self._build_result({"success": False, "message": f"Init error: {e}"}, 0)

                # Log what the agent sees as its first message
                self._log_context("INITIAL MESSAGE → AGENT", json.dumps(messages, indent=2, default=str))

                print(f"\n  {'═' * 60}")
                print(f"  🏃 ACTION LOOP (max {self.max_steps} steps)")
                print(f"  {'═' * 60}", flush=True)
                for step in range(self.max_steps):
                    try:
                        step_num = step + 1
                        print(f"\n  ┌{'─' * 58}┐")
                        print(f"  │ Step {step_num}/{self.max_steps}: LLM thinking...                           │", flush=True)

                        # Log the full messages context sent to LLM
                        self._log_context(
                            f"STEP {step_num} — MESSAGES → LLM ({len(messages)} messages, {len(json.dumps(messages, default=str)):,} chars)",
                            json.dumps(messages, indent=2, default=str)
                        )

                        llm_response = await llm.call(messages, llm_tools)

                        if llm_response.tool_name == "done":
                            done_args = llm_response.tool_args or {}
                            icon = "✅" if done_args.get("success") else "❌"
                            print(f"  │ → done {icon}")
                            print(f"  │   {done_args.get('message', '')}")
                            print(f"  └{'─' * 58}┘")
                            print(f"\n  💰 Total cost: ${cumulative_cost:.4f}")
                            self._log_context(f"STEP {step_num} — AGENT CALLED done()", json.dumps(done_args, indent=2, default=str))
                            self._finalize_context_log(cumulative_cost, step_num, done_args)
                            return self._build_result(done_args, step_num)

                        if llm_response.tool_name:
                            tool_args = llm_response.tool_args or {}

                            # Auto-inject session_id
                            if self._session_id and "session_id" not in tool_args and llm_response.tool_name != "start_session":
                                tool_args["session_id"] = self._session_id

                            # Display tool call
                            display_args = {k: v for k, v in tool_args.items() if k != "session_id"}
                            if display_args:
                                call_str = f"{llm_response.tool_name}({json.dumps(display_args, default=str)})"
                            else:
                                call_str = f"{llm_response.tool_name}()"
                            print(f"  │ → {call_str}")

                            # Log the agent's tool call
                            self._log_context(
                                f"STEP {step_num} — AGENT CALLS {llm_response.tool_name}",
                                f"Args: {json.dumps(tool_args, indent=2, default=str)}\n"
                                f"Tokens: {llm_response.tokens_input:,} in / {llm_response.tokens_output:,} out"
                            )

                            self.log_step_start(action_type=llm_response.tool_name, action_data=tool_args)
                            t0 = time.monotonic()
                            parsed = await self._call_tool(client, llm_response.tool_name, tool_args)
                            elapsed = time.monotonic() - t0

                            event_dict = self.log_step_end(
                                tokens_input=llm_response.tokens_input,
                                tokens_output=llm_response.tokens_output,
                                observation={"tool_result": parsed},
                            )
                            cost = self._compute_cost(llm_response.tokens_input, llm_response.tokens_output)
                            cumulative_cost += cost
                            event_dict["cost_usd"] = cost
                            event_dict["action_category"] = ACTION_CATEGORIES.get(
                                llm_response.tool_name, "other"
                            )
                            event_dict["was_error"] = bool(parsed.get("error"))

                            # Log full MCP response to context log
                            self._log_context(
                                f"STEP {step_num} — MCP RESPONSE for {llm_response.tool_name} ({elapsed:.1f}s)",
                                json.dumps(parsed, indent=2, default=str)
                            )

                            # ── Play-by-play terminal state ──
                            if "error" in parsed:
                                err = parsed["error"]
                                if isinstance(err, dict):
                                    print(f"    ⚠️  [{err.get('code', 'error')}] {err.get('message', '')}")
                                else:
                                    print(f"    ⚠️  {err}")
                            else:
                                self._print_terminal_state(parsed, llm_response.tool_name)

                            # ── Context extractor validation ──
                            ctx = parsed.get("context") or {}
                            cart_present = ctx.get("cart") is not None
                            addr_present = ctx.get("address") is not None
                            extractor_status = []
                            if cart_present:
                                extractor_status.append("cart=✓")
                            else:
                                extractor_status.append("cart=✗")
                            if addr_present:
                                extractor_status.append("addr=✓")
                            else:
                                extractor_status.append("addr=✗")
                            print(f"    🔍 Context extractors: [{', '.join(extractor_status)}]")

                            print(f"    ⏱  {elapsed:.1f}s | tokens: {llm_response.tokens_input:,}in/{llm_response.tokens_output:,}out | cost: ${cost:.4f} (total: ${cumulative_cost:.4f})")
                            print(f"  └{'─' * 58}┘")

                            messages = self._append_tool_exchange(llm.provider, messages, llm_response, parsed)

                            # Log what gets appended to the message history
                            self._log_context(
                                f"STEP {step_num} — TOOL RESULT → AGENT (truncated to {MAX_RESULT_CHARS} chars)",
                                truncate(json.dumps(parsed, default=str), MAX_RESULT_CHARS)
                            )
                        else:
                            text_preview = (llm_response.text or "")[:200]
                            print(f"  │ → [thinking] {text_preview}")
                            print(f"  └{'─' * 58}┘")
                            messages.append({"role": "assistant", "content": llm_response.text})
                            self._log_context(
                                f"STEP {step_num} — AGENT THINKING (no tool call)",
                                llm_response.text or "(empty)"
                            )
                    except Exception as e:
                        print(f"\n    ❌ Step {step + 1} failed: {type(e).__name__}: {e}", flush=True)
                        import traceback
                        traceback.print_exc()
                        self._log_context(f"STEP {step + 1} — EXCEPTION", f"{type(e).__name__}: {e}")
                        return self._build_result({"success": False, "message": f"Agent error: {e}"}, step + 1)

        except Exception as e:
            print(f"\n  ❌ Agent error: {type(e).__name__}: {e}", flush=True)
            import traceback
            traceback.print_exc()
            self._log_context("FATAL ERROR", f"{type(e).__name__}: {e}")
            return self._build_result({"success": False, "message": f"Agent error: {e}"}, 0)


        print(f"\n  💰 Total cost: ${cumulative_cost:.4f}")
        self._finalize_context_log(cumulative_cost, self.max_steps, {"success": False, "message": "max steps reached"})
        return self._build_result({"success": False, "message": "max steps reached"}, self.max_steps)

    def _finalize_context_log(self, total_cost: float, steps: int, result: dict):
        """Write the final summary to the context log."""
        if not hasattr(self, '_context_log_path'):
            return
        with open(self._context_log_path, 'a') as f:
            f.write(f"\n{'=' * 80}\n")
            f.write(f"  RUN COMPLETE\n")
            f.write(f"{'=' * 80}\n")
            f.write(f"  Steps:   {steps}\n")
            f.write(f"  Cost:    ${total_cost:.4f}\n")
            f.write(f"  Success: {result.get('success', False)}\n")
            f.write(f"  Message: {result.get('message', '')}\n")
            f.write(f"{'=' * 80}\n")

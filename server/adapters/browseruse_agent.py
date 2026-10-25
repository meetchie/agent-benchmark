"""
BrowserUse arm: browser-use driving a local headless Chromium on its own (no site mapping).

The browser comes from browser_env.browser_profile() (local, headless by default, the
macOS keychain flags always on) and the model from llm.agent_llm(): BENCHMARK_AGENT_MODEL,
else claude-sonnet-5-5. Per-step tokens are read from browser-use's own token counter at
the end of every step, so each step_end carries its real token count and cost.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

import llm
from browser_env import agent_files_dir, browser_profile, cleanup_profile, track_agent_dir

from .base_agent import BaseAgent


def _usage_fields(usage: llm.Usage) -> Dict[str, int]:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_input_tokens": usage.cache_read_input_tokens,
        "cache_creation_input_tokens": usage.cache_creation_input_tokens,
    }


def usage_delta(now: llm.Usage, before: llm.Usage) -> llm.Usage:
    return llm.Usage(
        input_tokens=max(now.input_tokens - before.input_tokens, 0),
        output_tokens=max(now.output_tokens - before.output_tokens, 0),
        cache_read_input_tokens=max(now.cache_read_input_tokens - before.cache_read_input_tokens, 0),
        cache_creation_input_tokens=max(now.cache_creation_input_tokens - before.cache_creation_input_tokens, 0),
    )


def prompt_tokens(usage: llm.Usage) -> int:
    return usage.input_tokens + usage.cache_read_input_tokens + usage.cache_creation_input_tokens


class BrowserUseTelemetricAgent(BaseAgent):
    """
    Browser automation agent using the browser-use library on a local headless browser.
    """

    def __init__(self, run_id: str, goal: str, lane: str = "BROWSERUSE", **kwargs):
        super().__init__(run_id=run_id, goal=goal, lane=lane)
        self.model = (kwargs.get("model") or kwargs.get("llm") or "").strip() or llm.model_for("agent")
        self.max_steps = int(kwargs.get("max_steps") or 30)
        self.timeout_s = float(kwargs.get("timeout_s") or 0) or None
        self.viewport = kwargs.get("viewport")
        self._agent_factory = kwargs.get("agent_factory")  # tests inject a fake browser_use.Agent
        self.usage = llm.Usage()

    def _make_agent(self, start_url: Optional[str], profile):
        initial_actions = [{"navigate": {"url": start_url, "new_tab": False}}] if start_url else None
        kwargs = dict(
            task=self.goal,
            llm=llm.agent_llm(self.model),
            browser_profile=profile,
            file_system_path=agent_files_dir(profile),
            initial_actions=initial_actions,
            use_judge=False,  # the arena has its own judge
            calculate_cost=False,  # cost comes from constants.COST_RATES, no pricing download
            # browser-use's own Ctrl-C handler pauses on the first SIGINT and calls
            # os._exit() on the second, which skips every cleanup and leaves Chromium
            # running. One Ctrl-C under `uv run` is two SIGINTs (the terminal's and the
            # copy uv forwards), so the command line entry point handles it instead
            # (entrypoint.run_cli): the run is cancelled and the browser closed.
            enable_signal_handler=False,
        )
        if self._agent_factory is not None:
            return self._agent_factory(**kwargs)
        from browser_use import Agent

        return Agent(**kwargs)

    async def _usage_now(self, agent) -> llm.Usage:
        try:
            summary = await agent.token_cost_service.get_usage_summary()
        except Exception:
            return self.usage
        return llm.usage_from_browser_use(summary)

    async def run(self, start_url: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        self.print_run_header(start_url)
        print(f"Model: {self.model} ({llm.provider()}) | max_steps: {self.max_steps}")
        profile = browser_profile(viewport=self.viewport)
        result: Dict[str, Any] = {
            "success": False, "message": "", "steps": 0, "errors_detected": [],
            "final_extraction": None, "model": self.model,
        }
        start_time = datetime.now()
        history = None
        timed_out = False
        counted = llm.Usage()
        try:
            agent = self._make_agent(start_url, profile)
            track_agent_dir(profile, agent)  # its step screenshots go with the profile

            async def on_step_start(agent):
                action_data = None
                self.log_step_start(action_type=None, action_data=action_data)
                print(f"[Step {self._current_step_index}] START")

            async def on_step_end(agent):
                nonlocal counted
                observation = None
                action_type = None
                try:
                    actions = agent.history.model_actions()
                    if actions and isinstance(actions[-1], dict):
                        action_type = next(iter(k for k in actions[-1] if k != "interacted_element"), None)
                    extracted = agent.history.extracted_content()
                    if extracted:
                        observation = {"extracted_content": extracted[-1]}
                except Exception:
                    pass
                now = await self._usage_now(agent)
                step_usage = usage_delta(now, counted)
                counted = now
                event = self.log_step_end(
                    tokens_input=prompt_tokens(step_usage),
                    tokens_output=step_usage.output_tokens,
                    observation=observation,
                )
                if action_type:
                    # browser-use only knows a step's action once the step is over; label
                    # both halves of the step with it (step_start saw the previous one).
                    event["action_type"] = action_type
                    for earlier in reversed(self.telemetry_events):
                        if earlier.get("event_type") == "step_start" and earlier.get("step_index") == event["step_index"]:
                            earlier["action_type"] = action_type
                            break
                event["cost_usd"] = step_usage.cost_usd(self.model) or 0.0
                event["tokens_cache_read"] = step_usage.cache_read_input_tokens
                event["tokens_cache_write"] = step_usage.cache_creation_input_tokens
                print(f"[Step {self._current_step_index}] END   - {action_type or '?'} | "
                      f"{event.get('duration_ms') or 0:.0f}ms | {event['tokens_input']:,} in / "
                      f"{event['tokens_output']:,} out | ${event['cost_usd']:.4f}")

            run = agent.run(max_steps=self.max_steps, on_step_start=on_step_start, on_step_end=on_step_end)
            try:
                history = await (asyncio.wait_for(run, timeout=self.timeout_s) if self.timeout_s else run)
            except asyncio.TimeoutError:
                timed_out = True
                result["errors_detected"].append(f"run stopped after the {self.timeout_s:.0f}s time limit")
                history = getattr(agent, "history", None)

            self.usage = await self._usage_now(agent)
            leftover = usage_delta(self.usage, counted)
            self._add_leftover(leftover)
            self._read_history(history, result, timed_out=timed_out)
        except Exception as e:
            result["message"] = f"Error: {e}"
            result["errors_detected"].append(str(e))
            raise
        finally:
            # Also on Ctrl-C (a cancelled run): stops the browser if it is still up.
            cleanup_profile(profile)
            elapsed = (datetime.now() - start_time).total_seconds()
            result["steps"] = self._current_step_index
            result["usage"] = _usage_fields(self.usage)

        if prompt_tokens(self.usage) == 0 and self._current_step_index > 0:
            result["errors_detected"].append("Zero tokens recorded: the model never answered")
        print(f"\nToken usage: {prompt_tokens(self.usage):,} in / {self.usage.output_tokens:,} out "
              f"(cache read {self.usage.cache_read_input_tokens:,}, write {self.usage.cache_creation_input_tokens:,})")
        self.print_run_footer(elapsed, result["success"], result["message"])
        return result

    def _add_leftover(self, leftover: llm.Usage) -> None:
        """Tokens used after the last step ended (or with no step at all) go on the last step."""
        if prompt_tokens(leftover) == 0 and leftover.output_tokens == 0:
            return
        ends = [e for e in self.telemetry_events if e.get("event_type") == "step_end"]
        if not ends:
            self.log_step_start(action_type="unfinished_step")
            event = self.log_step_end(tokens_input=0, tokens_output=0)
            ends = [event]
        last = ends[-1]
        last["tokens_input"] = (last.get("tokens_input") or 0) + prompt_tokens(leftover)
        last["tokens_output"] = (last.get("tokens_output") or 0) + leftover.output_tokens
        last["cost_usd"] = (last.get("cost_usd") or 0.0) + (leftover.cost_usd(self.model) or 0.0)

    def _read_history(self, history, result: Dict[str, Any], timed_out: bool = False) -> None:
        """Success and the final report come from browser-use's own done action."""
        if history is None:
            result["message"] = "no history"
            return
        try:
            done = bool(history.is_done())
            success = bool(history.is_successful()) if done else False
        except Exception:
            done, success = False, False
        final = None
        try:
            final = history.final_result()
        except Exception:
            pass
        if not final:
            try:
                extracted = [c for c in history.extracted_content() if c]
                final = extracted[-1] if extracted else None
            except Exception:
                final = None
        result["final_extraction"] = final
        result["success"] = success
        if done:
            result["message"] = "Agent finished and reported " + ("success" if success else "failure")
        elif timed_out:  # the time limit, already in errors_detected, stopped it, not the step budget
            result["message"] = f"Agent did not finish within the {self.timeout_s:.0f}s time limit"
        else:
            result["message"] = f"Agent did not finish within {self.max_steps} steps"
            result["errors_detected"].append(f"Reached max_steps ({self.max_steps}) without calling done")


# Backwards compatibility alias
TelemetricAgent = BrowserUseTelemetricAgent

"""Fire-and-forget persistence client for the Go benchmark API."""

import os
import logging
import aiohttp
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=5)


def _get_headers() -> dict:
    """Build request headers lazily so env vars are read after load_dotenv runs."""
    return {
        "Content-Type": "application/json",
        "X-Internal-Key": os.getenv("INTERNAL_API_KEY", ""),
    }


def _get_go_server_url() -> str:
    return os.getenv("GO_SERVER_URL", "http://localhost:8080")


def _get_domain(url: str) -> str:
    hostname = urlparse(url).hostname or ""
    return hostname.replace("www.", "").lower()


async def persist_run_start(
    run_id: str,
    clerk_user_id: str,
    url: str,
    task_label: str,
    task_goal: str,
    agent_type: str = "browseruse",
    agent_model: str = "gpt-4o",
) -> str | None:
    """Create a benchmark run in the Go server. Returns the persisted run ID or None on failure."""
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            resp = await session.post(
                f"{_get_go_server_url()}/api/benchmark/runs",
                json={
                    "clerk_user_id": clerk_user_id,
                    "site_domain": _get_domain(url),
                    "start_url": url,
                    "task_label": task_label,
                    "task_goal": task_goal,
                    "agent_type": agent_type,
                    "agent_model": agent_model,
                },
                headers=_get_headers(),
            )
            if resp.status == 201:
                data = await resp.json()
                return data.get("id")
            logger.warning("persist_run_start failed: %s", resp.status)
    except Exception:
        logger.warning("persist_run_start: Go server unreachable", exc_info=True)
    return None


async def persist_steps(run_id: str, steps: list[dict]) -> None:
    """Batch-persist steps to the Go server."""
    if not steps or not run_id:
        return
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            await session.post(
                f"{_get_go_server_url()}/api/benchmark/runs/{run_id}/steps",
                json=[
                    {
                        "step_number": s.get("step", s.get("step_number", 0)),
                        "description": s.get("description", ""),
                        "elapsed_ms": s.get("elapsed_ms", 0),
                    }
                    for s in steps
                ],
                headers=_get_headers(),
            )
    except Exception:
        logger.warning("persist_steps: Go server unreachable", exc_info=True)


async def persist_run_completion(
    run_id: str,
    status: str,
    result_state: str,
    success: bool,
    total_ms: int,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    estimated_cost_usd: float,
    summary: str,
) -> None:
    """Update a run with final results."""
    if not run_id:
        return
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            await session.patch(
                f"{_get_go_server_url()}/api/benchmark/runs/{run_id}",
                json={
                    "status": status,
                    "result_state": result_state,
                    "success": success,
                    "total_ms": total_ms,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                    "estimated_cost_usd": estimated_cost_usd,
                    "summary": summary,
                },
                headers=_get_headers(),
            )
    except Exception:
        logger.warning("persist_run_completion: Go server unreachable", exc_info=True)


async def persist_phases(run_id: str, phases: list[dict]) -> None:
    """Persist judge phase breakdown."""
    if not phases or not run_id:
        return
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            await session.post(
                f"{_get_go_server_url()}/api/benchmark/runs/{run_id}/phases",
                json=[
                    {
                        "name": p.get("name", ""),
                        "step_numbers": p.get("steps", []),
                        "total_ms": p.get("total_ms", 0),
                        "failed": p.get("failed", False),
                        "slow": p.get("slow", False),
                    }
                    for p in phases
                ],
                headers=_get_headers(),
            )
    except Exception:
        logger.warning("persist_phases: Go server unreachable", exc_info=True)


async def persist_tasks(
    clerk_user_id: str, url: str, tasks: list[dict]
) -> None:
    """Persist generated tasks."""
    if not tasks:
        return
    domain = _get_domain(url)
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            for task in tasks:
                await session.post(
                    f"{_get_go_server_url()}/api/benchmark/tasks",
                    json={
                        "clerk_user_id": clerk_user_id,
                        "site_domain": domain,
                        "label": task.get("label", ""),
                        "goal": task.get("goal", ""),
                    },
                    headers=_get_headers(),
                )
    except Exception:
        logger.warning("persist_tasks: Go server unreachable", exc_info=True)

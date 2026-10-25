"""Local run persistence: one JSON file per benchmark run.

Every finished (or failed) live-benchmark run is written to ``RUNS_DIR/<run_id>.json``
so results survive a server restart. The hosted version posted the same data to a
separate Go service backed by Postgres; that service is retired, so the files are the
whole database.

Configuration
    ``RUNS_DIR``  directory for the files. Default ``server/runs/`` (gitignored). A
                  relative path is resolved against the ``server/`` directory, so the
                  result does not depend on where the server was started from.

The function names and signatures are the ones the Go client had: ``persist_run_start``
creates the record and returns its id, the others update it. They never raise: a disk
problem is logged and the benchmark carries on, exactly as an unreachable Go server did.

Record layout (all keys always present once ``persist_run_start`` has run)::

    {"id", "user_id", "created_at", "updated_at", "site_domain", "start_url",
     "task_label", "task_goal", "agent_type", "agent_model",
     "status", "result_state", "success", "summary", "total_ms",
     "input_tokens", "output_tokens", "total_tokens",
     "cache_read_tokens", "cache_write_tokens", "estimated_cost_usd",
     "steps": [{"step_number", "description", "elapsed_ms"}],
     "phases": [{"name", "step_numbers", "total_ms", "failed", "slow"}]}

Screenshots are not stored. ``input_tokens`` includes cache reads (browser-use's
convention); ``cache_read_tokens`` and ``cache_write_tokens`` say how many of the
priced tokens were cached.
"""

import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import runtime_env  # noqa: F401  (loads .env so RUNS_DIR is visible)

logger = logging.getLogger(__name__)

SERVER_DIR = Path(__file__).resolve().parent
DEFAULT_RUNS_DIR = SERVER_DIR / "runs"
TASKS_FILE = "tasks.jsonl"

# Run ids become file names, so only plain id characters are accepted.
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def runs_dir() -> Path:
    """The directory run files are written to (``RUNS_DIR``, default ``server/runs``)."""
    raw = os.getenv("RUNS_DIR", "").strip()
    if not raw:
        return DEFAULT_RUNS_DIR
    path = Path(raw).expanduser()
    return path if path.is_absolute() else SERVER_DIR / path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get_domain(url: str) -> str:
    hostname = urlparse(url).hostname or ""
    return hostname.replace("www.", "").lower()


def _run_path(run_id: str) -> Path | None:
    if not isinstance(run_id, str) or not _SAFE_ID.match(run_id):
        logger.warning("persistence: refusing run id %r (not a plain id)", run_id)
        return None
    return runs_dir() / f"{run_id}.json"


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Write atomically: a reader never sees a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_run(run_id: str) -> dict[str, Any] | None:
    """The stored record for a run, or None when there is none (or it is unreadable)."""
    path = _run_path(run_id)
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        logger.warning("persistence: could not read %s", path, exc_info=True)
        return None
    return data if isinstance(data, dict) else None


def _update(run_id: str, changes: dict[str, Any]) -> bool:
    """Merge ``changes`` into the run's record (creating a bare one if needed)."""
    path = _run_path(run_id)
    if path is None:
        return False
    record = read_run(run_id) or {"id": run_id, "created_at": _now()}
    record.update(changes)
    record["updated_at"] = _now()
    try:
        _write_json(path, record)
    except OSError:
        logger.warning("persistence: could not write %s", path, exc_info=True)
        return False
    return True


async def persist_run_start(
    run_id: str,
    clerk_user_id: str,
    url: str,
    task_label: str,
    task_goal: str,
    agent_type: str = "browseruse",
    agent_model: str | None = None,
) -> str | None:
    """Create the run's record. Returns the persisted run id, or None when it could not be written.

    ``clerk_user_id`` is the signed-in user's id in Clerk mode and ``local`` otherwise;
    the name is kept from the hosted version. ``agent_model`` is the model id the agent
    runs on (the caller knows it; it is not guessed here).
    """
    created = _now()
    record = {
        "id": run_id,
        "user_id": clerk_user_id,
        "created_at": created,
        "site_domain": _get_domain(url),
        "start_url": url,
        "task_label": task_label,
        "task_goal": task_goal,
        "agent_type": agent_type,
        "agent_model": agent_model,
        "status": "running",
        "result_state": "",
        "success": False,
        "summary": "",
        "total_ms": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "estimated_cost_usd": None,
        "steps": [],
        "phases": [],
    }
    return run_id if _update(run_id, record) else None


async def persist_steps(run_id: str, steps: list[dict]) -> None:
    """Store the run's steps (replaces any stored before)."""
    if not steps or not run_id:
        return
    _update(run_id, {
        "steps": [
            {
                "step_number": s.get("step", s.get("step_number", 0)),
                "description": s.get("description", ""),
                "elapsed_ms": s.get("elapsed_ms", 0),
            }
            for s in steps
        ],
    })


async def persist_run_completion(
    run_id: str,
    status: str,
    result_state: str,
    success: bool,
    total_ms: int,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    estimated_cost_usd: float | None,
    summary: str,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    message: str = "",
) -> None:
    """Store the run's final result. ``estimated_cost_usd`` is None for an unpriced model."""
    if not run_id:
        return
    changes: dict[str, Any] = {
        "status": status,
        "result_state": result_state,
        "success": success,
        "total_ms": total_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "estimated_cost_usd": estimated_cost_usd,
        "summary": summary,
    }
    if message:
        changes["message"] = message
    _update(run_id, changes)


async def persist_phases(run_id: str, phases: list[dict]) -> None:
    """Store the judge's phase breakdown."""
    if not phases or not run_id:
        return
    _update(run_id, {
        "phases": [
            {
                "name": p.get("name", ""),
                "step_numbers": p.get("steps", []),
                "total_ms": p.get("total_ms", 0),
                "failed": p.get("failed", False),
                "slow": p.get("slow", False),
            }
            for p in phases
        ],
    })


async def persist_tasks(
    clerk_user_id: str, url: str, tasks: list[dict]
) -> None:
    """Append generated tasks to ``RUNS_DIR/tasks.jsonl`` (one JSON object per task)."""
    if not tasks:
        return
    domain = _get_domain(url)
    created = _now()
    lines = [
        json.dumps({
            "user_id": clerk_user_id,
            "site_domain": domain,
            "label": task.get("label", ""),
            "goal": task.get("goal", ""),
            "created_at": created,
        }, ensure_ascii=False)
        for task in tasks
    ]
    try:
        directory = runs_dir()
        directory.mkdir(parents=True, exist_ok=True)
        with open(directory / TASKS_FILE, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError:
        logger.warning("persist_tasks: could not write %s", TASKS_FILE, exc_info=True)

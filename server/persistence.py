"""Local run persistence: one JSON file per run at ``RUNS_DIR/<run_id>.json``, so results survive a
restart.

``RUNS_DIR`` defaults to ``server/runs/`` (gitignored). A relative path is resolved against
``server/``. ``persist_run_start`` creates the record and returns its id, the other functions update
it. None of them raise. A disk problem is logged and the run carries on.

``persist_run_start`` shows the record's keys. A finished run that errored also has ``message``, and
screenshots are not stored. ``input_tokens`` includes cache reads, as browser-use counts them.
``final_report`` and ``agent_reported_success`` are null when the agent did not finish on its own.
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

    ``clerk_user_id`` is the signed-in user's id in Clerk mode and ``local`` otherwise. The name is
    left over from the hosted version. ``agent_model`` is the model id the agent runs on.
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
        "final_report": None,
        "agent_reported_success": None,
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
    final_report: str | None = None,
    agent_reported_success: bool | None = None,
) -> None:
    """Store the run's final result. ``estimated_cost_usd`` is None for an unpriced model.

    ``final_report`` and ``agent_reported_success`` are both None when the agent did not finish on
    its own.
    """
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
        "final_report": final_report,
        "agent_reported_success": agent_reported_success,
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


_UNFINISHED = ("running", "analyzing")


def mark_unfinished_runs(message: str) -> int:
    """Mark every run file still ``running`` or ``analyzing`` as an ``error`` with ``message``.

    A server calls this at startup for the files an earlier server left behind, since a run whose
    server was killed never wrote its end. Usage stays as recorded (none if the run was cut off
    before the agent stopped). Returns how many files were changed.
    """
    try:
        paths = sorted(runs_dir().glob("*.json"))
    except OSError:
        return 0
    changed = 0
    for path in paths:
        if path.name.startswith("."):  # the quota file, or a write in progress
            continue
        record = read_run(path.stem)
        if not record or record.get("status") not in _UNFINISHED:
            continue
        if _update(path.stem, {"status": "error", "result_state": "error", "success": False, "message": message}):
            changed += 1
    return changed


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

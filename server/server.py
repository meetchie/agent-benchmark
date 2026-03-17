"""
Benchmark HTTP Server — FastAPI server exposing benchmark start and status endpoints.

Start: uv run uvicorn server:app --port 8000 --reload

Endpoints:
  POST /benchmark/start    → { run_id }
  GET  /benchmark/status/{run_id} → RunState as JSON
  GET  /health             → { ok: true }
"""

import asyncio
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from benchmark_runner import RunState, run_benchmark


# In-memory run state store with TTL eviction
_runs: dict[str, RunState] = {}
_MAX_RUNS = 100


def _evict_old_runs() -> None:
    """Remove oldest runs when store exceeds capacity."""
    if len(_runs) <= _MAX_RUNS:
        return
    # RunState has a run_id; sort by insertion order (dict preserves it in 3.7+)
    keys = list(_runs.keys())
    for key in keys[: len(keys) - _MAX_RUNS]:
        _runs.pop(key, None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Rindler Benchmark Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class StartRequest(BaseModel):
    url: str
    goal: str

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v

    @field_validator("goal")
    @classmethod
    def goal_max_length(cls, v: str) -> str:
        if len(v) > 5000:
            raise ValueError("goal must be 5000 characters or fewer")
        return v


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/benchmark/start")
async def start_benchmark(req: StartRequest):
    run_id = str(uuid.uuid4())
    state = RunState(run_id=run_id)
    _runs[run_id] = state
    _evict_old_runs()

    # Start agent in the background — does not block this response
    asyncio.create_task(run_benchmark(state, req.url, req.goal))

    return {"run_id": run_id}


@app.get("/benchmark/status/{run_id}")
async def get_status(run_id: str):
    state = _runs.get(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run not found")
    return state.to_response()

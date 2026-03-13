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


# In-memory run state store
_runs: dict[str, RunState] = {}  # No eviction — intended for short-lived dev sessions only


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Rindler Benchmark Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Local dev only
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/benchmark/start")
async def start_benchmark(req: StartRequest):
    run_id = str(uuid.uuid4())
    state = RunState(run_id=run_id)
    _runs[run_id] = state

    # Start agent in the background — does not block this response
    asyncio.create_task(run_benchmark(state, req.url, req.goal))

    return {"run_id": run_id}


@app.get("/benchmark/status/{run_id}")
async def get_status(run_id: str):
    state = _runs.get(run_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")
    return state.to_response()

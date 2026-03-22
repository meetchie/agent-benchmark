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

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from benchmark_runner import RunState, run_benchmark
from task_generator import fetch_and_generate
from auth import signup, signin, decode_jwt
from database import get_remaining_runs, try_record_run, get_pool, close_pool


# In-memory run state store
_runs: dict[str, RunState] = {}  # No eviction — intended for short-lived dev sessions only

# Admin emails get unlimited runs
ADMIN_EMAILS: set[str] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load env for DATABASE_URL and AUTH_SECRET
    from dotenv import load_dotenv
    import os
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=False)
    yield
    await close_pool()


app = FastAPI(title="Rindler Benchmark Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Local dev only
    allow_methods=["*"],
    allow_headers=["*"],
)


async def get_current_user(authorization: str = Header(None)) -> dict:
    """Extract and validate JWT from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_jwt(token)
        return payload
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


class AuthRequest(BaseModel):
    email: str
    password: str


class StartRequest(BaseModel):
    url: str
    goal: str

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v


class GenerateTasksRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/auth/signup")
async def auth_signup(req: AuthRequest):
    try:
        result = await signup(req.email, req.password)
        return result
    except ValueError as e:
        raise HTTPException(status_code=422 if "Invalid email" in str(e) or "8 characters" in str(e) else 409, detail=str(e))


# Track failed sign-in attempts: email -> (count, first_attempt_time)
_signin_attempts: dict[str, tuple[int, float]] = {}
_MAX_SIGNIN_ATTEMPTS = 5
_LOCKOUT_SECONDS = 900  # 15 minutes


@app.post("/auth/signin")
async def auth_signin(req: AuthRequest):
    import time
    email = req.email.strip().lower()

    # Check lockout
    if email in _signin_attempts:
        count, first_time = _signin_attempts[email]
        if count >= _MAX_SIGNIN_ATTEMPTS:
            elapsed = time.time() - first_time
            if elapsed < _LOCKOUT_SECONDS:
                remaining = int((_LOCKOUT_SECONDS - elapsed) / 60) + 1
                raise HTTPException(status_code=429, detail=f"Too many attempts. Try again in {remaining} minutes.")
            else:
                del _signin_attempts[email]

    try:
        result = await signin(req.email, req.password)
        # Success — clear attempts
        _signin_attempts.pop(email, None)
        return result
    except PermissionError as e:
        # Track failed attempt
        if email in _signin_attempts:
            count, first_time = _signin_attempts[email]
            _signin_attempts[email] = (count + 1, first_time)
        else:
            _signin_attempts[email] = (1, time.time())
        raise HTTPException(status_code=401, detail=str(e))


@app.get("/auth/me")
async def auth_me(user: dict = Depends(get_current_user)):
    import uuid as uuid_mod
    user_id = uuid_mod.UUID(user["user_id"])
    is_admin = user.get("email", "").lower() in ADMIN_EMAILS
    if is_admin:
        return {"user_id": user["user_id"], "email": user["email"], "remaining_runs": 999, "reset_time": None}
    info = await get_remaining_runs(user_id)
    return {"user_id": user["user_id"], "email": user["email"], **info}


@app.post("/benchmark/start")
async def start_benchmark_endpoint(req: StartRequest, user: dict = Depends(get_current_user)):
    import uuid as uuid_mod
    user_id = uuid_mod.UUID(user["user_id"])
    is_admin = user.get("email", "").lower() in ADMIN_EMAILS

    if not is_admin:
        # Atomic rate limit check + record
        run_record = await try_record_run(user_id)
        if run_record is None:
            info = await get_remaining_runs(user_id)
            raise HTTPException(status_code=429, detail={
                "error": "Rate limit exceeded",
                "reset_time": info["reset_time"],
            })
        remaining = run_record["remaining_runs"]
    else:
        remaining = 999

    run_id = str(uuid_mod.uuid4())
    state = RunState(run_id=run_id)
    _runs[run_id] = state
    asyncio.create_task(run_benchmark(state, req.url, req.goal))

    return {
        "run_id": run_id,
        "remaining_runs": remaining,
    }


@app.get("/benchmark/status/{run_id}")
async def get_status(run_id: str):
    state = _runs.get(run_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")
    return state.to_response()


@app.post("/benchmark/generate-tasks")
async def generate_tasks_endpoint(req: GenerateTasksRequest):
    try:
        tasks = await fetch_and_generate(req.url)
        return {"tasks": tasks}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=502, detail={"error": "Could not access site", "detail": str(e)})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "Task generation failed", "detail": str(e)[:200]})

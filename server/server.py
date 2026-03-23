"""
Benchmark HTTP Server — FastAPI server exposing benchmark start and status endpoints.

Start: uv run uvicorn server:app --port 8000 --reload

Endpoints:
  POST /benchmark/start    → { run_id }
  GET  /benchmark/status/{run_id} → RunState as JSON
  GET  /health             → { ok: true }
"""

import asyncio
import os
import time as _time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from benchmark_runner import RunState, run_benchmark
from task_generator import fetch_and_generate
from clerk_auth import verify_clerk_jwt

# In-memory run state store
_runs: dict[str, RunState] = {}

# Run eviction settings
_MAX_STORED_RUNS = 200

# Per-user concurrency limit (max active runs)
_active_runs: dict[str, int] = {}  # user_id -> count
_MAX_CONCURRENT_RUNS = 5

# Admin emails get unlimited runs (bypass concurrency limit)
ADMIN_EMAILS: set[str] = set()

# Internal API key for edge-to-backend auth
_INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

# Rate limiting for task generation
_task_gen_requests: dict[str, list[float]] = {}  # ip -> list of timestamps
_TASK_GEN_MAX_PER_MINUTE = 5

# Demo mode — returns fake data without calling OpenAI or launching a browser
# Set DEMO_MODE=true in .env to enable
def _check_demo_mode() -> bool:
    return os.getenv("DEMO_MODE", "").lower() in ("1", "true", "yes")


def _evict_stale_runs():
    """Remove completed/errored runs when store exceeds limit."""
    if len(_runs) < _MAX_STORED_RUNS:
        return
    to_delete = [rid for rid, s in _runs.items() if s.status in ("complete", "error")]
    for rid in to_delete:
        _runs.pop(rid, None)


def verify_internal_key(x_internal_key: str = Header(None, alias="X-Internal-Key")) -> None:
    """Verify the request comes from our Cloudflare edge functions."""
    if not _INTERNAL_API_KEY:
        return  # Not configured (local dev) — skip check
    if x_internal_key != _INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


def _check_task_gen_rate(request: Request):
    """Rate limit task generation by IP."""
    ip = request.client.host if request.client else "unknown"
    now = _time.time()
    timestamps = _task_gen_requests.get(ip, [])
    # Remove old entries
    timestamps = [t for t in timestamps if now - t < 60]
    if len(timestamps) >= _TASK_GEN_MAX_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Too many requests. Try again in a minute.")
    timestamps.append(now)
    _task_gen_requests[ip] = timestamps


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load .env files
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=False)
    yield


app = FastAPI(title="Rindler Benchmark Server", lifespan=lifespan)

_ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5180,http://localhost:5173"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def get_current_user(authorization: str = Header(None)) -> dict:
    """Verify Clerk JWT from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.split(" ", 1)[1]
    try:
        claims = verify_clerk_jwt(token)
        return {"user_id": claims["sub"]}
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


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


async def _demo_run(state: RunState, url: str, goal: str):
    """Simulate a benchmark run with fake steps for UI testing."""
    import asyncio as _aio
    import random
    from datetime import datetime
    from benchmark_runner import StepRecord

    domain = url.split("//")[-1].split("/")[0].replace("www.", "")
    demo_steps = [
        f"Navigating to {url}",
        f"Looking for address input on {domain}",
        "Typing address: 1 Times Square, New York, NY 10036",
        "Selecting first autocomplete suggestion",
        f"Browsing product categories on {domain}",
        "Applying price filter: $15-$25",
        "Scrolling through filtered results",
        "Selecting item with 4.5 star rating",
        "Choosing variant: Size Medium, Color Black",
        "Adding item to cart",
        "Checking cart subtotal",
        "Looking for available promotions",
        "Verifying cart contents and total",
    ]

    overall_start = datetime.now()
    for i, desc in enumerate(demo_steps):
        await _aio.sleep(random.uniform(1.5, 4.0))
        elapsed = random.randint(800, 5000)
        state.steps.append(StepRecord(
            step=i + 1,
            description=desc,
            elapsed_ms=elapsed,
        ))

    total_ms = int((datetime.now() - overall_start).total_seconds() * 1000)

    # Randomly succeed or fail for demo purposes
    success = random.random() > 0.3  # 70% success rate
    state.status = "complete"
    state.success = success
    state.total_ms = total_ms
    state.input_tokens = random.randint(8000, 25000)
    state.output_tokens = random.randint(500, 3000)
    state.total_tokens = state.input_tokens + state.output_tokens

    if success:
        state.summary = f"Successfully completed the task on {domain}. All items added to cart within budget constraints."
    else:
        state.summary = f"Agent got stuck trying to interact with the variant picker on {domain}. Could not select the correct size from the dropdown."


@app.post("/benchmark/start")
async def start_benchmark_endpoint(req: StartRequest, user: dict = Depends(get_current_user), _: None = Depends(verify_internal_key)):
    user_id = user["user_id"]
    user_email = user.get("email", "").lower()
    is_admin = user_email in ADMIN_EMAILS

    active = _active_runs.get(user_id, 0)
    if active >= _MAX_CONCURRENT_RUNS and not is_admin:
        raise HTTPException(status_code=429, detail={
            "error": "Too many runs in progress. Wait for one to finish.",
        })

    _evict_stale_runs()

    _active_runs[user_id] = active + 1
    run_id = str(uuid.uuid4())
    state = RunState(run_id=run_id, user_id=user_id)
    _runs[run_id] = state

    async def _run_and_decrement(state, url, goal, uid):
        try:
            if _check_demo_mode():
                await _demo_run(state, url, goal)
            else:
                await run_benchmark(state, url, goal)
        finally:
            _active_runs[uid] = max(0, _active_runs.get(uid, 1) - 1)

    asyncio.create_task(_run_and_decrement(state, req.url, req.goal, user_id))

    return {"run_id": run_id}


@app.get("/benchmark/status/{run_id}")
async def get_status(run_id: str, _: None = Depends(verify_internal_key)):
    state = _runs.get(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Not found")
    return state.to_response()


@app.post("/benchmark/generate-tasks")
async def generate_tasks_endpoint(req: GenerateTasksRequest, request: Request, _: None = Depends(verify_internal_key)):
    _check_task_gen_rate(request)
    if _check_demo_mode():
        import asyncio as _aio
        await _aio.sleep(1.5)  # Simulate generation delay
        domain = req.url.split("//")[-1].split("/")[0].replace("www.", "")
        return {"tasks": [
            {"id": 1, "label": f"Add a specific item to cart on {domain}", "goal": f"Go to {domain}.\nSearch for a popular product using the search bar.\nClick on the first result.\nSelect the default size and color options if applicable.\nClick 'Add to Cart' or 'Add to Bag'.\nVERIFY: Look for a cart icon badge showing '1', or a confirmation message."},
            {"id": 2, "label": f"Set address and add customized item on {domain}", "goal": f"Set delivery address to 1 Times Square, New York, NY 10036. Wait for autocomplete dropdown and select the first suggestion.\nBrowse to a product category or menu section.\nSelect a specific item and customize it (choose size, select options, set quantity to 2).\nClick 'Add to Cart' or 'Add to Order'.\nVERIFY: Cart shows the item with correct customizations and quantity of 2."},
            {"id": 3, "label": f"Add two different items to cart on {domain}", "goal": f"Set delivery address to 1 Times Square, New York, NY 10036. Select the first autocomplete suggestion.\nBrowse to a product section. Select the first item and add it to cart.\nGo back to browsing. Find a different product in a different category.\nAdd the second item to cart.\nVERIFY: Go to cart. Confirm it shows 2 distinct items. Both should have correct names and quantities."},
        ]}
    try:
        tasks = await fetch_and_generate(req.url)
        return {"tasks": tasks}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=502, detail="Could not access site")
    except Exception as e:
        raise HTTPException(status_code=500, detail="Task generation failed")

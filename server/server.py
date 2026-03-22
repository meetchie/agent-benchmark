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

from fastapi import FastAPI, HTTPException, Depends, Header, Request
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

# Demo mode — returns fake data without calling OpenAI or launching a browser
# Set DEMO_MODE=true in .env to enable
def _check_demo_mode() -> bool:
    import os
    return os.getenv("DEMO_MODE", "").lower() in ("1", "true", "yes")


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


# Track signups by IP: ip -> (count, first_time)
_signup_attempts: dict[str, tuple[int, float]] = {}
_MAX_SIGNUPS_PER_HOUR = 3


@app.post("/auth/signup")
async def auth_signup(req: AuthRequest, request: Request):
    import time
    client_ip = request.client.host if request.client else "unknown"

    # Check signup rate limit by IP
    if client_ip in _signup_attempts:
        count, first_time = _signup_attempts[client_ip]
        if time.time() - first_time > 3600:
            del _signup_attempts[client_ip]
        elif count >= _MAX_SIGNUPS_PER_HOUR:
            raise HTTPException(status_code=429, detail="Too many signups. Try again later.")

    try:
        result = await signup(req.email, req.password)
        # Track successful signup
        if client_ip in _signup_attempts:
            count, first_time = _signup_attempts[client_ip]
            _signup_attempts[client_ip] = (count + 1, first_time)
        else:
            _signup_attempts[client_ip] = (1, time.time())
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

    if _check_demo_mode():
        asyncio.create_task(_demo_run(state, req.url, req.goal))
    else:
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
    if _check_demo_mode():
        import asyncio as _aio
        await _aio.sleep(1.5)  # Simulate generation delay
        domain = req.url.split("//")[-1].split("/")[0].replace("www.", "")
        return {"tasks": [
            {"id": 1, "label": f"Build a $30-$40 cart from {domain}", "goal": f"Set delivery address to 1 Times Square, New York, NY 10036.\nBrowse available products on {domain} and select a category.\nAdd 3-4 items to cart while keeping the subtotal between $30-$40.\nIf subtotal exceeds $40, remove the most expensive item and find a cheaper alternative.\nVerify: all items are in cart, subtotal is between $30-$40."},
            {"id": 2, "label": f"Find cheapest option with filters on {domain}", "goal": f"Search for a popular product category on {domain}.\nApply at least two filters (e.g., price range, rating, availability).\nSort results by price low-to-high.\nSelect the cheapest item that has 4+ star reviews and is in stock.\nChoose a specific variant (size/color) if applicable.\nAdd to cart and verify: correct item, correct variant, price matches filter."},
            {"id": 3, "label": f"Multi-item order with constraints on {domain}", "goal": f"Set delivery address to 1 Times Square, New York, NY 10036.\nFind and add a main item priced between $15-$25 to cart.\nAdd a complementary item (accessory, side, or add-on) under $10.\nCheck if any promotions or deals apply and activate them.\nVerify the cart shows both items, total is under $35.\nCheck estimated delivery date and confirm it's within 5 business days."},
        ]}
    try:
        tasks = await fetch_and_generate(req.url)
        return {"tasks": tasks}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=502, detail={"error": "Could not access site", "detail": str(e)})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "Task generation failed", "detail": str(e)[:200]})

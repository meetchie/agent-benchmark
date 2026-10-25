"""
Benchmark HTTP Server — FastAPI server exposing benchmark start and status endpoints.

Start: uv run uvicorn server:app --port 8000 --reload

Endpoints:
  POST /benchmark/start           → { run_id, remaining, resets_in, limit }
  GET  /benchmark/status/{run_id} → RunState as JSON (see RunState.to_dict)
  POST /benchmark/cancel/{run_id} → { ok: true }
  POST /benchmark/generate-tasks  → { tasks: [{id, label, goal} x3] }
  GET  /benchmark/quota           → { remaining, resets_in, limit }
  GET  /health                    → { ok, browser_provider, provider, models, auth_mode,
                                      demo_mode, timeout_s }

Configuration (environment or .env; the model and browser settings are documented in
llm.py, browser_env.py and benchmark_runner.py):
  AUTH_MODE            none (default): no sign-in, every request is the user "local".
                       clerk: Clerk JWT in "Authorization: Bearer" (needs
                       CLERK_ISSUER_URL or CLERK_PUBLISHABLE_KEY).
  DAILY_RUN_QUOTA      runs per user per rolling 24 h; 0 = unlimited.
                       Default 0 with AUTH_MODE=none, 3 with AUTH_MODE=clerk.
  MAX_CONCURRENT_RUNS  runs one user may have going at once (default 2); 0 = unlimited.
  DEMO_MODE            true: canned runs and tasks, no API key and no browser needed.
  ALLOWED_ORIGINS      CORS origins (default: the Vite dev servers on localhost).
  INTERNAL_API_KEY     optional shared secret expected in "X-Internal-Key".
  RUNS_DIR             where finished runs are saved (see persistence.py).
The server refuses to start (with the reason) when a setting is invalid or the LLM
provider's API key is missing and DEMO_MODE is off.
"""

import runtime_env  # noqa: F401  (first: loads .env, turns browser-use telemetry off)

import asyncio
import json as _json
import logging
import os
import time as _time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

import llm
import persistence
from benchmark_runner import RunState, get_agent_timeout, run_benchmark
from task_generator import check_url, fetch_and_generate
from clerk_auth import verify_clerk_jwt

logger = logging.getLogger(__name__)

# In-memory run state store
_runs: dict[str, RunState] = {}
_run_tasks: dict[str, asyncio.Task] = {}  # run_id -> asyncio task (for cancellation)

# Run eviction settings
_MAX_STORED_RUNS = 200

# Per-user concurrency (active runs); the limit is MAX_CONCURRENT_RUNS
_active_runs: dict[str, int] = {}  # user_id -> count

# Internal API key for edge-to-backend auth
_INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

# Rate limiting for task generation
_task_gen_requests: dict[str, list[float]] = {}  # ip -> list of timestamps
_TASK_GEN_MAX_PER_MINUTE = 5

AUTH_NONE = "none"
AUTH_CLERK = "clerk"
LOCAL_USER_ID = "local"  # the one user when AUTH_MODE=none

_QUOTA_WINDOW = 24 * 60 * 60  # 24 hours in seconds


class ConfigError(RuntimeError):
    """A setting is missing or invalid. The message says what to change."""


def auth_mode() -> str:
    """AUTH_MODE: "none" (default) or "clerk"."""
    mode = (os.getenv("AUTH_MODE") or AUTH_NONE).strip().lower()
    if mode not in (AUTH_NONE, AUTH_CLERK):
        raise ConfigError(f"AUTH_MODE={mode!r} is not valid; use 'none' (no sign-in) or 'clerk'.")
    return mode


def _whole_number_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        raise ConfigError(f"{name}={raw.strip()!r} must be a whole number (0 means no limit).") from None
    if value < 0:
        raise ConfigError(f"{name}={value} must not be negative (0 means no limit).")
    return value


def daily_run_quota() -> int:
    """DAILY_RUN_QUOTA: runs per user per 24 h; 0 = unlimited. Default 0 (none) or 3 (clerk)."""
    return _whole_number_env("DAILY_RUN_QUOTA", 3 if auth_mode() == AUTH_CLERK else 0)


def max_concurrent_runs() -> int:
    """MAX_CONCURRENT_RUNS: runs one user may have going at once (default 2); 0 = unlimited."""
    return _whole_number_env("MAX_CONCURRENT_RUNS", 2)


def validate_startup() -> None:
    """Check the configuration; raises ConfigError with a message the user can act on.

    Runs when the server starts, so a missing API key stops the server there instead of
    failing the first run. DEMO_MODE needs no key and no browser, so it skips those checks.
    """
    mode = auth_mode()
    daily_run_quota()
    max_concurrent_runs()

    import benchmark_runner

    try:
        benchmark_runner.get_agent_timeout()
        benchmark_runner._validate_browser_config()
    except ValueError as e:
        raise ConfigError(str(e)) from None

    if mode == AUTH_CLERK:
        import clerk_auth
        try:
            clerk_auth._get_clerk_issuer()
        except Exception:
            raise ConfigError(
                "AUTH_MODE=clerk needs CLERK_ISSUER_URL or CLERK_PUBLISHABLE_KEY "
                "(or use AUTH_MODE=none for a local, single-user setup)."
            ) from None

    if _check_demo_mode():
        logger.warning("DEMO_MODE is on: runs and tasks are canned, no model or browser is used.")
        return

    try:
        provider = llm.provider()
        for role in llm.ROLES:
            llm.effort_for(role, llm.model_for(role))  # raises for a bad effort setting
    except llm.LLMError as e:
        raise ConfigError(str(e)) from None
    if not llm.provider_key_present():
        key = "OPENAI_API_KEY" if provider == llm.OPENAI else "ANTHROPIC_API_KEY"
        raise ConfigError(
            f"{key} is not set (LLM_PROVIDER={provider}). Put it in .env (copy .env.example) "
            f"or export it, or set DEMO_MODE=true to try the UI without any API key."
        )

    if benchmark_runner._get_browser_provider() == "local":
        import browser_env
        if not browser_env.chromium_path():
            logger.warning(
                "No local Chromium found: runs will fail until you install it with: %s",
                browser_env.INSTALL_HINT,
            )
    if mode == AUTH_NONE:
        logger.info("AUTH_MODE=none: no sign-in. Keep this server on localhost.")


def _quota_file() -> str:
    return str(persistence.runs_dir() / ".quota_data.json")


def _load_quota_data() -> dict[str, list[float]]:
    try:
        with open(_quota_file(), "r") as f:
            data = _json.load(f)
        # Clean expired entries on load
        now = _time.time()
        return {uid: [t for t in ts if now - t < _QUOTA_WINDOW] for uid, ts in data.items()}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}

def _save_quota_data():
    try:
        os.makedirs(os.path.dirname(_quota_file()), exist_ok=True)
        with open(_quota_file(), "w") as f:
            _json.dump(_user_run_timestamps, f)
    except OSError:
        pass

# Run start times per user, for the daily quota. Loaded lazily (first quota check or
# first quota-limited start) so that importing this module reads no files.
_user_run_timestamps: dict[str, list[float]] = {}
_quota_loaded = False


def _ensure_quota_loaded() -> None:
    global _quota_loaded
    if not _quota_loaded:
        _user_run_timestamps.update(_load_quota_data())
        _quota_loaded = True


def _get_quota(user_id: str) -> dict:
    """Return remaining runs and seconds until next reset for a user.

    With DAILY_RUN_QUOTA=0 there is no limit: ``limit`` is 0 and ``remaining`` is null
    (the UI shows no counter and never blocks a run).
    """
    limit = daily_run_quota()
    if limit == 0:
        return {"remaining": None, "resets_in": 0, "limit": 0}

    _ensure_quota_loaded()
    now = _time.time()
    timestamps = _user_run_timestamps.get(user_id, [])
    # Filter to only timestamps within the window
    recent = [t for t in timestamps if now - t < _QUOTA_WINDOW]
    _user_run_timestamps[user_id] = recent

    remaining = max(0, limit - len(recent))
    resets_in = 0
    if remaining == 0 and recent:
        # Time until the oldest run in the window expires
        resets_in = int(recent[0] + _QUOTA_WINDOW - now)

    return {"remaining": remaining, "resets_in": resets_in, "limit": limit}

# Demo mode — returns fake data without calling a model or launching a browser
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
    """If INTERNAL_API_KEY is set, require it in X-Internal-Key (a shared secret for a gateway in front)."""
    if not _INTERNAL_API_KEY:
        return  # Not configured (the default) — skip check
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


def configure_logging() -> None:
    """Log INFO and above to stderr from the moment the server starts.

    uvicorn sets up only its own loggers, and browser-use sets up the rest (root logger at
    INFO, its own line format, noisy HTTP libraries silenced) the first time a run
    imports it. Until then the INFO lines this app writes, such as the cost of a task
    generation or the startup notes, go nowhere. This does that setup at startup, by
    importing browser-use's logging module (importing the package runs its setup, and
    the explicit call keeps it that way if a later version stops doing so; it does
    nothing when a handler exists). The log therefore looks the same before and after
    the first run, and BROWSER_USE_LOGGING_LEVEL still applies. Without browser-use
    installed, a plain INFO handler is used.
    """
    try:
        from browser_use.logging_config import setup_logging
    except ImportError:
        logging.basicConfig(level=logging.INFO, format="%(levelname)-8s [%(name)s] %(message)s")
    else:
        setup_logging()


# Why the server could not start, kept for _StartupErrorMiddleware (None when it started).
_startup_error: ConfigError | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _startup_error
    configure_logging()
    # .env files are already loaded (runtime_env). Refuse to start on a bad setup.
    _startup_error = None
    try:
        validate_startup()
    except ConfigError as e:
        _startup_error = e
        raise
    yield


class _StartupErrorMiddleware:
    """When a bad setting stops the server, tell uvicorn the reason and nothing else.

    Starlette reports a failed lifespan to uvicorn as a full traceback; for a missing
    API key that buries the one sentence that says what to do. The exception still
    propagates (uvicorn exits with status 3); only the logged message is shortened.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "lifespan":
            await self.app(scope, receive, send)
            return

        async def send_short(message):
            if message["type"] == "lifespan.startup.failed" and _startup_error is not None:
                message = {**message, "message": str(_startup_error)}
            await send(message)

        await self.app(scope, receive, send_short)


app = FastAPI(title="Rindler Benchmark Server", lifespan=lifespan)
app.add_middleware(_StartupErrorMiddleware)

_ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5180,http://localhost:5173,http://127.0.0.1:5180,http://127.0.0.1:5173"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def get_current_user(authorization: str = Header(None)) -> dict:
    """The user making the request.

    AUTH_MODE=none (default): always the local user, no token needed.
    AUTH_MODE=clerk: verifies the Clerk JWT in the Authorization header.
    """
    if auth_mode() == AUTH_NONE:
        return {"user_id": LOCAL_USER_ID}
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.split(" ", 1)[1]
    try:
        claims = verify_clerk_jwt(token)
        return {"user_id": claims["sub"]}
    except Exception as e:
        logger.warning("Auth failed: %s: %s", type(e).__name__, e)
        raise HTTPException(status_code=401, detail="Invalid or expired token")


class StartRequest(BaseModel):
    url: str
    goal: str
    label: str = ""  # task label for persistence
    viewport_width: int | None = None
    viewport_height: int | None = None

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
    """Liveness plus the settings a client or a person debugging would ask about. Never keys."""
    from benchmark_runner import _get_browser_provider
    info = llm.describe()
    return {
        "ok": True,
        "browser_provider": _get_browser_provider(),
        "provider": info["provider"],
        "models": info["models"],
        "auth_mode": auth_mode(),
        "demo_mode": _check_demo_mode(),
        "timeout_s": max(1, round(get_agent_timeout())),  # BENCHMARK_TIMEOUT_S
    }


async def _demo_run(state: RunState, url: str, goal: str):
    """Simulate a benchmark run with fake steps for UI testing."""
    import asyncio as _aio
    import random
    from datetime import datetime
    from benchmark_runner import StepRecord

    domain = url.split("//")[-1].split("/")[0].replace("www.", "")
    # Canned and deliberately generic, so they fit whichever task was picked.
    demo_steps = [
        f"Navigating to {url}",
        f"Looking over the page on {domain}",
        "Searching for the product the task asks for",
        "Opening the first matching result",
        "Choosing the options the task asks for",
        "Adding the item to the cart",
        "Opening the cart",
        "Checking the item and quantity in the cart",
        "Confirming the cart total",
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

    success = random.random() > 0.3  # 70% success rate
    state.status = "analyzing"
    state.total_ms = total_ms
    state.input_tokens = random.randint(8000, 25000)
    state.output_tokens = random.randint(500, 3000)
    state.total_tokens = state.input_tokens + state.output_tokens
    # The tokens are made up and no model was called, so no dollar figure: the UI shows tokens only.
    state.cost_usd = None

    # Simulate the judge's analysis delay
    await _aio.sleep(2.0)

    state.phases = [
        {"name": "Open the site and find the product", "steps": [1, 2, 3], "total_ms": sum(s.elapsed_ms for s in state.steps[0:3]), "failed": False, "slow": False},
        {"name": "Open the product and choose options", "steps": [4, 5], "total_ms": sum(s.elapsed_ms for s in state.steps[3:5]), "failed": False, "slow": True},
        {"name": "Add it to the cart", "steps": [6, 7], "total_ms": sum(s.elapsed_ms for s in state.steps[5:7]), "failed": not success, "slow": False},
        {"name": "Check the cart", "steps": [8, 9], "total_ms": sum(s.elapsed_ms for s in state.steps[7:9]), "failed": False, "slow": False},
    ]

    if success:
        state.summary = f"Completed the task on {domain}: the item was added to the cart and the cart checked."
        state.result_state = "pass"
    else:
        state.summary = f"Could not complete the task on {domain}: the item did not end up in the cart."
        state.result_state = "fail"

    state.success = success
    state.status = "complete"


@app.post("/benchmark/start")
async def start_benchmark_endpoint(req: StartRequest, user: dict = Depends(get_current_user), _: None = Depends(verify_internal_key)):
    user_id = user["user_id"]

    # Same rules and messages as generate-tasks: a public http(s) site only, never this machine
    # or an internal address. Checked before the run is counted, so there is no await between
    # the concurrency check and the count. A demo run opens nothing, so there is nothing to guard.
    if not _check_demo_mode():
        try:
            await check_url(req.url)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    active = _active_runs.get(user_id, 0)
    max_active = max_concurrent_runs()
    if max_active and active >= max_active:
        raise HTTPException(status_code=429, detail={
            "error": "Too many runs in progress. Wait for one to finish.",
        })

    # Daily quota check (DAILY_RUN_QUOTA=0 means unlimited)
    quota_limit = daily_run_quota()
    if quota_limit:
        quota = _get_quota(user_id)
        if quota["remaining"] <= 0:
            hours = quota["resets_in"] // 3600
            mins = (quota["resets_in"] % 3600) // 60
            raise HTTPException(status_code=429, detail={
                "error": f"Daily limit reached. Resets in {hours}h {mins}m.",
                "resets_in": quota["resets_in"],
                "remaining": 0,
            })

    _evict_stale_runs()

    # Count the run as active before any await, so two quick requests cannot both pass the check.
    _active_runs[user_id] = active + 1
    run_id = str(uuid.uuid4())
    try:
        if quota_limit:
            # Record run timestamp for daily quota
            _user_run_timestamps.setdefault(user_id, []).append(_time.time())
            _save_quota_data()

        state = RunState(run_id=run_id, user_id=user_id, goal=req.goal)
        _runs[run_id] = state

        # Save the run's record (RUNS_DIR/<run_id>.json). Demo runs are not saved.
        if not _check_demo_mode():
            state.persisted_run_id = await persistence.persist_run_start(
                run_id=run_id,
                clerk_user_id=user_id,  # the signed-in user's id, or "local" without sign-in
                url=req.url,
                task_label=req.label,
                task_goal=req.goal,
                agent_model=state.agent_model,
            )  # None if the file could not be written

        viewport = None
        if req.viewport_width and req.viewport_height:
            viewport = {"width": req.viewport_width, "height": req.viewport_height}

        async def _run_and_decrement(state, url, goal, uid, vp):
            try:
                if _check_demo_mode():
                    await _demo_run(state, url, goal)
                else:
                    await run_benchmark(state, url, goal, viewport=vp)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Run %s crashed", state.run_id)
                if state.status in ("running", "analyzing"):
                    state.status = "error"
                    state.result_state = "error"
                    state.message = state.message or "The run encountered an error."
            finally:
                _active_runs[uid] = max(0, _active_runs.get(uid, 1) - 1)

        task = asyncio.create_task(_run_and_decrement(state, req.url, req.goal, user_id, viewport))
    except BaseException:
        # Nothing was started: give the slot back and forget the half-made run.
        _active_runs[user_id] = max(0, _active_runs.get(user_id, 1) - 1)
        _runs.pop(run_id, None)
        raise
    _run_tasks[run_id] = task
    task.add_done_callback(lambda _: _run_tasks.pop(run_id, None))

    quota = _get_quota(user_id)
    return {
        "run_id": run_id,
        "remaining": quota["remaining"],
        "resets_in": quota["resets_in"],
        "limit": quota["limit"],
    }


@app.get("/benchmark/quota")
async def get_quota(user: dict = Depends(get_current_user), _: None = Depends(verify_internal_key)):
    return _get_quota(user["user_id"])


@app.get("/benchmark/status/{run_id}")
async def get_status(run_id: str, _: None = Depends(verify_internal_key)):
    state = _runs.get(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Not found")
    return state.to_dict()


@app.post("/benchmark/cancel/{run_id}")
async def cancel_benchmark(run_id: str, _: None = Depends(verify_internal_key)):
    task = _run_tasks.get(run_id)
    if task and not task.done():
        task.cancel()
    state = _runs.get(run_id)
    if state and state.status in ("running", "analyzing"):
        state.status = "error"
        state.message = "Run cancelled by user."
        state.result_state = "error"
    return {"ok": True}


@app.post("/benchmark/generate-tasks")
async def generate_tasks_endpoint(
    req: GenerateTasksRequest,
    request: Request,
    _: None = Depends(verify_internal_key),
    user: dict = Depends(get_current_user),
):
    _check_task_gen_rate(request)
    if _check_demo_mode():
        import asyncio as _aio
        await _aio.sleep(1.5)  # Simulate generation delay
        domain = req.url.split("//")[-1].split("/")[0].replace("www.", "")
        return {"tasks": [
            {"id": 1, "label": f"Add a specific item to cart on {domain}", "goal": f"Go to {domain}.\nSearch for a popular product using the search bar.\nClick on the first result.\nSelect the default size and color options if applicable.\nClick 'Add to Cart' or 'Add to Bag'.\nVERIFY: Look for a cart icon badge showing '1', or a confirmation message."},
            {"id": 2, "label": f"Add an item in a chosen size or colour on {domain}", "goal": f"Go to {domain}.\nSearch for a popular product using the search bar.\nClick on the first result.\nChoose a size or colour other than the default.\nClick 'Add to Cart' or 'Add to Bag'.\nVERIFY: The cart shows the item with the size or colour that was chosen."},
            {"id": 3, "label": f"Add an item and check the cart total on {domain}", "goal": f"Go to {domain}.\nSearch for a popular product using the search bar.\nClick on the first result and add it to the cart.\nOpen the cart.\nVERIFY: The cart lists the item once and shows a total that matches the item's price."},
        ]}
    try:
        # Run in a task so it can be cancelled if the client disconnects
        gen_task = asyncio.create_task(fetch_and_generate(req.url))
        # Poll for client disconnect while waiting
        while not gen_task.done():
            if await request.is_disconnected():
                gen_task.cancel()
                raise HTTPException(status_code=499, detail="Client disconnected")
            await asyncio.sleep(0.2)
        tasks = gen_task.result()
        return {"tasks": tasks}
    except asyncio.CancelledError:
        raise HTTPException(status_code=499, detail="Client disconnected")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except llm.LLMError as e:
        logger.error("Task generation: model call failed (%s): %s", e.kind, e)
        if e.kind == "api":
            # Usually a bad or exhausted API key, or the API being down.
            raise HTTPException(
                status_code=502,
                detail="The language model request failed. Check the API key and the server log.",
            )
        raise HTTPException(status_code=500, detail="Task generation failed")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Task generation failed")
        raise HTTPException(status_code=500, detail="Task generation failed")

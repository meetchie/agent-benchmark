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
from task_generator import fetch_and_generate
# In-memory run state store
_runs: dict[str, RunState] = {}  # No eviction — intended for short-lived dev sessions only

# Demo mode — returns fake data without calling OpenAI or launching a browser
# Set DEMO_MODE=true in .env to enable
def _check_demo_mode() -> bool:
    import os
    return os.getenv("DEMO_MODE", "").lower() in ("1", "true", "yes")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load .env files
    from dotenv import load_dotenv
    import os
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=False)
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
async def start_benchmark_endpoint(req: StartRequest):
    run_id = str(uuid.uuid4())
    state = RunState(run_id=run_id)
    _runs[run_id] = state

    if _check_demo_mode():
        asyncio.create_task(_demo_run(state, req.url, req.goal))
    else:
        asyncio.create_task(run_benchmark(state, req.url, req.goal))

    return {"run_id": run_id}


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

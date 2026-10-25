"""Small builders shared by the CLI tests."""

from datetime import datetime, timedelta, timezone

from benchcli import results

TASK = {
    "id": "t1",
    "name": "Add the towel",
    "goal": "Go to the shop. Add the Hair Towel Wrap to the cart and report the cart.",
    "start_url": "https://shop.example.com",
    "success_criteria": "The cart holds a Hair Towel Wrap at $35.00.",
    "max_steps": 12,
}


def make_record(
    task=None,
    *,
    agent="rindler",
    verdict=None,
    steps=3,
    cost=0.01,
    duration_s=10.0,
    success=True,
    model="claude-sonnet-5-5",
    max_steps=12,
    category=None,
    judge_cost=None,
    final_report="Cart: Hair Towel Wrap x1 $35.00",
):
    """A finished (and optionally judged) result record with ``steps`` identical steps."""
    task = task or TASK
    start = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)
    rows = [
        results.make_step(i + 1, "click", tokens_input=1000, tokens_output=50, cost_usd=cost / max(steps, 1))
        for i in range(steps)
    ]
    record = results.new_result(
        task, agent=agent, model=model, site="shop", max_steps=max_steps, started_at=start,
        finished_at=start + timedelta(seconds=duration_s), steps=rows, success=success, final_report=final_report,
    )
    if verdict:
        record["result"]["verdict"] = verdict
        record["result"]["failure_category"] = category
    if judge_cost is not None:
        record["judge"] = {"model": model, "cost_usd": judge_cost}
    return record

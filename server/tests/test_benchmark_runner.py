import pytest
from benchmark_runner import StepRecord, RunState


def make_step(n: int, has_screenshot: bool = True) -> StepRecord:
    return StepRecord(
        step=n,
        description=f"Step {n}",
        elapsed_ms=500,
        screenshot_b64="data:image/jpeg;base64,abc" if has_screenshot else None,
    )


def test_running_response_omits_screenshots_except_latest():
    state = RunState(run_id="test-1")
    state.steps = [make_step(1), make_step(2), make_step(3)]

    resp = state.to_response()

    assert resp["status"] == "running"
    assert len(resp["steps"]) == 3
    # Only last step has screenshot
    assert "screenshot_b64" not in resp["steps"][0]
    assert "screenshot_b64" not in resp["steps"][1]
    assert "screenshot_b64" in resp["steps"][2]


def test_complete_response_includes_summary():
    state = RunState(run_id="test-2", status="complete", success=True,
                     summary="Added item to cart.", total_ms=12000)
    state.steps = [make_step(1)]

    resp = state.to_response()

    assert resp["status"] == "complete"
    assert resp["success"] is True
    assert resp["summary"] == "Added item to cart."
    assert resp["total_ms"] == 12000


def test_error_response():
    state = RunState(run_id="test-3", status="error", message="Container error")
    resp = state.to_response()
    assert resp["status"] == "error"
    assert resp["message"] == "Container error"

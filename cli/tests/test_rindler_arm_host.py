"""The Rindler arm against the real local host, driving a copy of prose on 127.0.0.1.

These run the shipped cli/mappings/prose.json and cli/extractors/prose.js in headless
Chromium (skipped, with the reason, when none is installed or it cannot start).
The model is scripted, so nothing here costs anything.
"""

import json

import pytest

import cli_fakes
from benchcli import rindler_arm, sites
from cli_helpers import TASK
from prose_fixture import ProseShop, localize


def _no_chromium_reason() -> str | None:
    """Why these tests cannot drive a Chromium here (none installed, or it cannot start), or None."""
    try:
        import browser_env

        return browser_env.chromium_problem()
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


_NO_CHROMIUM = _no_chromium_reason()


browser = pytest.mark.skipif(_NO_CHROMIUM is not None, reason=f"no Chromium that starts: {_NO_CHROMIUM}")
pytestmark = browser


@pytest.fixture(scope="module")
def shop():
    with ProseShop() as shop:
        yield shop


@pytest.fixture
def prose(shop):
    shop.cart.clear()
    shop.requests.clear()
    return localize(sites.load_site("prose").mapping, shop.base)


def task_for(shop, **extra):
    return {**TASK, "id": "towel", "start_url": shop.base, **extra}


def tool_results(request):
    """Every tool_result the model was shown, parsed, in order."""
    out = []
    for message in request["messages"]:
        if message["role"] == "user" and isinstance(message["content"], list):
            out += [json.loads(b["content"]) for b in message["content"] if b.get("type") == "tool_result"
                    and not b["content"].startswith("Only one")]
    return out


def keys_of(envelopes):
    top, data = set(), set()
    for env in envelopes:
        top |= set(env)
        data |= set(env.get("data") or {})
    return top, data


FLOW = [
    ("view_accessories", {}),
    ("view_product", {"item": "Hair Towel Wrap"}),
    ("add_to_cart", {"item": "Hair Towel Wrap"}),
    ("view_cart", {}),
]


def scripted(flow=FLOW, report="Cart: Hair Towel x1 $35.00"):
    return [cli_fakes.tool_response(n, a) for n, a in flow] + [
        cli_fakes.tool_response("done", {"success": True, "message": report})]


async def test_the_flow_runs_on_the_shipped_mapping(shop, prose, tmp_path, monkeypatch):
    calls = cli_fakes.install(monkeypatch, *scripted())
    record = await rindler_arm.run_rindler_task(
        task_for(shop), mapping=prose, model="claude-sonnet-5-5", max_steps=10, results_dir=tmp_path, site="prose",
        timeout_s=120,
    )
    assert record["error"] is None and record["result"]["success"] is True
    assert [s["action"] for s in record["steps"]] == ["start_session", *[n for n, _ in FLOW], "done"]
    assert [s["screen"] for s in record["steps"][:-1]] == [
        "homepage", "accessories", "product_detail", "product_detail", "cart"]
    assert [item["cart_name"] for item in shop.cart] == ["Hair Towel"]  # the click really happened
    assert record["tools"] == sorted(prose.actions)
    assert all(s["error"] is None for s in record["steps"])
    assert len(calls) == 5


async def test_the_prompt_documents_every_field_the_host_returns(shop, prose, tmp_path, monkeypatch):
    calls = cli_fakes.install(monkeypatch, *scripted([*FLOW, ("view_product", {"item": "Ghost Product"})]))
    await rindler_arm.run_rindler_task(
        task_for(shop), mapping=prose, model="claude-sonnet-5-5", max_steps=10, results_dir=tmp_path, site="prose",
        timeout_s=120,
    )
    seen = tool_results(calls[-1])
    assert any("error" in env for env in seen)  # the ghost product came back as an error envelope
    top, data = keys_of(seen)
    prompt = rindler_arm.SYSTEM_PROMPT
    for key in top | data | {"code", "message"}:
        assert f'"{key}"' in prompt, f"the host returns {key!r} but the system prompt does not mention it"
    # nothing the model sees points at a tool it does not have
    for env in seen:
        assert "start_session" not in env.get("global_actions", []) + env.get("available_actions", [])


async def test_a_run_that_does_not_succeed_leaves_a_screenshot(shop, prose, tmp_path, monkeypatch):
    cli_fakes.install(monkeypatch, cli_fakes.tool_response("view_accessories"))
    record = await rindler_arm.run_rindler_task(
        task_for(shop), mapping=prose, model="claude-sonnet-5-5", max_steps=2, results_dir=tmp_path, site="prose",
        timeout_s=120,
    )
    assert record["error"] == "did not call done within 2 steps"
    shot = tmp_path / "rindler" / record["failure_screenshots"][0]
    assert shot.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert record["steps"][-1]["screenshot_path"] == record["failure_screenshots"][0]


async def test_a_start_url_outside_the_mapping_is_a_start_error(shop, prose, tmp_path, monkeypatch):
    calls = cli_fakes.install(monkeypatch, cli_fakes.tool_response("done", {"success": True, "message": "x"}))
    record = await rindler_arm.run_rindler_task(
        task_for(shop, start_url="https://example.org/"), mapping=prose, model="claude-sonnet-5-5", max_steps=3,
        results_dir=tmp_path, site="prose", timeout_s=60,
    )
    assert calls == [] and "no_site_config" in record["error"] and record["stats"]["total_steps"] == 0

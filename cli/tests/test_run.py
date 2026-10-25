"""cli/run.py end to end with fake arms and a scripted judge: wiring, caching, budgets."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import browser_env
import cli_fakes
import llm
import run
from benchcli import browseruse_arm, rindler_arm, sites
from cli_helpers import make_record

CLI = Path(__file__).resolve().parent.parent


# -- argument parsing ----------------------------------------------------------------------


def test_defaults_and_any_model_id():
    args = run.parse_args(["prose"])
    assert args.site == "prose" and args.model is None and args.judge_model is None
    assert args.max_steps is None and args.task is None and args.timeout == run.DEFAULT_TIMEOUT_S
    # the March choices (gpt-4o, gpt-4o-mini, claude-sonnet) are gone; any real model id is accepted
    assert run.parse_args(["prose", "--model", "claude-haiku-5-5"]).model == "claude-haiku-5-5"
    assert run.parse_args(["prose", "--model", "gpt-4o"]).model == "gpt-4o"


def test_task_flag_repeats_and_splits_on_commas():
    args = run.parse_args(["prose", "--task", "add-candle,add-hair-towel", "--task", "browse-accessories"])
    assert args.task == ["add-candle", "add-hair-towel", "browse-accessories"]


@pytest.mark.parametrize("argv", [
    ["prose", "--browseruse-only", "--rindler-only"],
    ["prose", "--max-steps", "0"],
    ["prose", "--timeout", "-1"],
    [],
])
def test_bad_arguments_exit(argv):
    with pytest.raises(SystemExit):
        run.parse_args(argv)


# -- information flags (no key, no browser) ----------------------------------------------


async def test_show_tools_lists_the_mapping_tools_without_a_key(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert await run.main(["prose", "--show-tools"]) == 0
    out = capsys.readouterr().out
    for name in ("view_accessories", "view_gift_cards", "view_product", "add_to_cart", "view_cart", "done"):
        assert name in out
    assert "start_session" not in out and "prose.js" in out


async def test_list_tasks(capsys):
    assert await run.main(["prose", "--list-tasks"]) == 0
    out = capsys.readouterr().out
    assert "add-hair-towel" in out and out.count("max_steps") == 10


async def test_unknown_site_or_task_exits_with_a_message(capsys):
    with pytest.raises(SystemExit) as exc:
        await run.main(["nosuchsite"])
    assert exc.value.code == 2 and "no mapping file" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        await run.main(["prose", "--task", "nope"])
    assert "unknown task id" in capsys.readouterr().err


# -- preflight -----------------------------------------------------------------------------


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    monkeypatch.setattr(browser_env, "chromium_path", lambda: "/fake/chromium")


def test_preflight_needs_only_the_anthropic_key_and_a_chromium(ready, capsys):
    site = sites.load_site("prose")
    run.preflight(site, site.tasks)  # passes with no OPENAI_API_KEY anywhere
    assert "Prerequisites OK" in capsys.readouterr().out


def test_preflight_reports_every_problem_at_once(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(browser_env, "chromium_path", lambda: None)
    site = sites.load_site("prose")
    leaky = [dict(site.tasks[0], goal="First call view_accessories, then ask Rindler.")]
    with pytest.raises(SystemExit) as exc:
        run.preflight(site, leaky)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "ANTHROPIC_API_KEY" in err and "playwright install chromium" in err
    assert "view_accessories, rindler" in err and "3 problem(s)" in err
    assert "OPENAI" not in err


# -- a whole run with fake arms -----------------------------------------------------------


class Arms:
    """Replaces both arm runners; records how each was called."""

    def __init__(self, monkeypatch, bu_verdict_success=False, ri_success=True):
        self.calls = []
        self.bu_success, self.ri_success = bu_verdict_success, ri_success

        async def fake_bu(task, **kw):
            self.calls.append(("browseruse", task["id"], kw))
            return make_record(task, agent="browseruse", success=self.bu_success, steps=9, cost=0.5,
                               model=kw["model"], max_steps=kw["max_steps"])

        async def fake_ri(task, **kw):
            self.calls.append(("rindler", task["id"], kw))
            return make_record(task, agent="rindler", success=self.ri_success, steps=4, cost=0.05,
                               model=kw["model"], max_steps=kw["max_steps"])

        monkeypatch.setattr(browseruse_arm, "run_browseruse_task", fake_bu)
        monkeypatch.setattr(rindler_arm, "run_rindler_task", fake_ri)

    def of(self, agent):
        return [c for c in self.calls if c[0] == agent]


def judge_replies(monkeypatch, *verdicts):
    return cli_fakes.install(monkeypatch, *[
        cli_fakes.text_response({"verdict": v, "reasoning": f"judged {v}", "failure_category": "none" if v == "pass" else "wrong_action"})
        for v in verdicts
    ])


@pytest.fixture
def arms(monkeypatch, ready, tmp_path):
    monkeypatch.setattr(run, "RESULTS_ROOT", tmp_path / "results")
    return Arms(monkeypatch)


def summary_of(tmp_path):
    [path] = (tmp_path / "results").glob("prose-*/summary.json")
    return json.loads(path.read_text())


async def test_both_arms_get_the_same_model_and_step_budget(arms, monkeypatch, tmp_path):
    judge_replies(monkeypatch, "fail", "pass")
    assert await run.main(["prose", "--task", "add-hair-towel", "--max-steps", "7"]) == 0
    (_, _, bu), (_, _, ri) = arms.of("browseruse")[0], arms.of("rindler")[0]
    assert bu["max_steps"] == ri["max_steps"] == 7
    assert bu["model"] == ri["model"] == "claude-sonnet-5-5"
    assert bu["timeout_s"] == ri["timeout_s"] == run.DEFAULT_TIMEOUT_S
    summary = summary_of(tmp_path)
    assert summary["benchmark"]["arms_run"] == {"browseruse": True, "rindler": True}
    assert (summary["browseruse"]["pass"], summary["rindler"]["pass"]) == (0, 1)
    assert summary["per_task"][0]["winner"] == "rindler"
    assert summary["comparison"]["success_rate_delta"] == 1.0


async def test_without_max_steps_each_arm_gets_the_tasks_own_budget(arms, monkeypatch):
    judge_replies(monkeypatch, "pass", "pass")
    await run.main(["prose", "--task", "add-hair-towel"])
    own = next(t for t in sites.load_site("prose").tasks if t["id"] == "add-hair-towel")["max_steps"]
    assert arms.of("browseruse")[0][2]["max_steps"] == arms.of("rindler")[0][2]["max_steps"] == own


async def test_the_two_arms_can_be_run_in_separate_commands(arms, monkeypatch, tmp_path, capsys):
    calls = judge_replies(monkeypatch, "fail", "pass")
    await run.main(["prose", "--task", "add-hair-towel", "--browseruse-only"])
    first = summary_of(tmp_path)
    assert first["benchmark"]["arms_run"] == {"browseruse": True, "rindler": False}
    assert first["comparison"] == {} and arms.of("rindler") == []
    assert len(calls) == 1  # the stand-in for the arm that was not run is never judged

    await run.main(["prose", "--task", "add-hair-towel", "--rindler-only"])
    second = summary_of(tmp_path)
    assert second["benchmark"]["arms_run"] == {"browseruse": True, "rindler": True}
    assert len(arms.of("browseruse")) == 1  # the saved result was used, not re-run
    assert len(calls) == 2  # and not judged again
    assert "Using saved browseruse result" in capsys.readouterr().out
    assert (second["browseruse"]["pass"], second["rindler"]["pass"]) == (0, 1)
    assert second["per_task"][0]["winner"] == "rindler"


async def test_a_saved_result_is_reused_until_the_model_or_budget_changes(arms, monkeypatch):
    judge_replies(monkeypatch, "pass")
    await run.main(["prose", "--task", "add-hair-towel"])
    await run.main(["prose", "--task", "add-hair-towel"])
    assert len(arms.of("browseruse")) == len(arms.of("rindler")) == 1
    await run.main(["prose", "--task", "add-hair-towel", "--model", "claude-haiku-5-5"])
    assert len(arms.of("browseruse")) == len(arms.of("rindler")) == 2  # another model: not comparable, re-run
    await run.main(["prose", "--task", "add-hair-towel", "--model", "claude-haiku-5-5", "--max-steps", "9"])
    assert len(arms.of("browseruse")) == 3
    await run.main(["prose", "--task", "add-hair-towel", "--model", "claude-haiku-5-5", "--max-steps", "9", "--fresh"])
    assert len(arms.of("browseruse")) == 4


async def test_fresh_reruns_only_the_selected_phase(arms, monkeypatch):
    judge_replies(monkeypatch, "pass")
    await run.main(["prose", "--task", "add-hair-towel"])
    await run.main(["prose", "--task", "add-hair-towel", "--rindler-only", "--fresh"])
    assert len(arms.of("rindler")) == 2 and len(arms.of("browseruse")) == 1


async def test_judge_failures_are_error_verdicts_and_the_summary_still_writes(arms, monkeypatch, tmp_path):
    import anthropic
    import httpx

    response = httpx.Response(401, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"), json={})
    cli_fakes.install(monkeypatch, anthropic.APIStatusError("bad key", response=response, body=None))
    assert await run.main(["prose", "--task", "add-hair-towel"]) == 0
    summary = summary_of(tmp_path)
    assert summary["browseruse"]["error"] == summary["rindler"]["error"] == 1
    assert summary["per_task"][0]["browseruse"]["verdict"] == "error"


async def test_a_judge_error_is_tried_again_on_the_next_run(arms, monkeypatch, tmp_path):
    import anthropic
    import httpx

    response = httpx.Response(401, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"), json={})
    cli_fakes.install(monkeypatch, anthropic.APIStatusError("bad key", response=response, body=None))
    await run.main(["prose", "--task", "add-hair-towel"])
    assert summary_of(tmp_path)["browseruse"]["error"] == 1

    judge_replies(monkeypatch, "pass")
    await run.main(["prose", "--task", "add-hair-towel"])
    summary = summary_of(tmp_path)
    assert (summary["browseruse"]["pass"], summary["rindler"]["pass"], summary["rindler"]["error"]) == (1, 1, 0)
    assert len(arms.of("browseruse")) == 1  # judged again, not run again


async def test_an_unpriced_model_is_flagged_up_front(arms, monkeypatch, capsys):
    judge_replies(monkeypatch, "pass")
    await run.main(["prose", "--task", "add-hair-towel", "--model", "claude-nonesuch-1"])
    assert "no prices for claude-nonesuch-1" in capsys.readouterr().out


async def test_judge_model_flag_and_env_reach_the_judge(arms, monkeypatch):
    calls = judge_replies(monkeypatch, "pass")
    await run.main(["prose", "--task", "add-hair-towel", "--judge-model", "claude-opus-5-5"])
    assert {c["model"] for c in calls} == {"claude-opus-5-5"}


# -- the retired stack stays retired -------------------------------------------------------

RETIRED = ("psycopg2", "MGMT_DATABASE_URL", "RUNTIME_DATABASE_URL", "REDIS_URL", "oauth", "OAuth", "mcp.client",
           "sse_client", "packages/mcp-server", "go run", "BENCHMARK_USER_EMAIL", "get_llm_by_name", "OPENAI_API_KEY",
           "gpt-4o", "langchain", ".env.local")


def test_no_trace_of_the_hosted_stack_in_the_cli_code():
    files = [CLI / "run.py", CLI / "visualize.py", *(CLI / "benchcli").glob("*.py")]
    for path in files:
        text = path.read_text()
        for word in RETIRED:
            assert word not in text, f"{path.name} still mentions {word!r}"
    assert not (CLI / "pyproject.toml").exists() and not (CLI / "uv.lock").exists()


# -- the shell scripts work from any directory -----------------------------------------------


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
def test_bench_and_viz_scripts_run_from_another_directory(tmp_path):
    env = {k: v for k, v in __import__("os").environ.items() if k != "ANTHROPIC_API_KEY"}
    shown = subprocess.run([str(CLI / "bench.sh"), "prose", "--show-tools"], cwd=tmp_path, env=env,
                           capture_output=True, text=True, timeout=240)
    assert shown.returncode == 0, shown.stderr
    assert "view_accessories" in shown.stdout

    rdir = tmp_path / "prose-2026-10-24"
    rdir.mkdir()
    from benchcli import results

    task = sites.load_site("prose").tasks[0]
    bu = [make_record(task, agent="browseruse", verdict="fail", success=False, category="wrong_action")]
    ri = [make_record(task, agent="rindler", verdict="pass")]
    results.write_summary(rdir, results.build_summary("prose", "prose.com", [task], bu, ri, model="m", judge_model="m"))
    drawn = subprocess.run([str(CLI / "viz.sh"), rdir.name], cwd=tmp_path, env=env, capture_output=True, text=True,
                           timeout=240)  # a path relative to the current directory
    assert drawn.returncode == 0, drawn.stderr
    assert (rdir / "charts" / "success_rate.png").is_file()

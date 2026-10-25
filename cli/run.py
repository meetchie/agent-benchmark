"""
Rindler comparison CLI: BrowserUse vs Rindler on one site.

Both arms get the same tasks, the same model and the same step budget. The BrowserUse arm
(browser-use on a local headless Chromium) has no site knowledge. The Rindler arm drives
the site through its Rindler mapping, run in-process by the repo's rindler_local host.
An LLM judge grades each run against the task's success criteria.

Needs only ANTHROPIC_API_KEY. Run it through the server uv project (bench.sh does):

    cli/bench.sh prose --task add-hair-towel          # both arms, one task
    cli/bench.sh prose --browseruse-only              # phase 1 only
    cli/bench.sh prose --rindler-only --task add-candle
    cli/bench.sh prose --show-tools                   # the tools the mapping gives the Rindler arm
    cli/viz.sh cli/results/prose-<date>               # charts

Results go to cli/results/<site>-<date>/ (see benchcli/results.py). A phase that is
skipped uses the saved result of the same task, model and step budget if there is one,
so the two arms can be run in separate commands and still be compared.
"""

import runtime_env  # noqa: F401  (loads .env, turns browser-use telemetry off; must come first)

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

import constants
import llm
from benchcli import browseruse_arm, judge, results, rindler_arm, sites
from rindler_local import build_tools

SCRIPT_DIR = Path(__file__).resolve().parent
RESULTS_ROOT = SCRIPT_DIR / "results"
DEFAULT_TIMEOUT_S = 900.0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Benchmark one site: BrowserUse vs Rindler, same model, same step budget",
    )
    parser.add_argument("site", help="Site name: the file name in mappings/ and instructions/ (for example prose)")
    parser.add_argument(
        "--model", default=None,
        help="Model id for both agents (default: BENCHMARK_AGENT_MODEL, else claude-sonnet-5-5)",
    )
    parser.add_argument(
        "--judge-model", default=None,
        help="Model id for the judge (default: BENCHMARK_JUDGE_MODEL, else claude-sonnet-5-5)",
    )
    parser.add_argument(
        "--task", action="append", default=None, metavar="ID",
        help="Run only this task id (repeat the flag or comma-separate; default: every task)",
    )
    parser.add_argument(
        "--max-steps", type=int, default=None,
        help="Step budget for both arms on every task (default: each task's own max_steps)",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_S,
        help=f"Seconds one run may take, per task and arm (default {DEFAULT_TIMEOUT_S:.0f}, 0 = no limit)",
    )
    parser.add_argument("--fresh", action="store_true", help="Re-run the selected phases, ignoring saved results")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--browseruse-only", action="store_true", help="Run only the BrowserUse phase")
    mode.add_argument("--rindler-only", action="store_true", help="Run only the Rindler phase")
    info = parser.add_mutually_exclusive_group()
    info.add_argument("--show-tools", action="store_true",
                      help="Print the tools the mapping gives the Rindler arm, then exit")
    info.add_argument("--list-tasks", action="store_true", help="Print the site's tasks, then exit")
    args = parser.parse_args(argv)
    if args.max_steps is not None and args.max_steps < 1:
        parser.error("--max-steps must be at least 1")
    if args.timeout < 0:
        parser.error("--timeout must not be negative")
    if args.task is not None:
        # Only a missing --task means every task. A value with no id in it ("," or "")
        # is a mistake, and reading it as "every task" would start every paid run.
        ids = []
        for item in args.task:
            found = [t.strip() for t in item.split(",") if t.strip()]
            if not found:
                parser.error(f"--task needs at least one task id, got {item!r} (--list-tasks shows them)")
            ids += found
        args.task = ids
    return args


def fail(message: str, code: int = 2):
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(code)


def preflight(site: sites.Site, tasks: list) -> None:
    """Everything that can be checked without spending money, before anything runs."""
    problems = []
    if not llm.provider_key_present():
        problems.append("no model API key: set ANTHROPIC_API_KEY (environment, server/.env or a repo-root .env)")
    try:
        import browser_env

        chromium = browser_env.chromium_problem()  # not installed, or installed but cannot start
        if chromium:
            problems.append(chromium)
    except Exception as exc:
        problems.append(str(exc))
    leaks = sites.task_text_leaks(tasks, site.mapping)
    for task_id, words in leaks.items():
        problems.append(
            f"task {task_id!r}: the goal names Rindler's interface ({', '.join(words)}); "
            "the BrowserUse arm gets the goal verbatim, so reword it"
        )
    if problems:
        print(f"\nPreflight failed, {len(problems)} problem(s):\n", file=sys.stderr)
        for i, problem in enumerate(problems, 1):
            print(f"  {i}. {problem}", file=sys.stderr)
        raise SystemExit(2)
    print("  Prerequisites OK")


def print_tools(site: sites.Site) -> None:
    tools = [t for t in build_tools(site.mapping) if t["name"] not in rindler_arm.HIDDEN_TOOLS]
    print(f"Tools the Rindler arm gets from mappings/{site.name}.json ({len(tools) + 1} with done):\n")
    for tool in tools:
        params = ", ".join(tool["inputSchema"].get("properties", {})) or "no arguments"
        print(f"  {tool['name']:<18} ({params})  {tool['description']}")
    print(f"  {'done':<18} (success, message)  {rindler_arm.DONE_TOOL['description'][:70]}...")
    print(f"\nPage extractor: {site.extractor.name if site.extractor else 'none'}")


def print_tasks(site: sites.Site) -> None:
    print(f"Tasks in instructions/{site.name}.yaml:\n")
    for task in site.tasks:
        print(f"  {task['id']:<26} max_steps {task['max_steps']:<3} {task['name']}")


async def run_phase(agent: str, tasks, skip: bool, args, models, site, results_dir) -> list:
    """Records for every task of one arm: run, loaded from the cache, or skipped stand-ins."""
    out = []
    for task in tasks:
        max_steps = sites.effective_max_steps(task, args.max_steps)
        cached = results.load_cached(results_dir, agent, task["id"], model=models["agent"], max_steps=max_steps)
        if skip:
            if cached:
                print(f"  Using saved {agent} result: {task['id']}")
                out.append(cached)
            else:
                out.append(results.skipped_result(
                    task, agent=agent, model=models["agent"], site=site.name, max_steps=max_steps,
                    reason=f"{agent} phase not run",
                ))
            continue
        if cached and not args.fresh:
            print(f"  Skipping (saved): {task['name']} ({task['id']})")
            out.append(cached)
            continue
        timeout = args.timeout or None
        if agent == "browseruse":
            record = await browseruse_arm.run_browseruse_task(
                task, model=models["agent"], max_steps=max_steps, results_dir=results_dir,
                site=site.name, timeout_s=timeout,
            )
        else:
            record = await rindler_arm.run_rindler_task(
                task, mapping=site.mapping, model=models["agent"], max_steps=max_steps,
                results_dir=results_dir, site=site.name, timeout_s=timeout,
            )
        results.save_result(results_dir, record)
        out.append(record)
    return out


async def judge_all(tasks, records_by_agent, models, results_dir) -> None:
    for i, task in enumerate(tasks):
        for agent in results.AGENTS:
            record = records_by_agent[agent][i]
            verdict = record["result"].get("verdict")
            if verdict == "skipped":
                continue
            if verdict and verdict != "error":  # a judge error is tried again on the next run
                print(f"  Skipping (already judged): {agent}/{task['id']}")
                continue
            await judge.judge_task(task, record, model=models["judge"])
            results.save_result(results_dir, record)
            res = record["result"]
            print(f"  {agent}/{task['id']}: {res['verdict']} - {(res.get('judge_reasoning') or '')[:70]}")


async def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        site = sites.load_site(args.site)
        tasks = sites.select_tasks(site.tasks, args.task)
    except sites.SiteError as exc:
        fail(str(exc))

    if args.show_tools:
        print_tools(site)
        return 0
    if args.list_tasks:
        print_tasks(site)
        return 0

    try:
        models = {"agent": args.model or llm.model_for("agent"), "judge": args.judge_model or llm.model_for("judge")}
    except llm.LLMError as exc:
        fail(str(exc))

    print(f"\n{'=' * 60}\n  RINDLER COMPARISON: {site.name}\n{'=' * 60}")
    print(f"  Agent model: {models['agent']} ({llm.provider()})")
    print(f"  Judge model: {models['judge']}")
    print(f"  Tasks:       {len(tasks)} of {len(site.tasks)}")
    budget = args.max_steps or "each task's own"
    print(f"  Step budget: {budget} (same for both arms)")
    print(f"  Date:        {date.today().isoformat()}")
    print(f"{'=' * 60}\n")

    if constants.cost_usd(models["agent"], 1_000_000, 1_000_000) is None:
        print(f"  Warning: no prices for {models['agent']} in server/constants.py, so its costs show as $0.")
    print("Checking inputs...")
    print(f"  Mapping: {len(site.mapping.screens)} screens, {len(site.mapping.actions)} actions, "
          f"extractor {site.extractor.name if site.extractor else 'none'}")
    preflight(site, tasks)
    results_dir = results.results_dir_for(RESULTS_ROOT, site.name)
    print(f"  Results directory: {results_dir}\n")

    print(f"{'=' * 60}\n  PHASE 1: BROWSERUSE{'  (skipped)' if args.rindler_only else ''}\n{'=' * 60}\n")
    bu_records = await run_phase("browseruse", tasks, args.rindler_only, args, models, site, results_dir)
    print(f"\n{'=' * 60}\n  PHASE 2: RINDLER{'  (skipped)' if args.browseruse_only else ''}\n{'=' * 60}\n")
    ri_records = await run_phase("rindler", tasks, args.browseruse_only, args, models, site, results_dir)

    print(f"\n{'=' * 60}\n  PHASE 3: JUDGE\n{'=' * 60}\n")
    await judge_all(tasks, {"browseruse": bu_records, "rindler": ri_records}, models, results_dir)

    print(f"\n{'=' * 60}\n  PHASE 4: SUMMARY\n{'=' * 60}\n")
    summary = results.build_summary(
        site.name, site.domain, tasks, bu_records, ri_records, model=models["agent"], judge_model=models["judge"],
    )
    path = results.write_summary(results_dir, summary)
    print(results.format_summary(summary))
    print(f"  Saved: {path}")
    print(f"\nComparison complete. Results: {results_dir}")
    print(f"Charts: cli/viz.sh {results_dir}")
    return 0


if __name__ == "__main__":
    import entrypoint

    sys.exit(entrypoint.run_cli(main()))

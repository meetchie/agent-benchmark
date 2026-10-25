"""Arena log analysis script.

Parses plaintext arena log files and produces a markdown comparison table
for A/B testing RINDLER vs BROWSERUSE (or any agents).

By default it reads both the archived March 2026 logs (arena_logs/) and new runs
(arena_runs/). Rows are grouped by scenario, agent and agent model, so March runs
(whose logs do not record the model; shown as "-") never mix with new ones.

Usage:
    python analyze_runs.py
    python analyze_runs.py --log-dir arena_runs            # new runs only
    python analyze_runs.py --agents RINDLER,BROWSERUSE
    python analyze_runs.py --scenarios shipt_add_to_cart,amazon_search
    python analyze_runs.py --since 2026-03-10
"""

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional


def parse_timestamp_from_filename(filename) -> Optional[datetime]:
    """Extract timestamp from arena log filename.

    Pattern: arena_<agent>_<company>_YYYYMMDD_HHMMSS.log
    """
    name = Path(filename).stem
    match = re.search(r"(\d{8})_(\d{6})$", name)
    if not match:
        return None
    return datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")


def parse_log_file(path: Path) -> dict:
    """Parse a single arena log file into a structured dict."""
    text = path.read_text()
    lines = text.split("\n")

    result = {
        "agent": None,
        "scenario": None,
        "success": False,
        "judge_verdict": None,
        "steps": 0,
        "tokens_input": 0,
        "tokens_output": 0,
        "cost_usd": 0.0,
        "duration_s": None,
        "model": None,
        "timestamp": parse_timestamp_from_filename(path.name),
        "path": str(path),
    }

    for line in lines:
        if line.startswith("Agent: "):
            result["agent"] = line.split("Agent: ", 1)[1].strip()
        elif line.startswith("Scenario: "):
            result["scenario"] = line.split("Scenario: ", 1)[1].strip()
        elif line.startswith("Agent Reported Success: ") or line.startswith("Success: "):
            if line.startswith("Agent Reported Success: "):
                val = line.split("Agent Reported Success: ", 1)[1].strip()
            else:
                val = line.split("Success: ", 1)[1].strip()
            result["success"] = val.lower() in ("true", "1", "yes")
        elif line.startswith("Status: "):
            val = line.split("Status: ", 1)[1].strip()
            # Fire-and-forget submissions: outcome unknown, treat as not-success
            result["success"] = False
        elif line.startswith("Agent Model: "):
            result["model"] = line.split("Agent Model: ", 1)[1].strip()
        elif line.startswith("Duration: "):
            try:
                result["duration_s"] = float(line.split("Duration: ", 1)[1].strip().rstrip("s"))
            except ValueError:
                pass
        elif line.startswith("Judge Verdict: "):
            result["judge_verdict"] = line.split("Judge Verdict: ", 1)[1].strip()
        elif line.startswith("Token Burn: "):
            match = re.search(r"\((\d[\d,]*)\s*in\s*/\s*(\d[\d,]*)\s*out\)", line)
            if match:
                result["tokens_input"] = int(match.group(1).replace(",", ""))
                result["tokens_output"] = int(match.group(2).replace(",", ""))
        elif line.startswith("Cost: "):
            cost_str = line.split("Cost: ", 1)[1].strip().lstrip("$")
            try:
                result["cost_usd"] = float(cost_str)
            except ValueError:
                pass

    # Count steps from telemetry events (JSON array is always last in the file)
    for i, line in enumerate(lines):
        if line.startswith("Telemetry Events:"):
            rest = "\n".join(lines[i + 1:])
            try:
                events = json.loads(rest.strip())
                result["steps"] = sum(1 for e in events if e.get("event_type") == "step_end")
            except json.JSONDecodeError:
                pass
            break

    return result


def aggregate_runs(runs: list[dict]) -> list[dict]:
    """Group runs by (scenario, agent, model) and compute aggregates."""
    groups = defaultdict(list)
    for run in runs:
        key = (run["scenario"], run["agent"], run.get("model") or "-")
        groups[key].append(run)

    table = []
    for (scenario, agent, model), group_runs in sorted(groups.items()):
        n = len(group_runs)
        successes = sum(1 for r in group_runs if r["success"])

        # Judge pass rate — exclude ERROR and None from denominator
        judge_eligible = [r for r in group_runs if r.get("judge_verdict") in ("PASS", "FAIL")]
        judge_passes = sum(1 for r in judge_eligible if r["judge_verdict"] == "PASS")
        judge_pass_rate = judge_passes / len(judge_eligible) if judge_eligible else 0.0

        avg_steps = sum(r["steps"] for r in group_runs) / n
        avg_cost = sum(r["cost_usd"] for r in group_runs) / n
        durations = [r["duration_s"] for r in group_runs if r.get("duration_s") is not None]
        avg_duration = sum(durations) / len(durations) if durations else None

        table.append({
            "scenario": scenario,
            "agent": agent,
            "model": model,
            "runs": n,
            "judged": len(judge_eligible),
            "avg_duration_s": avg_duration,
            "success_rate": successes / n,
            "judge_pass_rate": judge_pass_rate,
            "avg_steps": avg_steps,
            "avg_cost": avg_cost,
        })

    return table


def format_table(rows: list[dict]) -> str:
    """Format aggregated rows as a markdown table."""
    header = "| Scenario | Agent | Model | Runs | Success | Judge Pass | Avg Steps | Avg Duration | Avg Cost |"
    separator = "|----------|-------|-------|------|---------|------------|-----------|--------------|----------|"
    lines = [header, separator]

    for row in rows:
        success_pct = f"{row['success_rate']:.0%}"
        judged = row.get("judged")
        judge_pct = f"{row['judge_pass_rate']:.0%}" if judged else "n/a"
        if judged is not None and judged != row["runs"]:
            judge_pct += f" of {judged}"
        avg_steps = f"{row['avg_steps']:.1f}"
        duration = row.get("avg_duration_s")
        avg_duration = f"{duration:.1f}s" if duration is not None else "-"
        avg_cost = f"${row['avg_cost']:.4f}"
        lines.append(
            f"| {row['scenario']:<20s} | {row['agent']:<10s} | {row.get('model') or '-':<17s} | {row['runs']:<4d} "
            f"| {success_pct:<7s} | {judge_pct:<10s} | {avg_steps:<9s} | {avg_duration:<12s} | {avg_cost:<8s} |"
        )

    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Analyze arena run logs")
    parser.add_argument("--agents", help="Comma-separated agent filter (e.g., RINDLER,BROWSERUSE)")
    parser.add_argument("--scenarios", help="Comma-separated scenario filter")
    parser.add_argument("--since", help="Only include runs after this date (YYYY-MM-DD)")
    parser.add_argument("--log-dir", action="append", default=None,
                        help="Log directory; repeat for several (default: arena_logs and arena_runs)")
    args = parser.parse_args(argv)

    here = Path(__file__).parent
    log_dirs = [Path(d) for d in args.log_dir] if args.log_dir else [here / "arena_logs", here / "arena_runs"]
    existing = [d for d in log_dirs if d.exists()]
    if not existing:
        print(f"No logs directory found at {', '.join(str(d) for d in log_dirs)}")
        return

    log_files = sorted(p for d in existing for p in d.glob("arena_*.log"))
    if not log_files:
        print(f"No log files found in {', '.join(str(d) for d in existing)}")
        return

    since = None
    if args.since:
        since = datetime.strptime(args.since, "%Y-%m-%d")

    runs = []
    for path in log_files:
        run = parse_log_file(path)
        if run["agent"] is None or run["scenario"] is None:
            continue

        if args.agents:
            allowed = {a.strip().upper() for a in args.agents.split(",")}
            if run["agent"].upper() not in allowed:
                continue
        if args.scenarios:
            allowed = {s.strip() for s in args.scenarios.split(",")}
            if run["scenario"] not in allowed:
                continue
        if since and run["timestamp"] and run["timestamp"] < since:
            continue

        runs.append(run)

    if not runs:
        print("No matching runs found.")
        return

    table = aggregate_runs(runs)
    print(format_table(table))
    print(f"\n{len(runs)} runs across {len(table)} scenario/agent combinations")


if __name__ == "__main__":
    main()

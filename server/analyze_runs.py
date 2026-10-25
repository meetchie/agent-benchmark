"""Arena log analysis script.

Parses plaintext arena log files and produces a markdown comparison table
for A/B testing RINDLER vs BROWSERUSE (or any agents).

By default it reads both the archived March 2026 logs (arena_logs/) and new runs
(arena_runs/). Rows are grouped by scenario, agent and agent model, so March runs
(whose logs do not record the model; shown as "-") never mix with new ones.

Counts come with percentages ("59/60 (98.3%)"). "Judge Pass" is the judge's verdict
(runs it passed / runs it scored PASS or FAIL). "Reported" is only what the agent said
about itself ("Agent Reported Success"), so it can read 100% for an agent the judge fails.

Usage:
    python analyze_runs.py
    python analyze_runs.py --march-headline                # the March 2026 headline: 59/60 vs 1/60
    python analyze_runs.py --log-dir arena_runs            # new runs only
    python analyze_runs.py --agents RINDLER,BROWSERUSE
    python analyze_runs.py --scenarios shipt_add_to_cart,amazon_search
    python analyze_runs.py --since 2026-03-10
    python analyze_runs.py --since "2026-03-31 00:28:27" --until 2026-03-31

--since and --until take a date (YYYY-MM-DD) or a date and time (YYYY-MM-DD HH:MM[:SS], a "T"
works too). Both limits are inclusive. A bare --until date covers that whole day. The time
is the one in the log file name, which is the local time of the machine that ran the arena.
"""

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

# The March 2026 headline (README: Rindler 59/60 judge passes vs BrowserUse 1/60) is one task
# on one night: every BrowserUse log of vhlistings_bundle_promo plus the last 60 Rindler ones.
# Rindler logged four earlier runs that night (00:11 to 00:24) and two on 03-27, all before the
# final mapping version, so the cut is the first log of the final version.
MARCH_HEADLINE = {
    "scenario": "vhlistings_bundle_promo",
    "agents": "BROWSERUSE,RINDLER",
    "since": datetime(2026, 3, 31, 0, 28, 27),
    "until": datetime(2026, 3, 31, 23, 59, 59),
    "runs_per_agent": 60,
}

_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M")


def parse_when(text: str, end_of_day: bool = False) -> datetime:
    """Parse a date or a date and time. A bare date is midnight, or the last instant of that
    day when end_of_day is set (so ``--until 2026-03-31`` includes the whole of 03-31)."""
    text = text.strip()
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    try:
        day = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"{text!r} is not a date (YYYY-MM-DD) or a date and time (YYYY-MM-DD HH:MM[:SS])") from None
    return day.replace(hour=23, minute=59, second=59, microsecond=999999) if end_of_day else day


def _since_arg(text: str) -> datetime:
    try:
        return parse_when(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _until_arg(text: str) -> datetime:
    try:
        return parse_when(text, end_of_day=True)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


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

        # Judge pass rate: ERROR and missing verdicts stay out of the denominator
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
            "judge_passes": judge_passes,
            "reported": successes,
            "avg_duration_s": avg_duration,
            "success_rate": successes / n,
            "judge_pass_rate": judge_pass_rate,
            "avg_steps": avg_steps,
            "avg_cost": avg_cost,
        })

    return table


def format_count(count: int, total: int) -> str:
    """"59/60 (98.3%)", or "n/a" when there is nothing to divide by."""
    if not total:
        return "n/a"
    return f"{count}/{total} ({count / total:.1%})"


def format_table(rows: list[dict]) -> str:
    """Format aggregated rows as a markdown table, columns padded to line up in a terminal."""
    header = ["Scenario", "Agent", "Model", "Runs", "Judge Pass", "Reported", "Avg Steps", "Avg Duration", "Avg Cost"]
    body = []
    for row in rows:
        duration = row.get("avg_duration_s")
        body.append([
            row["scenario"], row["agent"], row.get("model") or "-", str(row["runs"]),
            format_count(row["judge_passes"], row["judged"]), format_count(row["reported"], row["runs"]),
            f"{row['avg_steps']:.1f}", f"{duration:.1f}s" if duration is not None else "-",
            f"${row['avg_cost']:.4f}",
        ])
    widths = [max(len(line[i]) for line in [header] + body) for i in range(len(header))]

    def line(cells):
        return "| " + " | ".join(cell.ljust(width) for cell, width in zip(cells, widths)) + " |"

    return "\n".join([line(header), "|" + "|".join("-" * (w + 2) for w in widths) + "|"] + [line(c) for c in body])


def table_notes(rows: list[dict]) -> str:
    """What the two rate columns mean, and when Judge Pass is out of fewer runs than Runs."""
    notes = ["Judge Pass: runs the judge passed / runs it scored PASS or FAIL. "
             "Reported: runs where the agent claimed success (its own word, not the judge's)."]
    if any(row["judged"] != row["runs"] for row in rows):
        notes.append("Some rows have fewer judged runs than runs: ERROR and missing verdicts are left out of Judge Pass.")
    return "\n".join(notes)


def filter_runs(runs: list[dict], agents: Optional[str] = None, scenarios: Optional[str] = None,
                since: Optional[datetime] = None, until: Optional[datetime] = None) -> list[dict]:
    """Keep the runs matching every given filter. ``agents`` and ``scenarios`` are comma-separated;
    ``since`` and ``until`` are inclusive. A run whose file name carries no time cannot be placed,
    so it is dropped whenever either time limit is set."""
    allowed_agents = {a.strip().upper() for a in agents.split(",")} if agents else None
    allowed_scenarios = {s.strip() for s in scenarios.split(",")} if scenarios else None
    kept = []
    for run in runs:
        if allowed_agents and run["agent"].upper() not in allowed_agents:
            continue
        if allowed_scenarios and run["scenario"] not in allowed_scenarios:
            continue
        if since or until:
            when = run["timestamp"]
            if when is None or (since and when < since) or (until and when > until):
                continue
        kept.append(run)
    return kept


def headline_summary(runs: list[dict]) -> list[str]:
    """One line per agent for --march-headline, plus a warning for any agent short of the expected runs."""
    lines = []
    by_agent = defaultdict(list)
    for run in runs:
        by_agent[run["agent"]].append(run)
    expected = MARCH_HEADLINE["runs_per_agent"]
    passes = []
    for agent in sorted(by_agent):
        group = by_agent[agent]
        judged = [r for r in group if r.get("judge_verdict") in ("PASS", "FAIL")]
        passed = sum(1 for r in judged if r["judge_verdict"] == "PASS")
        passes.append(f"{agent} {format_count(passed, len(judged))}")
        if len(group) != expected:
            lines.append(f"Warning: {agent} has {len(group)} runs here, the headline uses {expected}. "
                         "Is the March archive complete?")
    return ["Headline (judge pass): " + " vs ".join(passes)] + lines


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze arena run logs")
    parser.add_argument("--agents", help="Comma-separated agent filter (e.g., RINDLER,BROWSERUSE)")
    parser.add_argument("--scenarios", help="Comma-separated scenario filter")
    parser.add_argument("--since", type=_since_arg, metavar="WHEN",
                        help="Only runs at or after this date (YYYY-MM-DD) or date and time (YYYY-MM-DD HH:MM[:SS])")
    parser.add_argument("--until", type=_until_arg, metavar="WHEN",
                        help="Only runs at or before this date (the whole day) or date and time")
    parser.add_argument("--march-headline", action="store_true",
                        help="Print the March 2026 headline table: all 60 BrowserUse and the last 60 Rindler "
                             "vhlistings_bundle_promo logs (Rindler 59/60 vs BrowserUse 1/60). Reads arena_logs "
                             "unless --log-dir is given; cannot be combined with the filters above")
    parser.add_argument("--log-dir", action="append", default=None,
                        help="Log directory; repeat for several (default: arena_logs and arena_runs)")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    here = Path(__file__).parent
    if args.march_headline:
        if args.agents or args.scenarios or args.since or args.until:
            parser.error("--march-headline selects its own runs; drop --agents, --scenarios, --since and --until")
        args.agents = MARCH_HEADLINE["agents"]
        args.scenarios = MARCH_HEADLINE["scenario"]
        args.since = MARCH_HEADLINE["since"]
        args.until = MARCH_HEADLINE["until"]
        default_dirs = [here / "arena_logs"]
    else:
        default_dirs = [here / "arena_logs", here / "arena_runs"]

    log_dirs = [Path(d) for d in args.log_dir] if args.log_dir else default_dirs
    existing = [d for d in log_dirs if d.exists()]
    if not existing:
        print(f"No logs directory found at {', '.join(str(d) for d in log_dirs)}")
        return

    log_files = sorted(p for d in existing for p in d.glob("arena_*.log"))
    if not log_files:
        print(f"No log files found in {', '.join(str(d) for d in existing)}")
        return

    parsed = (parse_log_file(path) for path in log_files)
    parsed = [run for run in parsed if run["agent"] is not None and run["scenario"] is not None]
    runs = filter_runs(parsed, agents=args.agents, scenarios=args.scenarios, since=args.since, until=args.until)

    if not runs:
        print("No matching runs found.")
        return

    table = aggregate_runs(runs)
    if args.march_headline:
        print(f"March 2026 headline: {MARCH_HEADLINE['scenario']}, logs from "
              f"{MARCH_HEADLINE['since']:%Y-%m-%d %H:%M:%S} to {MARCH_HEADLINE['until']:%H:%M:%S}, "
              f"{MARCH_HEADLINE['runs_per_agent']} runs per agent expected\n")
    print(format_table(table))
    print(f"\n{table_notes(table)}")
    if args.march_headline:
        print("\n" + "\n".join(headline_summary(runs)))
    print(f"\n{len(runs)} runs across {len(table)} scenario/agent combinations")


if __name__ == "__main__":
    main()

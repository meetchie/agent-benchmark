"""
Benchmark Visualization: draw comparison charts from a run's summary.json.

Usage: cli/viz.sh <results-dir>
Example: cli/viz.sh cli/results/prose-2026-10-24
(a relative path is tried against the current directory first, then against cli/)

If only one arm was run, the charts that compare the arms are skipped and the
other charts mark the missing arm "not run".
"""

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import numpy as np


def load_summary(results_dir: Path) -> dict:
    summary_path = results_dir / "summary.json"
    if not summary_path.exists():
        print(f"Error: summary.json not found in {results_dir}")
        sys.exit(1)
    with open(summary_path) as f:
        return json.load(f)


COLORS = {"browseruse": "#e74c3c", "rindler": "#3c49ad"}
LABELS = {"browseruse": "BrowserUse", "rindler": "Rindler"}


def arms_run(summary: dict) -> dict:
    """{"browseruse": bool, "rindler": bool}. Summaries from before this was recorded ran both."""
    return summary["benchmark"].get("arms_run") or {"browseruse": True, "rindler": True}


def both_ran(summary: dict) -> bool:
    ran = arms_run(summary)
    return ran["browseruse"] and ran["rindler"]


def arm_labels(summary: dict) -> list:
    ran = arms_run(summary)
    return [LABELS[a] + ("" if ran[a] else " (not run)") for a in ("browseruse", "rindler")]


def chart_success_rate(summary: dict, charts_dir: Path):
    """Side-by-side success rate bar chart."""
    fig, ax = plt.subplots(figsize=(6, 4))
    agents = arm_labels(summary)
    rates = [summary["browseruse"]["success_rate"] * 100, summary["rindler"]["success_rate"] * 100]
    bars = ax.bar(agents, rates, color=[COLORS["browseruse"], COLORS["rindler"]], width=0.5)
    ax.set_ylabel("Success Rate (%)")
    ax.set_title(f"Success Rate — {summary['benchmark']['site']}")
    ax.set_ylim(0, 110)
    ran = arms_run(summary)
    for bar, rate, arm in zip(bars, rates, ("browseruse", "rindler")):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2,
                f"{rate:.0f}%" if ran[arm] else "not run", ha="center", va="bottom", fontweight="bold")
    plt.tight_layout()
    plt.savefig(charts_dir / "success_rate.png", dpi=150)
    plt.close()


def chart_grouped_bars(summary: dict, charts_dir: Path, metric: str, ylabel: str, title: str, filename: str):
    """Generic grouped bar chart comparing per-task metrics."""
    per_task = summary["per_task"]
    task_ids = [t["task_id"] for t in per_task]
    bu_vals = [t["browseruse"][metric] for t in per_task]
    ri_vals = [t["rindler"][metric] for t in per_task]

    x = np.arange(len(task_ids))
    width = 0.35

    fig, ax = plt.subplots(figsize=(max(8, len(task_ids) * 1.5), 5))
    ax.bar(x - width / 2, bu_vals, width, label="BrowserUse", color=COLORS["browseruse"])
    ax.bar(x + width / 2, ri_vals, width, label="Rindler", color=COLORS["rindler"])
    ax.set_ylabel(ylabel)
    ax.set_title(f"{title} — {summary['benchmark']['site']}")
    ax.set_xticks(x)
    ax.set_xticklabels(task_ids, rotation=30, ha="right")
    ax.legend()
    plt.tight_layout()
    plt.savefig(charts_dir / filename, dpi=150)
    plt.close()


def chart_failure_categories(summary: dict, charts_dir: Path, agent: str):
    """Pie chart of failure categories for one agent."""
    cats = summary[agent].get("failure_categories", {})
    if not cats:
        return

    fig, ax = plt.subplots(figsize=(6, 4))
    labels = list(cats.keys())
    sizes = list(cats.values())
    ax.pie(sizes, labels=labels, autopct="%1.0f%%", startangle=90)
    ax.set_title(f"Failure Categories — {agent.title()} — {summary['benchmark']['site']}")
    plt.tight_layout()
    plt.savefig(charts_dir / f"failure_categories_{agent}.png", dpi=150)
    plt.close()


def chart_radar(summary: dict, charts_dir: Path):
    """Radar chart comparing normalized metrics."""
    bu = summary["browseruse"]
    ri = summary["rindler"]

    categories = ["Success Rate", "Fewer Steps", "Faster", "Cheaper"]
    # Normalize so higher = better, scale 0-1
    max_steps = max(bu["avg_steps_per_task"], ri["avg_steps_per_task"], 1)
    max_dur = max(bu["avg_duration_ms"], ri["avg_duration_ms"], 1)
    max_cost = max(bu["avg_cost_per_task_usd"], ri["avg_cost_per_task_usd"], 0.001)

    bu_vals = [
        bu["success_rate"],
        1 - bu["avg_steps_per_task"] / max_steps,
        1 - bu["avg_duration_ms"] / max_dur,
        1 - bu["avg_cost_per_task_usd"] / max_cost,
    ]
    ri_vals = [
        ri["success_rate"],
        1 - ri["avg_steps_per_task"] / max_steps,
        1 - ri["avg_duration_ms"] / max_dur,
        1 - ri["avg_cost_per_task_usd"] / max_cost,
    ]

    angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
    bu_vals += bu_vals[:1]
    ri_vals += ri_vals[:1]
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))
    ax.plot(angles, bu_vals, "o-", color=COLORS["browseruse"], label="BrowserUse")
    ax.fill(angles, bu_vals, alpha=0.15, color=COLORS["browseruse"])
    ax.plot(angles, ri_vals, "o-", color=COLORS["rindler"], label="Rindler")
    ax.fill(angles, ri_vals, alpha=0.15, color=COLORS["rindler"])
    ax.set_thetagrids(np.degrees(angles[:-1]), categories)
    ax.set_ylim(0, 1)
    ax.set_title(f"Agent Comparison — {summary['benchmark']['site']}", pad=20)
    ax.legend(loc="lower right")
    plt.tight_layout()
    plt.savefig(charts_dir / "radar_comparison.png", dpi=150)
    plt.close()


def chart_token_usage(summary: dict, charts_dir: Path):
    """Stacked bar chart of input vs output tokens per task."""
    per_task = summary["per_task"]
    # Aggregate totals from summary.json. Input counts every prompt token, cache reads included.
    input_tokens = [summary["browseruse"]["total_tokens_input"], summary["rindler"]["total_tokens_input"]]
    output_tokens = [summary["browseruse"]["total_tokens_output"], summary["rindler"]["total_tokens_output"]]

    agents = arm_labels(summary)
    fig, ax = plt.subplots(figsize=(6, 4))
    x = np.arange(len(agents))
    ax.bar(x, input_tokens, 0.5, label="Input Tokens", color=[COLORS["browseruse"], COLORS["rindler"]], alpha=0.7)
    ax.bar(x, output_tokens, 0.5, bottom=input_tokens, label="Output Tokens",
           color=[COLORS["browseruse"], COLORS["rindler"]], alpha=0.4)
    ax.set_ylabel("Tokens")
    ax.set_title(f"Token Usage — {summary['benchmark']['site']}")
    ax.set_xticks(x)
    ax.set_xticklabels(agents)
    ax.legend()
    plt.tight_layout()
    plt.savefig(charts_dir / "token_usage.png", dpi=150)
    plt.close()


def print_summary_table(summary: dict):
    """Print a text summary table to the terminal."""
    bu = summary["browseruse"]
    ri = summary["rindler"]

    print(f"\n{'=' * 60}")
    print(f"  BENCHMARK RESULTS — {summary['benchmark']['site']}")
    print(f"  Model: {summary['benchmark']['model']}  |  Date: {summary['benchmark']['date']}")
    print(f"{'=' * 60}")
    print(f"  {'Metric':<25} {'BrowserUse':>12} {'Rindler':>12}")
    print(f"  {'-' * 49}")
    print(f"  {'Success Rate':<25} {bu['success_rate']:>11.0%} {ri['success_rate']:>11.0%}")
    print(f"  {'Avg Steps':<25} {bu['avg_steps_per_task']:>12.1f} {ri['avg_steps_per_task']:>12.1f}")
    print(f"  {'Avg Duration (s)':<25} {bu['avg_duration_ms']/1000:>12.1f} {ri['avg_duration_ms']/1000:>12.1f}")
    print(f"  {'Avg Cost ($)':<25} {bu['avg_cost_per_task_usd']:>12.4f} {ri['avg_cost_per_task_usd']:>12.4f}")
    print(f"  {'Total Cost ($)':<25} {bu['total_cost_usd']:>12.4f} {ri['total_cost_usd']:>12.4f}")
    print(f"{'=' * 60}")
    for arm in ("browseruse", "rindler"):
        if not arms_run(summary)[arm]:
            print(f"  ({LABELS[arm]} was not run, its columns are zeros)")

    print(f"\n  Per-Task Results:")
    print(f"  {'Task':<25} {'BU':>8} {'RI':>8} {'Winner':>12}")
    print(f"  {'-' * 49}")
    for t in summary["per_task"]:
        print(f"  {t['task_id']:<25} {t['browseruse']['verdict']:>8} {t['rindler']['verdict']:>8} {t.get('winner') or '-':>12}")

    comp = summary.get("comparison", {})
    print(f"\n  Rindler vs BrowserUse:")
    if "avg_steps_reduction" in comp:
        print(f"    Steps reduction:    {comp['avg_steps_reduction']:>7.1%}")
    if "avg_duration_reduction" in comp:
        print(f"    Duration reduction: {comp['avg_duration_reduction']:>7.1%}")
    if "avg_cost_reduction" in comp:
        print(f"    Cost reduction:     {comp['avg_cost_reduction']:>7.1%}")
    print()


def main():
    if len(sys.argv) < 2:
        print("Usage: python visualize.py <results-dir>")
        print("Example: python visualize.py results/prose-2026-03-18/")
        sys.exit(1)

    results_dir = Path(sys.argv[1])
    if not results_dir.is_absolute() and not results_dir.is_dir():
        results_dir = Path(__file__).parent / results_dir

    summary = load_summary(results_dir)
    charts_dir = results_dir / "charts"
    charts_dir.mkdir(exist_ok=True)

    print(f"Generating charts in {charts_dir}...")

    chart_success_rate(summary, charts_dir)
    print("  success_rate.png")

    if both_ran(summary):
        chart_grouped_bars(summary, charts_dir, "steps", "Steps", "Steps per Task", "steps_per_task.png")
        print("  steps_per_task.png")

        chart_grouped_bars(summary, charts_dir, "duration_ms", "Duration (ms)", "Duration per Task", "duration_per_task.png")
        print("  duration_per_task.png")

        chart_grouped_bars(summary, charts_dir, "cost_usd", "Cost (USD)", "Cost per Task", "cost_per_task.png")
        print("  cost_per_task.png")
    else:
        print("  only one arm ran: skipping the per-task and radar comparisons")

    chart_failure_categories(summary, charts_dir, "browseruse")
    chart_failure_categories(summary, charts_dir, "rindler")
    print("  failure_categories (if applicable)")

    if both_ran(summary):
        chart_radar(summary, charts_dir)
        print("  radar_comparison.png")

    chart_token_usage(summary, charts_dir)
    print("  token_usage.png")

    print_summary_table(summary)
    print(f"Charts saved to {charts_dir}")


if __name__ == "__main__":
    main()

"""Draw comparison charts from a run's summary.json.

Usage: cli/viz.sh <results-dir>, e.g. cli/viz.sh cli/results/prose-<date>. A relative path is tried
against the current directory first, then against cli/.

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


def relative_scores(value_a: float, value_b: float, lower_is_better: bool) -> tuple:
    """Score two arms against each other on one metric: the better arm gets 1.0, the other gets
    its fraction of that (best / value when lower is better, value / best when higher is).
    A tie scores 1.0 for both. If the better arm is at 0 (say a zero-cost run) the other scores 0."""
    if value_a == value_b:
        return 1.0, 1.0
    if lower_is_better:
        best = min(value_a, value_b)
        return tuple(1.0 if v == best else (best / v if v else 1.0) for v in (value_a, value_b))
    best = max(value_a, value_b)
    return tuple(1.0 if v == best else v / best for v in (value_a, value_b))


# (label, value from an arm's summary, lower is better, how to print the raw value)
RELATIVE_METRICS = [
    ("Success rate", lambda arm: arm["success_rate"], False, lambda v: f"{v:.0%}"),
    ("Steps\nper task", lambda arm: arm["avg_steps_per_task"], True, lambda v: f"{v:.1f}"),
    ("Duration\nper task", lambda arm: arm["avg_duration_ms"] / 1000, True, lambda v: f"{v:.1f}s"),
    ("Cost\nper task", lambda arm: arm["avg_cost_per_task_usd"], True, lambda v: f"${v:.4f}"),
]


def relative_chart_data(summary: dict) -> list:
    """One row per metric: label, each arm's score against the better arm, and each arm's raw value as text."""
    bu, ri = summary["browseruse"], summary["rindler"]
    rows = []
    for label, value, lower_is_better, show in RELATIVE_METRICS:
        a, b = relative_scores(value(bu), value(ri), lower_is_better)
        rows.append({"label": label, "browseruse": a, "rindler": b,
                     "browseruse_raw": show(value(bu)), "rindler_raw": show(value(ri))})
    return rows


def chart_relative_comparison(summary: dict, charts_dir: Path):
    """Grouped bars, one pair per metric, each scored against the better arm (1.0 = best).

    Both arms are scored the same way on every metric, so neither bar is zero by construction. The
    raw averages are printed above the bars.
    """
    rows = relative_chart_data(summary)
    labels = [r["label"] for r in rows]
    bu_scores, ri_scores = [r["browseruse"] for r in rows], [r["rindler"] for r in rows]
    bu_raw, ri_raw = [r["browseruse_raw"] for r in rows], [r["rindler_raw"] for r in rows]

    x = np.arange(len(labels))
    width = 0.36
    fig, ax = plt.subplots(figsize=(8.5, 5.4))
    bars = (
        ax.bar(x - width / 2 - 0.01, bu_scores, width, label="BrowserUse", color=COLORS["browseruse"]),
        ax.bar(x + width / 2 + 0.01, ri_scores, width, label="Rindler", color=COLORS["rindler"]),
    )
    for group, raws in zip(bars, (bu_raw, ri_raw)):
        for bar, raw in zip(group, raws):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02, raw,
                    ha="center", va="bottom", fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 1.18)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_ylabel("Score against the better arm (1.0 = best)")
    ax.yaxis.grid(True, color="#dddddd", linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    n_tasks = summary["benchmark"].get("total_tasks")
    ax.set_title(f"Agent Comparison — {summary['benchmark']['site']}"
                 + (f" ({n_tasks} task{'s' if n_tasks != 1 else ''})" if n_tasks else ""))
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2, frameon=False)
    fig.text(0.5, 0.01,
             "Higher is better on every axis. Success: value / best. Steps, duration, cost: best / value.\n"
             "The number above each bar is the arm's raw average.",
             ha="center", va="bottom", fontsize=8, color="#555555")
    plt.tight_layout(rect=(0, 0.07, 1, 1))
    plt.savefig(charts_dir / "relative_comparison.png", dpi=150)
    plt.close()


# How dark each kind of token is drawn: input is the solid shade, output the paler one on top.
TOKEN_ALPHA = {"input": 0.7, "output": 0.4}


def token_usage_figure(summary: dict):
    """Stacked bars of input vs output tokens per arm, with a legend key for all four shades."""
    from matplotlib.patches import Patch

    # Aggregate totals from summary.json. Input counts every prompt token, cache reads included.
    input_tokens = [summary["browseruse"]["total_tokens_input"], summary["rindler"]["total_tokens_input"]]
    output_tokens = [summary["browseruse"]["total_tokens_output"], summary["rindler"]["total_tokens_output"]]
    arms = ("browseruse", "rindler")
    colors = [COLORS[arm] for arm in arms]

    agents = arm_labels(summary)
    fig, ax = plt.subplots(figsize=(6, 4.4))
    x = np.arange(len(agents))
    ax.bar(x, input_tokens, 0.5, color=colors, alpha=TOKEN_ALPHA["input"])
    ax.bar(x, output_tokens, 0.5, bottom=input_tokens, color=colors, alpha=TOKEN_ALPHA["output"])
    ax.set_ylabel("Tokens")
    ax.set_title(f"Token Usage — {summary['benchmark']['site']}")
    ax.set_xticks(x)
    ax.set_xticklabels(agents)
    # One key per arm and kind. A plain legend would take its colours from the first bar of each
    # series, which is BrowserUse's, and Rindler's shades would have no key.
    keys = [Patch(facecolor=COLORS[arm], alpha=TOKEN_ALPHA[kind], label=f"{LABELS[arm]} {kind} tokens")
            for arm in arms for kind in ("input", "output")]
    ax.legend(handles=keys, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=2, frameon=False)
    fig.tight_layout()
    return fig


def chart_token_usage(summary: dict, charts_dir: Path):
    """Stacked bar chart of input vs output tokens per arm."""
    fig = token_usage_figure(summary)
    fig.savefig(charts_dir / "token_usage.png", dpi=150)
    plt.close(fig)


def print_summary_table(summary: dict):
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
        print("  only one arm ran: skipping the comparison charts")

    chart_failure_categories(summary, charts_dir, "browseruse")
    chart_failure_categories(summary, charts_dir, "rindler")
    print("  failure_categories (if applicable)")

    if both_ran(summary):
        chart_relative_comparison(summary, charts_dir)
        print("  relative_comparison.png")

    chart_token_usage(summary, charts_dir)
    print("  token_usage.png")

    print_summary_table(summary)
    print(f"Charts saved to {charts_dir}")


if __name__ == "__main__":
    main()

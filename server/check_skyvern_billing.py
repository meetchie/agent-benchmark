#!/usr/bin/env python3
"""
Check Skyvern billing for a completed task.

Usage:
    python check_skyvern_billing.py tsk_v2_REDACTED
    python check_skyvern_billing.py tsk_v2_REDACTED --json
    python check_skyvern_billing.py wr_REDACTED --save-log
"""

import os
import sys
import json
import argparse
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from adapters import SkyvernTelemetricAgent


def save_arena_log(billing: dict, run_id: str) -> str:
    """Save billing data as an arena log file."""
    log_dir = os.path.join(os.path.dirname(__file__), "arena_logs")
    os.makedirs(log_dir, exist_ok=True)
    
    # Generate timestamp from created_at or now
    created = billing.get("created_at") or datetime.now().isoformat()
    if isinstance(created, str):
        # Parse ISO format and convert to log format
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            timestamp = dt.strftime("%Y%m%d_%H%M%S")
        except (ValueError, AttributeError):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    log_path = os.path.join(log_dir, f"arena_skyvern_{timestamp}_{run_id}.log")
    
    totals = billing.get("totals", {})
    raw = billing.get("_raw_run_data", {})
    
    with open(log_path, 'w') as f:
        f.write(f"Lane: SKYVERN\n")
        f.write(f"Run ID: {run_id}\n")
        f.write(f"Status: {billing.get('status')}\n")
        f.write(f"Created: {billing.get('created_at')}\n")
        f.write(f"Finished: {billing.get('finished_at')}\n")
        f.write(f"\n")
        f.write(f"BILLING\n")
        f.write(f"-------\n")
        f.write(f"Total tasks: {billing.get('total_tasks', 0)}\n")
        f.write(f"Total steps: {billing.get('total_steps', 0)}\n")
        f.write(f"Estimated cost: ${totals.get('cost_usd', 0):.2f}\n")
        f.write(f"\n")
        f.write(f"TASK BREAKDOWN\n")
        f.write(f"--------------\n")
        for task in billing.get('tasks', []):
            f.write(f"{task['task_id']}: {task['step_count']} steps, {task['status']}\n")
        f.write(f"\n")
        
        # Add artifacts
        if raw.get("app_url"):
            f.write(f"App URL: {raw['app_url']}\n")
        if raw.get("recording_url"):
            f.write(f"Recording URL: {raw['recording_url']}\n")
        
        f.write(f"\n")
        f.write(f"Full Billing Data:\n")
        # Remove raw data before saving
        billing_save = {k: v for k, v in billing.items() if k != "_raw_run_data"}
        f.write(json.dumps(billing_save, indent=2, default=str))
    
    return log_path


def main():
    parser = argparse.ArgumentParser(
        description="Check Skyvern billing for a task (works retroactively on completed tasks)"
    )
    parser.add_argument(
        "task_id",
        help="Skyvern task ID (e.g., tsk_v2_REDACTED or wr_REDACTED)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted summary"
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="Just show current status, not full billing"
    )
    parser.add_argument(
        "--save-log",
        action="store_true",
        help="Save billing as an arena log file"
    )
    
    args = parser.parse_args()
    
    try:
        if args.status_only:
            # Quick status check
            status = SkyvernTelemetricAgent.get_task_status(args.task_id)
            if args.json:
                print(json.dumps(status, indent=2, default=str))
            else:
                print(f"\nTask: {args.task_id}")
                print(f"Status: {status.get('status')}")
                if status.get("app_url"):
                    app_url = status["app_url"]
                    if not app_url.endswith("/overview"):
                        app_url = f"{app_url}/overview"
                    print(f"URL: {app_url}")
                if status.get("failure_reason"):
                    print(f"Failure: {status['failure_reason']}")
        else:
            # Full billing info
            billing = SkyvernTelemetricAgent.get_run_billing(
                args.task_id,
                verbose=not args.json
            )
            
            if args.json:
                # Remove raw data for cleaner JSON output
                billing.pop("_raw_run_data", None)
                print(json.dumps(billing, indent=2, default=str))
            
            # Save as arena log if requested
            if args.save_log:
                log_path = save_arena_log(billing, args.task_id)
                print(f"\n✅ Log saved: {log_path}")
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()


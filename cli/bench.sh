#!/usr/bin/env bash
cd "$(dirname "$0")" && PYTHONUNBUFFERED=1 uv run python run.py "$@"

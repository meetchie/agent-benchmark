#!/usr/bin/env bash
cd "$(dirname "$0")" && uv run python visualize.py "$@"

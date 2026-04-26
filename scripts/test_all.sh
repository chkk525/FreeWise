#!/usr/bin/env bash
# Run the three independent test suites that make up FreeWise.
# Each one isolates its own pytest session because the conftest.py files
# can't coexist in a single collection (they each set up an in-process
# FastAPI app + dependency overrides).
set -euo pipefail

cd "$(dirname "$0")/.."

echo "── main app ─────────────────────────────"
uv run pytest tests/ "$@"

echo "── cli ──────────────────────────────────"
uv run pytest cli/tests/ "$@"

echo "── mcp ──────────────────────────────────"
uv run pytest mcp/tests/ "$@"

echo "✓ all three suites passed"

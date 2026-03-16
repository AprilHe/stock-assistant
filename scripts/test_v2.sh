#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Running v2 smoke pipeline..."
python scripts/validate_v2_pipeline.py > /tmp/validate_v2_pipeline_output.json
echo "Smoke pipeline passed. Output saved to /tmp/validate_v2_pipeline_output.json"

if python -c "import pytest" >/dev/null 2>&1; then
  echo "Running pytest checks..."
  python -m pytest \
    tests/test_candidate_merge_service.py \
    tests/test_constraint_engine.py \
    tests/test_execution_planner.py
else
  echo "pytest is not installed in the active environment; skipped pytest checks."
  echo "Install with: pip install -r requirements.txt"
fi

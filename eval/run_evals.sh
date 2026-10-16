#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Groundswell Eval Suite ==="
echo ""

echo "--- Unit tests (deterministic nodes) ---"
python -m pytest tests/ -v --tb=short
echo ""

echo "--- Discovery trajectory ---"
adk eval agents/orchestrator.py eval/goldens/discovery.evalset.json \
    --config_file_path eval/test_config.json
echo ""

echo "--- Signal extraction ---"
adk eval agents/signal_agent.py eval/goldens/signals.evalset.json \
    --config_file_path eval/test_config.json
echo ""

echo "--- Commerce / cart ---"
adk eval agents/commerce.py eval/goldens/commerce.evalset.json \
    --config_file_path eval/test_config.json
echo ""

echo "--- Adversarial safety ---"
adk eval agents/orchestrator.py eval/goldens/adversarial.evalset.json \
    --config_file_path eval/test_config.json
echo ""

echo "--- Manager analyst ---"
adk eval agents/analyst.py eval/goldens/analyst.evalset.json \
    --config_file_path eval/test_config.json
echo ""

echo "=== All evals complete (85 golden cases) ==="

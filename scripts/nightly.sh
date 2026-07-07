#!/bin/bash
# Nightly paper-trading run, invoked by the launchd job
# com.cognitivetrader.daily (see scripts/com.cognitivetrader.daily.plist).
#
# Runs the daily loop in --execute mode and appends a timestamped block to
# logs/nightly.log so you can review each evening's run. Market holidays are
# harmless: ingest is idempotent and reconcile simply finds nothing new.
set -euo pipefail

PROJECT_DIR="/Users/samxie/Desktop/proj/Cowork/CognitiveTrader/Cognitive Trader"
PYTHON="/Users/samxie/anaconda3/bin/python3"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR"

{
    echo "===================================================================="
    echo "Run started: $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "--------------------------------------------------------------------"
    if "$PYTHON" scripts/run_daily.py --execute; then
        echo "Run finished OK: $(date '+%Y-%m-%d %H:%M:%S %Z')"
    else
        echo "Run FAILED (exit $?): $(date '+%Y-%m-%d %H:%M:%S %Z')"
    fi
    echo ""
} >> "$LOG_DIR/nightly.log" 2>&1

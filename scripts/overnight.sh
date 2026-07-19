#!/usr/bin/env bash
# Overnight runner: finish ESPN history bridge, then execute the full study.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"
LOG="reports/overnight.log"
mkdir -p reports data/interim data/features reports/figures

exec > >(tee -a "$LOG") 2>&1
echo "==== overnight start $(date) ===="

echo "[overnight] ensuring ESPN history seasons…"
$PY - <<'PY'
from refedge.data import espn
for s in ["2023-24", "2024-25", "2025-26"]:
    print("===", s, flush=True)
    df = espn.build_season_games(s, force=False)
    print(s, "games", len(df), flush=True)
print("HISTORY BRIDGE DONE", flush=True)
PY

echo "[overnight] running full study…"
$PY scripts/run_study.py --n-perms 20 --prefer-train espn --prefer-backtest espn

echo "==== overnight done $(date) ===="
ls -la reports/

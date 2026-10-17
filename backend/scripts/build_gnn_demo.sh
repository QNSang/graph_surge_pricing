#!/usr/bin/env bash
# Generate GNN surge proposals from a trained checkpoint and import them into the backend database.
# Same steps as build_gnn_demo.ps1. Usage (from backend/): scripts/build_gnn_demo.sh [split] [seed] [variant] [stride]
set -euo pipefail
SPLIT="${1:-test}"
SEED="${2:-42}"
VARIANT="${3:-gru_gatv2_40}"
STRIDE="${4:-1}"
BACKEND="$(cd "$(dirname "$0")/.." && pwd)"
PIPELINE="$(dirname "$BACKEND")/pipeline"

OUT_DIR="$(cd "$PIPELINE" && uv run python -c "from surge_ml.cli import DEFAULT_CONFIG; from surge_ml.config import load_config; from surge_ml.orchestration.runner import trial_dir; print(trial_dir(load_config(DEFAULT_CONFIG), '$VARIANT', $SEED) / 'surge' / '$SPLIT')")"
(cd "$PIPELINE" && uv run surge-ml surge --variant "$VARIANT" --seed "$SEED" --split "$SPLIT" --stride "$STRIDE" --out-dir "$OUT_DIR")
(cd "$BACKEND" && uv run python scripts/import_dataset.py --provider precomputed --source "$OUT_DIR")

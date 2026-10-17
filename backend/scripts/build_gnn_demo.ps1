# Generate GNN surge proposals from a trained checkpoint and import them into the backend database.
#
# Prerequisites: a trained checkpoint (`surge-ml train --variant gru_gatv2_40 --seed 42` in pipeline/),
# Postgres running (`docker compose up -d db`) and migrations applied (`uv run alembic upgrade head`).
#
# Usage (from backend/):
#   powershell -File scripts/build_gnn_demo.ps1                      # test split, seed 42
#   powershell -File scripts/build_gnn_demo.ps1 -Split val -Seed 43
param(
    [string]$Split = "test",
    [int]$Seed = 42,
    [string]$Variant = "gru_gatv2_40",
    [int]$Stride = 1
)
$ErrorActionPreference = "Stop"
$backend = Split-Path -Parent $PSScriptRoot
$pipeline = Join-Path (Split-Path -Parent $backend) "pipeline"

# The output directory comes from the pipeline config (runs_root/study_id/variant/seed_N/surge), never hardcoded.
Push-Location $pipeline
try {
    $outDir = uv run python -c "from surge_ml.cli import DEFAULT_CONFIG; from surge_ml.config import load_config; from surge_ml.orchestration.runner import trial_dir; print(trial_dir(load_config(DEFAULT_CONFIG), '$Variant', $Seed) / 'surge' / '$Split')"
    if ($LASTEXITCODE -ne 0) { throw "could not resolve the proposal directory" }
    $outDir = $outDir.Trim()
    uv run surge-ml surge --variant $Variant --seed $Seed --split $Split --stride $Stride --out-dir $outDir
    if ($LASTEXITCODE -ne 0) { throw "surge-ml surge failed" }
} finally {
    Pop-Location
}

Push-Location $backend
try {
    uv run python scripts/import_dataset.py --provider precomputed --source $outDir
    if ($LASTEXITCODE -ne 0) { throw "import_dataset.py failed" }
} finally {
    Pop-Location
}

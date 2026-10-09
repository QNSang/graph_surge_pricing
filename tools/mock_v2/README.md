# Mock V2: 30-day data preparation

This workflow corrects the existing minute-level generator and exports a
training-ready release. The current release lives at `data/hcm_data_2` (see
`data/CURRENT.json`). The training pipeline is being rewritten from scratch in
`pipeline/`; the loader/model used when this release was generated is preserved
under the release's `provenance/pipeline/`.

## Output contract

Exactly 30 main days: 2026-01-05 through 2026-02-03. Last snapshot is
2026-02-04 00:00, the end of the final 5-minute window. One earlier burn-in day is
retained under `context/` only. Train/validation/test are 21/4/5 days.

Node tensor: `[8640, 61, 40]`. Model batches: `[B, 4, 61, 40]`.
Directed edge attributes: `[E, 10]`, with separate adjacency and OD relations.
Existing GAT adds reverse-edge/self-loop flags to make 12 internal dimensions.
Labels: `[8640, 61, 3]`, horizons 5/10/15 minutes, epsilon 1. Invalid labels remain
NaN with false masks, and are excluded from sample indices. The target is a
pressure proxy, not optimal surge or causal revenue uplift.

## Implemented plan

1. Fix intra-hex radius, chronological dispatch/release, patience and driver availability.
2. Treat repositioning drivers as unavailable until arrival; report this assumption.
3. Censor unknown lifecycle timestamps independently and retain historical context.
4. Run six development calibrations: three cases x two seeds, seven days each.
5. Validate raw order/snapshot invariants and driver job non-overlap.
6. Build 40 node / 10 edge features with support columns and point-in-time prefix tests.
7. Use one manifest-based split, train-only normalization and payload SHA256 checks.
8. Smoke-test LightGBM/GRU-GATv2 models (legacy pipeline, since removed).
9. Promote the validated staging directory and write `data/CURRENT.json`
   (the one-off `promote.py` is in git history; it depended on the removed pipeline).

## Commands (from repository root; PowerShell)

```powershell
.\pipeline\.venv\Scripts\python.exe -m pytest tools/mock_v2/test_v2.py -q
.\pipeline\.venv\Scripts\python.exe -m pytest mock_data_pipeline/tests -q -o pythonpath=mock_data_pipeline --basetemp=artifacts/NEW_unique_pytest_tmp
.\pipeline\.venv\Scripts\python.exe tools/mock_v2/run.py --mode calibrate --out artifacts/NEW_calibration_directory
.\pipeline\.venv\Scripts\python.exe tools/mock_v2/run.py --mode release --case moderate_reposition --seed 42 --out data/staging/NEW_30day_dataset
```

Outputs must be new paths. Generation deliberately refuses overwrite. Pytest's
`--basetemp` must be a new disposable directory inside this authorized repository.

Training on the release is handled by the new pipeline in `pipeline/` (in progress).
It should read `features/` and `raw/` parquet; `training/` is a pre-built tensor cache.

## Scope and limitations

Training-ready means technical data/loader/model compatibility. It does not mean
all heuristic realism targets pass or that the model is validated for production.
Completion and surge exposure warnings are explicitly retained in the manifest.
Utilization is calculated from minute-end samples, not exact time integration.
Booking rate, driver-offer acceptance, GMV, car service and res9 are not fabricated.
Network/graph benefit and pricing impacts still require controlled evaluation.

Rates use fixed Beta(1,1) smoothing with matured cohorts. Pickup waiting P90 uses
observed pickups and falls back to current ETA with separate support counters.
Detailed formulas and feature ordering are in the release's `feature_contract.json`.

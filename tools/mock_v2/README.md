# Mock V2: 30-day data preparation

This workflow corrects the existing minute-level generator and prepares inputs for
`pipeline/model.py`. It does not overwrite `data/hcm_data`, old training runs or the
user's existing EDA notebook.

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
8. Exercise existing LightGBM/GRU-GATv2 models and checkpoint reloads.
9. Promote only a validated staging directory and write `data/CURRENT.json`.

## Commands (from repository root; PowerShell)

```powershell
.\pipeline\.venv\Scripts\python.exe -m pytest tools/mock_v2/test_v2.py -q
.\pipeline\.venv\Scripts\python.exe -m pytest mock_data_pipeline/tests -q -o pythonpath=mock_data_pipeline --basetemp=artifacts/NEW_unique_pytest_tmp
.\pipeline\.venv\Scripts\python.exe tools/mock_v2/run.py --mode calibrate --out artifacts/NEW_calibration_directory
.\pipeline\.venv\Scripts\python.exe tools/mock_v2/run.py --mode release --case moderate_reposition --seed 42 --out data/staging/NEW_30day_dataset
```

Outputs must be new paths. Generation deliberately refuses overwrite. Pytest's
`--basetemp` must be a new disposable directory inside this authorized repository.

After release:

```powershell
.\pipeline\.venv\Scripts\python.exe pipeline/train_v2.py --data data/releases/hcm_mock_v2_30d_seed42 --model lgbm --trees 300 --out pipeline/runs_v2/lgbm_full_01
.\pipeline\.venv\Scripts\python.exe pipeline/train_v2.py --data data/releases/hcm_mock_v2_30d_seed42 --model gru_gatv2 --epochs 30 --out pipeline/runs_v2/gat_full_01
```

The old `pipeline/train.py` raw loader retains its legacy contract. Use
`pipeline/train_v2.py` / `pipeline/prepared_data.py` for these prepared arrays.
The existing model and loss implementations are reused; no legacy cache is loaded.

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

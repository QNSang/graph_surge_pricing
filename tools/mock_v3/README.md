# Mock V3 — temporally persistent demand and OD-coupled marketplace

This is a **new synthetic DGP**, not a rescaling of existing D/S labels.
It reuses the existing minute-level driver, matching, trip, repositioning, price and
point-in-time feature calculation. All orders, supply changes and graph edges are
generated from simulated market state rather than altered after export.

## Change from V2

1. Higher calibrated *potential intent* intensity in low-volume zone classes.
2. A persistent per-hex demand-intensity state with H3 adjacency diffusion, driven
   by independent, seeded innovations every 5 minutes; the innovations are
   **not** training inputs.
3. Existing Gamma-Poisson request generation is retained at a higher
   concentration (less independent 5-minute noise). Requests still pass through
   the unchanged fare and available-car acceptance filters.
4. A moderately tighter online-driver pool and updated reposition attempt
   probability. The same trip lifecycle, physical fleet conservation and OD feature
   construction remain in use. No artificial oscillation of D/S is introduced.

**Research assumptions only.** No claim that a lower zero-demand rate or increased
shortage is necessarily closer to real HCMC until externally calibrated.

## Run from the repository root

```powershell
python tools/mock_v3/run.py --mode calibrate --days 7 --out artifacts/mock_v3_calibration_7d
python tools/mock_v3/run.py --mode release --days 90 --seed 42 --out data/staging/hcm_mock_v3_90d_seed42_temporal_od
python tools/mock_v3/refresh_clean.py --source data/staging/hcm_mock_v3_90d_seed42_temporal_od --target data/hcm_data_2 --out data/hcm_mock_v3_90d_seed42_temporal_od --dataset-id hcm_mock_v3_90d_seed42_temporal_od
```

The calibration command writes **only diagnostics**, not a training dataset.
The release command writes a new staging directory; it refuses to overwrite.
The clean converter writes a new compatible `clean_v1` directory and validates
keys, timestamp grid, order reconciliation, OD/node sums, effective supply,
physical D/S bound and point-in-time prefixes. It does **not** promote, archive,
overwrite or repoint `data/CURRENT.json`.

To train on V3, use a **new study_id** and explicit `data.source_root` plus
`data.dataset_id` in a separate training YAML. Do not change prior study hashes.
The feature contract remains `hex40_edge10_v2.1`; only the dataset/DGP
version changes. Never train on `oracle/`, `diagnostics/` or `meta/`
simulator secrets.

## Diagnostics

`reports/v3_diagnostics.json` records zero-demand fraction, D/S state
transitions, run lengths, autocorrelation of observed demand and effective
supply, and the V3 parameters. Target flags are not modified.
`diagnostics/v3_latent_oracle.npz` holds latent intensity and potential intents
**only for diagnostic/positive-control purposes**, never model input.
The full versioned data release is valid only when
`dataset_manifest.json` reports passed raw and feature integrity.

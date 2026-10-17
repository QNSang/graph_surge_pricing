# GeoMobiNet-SMG pipeline

The current forecast implementation follows the GeoMobiNet direction documented in
[the preserved model handoff](../docs/model/duocast_model.md). Read the
[forecasting contract and compatibility notes](../docs/model/forecasting_contract.md)
and [coding-agent documentation index](../docs/README.md) before GGSO integration.
The handoff and implementation may reflect different stages; it is not a claim of
complete code/data/checkpoint parity for the agreed DuoCast semantics or
architecture. DuoCast is defined in GGSO as a temporal GRU with separate Spatial
GATv2 and directed Mobility GATv2 branches, gated fusion, and independent demand
and supply heads. It does not include the GeoMobiNet static-geography branch.
The current default implementation therefore remains implementation evidence,
not a drop-in DuoCast checkpoint.

The default `surge-ml` CLI uses `surge_ml.geomobinet` and `configs/geomobinet.yaml`.
The previous W4 log-ratio model is not used by default. Its code/checkpoints remain
available only through explicit `surge-ml legacy ...` commands so unrelated
backend/policy work is not deleted.

The new GGSO response, candidate, MILP and decision documents describe planned
integration, not already implemented pricing behavior. Request/booking demand and
idle/effective supply mappings require explicit semantic decisions; do not silently
rewire the legacy controller or backend consumers. This documentation update does
not change code, configuration, training commands or deployment eligibility.

## Model and output

The model predicts two distinct quantities, five minutes ahead:

- Demand (agreed semantics, actual data/label parity pending): new valid **confirmed booking requests** in `(t, t+5min]`.
- Supply: idle, online, dispatch-eligible drivers at `t+5min`.

The current default `geomobinet_smg` implementation reads the 12 snapshots ending
at `t` with a shared GRU. A static geo MLP and separate spatial/mobility GATv2
branches enter gated residual fusion. Spatial edges are
bidirectional H3 ring-1 edges. Mobility edges are **directed observed physical
driver transitions at the cutoff**, never passenger/request OD. Empty movement
snapshots produce zero mobility messages.

This static-geo branch belongs to GeoMobiNet-SMG, not to the agreed DuoCast
architecture. The existing `gru_dual_graph` variant is structurally closest to
DuoCast because it retains both graph branches without geography, but its data,
training, checkpoint, and adapter parity must be verified before it is promoted
as DuoCast.

The two Softplus heads output nonnegative `log1p(D)` and `log1p(S)` forecasts.
Training uses equally weighted Huber losses by default. Counts are recovered with
`expm1`. This is **not** the previous residual forecast of a D/S log-ratio.
`D/(S+1)` is an evaluation diagnostic, not a learned target or a pricing rule.

No surge multiplier, INCREASE/DECREASE action, profitability estimate, causal
response curve, or deployment eligibility is generated. The existing policy and
backend consumers are not silently rewired to this incompatible output contract.

## Installation and quick verification

Run these commands from the repository root:

```bash
uv sync --project pipeline --extra baselines
uv run --project pipeline pytest pipeline/tests/test_geomobinet.py pipeline/tests/test_geomobinet_workflow.py -q
```

`torch-geometric` provides the actual GATv2 layers. `h3` validates production node
IDs and ring-1 edges. The `baselines` extra installs LightGBM. No module imports
from `experiments/` are required.

An isolated synthetic run exercises the entire workflow:

```bash
uv run --project pipeline surge-ml demo --output-dir pipeline/runs/smg-demo-input
uv run --project pipeline surge-ml prepare --config pipeline/runs/smg-demo-input/config.yaml
uv run --project pipeline surge-ml benchmark --config pipeline/runs/smg-demo-input/config.yaml
uv run --project pipeline surge-ml select --config pipeline/runs/smg-demo-input/config.yaml
uv run --project pipeline surge-ml finalize --config pipeline/runs/smg-demo-input/config.yaml
uv run --project pipeline surge-ml predict --config pipeline/runs/smg-demo-input/config.yaml --checkpoint pipeline/runs/smg-demo-input/runs/geomobinet_smg/seed_42/best.pt --output pipeline/runs/smg-demo-input/latest_forecast.csv
```

The demo is a small deterministic **software-test fixture**, not a realistic
marketplace or evidence that the model beats persistence. Its synthetic node IDs
are allowed only because the metadata declares `synthetic: true`. Existing demo
folders and forecast output files are not overwritten.

## Production input contract

Edit the five paths in `configs/geomobinet.yaml`. CSV and Parquet are supported.
All paths are resolved relative to that YAML, not the current working directory.
The default paths under `data/geomobinet/` are an input contract, not an assertion
that production-ready data already exists in this checkout.

| Table | Required minimal columns |
| --- | --- |
| Market | `timestamp, hex_id, demand_5m, idle_supply_t, backlog_t, eta_sec_t, base_surge, available_at` |
| Geo | `hex_id, distance_to_cbd_km, east_offset_km, north_offset_km, road_neighbor_count` |
| Spatial | `source_hex, target_hex` |
| Mobility | `timestamp, origin_hex, dest_hex, flow_5m, eta_min, distance_km, available_at` |

A market row stamped `t` contains historical observations ending at `t`, including
demand during `(t-5min,t]` and idle supply at `t`. Its training label comes from
the next row, not the current row. `eta_sec_t`/`eta_min` must be an actual value
available at the cutoff; do not substitute a retrospectively finalized travel
time or predicted future supply.

Minimal `meta.json` structure:

```json
{
  "dataset_id": "your-versioned-dataset-id",
  "feature_definition_version": "smg_canonical_minimal_v1",
  "geo_version": "your-static-geo-version",
  "mobility_semantics": "physical_driver_transitions",
  "static_as_of": "2026-01-01T00:00:00+07:00"
}
```

`static_as_of` must actually be no later than the first market timestamp. Static
tables may instead provide per-row `available_at`. `node_order` can be supplied
as a list in metadata; otherwise the loader sorts market IDs and freezes the
result in the checkpoint. All production IDs must be H3 resolution 7.

Default `availability: strict` requires dynamic/mobility `available_at <= t` and
checks optional `event_time`/`window_end <= t`. Explicit
`availability: snapshot_contract` permits upstream-certified aggregate files
without availability columns only when metadata includes `point_in_time: true`.
That mode records an **upstream assertion**, not independently verified event
lineage. Neither mode can prove unprovided event-level semantics; producers must
construct eligible requests and physical driver transitions correctly.

Missing timestamps, missing hex rows, duplicate keys, unknown edge nodes,
negative counts, nonfinite targets, future availability, passenger OD, and
inconsistent signed CBD deltas fail validation. Null observations are not turned
into true zeros. For configurable nullable dynamic fields, the pipeline fits a
train-only mean and always appends a stable observed/not-observed mask. Targets
can never be nullable. Signed geographic offsets and CBD deltas retain their
sign and cannot use `log1p` transforms.

To use the richer `experiments/geomobinet` schema, explicitly configure its
`market_5min.parquet`, `mobility_edges_5min.parquet`, dynamic/geo feature names,
edge names, log-transform lists, and nullable lists. Supply real availability
metadata. There is deliberately no automatic renaming of passenger trips into
driver flow and no silent reuse of the old hex40 feature cache.

## Training and evaluation

```bash
uv run --project pipeline surge-ml prepare --config pipeline/configs/geomobinet.yaml
uv run --project pipeline surge-ml train --config pipeline/configs/geomobinet.yaml --variant geomobinet_smg --seed 42 --epochs 50
uv run --project pipeline surge-ml train --config pipeline/configs/geomobinet.yaml --variant geomobinet_smg --seed 42 --epochs 100 --resume
```

Resume restores model, optimizer, learning-rate scheduler, early-stop state,
NumPy sampler state, and Torch RNG state. Only the epoch budget may change in the
same training identity. Dataset content hashes, schema, model/loss parameters,
variant and seed must agree. Exact CPU resume is regression-tested; bitwise
GPU determinism is not promised. A trial that already exhausted early-stopping
patience is not restarted merely by increasing the epoch budget.

`--smoke` uses a separate `-smoke` study directory, two epochs and at most two
training batches per epoch. Use the same flag for `prepare`, `report`, `select`
and `finalize` when operating on that smoke study. Smoke artifacts are never
marked deployment eligible.

Training/validation/test boundaries are chronological 70/15/15 by default.
`split_mode: strict` requires each split's full lookback to be inside its own
partition; those initial lookback rows are excluded from scored samples.
`rolling` permits earlier observed context at a boundary but never future labels.
An optional additional `embargo_steps` is applied to validation/test cutoffs.
Scalers fit **training input rows only**, not validation, test, or the final
training label. Static geo/road attributes are validated as-of the first snapshot.

Supported variants:

| Variant | Purpose |
| --- | --- |
| `persistence`, `seasonal_naive` | Current counts, or previous-day slot; seasonal startup fallback is explicit |
| `lgbm_local`, `lgbm_network` | Causal historical-window baseline; network adds geo, neighbor, and observed OD summaries |
| `gru` | Temporal-only ablation |
| `gru_spatial`, `gru_mobility` | One graph branch |
| `gru_dual_graph` | Both graphs without geography |
| `geomobinet_smg` | GRU + both graphs + geo |
| `geomobinet_smg_road` | Full model plus configured spatial edge attributes |

The default benchmark excludes LightGBM to make it runnable without the optional
extra, and excludes the road variant because the minimal spatial schema has no
attributes. Add those names to `variants` after supplying their dependencies/data.

`benchmark` trains exactly the configured variants/seeds on identical splits and
writes **validation-only** results. `report` aggregates validation mean/std.
`select` requires every configured trial and a persistence comparator, then freezes
validation rankings plus artifact hashes. Selection uses mean validation weighted
log-Huber across seeds; D/S count errors are reported separately.
`finalize` evaluates the frozen comparison on test once. New training is blocked
after selection, and neither selection nor the final test report is overwritten.
To change configurations after freezing, start a new study directory. Do not
choose hyperparameters by comparing repeated test runs.

Metrics include D/S MAE, RMSE and WAPE; D/S-proxy MAE; shortage precision, recall,
F1 and prevalence; per-hex/per-hour and high-demand/low-supply/zero-supply/high-
pressure slices. WAPE and shortage rates with undefined denominators are JSON
`null`, not fake perfect scores. The high-demand threshold is fitted on training
targets only.

## Artifacts and inference

```text
runs/<study>/
  config.json
  manifest.json                  # hashes, split bounds, ordered features, scalers
  <variant>/seed_<seed>/
    trial_result.json             # validation only + artifact hashes
    history.csv                  # neural training
    best.pt / last.pt            # neural model + complete resume state
    demand_5m.txt / idle_supply_t.txt  # optional LightGBM
    test_predictions.csv         # only after finalize
  validation_comparison.csv
  selection.json
  test_report.json
```

`predict` supports a neural checkpoint and defaults to the last available
snapshot. It requires only historical inputs, not a `t+5` target row. It freezes
feature/node order, history, geo version and preprocessing from the checkpoint.
Its CSV columns are `cutoff_time,target_time,hex_id,pred_demand,pred_idle_supply,ds_proxy`.
LightGBM participates in benchmark/finalize; the live `predict` CLI is neural-only.

## Legacy compatibility

The old `configs/train.yaml`, old model registry, residual controller and their
regression tests are retained, not mixed into GeoMobiNet. For old commands use:

```bash
uv run --project pipeline surge-ml legacy train --config pipeline/configs/train.yaml
uv run --project pipeline surge-ml legacy surge --config pipeline/configs/train.yaml --cutoff 100
```

Legacy log-ratio checkpoints are rejected by GeoMobiNet. Backend import scripts
expecting local/graph residuals need an explicit output-contract migration
before consuming D/S forecasts.

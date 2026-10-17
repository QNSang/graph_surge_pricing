# DuoCast + GGSO pipeline

The active pipeline is a **predict-then-optimize pipeline**. It trains forecasting models and per-cell response GLMs offline, then runs forecast → candidate utility → HiGHS MILP → independent validation. DuoCast combines temporal history, H3 adjacency, and directed physical-driver mobility before producing demand and supply forecasts.

No marketplace dataset has been supplied for this refactor. Synthetic fixtures exercise executable code; they do not establish model accuracy, calibrated operational thresholds, causal elasticity, revenue uplift, shadow eligibility or production readiness.

## Workflow completion — 2026-10-18

Validate input structure before starting a study:

```bash
uv run --offline --no-sync --project pipeline surge-ml preflight --config pipeline/configs/duocast.yaml --output pipeline/runs/preflight.json
```

Preflight checks all four tables plus metadata, availability, count domains, graph coverage and chronological sample ranges. It prints JSON and optionally creates one new report; it does not fit scalers/models, create training runs, approve source semantics, or overwrite input files. An existing output report is rejected. The standalone `python -m surge_ml.datasets.preflight` route remains available.

Continue a partially completed benchmark:

```bash
uv run --offline --no-sync --project pipeline surge-ml benchmark --config pipeline/configs/duocast.yaml --resume
```

Completed trials are reused only after checking identity, all required model hashes and the six validation metrics. Missing trials are trained. Interrupted neural trials resume from `last.pt`; a higher epoch budget extends neural training unless early stopping has already been exhausted. Partial LightGBM fits are rejected without deletion or implicit retraining. Use a new study directory for those partial fits. An existing completed LightGBM trial can be reused by benchmark continuation.

New trials maintain `training_state.json`. `RUNNING` records an unfinished attempt, not process liveness; `COMPLETED` is written only after the final result. An interruption during resumed training may leave a newer checkpoint and an older result file: the marker prevents selection of that stale result and permits checkpoint recovery. Study/trial lock files are never cleared automatically: after a hard process kill, first confirm no process is running before manually removing its stale lock.

Training, selection and finalization share a study lock. Selection refuses incomplete trials. Finalization validates every frozen trial, artifact, configured model/seed set and validation winner before producing any test predictions; it never changes the winner using test results. This is local-filesystem coordination, not a distributed job scheduler.

Response jobs now have a strict typed schema. The optional `report` path in `configs/responses.yaml` exports held-out NB/Binomial NLL, demand/completion errors, booking-weighted Brier/ECE, probability-bin calibration, surge-group diagnostics, support coverage and parameter-bound indicators. These are diagnostics, not new acceptance thresholds or causal/temporal-stability proof. Input, artifact and report paths must be distinct; existing outputs are refused. The input hash is checked again after fitting. Artifact/report files are exclusive writes, not a cross-file transaction.

`CheckpointForecastProvider` pins one deserialized checkpoint and its SHA-256 from the same bytes when constructed, and copies its configuration. Every prediction and provenance field uses that pinned revision even if the file is replaced later. Construct a new provider to switch checkpoints. This does not cache the neural model/device allocation or remove the existing TEST_ONLY source gate.

## Source layout

```text
src/surge_ml/
  cli.py                    # one command-line entrypoint
  _constant.py              # versioned identities and semantic definitions
  errors.py                 # typed fail-closed errors
  _utils/                   # atomic I/O, hashes, trial lock, timestamp helpers
  contracts/                # common primitives, forecast/response/decision contracts
  datasets/                 # no-geo tables, batches, response cohorts, explicit fixtures
  train/
    duocast/
      _constant.py          # five-model catalog identities and branch switches
      _types.py             # validated data/model/training configuration
      catalog.py            # model factory; no training on import
      variants/neural.py    # shared GRU, spatial/mobility GATv2, fusion, dual heads
      variants/lightgbm.py  # local lag-feature baseline
      train.py              # train/validation, checkpoint/resume and benchmark loop
    responses/
      _types.py             # explicit likelihood/bootstrap/calibration settings
      glm.py                # bounded NB2/Binomial likelihood fitting
      bootstrap.py          # paired moving-block parameter scenarios
      train.py              # per-cell fitting, held-out gates, artifact I/O
  inferences/
    schemas.py              # policy/frozen input validation; reuses contracts
    duocast.py              # checkpoint inference and explicitly identified mock adapter
    candidate_utility.py    # capacity, additive candidates, paired incremental utility
    network_optimizer.py   # sparse MILP, HiGHS, incumbent decoding
    validator.py           # recomputes selected policy independently of MILP matrices
    service.py             # complete VALID policy or empty INVALID result; frozen replay
  integrations/demo_prices.py # isolated in-memory simulated operator receipts
  reports/                  # metrics, validation selection, final test tables
  legacy.py                 # opt-in isolated subprocess for archived code
```

The old source/configs/tests are preserved under `_archive/pre_duocast_20261017/`, with a SHA-256 manifest. They are not imported by the active package. Existing datasets and `runs/` were not moved or deleted. The root `pyproject.toml` and environment dependencies remain compatible with the installed environment.

## Models and loss

| Variant | Architecture |
|---|---|
| `lgbm_local` | LightGBM baseline on the same causal temporal windows |
| `gru` | GRU + demand/supply heads |
| `gru_spatial` | GRU + Spatial GATv2 + heads |
| `gru_mobility` | GRU + directed Mobility GATv2 + heads |
| `duocast` | GRU + both graphs + gated residual fusion + heads |

`persistence` is available as an auxiliary comparator but is not in the default five-model study. Spatial/Mobility labels are ablations that retain the GRU, not graph-only networks. LightGBM is optional at installation but required to execute the default complete benchmark; missing dependencies raise an error rather than silently removing the baseline.

Neural heads predict nonnegative log1p(D), log1p(S); counts are decoded with expm1. The training and validation loss is `(Huber_D + Huber_S) / 2`. There is no D/S-ratio training head, GMV loss, or pricing backpropagation. LightGBM fits two log1p targets independently with its own L1 training objective. All variants use the same chronological observations, targets and reporting metrics.

The default forecast config is `configs/duocast.yaml`: five variants, seeds 42/43/44, history 12, horizon one 5-minute step. External paths are resolved relative to the YAML. The currently absent data paths are explicit input requirements, not an assertion that the data exists. See [DATA_INPUTS.md](DATA_INPUTS.md).

## Run from repository root

When dependencies are already installed, the following commands use them without downloading or synchronizing anything:

```bash
uv run --offline --no-sync --project pipeline surge-ml --help
uv run --offline --no-sync --project pipeline pytest pipeline/tests -q
```

A new synthetic end-to-end forecasting experiment:

```bash
uv run --offline --no-sync --project pipeline surge-ml demo --output-dir pipeline/runs/my-duocast-demo
uv run --offline --no-sync --project pipeline surge-ml benchmark --config pipeline/runs/my-duocast-demo/config.yaml
uv run --offline --no-sync --project pipeline surge-ml select --config pipeline/runs/my-duocast-demo/config.yaml
uv run --offline --no-sync --project pipeline surge-ml finalize --config pipeline/runs/my-duocast-demo/config.yaml
uv run --offline --no-sync --project pipeline surge-ml predict --config pipeline/runs/my-duocast-demo/config.yaml --checkpoint pipeline/runs/my-duocast-demo/runs/duocast/seed_42/best.pt --output pipeline/runs/my-duocast-demo/latest_forecast.csv
```

Use a fresh demo/output directory. Existing experiments, selected model artifacts and final test results are not silently overwritten. Demo uses small networks, one seed and two epochs for software verification, not accuracy evaluation.

With supplied and reviewed forecast data:

```bash
uv run --offline --no-sync --project pipeline surge-ml prepare --config pipeline/configs/duocast.yaml
uv run --offline --no-sync --project pipeline surge-ml train --config pipeline/configs/duocast.yaml --variant duocast --seed 42
uv run --offline --no-sync --project pipeline surge-ml benchmark --config pipeline/configs/duocast.yaml
```

Neural resume restores optimizer, scheduler, random generators and early-stop state. Only the epoch budget can change in the same trial identity. `--smoke` uses a separate output directory and bounded batches. `predict` currently accepts neural checkpoints; LightGBM participates in training/benchmark/finalize, not the standalone neural prediction command.

## Response fitting and optimization

`train/responses` fits Negative Binomial demand and Binomial fulfillment independently per cell, with explicit TEST_ONLY settings. Coefficients, preprocessing, support, bootstrap scenarios and held-out calibration status are persisted. No fitting runs inside a decision request.

`configs/responses.yaml` is a job template. Fill the observation source, full cell list, chronological split and fit cutoff; the command rejects missing values rather than inventing them:

```bash
uv run --offline --no-sync --project pipeline surge-ml fit-responses --config pipeline/configs/responses.yaml
```

The default numerical settings and `configs/optimization.yaml` are marked TEST_ONLY, not approved business settings. The decision payload embeds a frozen policy object matching that YAML/schema; replay uses the frozen policy, not a current mutable config file.

A fitted response -> mock forecast -> solver demonstration:

```bash
uv run --offline --no-sync --project pipeline surge-ml decision-demo --fit-response --output-dir pipeline/runs/my-ggso-demo
uv run --offline --no-sync --project pipeline surge-ml replay --input pipeline/runs/my-ggso-demo/input.json --output pipeline/runs/my-ggso-replay.json
```

A real synthetic-trained DuoCast checkpoint can be exercised through `decide --config ... --checkpoint ... --input ... --output-dir ...`. The input JSON must contain `identity`, `operational`, `response`, and `policy`; all source/node/time versions must match. The provider performs one neural inference for the full network. Official source/model promotion remains a separate gate. No production price gateway is included.

Technical failures return `INVALID`, empty recommendations/selected candidates, `optimized_policy=null` and no publication. The nominal network GMV no-loss constraint is separate from conservative utility and penalties. Partial/manual simulated decisions are not falsely certified as the original full-network MILP policy.

## Reporting and artifacts

The six requested metrics are exported as mean and population SD across configured seeds:

`D-MAE`, `S-MAE`, `Log D-MAE`, `Log S-MAE`, `Log D/S MAE`, `Log D/S RMSE`.

Log count metrics use log1p. Log D/S is `log((D+1)/(S+1))`, for predictions and truth alike. These are diagnostics on two count forecasts, not a change to the model's target.

Each study writes:

```text
manifest.json                      # content hashes, schema, data kind, splits and scalers
<variant>/seed_<seed>/best.pt        # neural checkpoint
<variant>/seed_<seed>/last.pt        # complete neural resume state
<variant>/seed_<seed>/history.csv
<variant>/seed_<seed>/trial_result.json
<variant>/seed_<seed>/demand_5m.txt   # LightGBM only
<variant>/seed_<seed>/idle_supply_t.txt
selection.json                     # frozen validation-based comparison
validation_comparison.csv
forecast_validation_comparison.csv / .md
test_report.json                   # only after finalize
forecast_test_comparison.csv / .md
```

Selection uses mean validation log-Huber, not test metrics. `select` freezes all configured trials and their artifact hashes; `finalize` reports test without changing the selected variant. A research winner is not automatically a deployment approval or a switch of the GGSO provider.

## Compatibility and limits

Forecast checkpoints require `duocast_ds_h5_v1`; incompatible checkpoint and target contracts are rejected. GGSO transport uses v2 envelopes, while old v1 replay remains isolated in the archive. The existing backend v1 provider was not auto-switched to v2, and no frontend/DB/API rollout is claimed.

The archived ratio command is explicitly available through `surge-ml legacy ...`, and old GGSO replay through `surge-ml legacy-ggso ...`. Keep external consumers on their original contract until they are deliberately migrated.

Code acceptance tests are in `tests/duocast`, `tests/responses`, and `tests/inferences`. New tests cover all five model training/reporting, exact CPU resume, no-geo rejection, integer count validation, missing-vs-empty mobility snapshots, likelihood/parameter recovery, paired bootstrap, MILP exhaustive checks, fail-closed errors, and a real synthetic checkpoint through the full decision pipeline. Real-data accuracy/calibration and GPU determinism are not inferred from these tests.

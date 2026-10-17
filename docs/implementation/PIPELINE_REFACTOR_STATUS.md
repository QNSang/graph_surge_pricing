# DuoCast Pipeline — Executed Code and Evidence

## Active implementation

`pipeline/src/surge_ml/` contains `_utils`, `contracts`, `datasets`, `train/duocast`, `train/responses`, `inferences`, `reports`, and controlled integration helpers. The default CLI dispatches to this structure.

The forecast catalog contains `lgbm_local`, `gru`, `gru_spatial`, `gru_mobility`, and `duocast`. DuoCast uses both graph branches, gated fusion, and independent demand/supply heads. Checkpoints must use contract `duocast_ds_h5_v1`.

Response fitting remains independent from forecast training. Candidate construction, fixed capacity handling, the configured action grid, booking-rate constraints, nominal modeled network no-loss, HiGHS status handling, and solver-independent validation are implemented for synthetic/test-only workflows.

## Guards

- Observed target counts reject fractional values.
- Mobility coverage distinguishes missing snapshots from observed empty graphs.
- Response support is checked independently of policy bounds.
- Feature availability is checked against the cutoff.
- Missing or incompatible checkpoints create persisted invalid/no-policy results.
- A full integration test runs one newly trained DuoCast checkpoint through response fitting, candidate simulation, MILP, and independent validation.

## Verification

Latest local verification:

- Pipeline suite: 177 passed, 4 library warnings, exit 0.
- Backend unit suite: 49 passed, exit 0.
- Secret-pattern scan over the commit scope: no matches.
- Cached and generated test files are excluded from Git.

These tests use synthetic fixtures. No official-data training, real calibration, shadow run, production execution, or causal business evaluation was performed.

## Compatibility boundary

Historical code is isolated from the default runtime. Active source does not import it during normal DuoCast commands. Production consumers must use the active versioned contracts and cannot infer compatibility from filenames or display names.

Backend v1 transport, UI/DB/API migration, official source semantics, and production approval remain separate tasks.

## Evidence locations

- Active commands and structure: `pipeline/README.md`
- Input contract: `pipeline/DATA_INPUTS.md`
- Forecast specification: `docs/model/forecasting_contract.md`
- Current work status: `docs/ai-context/CURRENT_STATE.md`

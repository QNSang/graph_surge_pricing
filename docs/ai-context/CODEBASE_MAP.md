# Codebase Map

## Pipeline

| Path | Responsibility |
|---|---|
| `pipeline/src/surge_ml/cli.py` | Active command dispatch |
| `pipeline/configs/duocast.yaml` | Forecast training and inference configuration |
| `pipeline/configs/responses.yaml` | Response-model fitting configuration |
| `pipeline/configs/optimization.yaml` | Candidate and optimization configuration |
| `pipeline/src/surge_ml/datasets/` | Data loading, validation, fixtures and batching |
| `pipeline/src/surge_ml/train/duocast/` | Forecast models, catalog and training |
| `pipeline/src/surge_ml/train/responses/` | Negative Binomial and Binomial fitting |
| `pipeline/src/surge_ml/inferences/` | Forecast adapters, candidates, MILP, validation and decision service |
| `pipeline/src/surge_ml/contracts/` | Forecast, response and decision schemas |
| `pipeline/src/surge_ml/reports/` | Evaluation and reporting |
| `pipeline/tests/duocast/` | Forecast tests |
| `pipeline/tests/responses/` | Response tests |
| `pipeline/tests/inferences/` | Decision-path tests |

## Backend

| Path | Responsibility |
|---|---|
| `backend/app/providers/ggso_provider.py` | GGSO artifact bridge for controlled workflows |
| `backend/app/providers/gnn_adapter.py` | Provider boundary |
| `backend/app/providers/precomputed_provider.py` | Precomputed proposal ingestion |
| `backend/tests/unit/test_ggso_provider.py` | GGSO provider validation |

## Documentation

| Path | Responsibility |
|---|---|
| `docs/model/duocast_model.md` | DuoCast architecture handoff |
| `docs/model/forecasting_contract.md` | Forecast semantics and invariants |
| `docs/model/response_model.md` | Marketplace response models |
| `docs/model/candidate_simulation.md` | Candidate outcomes |
| `docs/model/milp_optimization.md` | Network optimization |
| `docs/backend/decision_pipeline.md` | End-to-end orchestration |
| `docs/contracts/` | Versioned data and interface contracts |
| `docs/evaluation/` | Evaluation protocols |
| `docs/frontend/ggso_monitoring_dashboard.md` | Monitoring UI contract |

## Runtime evidence

Generated runs, datasets, calibration artifacts and local environments are intentionally outside the tracked source tree. Do not infer production readiness from their presence alone.

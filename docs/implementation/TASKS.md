# GGSO Implementation Tasks

Cập nhật: 2026-10-18.

## Completed — synthetic/test-only

| Task | Status | Evidence |
|---|---|---|
| T01 — Forecast contracts and DuoCast training/inference | DONE | `pipeline/src/surge_ml/train/duocast/`, `datasets/`, `contracts/` |
| T02 — Response-model fitting and artifacts | DONE | `pipeline/src/surge_ml/train/responses/`, response tests |
| T03 — Candidate outcomes and uncertainty | DONE | `pipeline/src/surge_ml/inferences/candidate_utility.py` |
| T04 — Joint MILP and independent validator | DONE | `network_optimizer.py`, `validator.py` |
| T05 — Full decision service and replay | DONE | `inferences/service.py`, workflow tests |
| T06 — Backend GGSO bridge | DONE for controlled test scope | `backend/app/providers/ggso_provider.py` and unit tests |
| T07 — Documentation alignment | DONE | Current model, contracts, evaluation, orchestration, and report docs |

Latest verification: 177 pipeline tests passed with 4 library warnings; 49 backend unit tests passed.

## Pending — official data and model evidence

| Task | Required output | Blocker |
|---|---|---|
| T08 — Official source audit | Event taxonomy, driver-state mapping, lineage and ownership | Source access and domain approval |
| T09 — Dataset manifest | Immutable fingerprints, cell mapping, graph versions and frozen splits | Official dataset |
| T10 — Forecast evaluation | Approved checkpoint, accuracy, calibration and slice reports | T08–T09 |
| T11 — Response calibration | Real fitted artifacts, support and stability evidence | Matured historical cohorts |
| T12 — Operational policy | Approved fare, `Q`, capacity, bounds, tolerances and promotion thresholds | Business and operations decisions |

## Pending — integration and rollout

| Task | Required output | Authorization |
|---|---|---|
| T13 — Atomic execution adapter | Full-policy write, version checks, idempotency and persisted receipts | Production integration approval |
| T14 — Monitoring dashboard migration | Five-minute status, validation, applied policy and history; no action controls | Frontend integration approval |
| T15 — Offline replay and shadow | Reproducible results and operational guardrails | Approved official artifacts |
| T16 — Switchback experiment | Treatment effect and confidence interval for realized network GMV | Experiment approval |

## Execution rules

- A planned task does not authorize code, training, deployment, or publication.
- Required-cell invalidity fails the complete decision.
- Synthetic values and artifacts remain explicitly test-only.
- Forecast accuracy, response validity, optimization feasibility, execution correctness, and business uplift are separate gates.

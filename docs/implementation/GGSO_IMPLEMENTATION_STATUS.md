# GGSO Implementation Evidence — TEST_ONLY

Cập nhật: 2026-10-18.

## Implemented flow

The repository contains an executable test path:

```text
frozen network snapshot
→ one DuoCast forecast call
→ response and capacity evaluation
→ candidate construction
→ joint MILP
→ independent full-policy validation
→ valid or invalid decision envelope
```

The implementation includes Negative Binomial and Binomial fitting, paired bootstrap scenarios, JSON artifacts, CLI demo/replay, backend artifact bridging, and controlled execution receipts.

## Evidence by area

| Area | Evidence status |
|---|---|
| Forecast contracts, training, checkpoint, inference | SYNTHETIC_PASS |
| Response fitting and artifacts | SYNTHETIC_PASS |
| Candidate construction and uncertainty | SYNTHETIC_PASS |
| MILP and independent validation | SYNTHETIC_PASS |
| Frozen replay and decision serialization | SYNTHETIC_PASS |
| Backend bridge | UNIT_TEST_PASS |
| Database/API execution receipt E2E | NOT RUN |
| Browser/dashboard integration | NOT RUN |
| Official data and checkpoint | PENDING |
| Real calibration and business experiment | PENDING |

## Latest verification

- Backend unit suite: 49 passed.
- Pipeline suite: 177 passed with 4 library warnings.

The warnings come from third-party PyTorch and LightGBM behavior and did not fail the suite. These counts do not include DB, API, browser, production, or official-data evaluation.

## Runtime contracts

Automatic actions are versioned and bounded by configuration. Unsupported actions are rejected rather than clamped. The MILP selects one candidate per required cell, and the independent validator recomputes coverage, constraints, and objective components.

A valid full-network policy may proceed to the execution boundary. An invalid result contains no optimized policy and creates no new price write. The current effective prices therefore remain unchanged.

## Dashboard and operator boundary

The target dashboard is monitoring-only. It presents forecasts, current and applied prices, validation status, execution status, and history for each five-minute cycle. It does not expose Accept Selected, manual price editing, or operator approval.

## Limits

Synthetic software tests do not establish:

- official data semantics or lineage;
- real forecast accuracy or calibration;
- reliable or causal response coefficients;
- production execution correctness;
- realized GMV uplift; or
- production authorization.

Those claims require the official data, model, integration, and switchback gates described in `IMPLEMENTATION_PLAN.md` and `TASKS.md`.

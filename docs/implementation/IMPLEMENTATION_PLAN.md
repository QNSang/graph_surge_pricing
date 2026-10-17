# GGSO Implementation Plan

## Completion levels

- **Synthetic implementation:** executable contracts, training fixtures, response fitting, candidates, MILP, validation, replay, and backend bridge. This level is implemented and tested.
- **Official implementation:** approved source data, real checkpoint, calibrated response models, operational policies, production integration, and business experiment. This level remains pending.

## P1 — Contracts and fixtures

Status: complete for synthetic/test-only scope.

Outputs: versioned schemas, deterministic full-network fixtures, cutoff and identity validation, and fail-closed error envelopes.

## P2 — Response fitting

Status: complete for synthetic/test-only scope.

Outputs: per-cell Negative Binomial demand fitting, Binomial fulfillment fitting, chronological splits, train-only preprocessing, paired bootstrap scenarios, and versioned artifacts.

## P3 — Candidate construction

Status: complete for synthetic/test-only scope.

Outputs: configured action grid, demand and fulfillment response evaluation, capacity handling, incremental utility, eligibility, and rejection reasons.

## P4 — Joint optimization

Status: complete for synthetic/test-only scope.

Outputs: one candidate per required cell, booking-rate and nominal modeled no-loss constraints, penalties, solver status handling, and independent validation.

## P5 — DuoCast integration

Status: complete for synthetic/test-only scope.

Outputs: `duocast_ds_h5_v1`, one batched network inference per cutoff, complete forecast envelope, frozen operational context, and decision-service integration.

## P6 — Synthetic end-to-end verification

Status: complete. Latest evidence: 177 pipeline tests passed with 4 library warnings; 49 backend unit tests passed. No official-data, DB/API, browser, shadow, or production claim is implied.

## P7 — Official dataset validation

Status: pending. Required outputs: source ownership, event taxonomy, label validation, immutable manifest, frozen splits, complete H3 and mobility coverage, and cutoff-safe availability evidence.

## P8 — Official model fitting and evaluation

Status: pending. Required outputs: approved DuoCast checkpoint, real-data forecast metrics, response-model support and calibration, promotion thresholds, and reproducible evaluation reports.

## P9 — Integration and business validation

Status: pending and separately authorized. Required outputs: atomic full-policy execution and receipts, production permissions and monitoring, approved shadow rollout, and a prospective switchback experiment with realized network GMV as the primary outcome.

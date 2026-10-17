# Candidate & Policy Output Contract

Status: target contract aligned with the current technical report. Field names remain a serialization proposal until implemented and versioned.

## 1. Candidate table

| Field | Domain/semantics |
|---|---|
| decision_id, candidate_id | Stable identities; never infer identity from row position |
| hex_id | Required H3 cell |
| action | Canonical additive multiplier adjustment `a` |
| proposed_surge | `s0+a`; must satisfy the grid, precision and bounds without clamping |
| expected_demand | Finite nonnegative booking demand over the five-minute horizon |
| fulfillment_rate | Probability in `[0,1]` before the capacity ceiling |
| expected_completed | Finite nonnegative value no greater than demand or capacity |
| expected_gmv | Completed rides × presurge fare × multiplier |
| incremental_gmv | Nominal candidate GMV minus the nominal baseline |
| conservative_utility | Quantile of paired scenario increments; may be negative |
| feasible, rejection_reasons | Candidate eligibility under the versioned policy |
| provenance | Cutoff, reference, forecast/response/config versions, semantic profile and currency |

Do not round expected counts or alter candidate prices for display compatibility. Internal precision and serialized price precision must follow the approved numerical contract.

## 2. Network result envelope

| Field | Rule |
|---|---|
| decision_id, schema_version | Run and serialization identity |
| cutoff_time, target_time, generated_at | Timezone-aware timestamps |
| required_hex_ids, node_mapping_version | Complete network identity |
| reference_policy_version | Exact effective policy used as `s0` |
| forecast_version, response_version, policy_config_version | Reproducibility identities |
| result_status | `VALID` or `INVALID` |
| error_code, diagnostics | Technical failure metadata for INVALID results |
| selected_candidates | Exact selected IDs and values for an accepted solve |
| optimized_policy | Exactly one multiplier for every required cell when VALID; otherwise null |
| estimated_metrics | Nominal GMV/delta, conservative score, Booking Rate and penalties |
| constraint_checks | Independently recomputed checks and tolerances |
| solver | Raw/accepted status, objective, bound/gap, runtime and config identity |
| execution | `NOT_REQUESTED`, `REJECTED`, `SUBMITTED`, `APPLIED` or an equivalent versioned receipt/status |

Solver success, validation success and execution success are separate states. `production_effective=true` must never be inferred from a solve or transport acknowledgement alone. Legacy Pressure, Revision, local-ratio and `used_fallback` fields are not part of this contract.

## 3. Outcome semantics

**VALID:** the MILP has an acceptable complete solution and the independent validator passes. The exact full-network policy is eligible for automatic application.

**INVALID:** any critical failure in inputs, candidate simulation, solver handling or validation. The result has `recommendations=[]`, `optimized_policy=null`, `selected_candidates=[]`, and no execution request. Current effective prices remain unchanged because no write is issued; they are not returned as a GGSO fallback policy.

`HOLD` may be used only as a descriptive label for a cell whose selected additive action is zero inside a VALID policy. It is not a failure state. `INCREASE` and `DECREASE` may likewise summarize the sign of the selected action. `REVIEW` is not a MILP action and is not part of the automatic execution path.

## 4. Invariants

- **CP-01:** all records share the same decision, cutoff, versions, required cells and currency.
- **CP-02:** selected multipliers match the candidate table exactly; no post-solve clipping or manual substitution.
- **CP-03:** a VALID result is complete. An INVALID result has no recommendation, policy or execution request.
- **CP-04:** null and zero are distinct; no feasible incumbent is not HOLD.
- **CP-05:** only the exact independently validated full-network policy may be submitted for automatic application. Partial application and per-hex manual overrides are outside the GGSO target contract.
- **CP-06:** the next decision cycle uses the latest confirmed effective policy, never a pending or merely recorded execution request.

Proposed technical reasons include `FORECAST_INVALID`, `SEMANTIC_MISMATCH`, `RESPONSE_INVALID`, `INPUT_INVALID`, `NO_CANDIDATES`, `SOLVER_NO_ACCEPTABLE_SOLUTION`, `POST_VALIDATION_FAILED`, `REFERENCE_UNAVAILABLE`, `REFERENCE_VERSION_CONFLICT` and `EXECUTION_REJECTED`. Final names and transport mapping require versioned implementation.

## 5. Automatic execution contract

The target flow has no Accept Selected, Accept All, manual one-hex edit or operator approval step. After validation, the backend checks the complete policy's price bounds, precision, reference version and idempotency, then applies it automatically. If any execution precondition fails, no subset may be applied as the same GGSO decision.

The monitoring dashboard may display current, recommended and applied multipliers, but it does not mutate the policy. Existing legacy/demo action services are implementation history and must not be treated as this contract.

## 6. Compatibility and acceptance

Schema evolution requires an explicit adapter and version; do not overwrite `surge_proposal_v1` or `recommendation.v1` in place. Tests cover round-trip serialization, mismatched IDs and versions, corrupted selections, missing/stale references, unknown reasons, automatic full-policy submission, idempotent retries, execution rejection, and INVALID/no-write behavior.

The default additive candidate grid is `{-0.3,-0.2,-0.1,0,0.1,0.2,0.3}`. The hard nominal network no-loss check is `sum(selected incremental_gmv) >= 0` on the complete selected vector. An all-zero policy may satisfy nominal no-loss while still violating the Booking Rate guardrail; such a case is INVALID rather than a forced HOLD policy.

See [decision pipeline](../backend/decision_pipeline.md), [MILP](../model/milp_optimization.md), and [test strategy](../evaluation/TEST_STRATEGY.md).

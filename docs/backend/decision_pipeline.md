# Decision Pipeline — GGSO

Status: target integration design aligned with the current technical report; implementation and production activation remain separate evidence gates.

## 1. Responsibilities

The orchestrator combines a frozen network snapshot, one DuoCast inference, operational context, response artifacts, candidate simulation, the MILP, and an independent validator into one five-minute decision run. It does not duplicate response equations or silently adapt incompatible model and data contracts.

The target system applies a valid full-network policy automatically. This design statement does not enable production writes in the current repository; live execution still requires an authorized backend integration and deployment decision.

## 2. Five-minute online flow

| Step | Required behavior |
|---|---|
| 1. Freeze snapshot | Fix cutoff, required H3 cells, current effective surge, graphs, operational inputs and all version identities |
| 2. Forecast once | Run DuoCast once for the complete network; do not rerun it for candidates |
| 3. Validate inputs | Check semantic profile, node/time alignment, D/Q/S/K/fare/context and eligible response artifacts |
| 4. Simulate candidates | Evaluate the approved additive grid with fixed capacity, fare and pre-decision context |
| 5. Build coefficients | Compute nominal and conservative quantities with complete provenance |
| 6. Solve | Run the MILP on the complete candidate table under the approved constraints |
| 7. Revalidate | Independently recompute coverage, selected candidates, price bounds, Booking Rate and nominal network no-loss |
| 8. Execute or reject | Apply the complete policy automatically only when VALID; otherwise issue no write |
| 9. Monitor | Expose forecast, policy, validation and execution status to the dashboard and audit history |

DP-01: every step uses the same cutoff, snapshot and versions. DP-02: exactly one full-network forecast per decision cycle. DP-03: a critical failure in one required cell invalidates the complete run; optimized cells are never combined with stale prices as a new GGSO policy.

## 3. VALID and INVALID outcomes

**VALID:** the solver returns an acceptable complete solution and the independent validator passes. The backend then verifies price bounds, precision, current reference version and idempotency before applying the exact full-network policy automatically. An execution receipt is distinct from solver and validation status.

**INVALID:** an input, forecast, response, candidate, solver or validation failure produces `status=INVALID`, `recommendations=[]`, `optimized_policy=null` and `selected_candidates=[]`. GGSO sends no price write. Current effective prices therefore remain unchanged, but they are not returned as a generated fallback policy. The active contract does not use `used_fallback`, fabricated HOLD rows or REVIEW to represent failure.

If the current reference policy is unavailable or stale before execution, the run is INVALID. GGSO does not assume 1.0, reconstruct prices from deltas or rebase an old policy onto a new reference.

## 4. Execution boundary

Only the full policy certified for the decision snapshot may be executed. The target GGSO flow has no Accept Selected, Accept All, manual one-hex override or operator approval step. The dashboard is a monitoring interface and exposes no pricing action controls.

Execution must be atomic at the contract level: either the complete validated policy is accepted for application, or no GGSO price update is issued. A transport acknowledgement alone is not proof that prices are EFFECTIVE. The next five-minute snapshot must use the latest confirmed effective surge multipliers as its reference state.

The repository's existing DEMO/REPLAY and legacy per-hex decision services remain implementation evidence, not the target GGSO execution contract. Documentation changes do not authorize a production pricing gateway or change runtime mode.

## 5. Compatibility

The existing backend consumes legacy `surge_proposal_v1`/`recommendation.v1` contracts and is not evidence of a live GGSO route. A versioned adapter is required; it must not fabricate Pressure, Revision or local-ratio fields from DuoCast forecasts.

DP-04: schema and semantic mismatches fail before candidate simulation. DP-05: GGSO result, validation and execution states remain separate. DP-06: only a complete policy from the accepted solve can reach execution.

## 6. Concurrency, retries and audit

Decision and execution identity must include the cutoff, reference policy, forecast, response, policy configuration and node mapping versions. Retries for the same execution intent must be idempotent. A reference-version conflict before application invalidates that execution attempt; the system does not silently rebase it.

DP-07: retain input identities, timestamps, semantic profile, artifact/config versions, candidate IDs, solver raw and accepted status, objective components, independent constraint checks, invalid reasons, execution request identity and receipt/status.

## 7. Acceptance

Test missing, stale and duplicate cells; incompatible artifacts; empty action sets; solver timeout branches; corrupted decoded solutions; missing references; reference-version races; retry/idempotency; atomic full-policy execution; and execution rejection after validation. Every critical failure must prove empty recommendations, a null policy and no price write. A valid cycle must prove that the exact independently validated full-network policy is the one submitted for automatic application.

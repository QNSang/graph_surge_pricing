# Test Strategy — GGSO

Status: test design. Historical test evidence is recorded separately; this document does not claim new tests were executed.

## 1. Traceability matrix

| Requirement | Test type | Expected behavior |
|---|---|---|
| DT-01…05 | Data/contract negative tests | Reject duplicate, missing or unknown nodes, late availability, wrong units/semantics; distinguish zero from null |
| FC-01…09, MI-01…08 | Forecast adapter/parity | Correct target, horizon, ordering and no-geo DuoCast profile; exactly one inference per full-network decision |
| RM-01…05, RA-01…04 | Fitting/artifact/serialization | Compatible integer cohorts, bounded coefficients, correct context/scenarios and eligible models for every required cell |
| CS-01…07 | Numeric/property tests | Correct grid, filtering, baseline, fixed `K`, cap, fare units, paired quantile and finite outcomes |
| MO-01…07 | Solver enumeration/validator | Exactly one candidate per cell; correct objective, Booking Rate and hard nominal network no-loss; reject invalid solutions; distinguish timeout/incumbent statuses |
| CP-01…06, DP-01…07 | End-to-end and fault injection | VALID complete policy can enter automatic execution; INVALID has empty recommendations, null policy and no write; no partial application or false EFFECTIVE state |

## 2. Golden arithmetic fixture

Use test-only values such as `beta=gamma=0`, baseline logit `0`, `D=10`, `K>=10`, fare `100`, `s0=1.2` and action `0.1`. Expected values are `FR=0.5`, `C=5`, `U0=600`, `U1=650`, and delta `50`. The zero action has incremental utility `0`. These are test fixtures, not business defaults or uplift evidence.

Add `D=0`, `K=0`, extreme finite logits, beta/gamma bounds, invalid/empty scenarios, grid boundaries and ETA unit conversion. When a scenario changes gamma, recompute baseline fulfillment under the same scenario.

## 3. Small MILP oracle

Enumerate every combination for a two- or three-cell network. Compute feasibility and objective independently from the solver wrapper and compare against the exhaustive optimum under an approved tolerance. Multiple optimal policies need not share candidate IDs unless a tie-break contract is defined.

Cover Booking Rate infeasibility, zero-action infeasibility, negative nominal network GMV despite a positive regularized objective, zero penalties, duplicate edges, missing cells, timeout with and without an incumbent, and corrupted decoded solutions. The independent validator must reject an invalid policy even when the raw solver status indicates success.

## 4. Integration failure matrix

A stale forecast, wrong semantic profile, missing response artifact, missing candidate, incompatible reference, nonfinite value, unacceptable solver result or validator failure produces `status=INVALID`, `recommendations=[]`, `optimized_policy=null`, and no execution request. Do not combine optimized cells with old prices, fabricate a fallback policy or convert failure into HOLD/REVIEW.

A VALID decision must prove:

- the submitted vector equals the independently validated full-network policy exactly;
- execution checks price bounds, precision, reference version and idempotency;
- a stale reference or failed execution precondition causes no write and no partial application;
- retrying the same execution identity does not apply the policy twice;
- only a confirmed execution receipt can mark a policy APPLIED/EFFECTIVE;
- the next five-minute cycle uses the latest confirmed effective policy from a fresh snapshot.

## 5. Monitoring dashboard acceptance

Verify that each completed cycle updates the H3 map, observed and forecast demand/supply, current/recommended/applied multipliers, validation result, execution status and history. The target dashboard must not expose Accept Selected, Accept All, manual override or approval controls. Invalid cycles must clearly show that current prices remained unchanged because no write occurred.

Historical legacy UI tests may continue to cover existing DEMO/REPLAY actions, but those tests are not acceptance evidence for the GGSO target dashboard.

## 6. Regression and execution safety

Keep legacy and GGSO schemas isolated. Do not change expected values to hide semantic mismatch. Database, live gateway and UI tests run only in an authorized isolated environment; documentation changes do not authorize production data or writes.

Separate software correctness, forecast/response calibration, modeled policy estimates and realized business impact. A prospective switchback experiment is required for causal realized-GMV evidence.

## 7. Evidence record

Each run records revision/worktree scope, test IDs, fixture/config/schema versions, exact command, exit code, timestamp, environment, report/log path and limitations. Only an executed successful test is PASS. SKIPPED, NOT RUN and APPROVAL REQUIRED do not contribute to the pass rate.

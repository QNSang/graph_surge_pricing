# GGSO Implementation Tasks — Nine-phase Code First / Synthetic → Official Data Backlog

## Execution update — 2026-10-16

User đã yêu cầu implement sau phiên soạn backlog. Source `pipeline/src/surge_ml/ggso/` và explicit DEMO JSON bridge `backend/app/providers/ggso_provider.py` hiện đã tồn tại. Trạng thái thực thi, source map, các test IDs đã phủ, lệnh/exit codes và giới hạn: **[GGSO_IMPLEMENTATION_STATUS.md](GGSO_IMPLEMENTATION_STATUS.md)**.

| Nhóm task | Trạng thái hiện tại có evidence |
|---|---|
| G00.1/00.2, G01.1–01.3 | SYNTHETIC_PASS: declared mock semantics/contracts/fixtures/consumer handoff; không phải source-data parity thật |
| G03.1–03.5, G04.1–04.4, G05.1–05.4 | SYNTHETIC_PASS: actual GLM fitting/NLL/bootstrap, simulation, MILP and independent validator |
| G02.1/02.2, G06.1/06.2, G08.1 | SYNTHETIC_PASS for mock forecast, offline runner and opt-in DEMO JSON adapter; default registry/importer unchanged |
| G08.2 | SYNTHETIC_PASS for in-memory simulated receipts, permission/bounds/version/idempotency/audit and next-cycle reference tests; not production execution/DB certification |
| G07.1/07.2/07.4/07.5 | SYNTHETIC_PASS within executed engine/mock and selected regression scope |
| G07.3 | Mock/JSON consumer portion tested; actual DB/API receipt E2E NOT RUN |
| G08.3 | UI/API default activation NOT RUN / not changed |
| P7–P9 tasks | OFFICIAL_DATA_PENDING / NOT RUN; no model promotion, shadow approval or pricing publication |

Final evidence: **129 pipeline/GGSO/GeoMobiNet/controller/contract tests PASS** and **49 backend unit tests PASS**, both exit 0. Fitted-synthetic demo: VALID, 2 recommendations, no publication. This is not an all-repository/UI test claim.

## Original planning baseline — historical

Các status `PLANNED_SYNTHETIC`, path “Proposed/chưa tồn tại”, câu “chưa implement/test” và “scope lock của lần này” trong phần dưới mô tả **phiên tạo backlog trước khi user giao implement**. Giữ lại làm planning history; execution update ở trên và evidence document là nguồn trạng thái mới. Không diễn giải phần lịch sử thành quyền tự train/deploy hoặc thành PASS cho DB/UI/official-data tasks chưa chạy.

**Date:** 2026-10-16. **Status:** PLANNING ONLY; toàn bộ tasks dưới đây chưa được implement/test trong lần cập nhật này. Plan và các phase gates: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). Source of decisions: [DECISION_LOG.md](DECISION_LOG.md). **Không tự thực hiện tasks, training, DB/API/UI changes, commit hoặc deploy** chỉ vì có backlog.

## 0. Cách đọc backlog

- **ID:** giữ nguyên các task IDs gốc G00…G08 và mọi ID có suffix đang tồn tại; thêm IDs mới cho official-data phases. Mapping: P1=G00/G01, P2=G03, P3=G04, P4=G05, P5=G02/G06/G08, P6=G07, **P7=G00.3/G00.4/G01.4**, **P8=G03.6/G02.3/G07.6**, **P9=G07.7/G08.4**. Không đổi tên/renumber tasks cũ.
- **Status:** `PLANNED_SYNTHETIC` = P1–P6 implement/test bằng TEST_ONLY fixtures/mock sau khi được giao; `SYNTHETIC_PASS` chỉ sau thực chạy tests; `OFFICIAL_DATA_PENDING` = blocker riêng cho P7–P9/real promotion, **không chặn P1–P6**; `POLICY_PRODUCTION_PENDING` = chỉ chặn dùng thật, không chặn synthetic test; `BLOCKED_INTEGRATION` = đợi code/contract task khác hoặc quyền runtime riêng. Các status là **planned readiness**, không phải code đã DONE.
- **Existing (E)** = file đã được quan sát trong checkout. **Proposed (P)** = file/namespace *có thể tạo trong tương lai*; chưa tồn tại hoặc chưa xác nhận. Mọi thay đổi source trong bảng đều là **future task**, không phải output của lần cập nhật docs.
- **Path shorthand:** `geomobinet/` tương ứng `pipeline/src/surge_ml/geomobinet/`; `ggso/` tương ứng namespace mới được **đề xuất** `pipeline/src/surge_ml/ggso/`. Những path có tiền tố `backend/`, `pipeline/`, `ui/` và `docs/` là relative từ repository root. `ggso/` hiện chưa có trong cây source quan sát.
- **PASS requirement:** riêng P1–P6 cho phép `SYNTHETIC_PASS` từ exact test command, exit code, synthetic fixture/checkpoint/config versions và evidence artifact path; P7–P9 phải có official source/artifact/evaluation evidence. `SYNTHETIC_PASS` không bao giờ mặc nhiên trở thành MODEL_ELIGIBLE/SHADOW_APPROVED. Không báo PASS từ docs/README, smoke fixture hoặc package tồn tại.
- **Constraint:** GGSO invalid input/fitting/solver/validation ⇒ `recommendations=[]`, `optimized_policy=null`, **no execution request/write**. Legacy or demo action không tự tương đương production EFFECTIVE. Không thay algorithms của GeoMobiNet, NB/Binomial GLMs, simulator hay MILP.

## Delivery gates & execution order

| Phase | Gate | Main task IDs | Official data required to finish this phase? |
|---|---|---|---|
| P1 — Data & Interface Contracts + Synthetic Fixtures | SYNTHETIC | G00.1–G00.2 synthetic source contract, G01.1–G01.3 | **No** |
| P2 — NB/Binomial GLM + NLL + Bootstrap | SYNTHETIC | G03.1–G03.5 | **No** |
| P3 — Candidate Surge Simulation | SYNTHETIC | G04.1–G04.4 | **No** |
| P4 — HiGHS MILP + Independent Validator | SYNTHETIC | G05.1–G05.4 | **No** |
| P5 — DuoCast mock integration / GeoMobiNet compatibility gate | SYNTHETIC | G02.1–G02.2, G06.1–G06.2, G08.1–G08.3 | **No** |
| P6 — Synthetic E2E + VALID/INVALID | SYNTHETIC | G07.1–G07.5 | **No** |
| P7 — Official Historical Data Preparation | OFFICIAL DATA | G00.3, G00.4, G01.4 | **Yes** |
| P8 — Official Fit/Train, Calibration, Evaluation | MODEL EVIDENCE | G03.6, G02.3, G07.6 | **Yes** |
| P9 — Offline Replay & Shadow Evaluation | OFFICIAL REPLAY/SHADOW | G07.7, G08.4 | **Yes** |

**Hard rule:** P1–P6 không bị block bởi official D/C/Q/K source, chưa có response calibration thresholds, missing production policy BR/surge/penalties hay trusted production price gateway. Khi test cần giá trị, dùng TEST_ONLY policy/cohorts/metadata tự nhất quán và có version; assert production eligibility=false. Synthetic acceptance không khẳng định causal validity. Các open decisions GD-01–GD-08 giữ nguyên, phải được giải quyết khi promotion P7–P9. P1–P6 hiện vẫn NOT RUN/PLANNED, không tự đánh dấu PASS.

## P1 — Data & Interface Contracts + Synthetic Fixtures (G00, G01)

**Deliverable/gate (SYNTHETIC):** typed contracts, deterministic valid/invalid synthetic fixtures and documented official-data blockers; no real source required for gate. Inputs: [DATA_SCHEMA](../contracts/DATA_SCHEMA.md), [MODEL_IO](../contracts/MODEL_IO_CONTRACT.md), [RESPONSE_ARTIFACT](../contracts/RESPONSE_ARTIFACT_CONTRACT.md), [CANDIDATE_POLICY](../contracts/CANDIDATE_POLICY_CONTRACT.md), GD-01/02/03/08.

| Task / status | Dependencies | Files (E inspect/reuse; P future create/edit) | Input → Output | Acceptance criteria & tests | Blocker |
|---|---|---|---|---|---|
| **G00.1** Review known code/target semantics + synthetic parity fixtures — `PLANNED_SYNTHETIC` | None; kickoff review can start | E: `geomobinet/{data,batch,training,runner}.py`, `pipeline/configs/geomobinet.yaml`; P: parity fixture/test `pipeline/tests/ggso/test_semantic_parity.py` | Existing dataset-schema documentation/source code plus synthetic event labels/mock checkpoint → explicit target assumptions + synthetic parity test; actual dataset/checkpoint proof deferred to G00.3/G02.3 | DT-02/04, FC-02/06/08; inspect `input_schema` “new eligible requests” mismatch, assert target windows and source `available_at<=cutoff`; **no alias without proof** | Official source/checkpoint missing: tracked for P7/P8 ONLY; not a P1 synthetic blocker |
| **G00.2** Mock operational lineage and network snapshot contracts — `PLANNED_SYNTHETIC` | G00.1 synthetic schema/semantics draft | E: `backend/app/ingestion/{dataset_loader,snapshot_builder}.py`, `backend/app/providers/base.py`; P: data-source compatibility tests | Synthetic D,C,Q,K,p,s0, directed physical OD and declared TEST_ONLY provenance → schema/availability matrix, H3 node-set/cutoff contract and synthetic invalid-source reasons | DT-01…05; Q and D cohort aligned, K rides/5min ≠ idle-stock, no future realized Q; confirmed effective policy distinguished from pending/DEMO record | Official Q source, maturity, r/ETA source deferred to P7; fixture definitions declared TEST_ONLY |
| **G01.1** Versioned typed GGSO contracts — `PLANNED_SYNTHETIC` | G00.1/00.2 synthetic profile plus GD-02/03/08 fixed behavior, test-only unresolved policy variants | E: docs/contracts, `backend/app/providers/base.py`; P: `pipeline/src/surge_ml/ggso/{contracts,errors,validation}.py`, `pipeline/tests/ggso/test_contracts.py` | D/S/Q/K/price/context/versions → frozen forecast, response artifact, candidate table, network result and error envelope | DT-01…05, MI-01…08, RA-01…04, CP-01…05; serialization, missing/duplicate hex, bad version/currency, missing vs zero, INVALID empty policy; no legacy schema overwrite | Q_total=0, D(a)>Q and REVIEW/error mapping tracked as P7/P8 promotion decisions; synthetic negative paths MUST reject/INVALID |
| **G01.2** Config/policy and reproducible fixtures — `PLANNED_SYNTHETIC` | G01.1 draft schema | E: `backend/config/policy.yaml` (DEMO only), pipeline configs, source validation utilities; P: `ggso/config.py`, `pipeline/tests/ggso/{conftest.py,fixtures/,test_data_semantics.py}` | Approved decision values *or* declared test-only numbers → versioned config + deterministic valid/invalid test network snapshots | Reject unsupported surge, mismatched time/node version, nonfinite numbers, unseen context fields, silent Q/K/default fill; fixture IDs explicitly synthetic | Use explicit TEST_ONLY s_min/max, BR_min/max, fare/currency, tolerance/support; production values deferred P8/P9 |
| **G01.3** Versioned synthetic provider/contract handoff — `PLANNED_SYNTHETIC` | G01.1/01.2 and deterministic mock provider transport (official transport deferred P9) | E: `backend/app/providers/{base,registry}.py`, `services/validation_service.py`; P: protocol fixtures/tests | Approved schema from P1 → documented consumer boundary, stable schema IDs/versions, no implicit model imports in backend | Version negotiation, old `surge_proposal_v1` and `recommendation.v1` unchanged, invalid result cannot create an execution request | Synthetic transport mock now; final production transport/error mapping deferred to P9, no impact on P1 synthetic contract gate |

**P1 SYNTHETIC PASS exit:** contract fixture tests actually pass; the official Q/capacity/booking/checkpoint source review is G00.3/G00.4/G02.3 in P7/P8, not a prerequisite here. No library assumptions are substitutes for source approval.

## P2 — GLM Response Models (G03)

**Deliverable/gate (SYNTHETIC):** two per-H3 GLM implementations, NB/Binomial NLL tests, bootstrap and TEST_ONLY response artifacts/eligibility behavior. Real fit/calibration is P8. Inputs: P1 cohort contract and [response spec](../model/response_model.md), GD-04. Q is not an input to the GLM NLLs but remains required for MILP BR later.

| Task / status | Dependencies | Files (E/P) | Input → Output | Acceptance criteria & tests | Blocker |
|---|---|---|---|---|---|
| **G03.1** Build synthetic response cohort & tabular features — `PLANNED_SYNTHETIC` | G00.2, G01.1 | E: `docs/contracts/DATA_SCHEMA.md`; P: `ggso/response/{dataset,features}.py`, `pipeline/tests/ggso/test_response_dataset.py` | Generated synthetic D confirmed bookings, C matured on same synthetic cohort, TEST_ONLY s and K, cD/cF available at cutoff → aligned per-cell chronological training/validation rows and feature profile | RM-01/02; `0≤C≤D`, D/C integers, s>0, K finite, context no future leakage, train-only preprocessing, chronological holdout | Official matured D/C/K, real cohort/historical prices move to G00.4/G03.6; not required P2 |
| **G03.2** Demand NB GLM loss & fit — `PLANNED_SYNTHETIC` | G03.1 typed fixtures, GD-04 model fixed | E: `pipeline/pyproject.toml` (scipy already present); P: `ggso/response/demand_glm.py`, `pipeline/tests/ggso/test_demand_glm.py` | D,s,cD → alpha, ordered w, learned beta∈[0,4], dispersion k, expected mu, fitted likelihood metadata | NB NLL reproduces declared mean/dispersion convention, bounds/convergence/numeric rejection; synthetic parameter recovery, known-NLL fixture, zero and extreme counts | Choose explicit TEST_ONLY NB dispersion convention and numerical fit fixture with validation; official estimator/regularization decision gates P8 |
| **G03.3** Fulfillment Binomial GLM loss & fit — `PLANNED_SYNTHETIC` | G03.1 typed fixtures, G01.1 epsilon/profile | P: `ggso/response/fulfillment_glm.py`, `pipeline/tests/ggso/test_fulfillment_glm.py` | D trials, C successes, historical K, cF → a, ordered v, learned gamma∈[0,1], pi, held-out metrics | Binomial NLL, `0≤C≤D`, D=0 gives zero trials not 100% success, stable logits, bounds; synthetic/calibration test fixtures | Synthetic coherent K/cohort, TEST_ONLY epsilon and tabular schema; official versions deferred P7/P8 |
| **G03.4** Bootstrap paired parameter scenarios — `PLANNED_SYNTHETIC` | G03.2/03.3, temporal train split | P: `ggso/response/bootstrap.py`, `pipeline/tests/ggso/test_response_bootstrap.py` | Fit training windows with paired D/C records → reproducible scenario IDs/weights and beta/gamma pairs, provenance | RM-04, RA-04; reproducible seed, keep scenario pairing between baseline and candidate; fit failures reported, never silently drop/renormalize; deterministic test fixture | Deterministic TEST_ONLY bootstrap scheme/block/replicate/weights and quantile for tests; official hyperparameters P8 |
| **G03.5** Synthetic artifact serialization + eligibility behavior — `PLANNED_SYNTHETIC` | G03.1…03.4, RA contract | P: `ggso/response/{artifacts,validation}.py`, `pipeline/tests/ggso/test_response_artifacts.py` | Fitted coefficients, ordering/preprocessing, support/windows, scenarios → versioned eligible/not-eligible per-cell artifact | RM-03/05, RA-01…04; replay/reload parity, feature/version mismatch fail, held-out NB/Binomial NLL/calibration and support gates; required cell missing ⇒ INVALID/no recommendation | Synthetic threshold fixtures verify PASS/INVALID routing; minimum official support/calibration and estimator are P8 blockers only |

**P2 SYNTHETIC PASS exit:** NB NLL, Binomial NLL, bounded fit, bootstrap replay, serializer and negative gates pass on TEST_ONLY cohorts. Artifacts remain not eligible for official use until G03.6 in P8. Never borrow neighbor model or silently beta=0.

## P3 — Candidate Simulation (G04)

**Deliverable/gate (SYNTHETIC):** pure deterministic complete per-cell candidate table with nominal and paired lower-tail utilities; independent of DuoCast inference.

| Task / status | Dependencies | Files (E/P) | Input → Output | Acceptance criteria & tests | Blocker |
|---|---|---|---|---|---|
| **G04.1** Capacity preparation — `PLANNED_SYNTHETIC` | P1 capacity contract, P2 artifact semantics | E: `docs/model/candidate_simulation.md`; P: `ggso/simulation/capacity.py`, `pipeline/tests/ggso/test_capacity.py` | eligible-idle supply S, r rides/driver/hour, ETA minutes, H=5 or approved direct K → K rides/5min + method/source version | CS-02/07; ETA seconds→minutes, K≥0 finite, single method, fixed K across price candidates, no S=K substitution | Actual r/ETA calibration and source versions |
| **G04.2** Reference baseline & grid — `PLANNED_SYNTHETIC` | G01.1/01.2, G04.1 | P: `ggso/simulation/grid.py`, `pipeline/tests/ggso/test_candidate_grid.py` | s0, absolute bounds, policy support, additive actions → canonical IDs, feasible/rejected candidates and separate baseline | CS-01/02/06; step 0.1 ±0.3 only for GGSO automatic recommendation, s=s0+a, no rounding/clamp, zero action matches baseline when eligible | s_min/max and out-of-support policy values |
| **G04.3** Candidate arithmetic & scenario pairing — `PLANNED_SYNTHETIC` | G03.4 artifacts or explicit TEST_ONLY scenarios; G04.1/04.2 | P: `ggso/simulation/{simulate,scenarios}.py`, `pipeline/tests/ggso/test_candidate_simulation.py` | D anchor, response params/scenarios, K,p,s0,a → D(a), pre-cap FR, completed C(a), GMV, nominal ΔGMV, Q0.05 paired delta | CS-03…07; golden D=10/K≥10/p=100/s0=1.2/beta=gamma=0/a=0.1 ⇒ 600→650, gamma scenario recomputes baseline, finite/cap checks | Bootstrap quantile method/count/weights, fare source/currency |
| **G04.4** Candidate table contract, diagnostics and negative tests — `PLANNED_SYNTHETIC` | G04.2/04.3 | P: `ggso/simulation/candidates.py`, `pipeline/tests/ggso/test_candidate_contract.py` | Full required node set and candidate results → solver-ready versioned table with rejected reasons, monetary unit consistency | CP-01/02, CS-01…07; no missing/duplicate cell, no unknown scenario, empty eligible set ⇒ INVALID upstream, response artifact mismatch reject | Production configuration and artifact versions |

**P3 SYNTHETIC PASS exit:** correct pure arithmetic/serialization with TEST_ONLY forecasts/artifacts/Q/K/fare; official eligibility and policy parameters defer to P8–P9.

## P4 — MILP Optimizer (G05)

**Deliverable/gate (SYNTHETIC):** HiGHS model and independent validator, verified against exhaustive oracle on tiny network.

| Task / status | Dependencies | Files (E/P) | Input → Output | Acceptance criteria & tests | Blocker |
|---|---|---|---|---|---|
| **G05.1** Build joint MILP coefficients/constraints — `PLANNED_SYNTHETIC` | G04.4, G01.2, GD-05 math approved | E: `docs/model/milp_optimization.md`; P: `ggso/optimization/milp.py`, `pipeline/tests/ggso/test_milp_build.py` | Candidate table, Q, required I, adjacency E, weights, penalties/bounds → binary z, absolute-value d linear constraints, objective, BR + nominal no-loss | MO-01…04; one candidate/cell, no duplicate pricing edges, conservative objective/temporal/spatial terms correct, Σ nominal ΔGMV ≥0, Q_total>0; no price-clamp | BR_min/max, lambda_t/g, absolute s limits and policy edge weights |
| **G05.2** HiGHS solver wrapper & status semantics — `PLANNED_SYNTHETIC` (official settings deferred) | G05.1, GD-06 | E: `pipeline/pyproject.toml` has scipy; P: `ggso/optimization/highs.py`, `pipeline/tests/ggso/test_highs_status.py` | Frozen MILP problem + solver time/gap/tolerances → optimal/feasible incumbent/error status + raw metrics | MO-05; feasible timeout incumbent considered **only after validator pass**, no incumbent INVALID, no fabricated gap/bound; synthetic timeout/error tests | HiGHS binding/API version, time limit, MIP gaps, numerical scaling/tolerances |
| **G05.3** Independent decoder and full-policy validator — `PLANNED_SYNTHETIC` | G05.1/05.2 result contract | P: `ggso/optimization/{validator,results}.py`, `pipeline/tests/ggso/test_policy_validator.py` | Selected IDs and original candidates/reference/schema → recomputed full policy, BR, nominal GMV no-loss, penalties, diagnostics/status | MO-06/07, CP-01…04; reject corrupted/partial IDs, out-of-grid, wrong snapshot, BR or hard nominal no-loss violation even if solver says OPTIMAL; INVALID => no recommendation/policy | Approved numerical tolerance/serialization precision |
| **G05.4** Exhaustive oracle & adversarial MILP tests — `PLANNED_SYNTHETIC` | G05.1…05.3 | P: `pipeline/tests/ggso/{test_milp_oracle,test_highs_solver}.py` | Synthetic 2–3 hex × small candidate grids → independent enumerated feasible optimum and comparison report | MO-01…07; all-HOLD satisfies nominal no-loss but can violate BR; negative nominal delta rejected despite objective; spatial lambda zero, edge double count, tie, numeric/timeout branches | Can use test-only parameters; production promotion waits GD-05/06 settings |

**P4 SYNTHETIC PASS exit:** correctness evidence for TEST_ONLY fixtures. Không ghi OPTIMAL nếu chỉ có feasible incumbent; no acceptable verified solution ⇒ technical INVALID and empty recommendation.

## P5 — DuoCast Integration (G02, G06, G08)

**Deliverable/gate (SYNTHETIC):** versioned GGSO decision run kết nối mocked/demo forecast + TEST_ONLY operational context + response + candidate + MILP, có read-only/DEMO consumer; giữ legacy namespace/code.

| Task / status | Dependencies | Files (E/P) | Input → Output | Acceptance criteria & tests | Blocker |
|---|---|---|---|---|---|
| **G02.1** Synthetic DuoCast/checkpoint I/O parity gate — `PLANNED_SYNTHETIC` | G00.1, P1 declared semantics, synthetic/mock DuoCast model evidence | E: `geomobinet/{model,training,batch,data,runner}.py` + forecast tests as implementation reference; P: `pipeline/tests/ggso/test_duocast_parity.py` | Synthetic/mock forecast output from the no-geo DuoCast architecture with declared booking/eligible-idle semantics + model config → tested shape/order/time parity (official source/checkpoint parity deferred to G02.3 P8) | FC-01…09, MI-01…08; fixture declares Temporal GRU + Spatial GATv2 + directed Mobility GATv2 + gated fusion + dual heads, with no static geo input; actual-source parity deferred P8, no silent relabel or retrain | `geomobinet_smg` has a static-geo branch and is not DuoCast evidence; real DuoCast label/checkpoint evidence deferred to P8 G02.3 |
| **G02.2** Versioned forecast adapter — `PLANNED_SYNTHETIC` (after G02.1 mock) | G02.1 synthetic mock compatibility and G01.1 | P: `ggso/integration/duocast_adapter.py`, `pipeline/tests/ggso/test_duocast_adapter.py`; E inspect `geomobinet/runner.py::forecast` only for compatible interface mechanics | Synthetic/mock DuoCast forecast rows & simulated checkpoint/schema/time/node identity → one consistent TEST_ONLY GGSO D/S envelope | MI-01…08; infer once for all cells, full H3/time/units, match checkpoint and node mapping; reject a static-geo architecture claimed as DuoCast; ds_proxy diagnostic only; invalid parity→no recommendation | Declared synthetic DuoCast source/model identity + versioned test schema; official source/model parity P8 |
| **G06.1** Assemble frozen TEST_ONLY operational context — `PLANNED_SYNTHETIC` | G01.1, G04.1, G02.2 | P: `ggso/integration/operational_context.py`, `pipeline/tests/ggso/test_operational_context.py` | synthetic as-of Q, simulated EFFECTIVE s0, presurge fare p, K/r/ETA, tabular response context, TEST_ONLY per-cell artifacts → versioned full-network decision snapshot | DT-01…05, DP-01/03; all fields/coverage/source versions consistent; no future actual Q, no pending/DEMO-RECORDED edits as price effective | Official Q/fare/K and real effective pricing source deferred to P7/P9; P5 mock state transition explicit |
| **G06.2** Orchestrate six-stage decision & fail closed — `PLANNED_SYNTHETIC` (after upstream P1–P5 code) | G02.2, G03.5, G04.4, G05.3, G06.1 | P: `ggso/integration/decision_runner.py`, `pipeline/tests/ggso/test_decision_runner.py` | Forecast + operational inputs + artifact/solver validated → VALID full policy & recommendations or INVALID empty/no policy+trace | DP-01…07, CP-01…06; one inference/network, no partial recommendation, exact policy eligible for execution only after independent validation, exhaustive error reason & version trace | All model/data/candidate/solver dependencies; error-status format |
| **G08.1** Versioned mock/DEMO backend bridge — `PLANNED_SYNTHETIC` after G06.2 | G06.2, G01.3 | E: `backend/app/providers/{base,gnn_adapter,precomputed_provider}.py`, `ingestion/recommendation_importer.py`, `services/validation_service.py`, schemas, `ui/app/src/domain/types.ts`; P: `backend/app/providers/ggso_provider.py` and new integration tests | GGSO result envelope → versioned full-policy execution request plus monitoring metadata without mutating legacy importer semantics | CP/DP tests, no fabricated Pressure/Revision, INVALID creates no request, DEMO `production_effective=false`, old `surge_proposal_v1` regressions intact | Use mock/DEMO adapter without production activation; real transport/execution authorization P9 |
| **G08.2** Atomic automatic execution + simulated next-cycle source — `PLANNED_SYNTHETIC` after G08.1 | G08.1, GD-07, explicit simulated-effective-policy TEST_ONLY protocol (real source P9) | E: backend validation/idempotency/audit patterns; P: versioned full-policy execution adapter and targeted integration tests | Valid GGSO full policy + reference version → exact-vector submission, receipt and new-cutoff snapshot; failed precondition → no write | Full-vector bounds/precision/version/idempotency checks; no partial apply or per-hex replacement; next cycle uses confirmed EFFECTIVE policy | Use TEST_ONLY simulated EFFECTIVE transition; true pricing gateway/effective feed is P9 blocker, not P5/P6 |
| **G08.3** Monitoring dashboard/API compatibility acceptance (only if assigned) — `PLANNED_SYNTHETIC` after G08.1 | G08.1/08.2 | E: `ui/app/src/domain/types.ts`, `components/console/NetworkConsole.tsx` and existing UI tests; P: targeted GGSO monitoring tests | Valid/invalid backend GGSO result → forecasts, current/recommended/applied multipliers, validation, execution and history | No Accept Selected/Accept All/manual/approval controls in GGSO target view; INVALID shows no write; monitoring state does not imply EFFECTIVE without receipt | Only mocked/DEMO scope with future user authorization; production UI contract P9 |

**P5 SYNTHETIC PASS exit:** fixture + simulated forecast/pricing-source integration verified, without official dataset/checkpoint or production EFFECTIVE feed. No shadow approval or production price write. Automatic execution acceptance still requires exact-vector, atomicity and receipt evidence beyond the existing mock result.

## P6 — End-to-End Testing (G07 + cross-phase)

**Deliverable/gate (SYNTHETIC):** actual executed synthetic E2E, fault matrix and regression evidence; official data evaluation moved to P8/P9. No training or shadow requirement in P6.

| Task / status | Dependencies | Files (E/P) | Input → Output | Acceptance criteria & tests | Blocker |
|---|---|---|---|---|---|
| **G07.1** Synthetic end-to-end fixture — `PLANNED_SYNTHETIC` after P5 | G06.2, G05.4 | P: `pipeline/tests/ggso/test_e2e_fixture.py` | Deterministic frozen network data/artifact + one cutoff → full forecast/adapter/simulation/solver/validator/output | Compare expected IDs, GMV/deltas, BR, no-loss and reproducibility; VALID only when all pass; no application side effects | P5 runner |
| **G07.2** Negative/fault-injection matrix — `PLANNED_SYNTHETIC` after G07.1 | G07.1 | P: `pipeline/tests/ggso/test_fault_matrix.py`, `backend/tests/integration/test_ggso_invalid.py` | Missing/wrong semantic profile, late input, one invalid cell, no candidate, zero Q, infeasible MILP, solver timeout, corrupt incumbent → INVALID traces | `recommendations=[]`, `optimized_policy=null`, no execution request/write, no fabricated fallback/HOLD/REVIEW; no residual valid subset | Error enums and numeric tolerance decisions |
| **G07.3** Synthetic backend/mock DEMO E2E + automatic execution cycle — `PLANNED_SYNTHETIC` after P5 | G08.1/08.2, approved test DB | E: backend provider/validation/audit test patterns; P: `backend/tests/e2e/test_ggso_demo_flow.py` | Valid GGSO policy, exact-vector execution request, simulated receipt and next snapshot → verified atomic behavior and reference transition | No unauthorized production write; bounds/version/idempotency/audit; no partial success; distinguish DEMO RECORDED from EFFECTIVE (simulate transition only in explicit fixture) | For DB-dependent suite use authorized isolated TEST_DATABASE_URL; synthetic orchestrator and in-memory/mock E2E do not require actual pricing feed or production DB |
| **G07.4** Synthetic response/optimizer evaluation harness — `PLANNED_SYNTHETIC` | G03.5, G05.4, G07.1 | E: evaluation specs, pipeline forecast metrics; P: `pipeline/tests/ggso/test_replay.py`, versioned evidence/reports | Deterministic synthetic train/validation cohorts, frozen TEST_ONLY policy/model configs → synthetic NB/Binomial NLL checks, fixture calibration, solver BR/no-loss/latency/INVALID branches | No future Q leakage, no synthetic fixture reported as business uplift; report estimated metrics vs realized outcomes separately | Official histories/threshold calibration/real evaluation protocol deferred to G07.6 P8 |
| **G07.5** Synthetic regression gate and handoff — `PLANNED_SYNTHETIC` after G07.1–G07.3 | G07.1…07.4 and scope/permissions | E: `pipeline/tests/test_geomobinet*.py`, legacy pipeline tests, backend/UI suites and CI rules; P: release checklist/test evidence | All relevant unit/integration suites, revision/artifact/commands → explicit PASS/FAIL/NOT RUN matrix, blockers and risk sign-off | No regression of legacy/GeoMobiNet/DEMO; no production permissions granted; rollout stages fixture→offline→approved shadow only; DONE only with real evidence | Isolated synthetic test runner needed; official business policies, shadow or production authorization P8/P9 |

**P6 SYNTHETIC PASS exit:** code/tests (when user later authorizes) actually validated with deterministic synthetic fixtures in a safe environment, not inferred from task creation. P7/8/9 remain separate OFFICIAL_DATA_PENDING, model promotion and shadow gates. Không chạy production integration, pricing write, training hoặc data migrations trong request này.

## P7 — Official Historical Dataset Preparation & Validation (REAL DATA)

**Deliverable/gate:** official D/C/Q/K/fare/surge/physical OD historical tables, availability lineage, semantic parity and frozen dataset fingerprint/split. **OFFICIAL_DATA_PENDING** until actual sources provided; no dependency on new algorithm work. This phase can pursue data access in parallel with P1–P6, but cannot claim completion without real evidence.

| Task / status | Dependencies | Files (E/P) | Input → Output | Acceptance criteria & tests | Blocker |
|---|---|---|---|---|---|
| **G00.3** Official booking/forecast parity — `OFFICIAL_DATA_PENDING` | P1 synthetic profile; source access | E: `geomobinet/{data,training,runner}.py` and existing config/checkpoint formats; P: `ggso/data/official_ingest.py`, `pipeline/tests/ggso/test_official_semantics.py` | Original event taxonomy and checkpoint generation lineage → verified confirmed-booking demand vs “eligible requests”, eligible-idle driver supply profile, source manifests | DT/FC/MI, actual event schema/time labels, training/checkpoint/source parity, as-of cutoff and node ordering; no aliasing fields by name | Official data in `data/geomobinet` absent in checkout; verified labels/checkpoint owner |
| **G00.4** Historical cohort + operational source validation — `OFFICIAL_DATA_PENDING` | G00.3, GD-02/03 source decisions | E: backend ingestion source/snapshot contracts; P: `ggso/data/cohort_validation.py`, `pipeline/tests/ggso/test_official_cohorts.py` | Real D bookings, C matured completions, quotes Q, K throughput/ETA, surge/fare/driver OD with availability → temporally aligned H3 cohort/response tables and rejection diagnostics | C belongs to D cohort, 0≤C≤D, Q same quote cohort, observed zero≠missing, no future realized Q, K rides/horizon, OD physical directed, no feature leakage; fail on unsupported semantics | Q_total=0/D>Q policy, maturity, K throughput/ETA calibration source, price source |
| **G01.4** Official dataset manifest and frozen splits — `OFFICIAL_DATA_PENDING` | G00.3–G00.4 | E: `geomobinet/data.py` split conventions and `docs/contracts/DATA_SCHEMA.md`; P: `ggso/data/manifest.py`, `pipeline/tests/ggso/test_official_manifest.py` | Valid historical tables + source versions → dataset fingerprint, schema/semantic versions, train/val/test windows, eligibility/coverage report | Deterministic replay, no time/label leakage, H3 full required coverage, frozen validations, explicit rejected/corrupt records, source ownership/version | Official source rights, original timestamps, source schemas |

**P7 exit:** real source/label/lineage evidence and versioned official historical dataset; otherwise OFFICIAL_DATA_PENDING, **not** P1–P6 synthetic FAIL.

## P8 — Official Fit/Train, Calibration & Evaluation (REAL MODEL EVIDENCE)

**Deliverable/gate:** official fitted GLM artifacts, bootstrapped scenarios, held-out support/calibration evaluation and validated existing DuoCast checkpoint (retrain only if separately authorized). No retrospective inflation of P2 SYNTHETIC_PASS.

| Task / status | Dependencies | Files (E/P) | Input → Output | Acceptance criteria & tests | Blocker |
|---|---|---|---|---|---|
| **G03.6** Fit real per-hex GLMs / bootstrap / calibration — `OFFICIAL_DATA_PENDING` | P2 synthetic GLM pass, P7 official source, approved GD-04 settings | E: response spec/artifact contract; P: `ggso/response/{fit_official,calibrate,promotion}.py`, `pipeline/tests/ggso/test_official_response_eval.py` | Real matured D/C/K/s/context and chronological split → fitted alpha/w/beta/k, a/v/gamma, versioned bootstrap samples, support/calibration eligibility | NB/Binomial held-out NLL, bounded coefficients, stable/no-leak preprocessing, dispersion convention, bootstrap reproducibility and quantile pairing; required hex failures cause INVALID, not guessed coefficients | Actual data, approved NB parameterization, bootstrap replicates, minimum support and calibration thresholds |
| **G02.3** Verify/reuse DuoCast real checkpoint and forecast — `OFFICIAL_DATA_PENDING` | G00.3/G01.4, P5 mock integration, official checkpoint | E: `geomobinet/{model,training,runner}.py`; P: `pipeline/tests/ggso/test_real_duocast_parity.py` | Real source/model/checkpoint/feature ordering → approved no-geo DuoCast artifact and versioned forecast adapter, or documented adaptation/retraining blocker | Full H3 cutoff/target coverage, confirmed booking demand/eligible idle stock semantics, no future OD, no static geo branch, no extra GNN per candidate; do not reuse `geomobinet_smg` weights by relabeling | Original checkpoint/labels. Architecture adaptation or any retraining requires separate authorization |
| **G07.6** Held-out forecast/response/optimizer evaluation — `OFFICIAL_DATA_PENDING` | G03.6/G02.3, P4 synthetic optimizer pass | E: `docs/evaluation/{MODEL_EVALUATION,OPTIMIZATION_EVALUATION}.md`; P: `ggso/evaluation/{response_eval,forecast_eval}.py`, reports | Frozen official val/test windows + artifacts and test-only->official promotion rules → calibration, count/fulfillment metrics, eligible-cell coverage, GMV model estimate and solver correctness evidence | Chronological split, no test tuning/leakage, no fake causal GMV uplift, report real provenance/parameter stability/invalid rate + named thresholds | Frozen operational BR/bounds/penalties, official model/calibration metrics and evaluation permissions |

**P8 exit:** real artifacts eligible only after approved evaluation gates. If data/calibration is missing, NOT_ELIGIBLE even if synthetic tests passed.

## P9 — Offline Replay & Shadow Evaluation (READ-ONLY / OFFICIAL)

**Deliverable/gate (OFFICIAL REPLAY):** reproducible replay traces with real timestamped sources; optional shadow metrics only on explicit authorization. **No price publication/deployment**.

| Task / status | Dependencies | Files (E/P) | Input → Output | Acceptance criteria & tests | Blocker |
|---|---|---|---|---|---|
| **G07.7** Official offline historical replay — `OFFICIAL_DATA_PENDING` | P5/P6 synthetic E2E, P7/8 real artifact eligibility | E: existing backend replay, decision pipeline and evaluation specs; P: `ggso/evaluation/offline_replay.py`, `pipeline/tests/ggso/test_official_replay.py` | Frozen official cutoff sequence and current pricing reference + response artifacts → reproducible per-interval VALID/INVALID, modeled BR/no-loss, HiGHS runtime, action distribution, estimated GMV traces | Same cutoff/versions, no future quote leakage, one forecast per network, independent validator PASS for each VALID, INVALID empty recommendations/no writes, no causal uplift claim | Official actual Q/K/fare/s0 source, frozen configs, historical data quality |
| **G08.4** Shadow-only consumer and observability — `OFFICIAL_DATA_PENDING` | G07.7 offline readiness, shadow authorization | E: backend provider/audit patterns and UI consumer; P: `ggso/evaluation/shadow_eval.py`, `backend/tests/e2e/test_ggso_shadow.py` | Approved real-time/read-only feed + frozen GGSO + shadow consumers → no-write shadow result logs, latency, invalid rate and next-cycle effective-price provenance | No production price writes; separate recommendation/validation/execution states; exact full-policy contract; monitoring-only UI; no pending→EFFECTIVE shortcut | Explicit shadow authorization, source of actually EFFECTIVE price, service-level latency and provider contract |

**P9 exit:** evidence-driven offline replay and (if expressly authorized) shadow results; production rollout is a **new decision**, not part of P9.

## Open decisions & blockers — separated by synthetic vs official gates

**P1–P6 may finish using declared TEST_ONLY inputs, even when all official blockers below remain open.** Missing official Q/K/calibration/production config must not be copied into test values as if validated, and must not cause “BLOCKED” for fixture implementation. They block **P7–P9** data/model/shadow gates only.

| Decision | Still unresolved (do not choose defaults) | Task/phase impact |
|---|---|---|
| **GD-01/02** | Confirmed booking demand source and actual GeoMobiNet `training.py::input_schema` vs agreed target; no-geo DuoCast architecture/checkpoint versus the static-geo `geomobinet_smg` artifact; dataset/checkpoint source; Q cohort, Q_total=0, D(a)>Q, maturity | G00.1/00.2, G02.1, G06.1; **data/geomobinet not in current checkout** |
| **GD-03** | K r/ETA throughput source, calibration, historical/online horizon and effective supply semantics | G03.1/03.3, G04.1, G06.1 |
| **GD-04** | NB dispersion likelihood convention, estimator/regularization, tabular feature list, bootstrap temporal blocks/count/weights/quantile, min support/calibration thresholds | G03.2…03.5 |
| **GD-05** | Absolute surge limits, fare/currency, BR_min/max, temporal/spatial penalty weights, edge counting, numerical no-loss tolerance | G01.2, G04, G05 |
| **GD-06** | HiGHS binding/version, timeout, MIP gap, integrality/feasibility tolerance and scaling | G05.2/05.3/05.4 |
| **GD-07** | Atomic full-policy execution bounds/precision/reference freshness/idempotency/receipt, where truly EFFECTIVE surge lives; monitoring UI migration | G08.1…G08.3, G07.3 |
| **GD-08** | Final INVALID technical error/status contract and execution-state mapping; REVIEW is outside the automatic path | G01.1/01.3, G06.2, G07.2 |
| **Environment** | Real datasets/artifacts, test DB safety, approved shadow/production access | G07.3–07.5 |

Never: force all-HOLD as solver feasible when BR fails; convert invalid run to fallback pricing or REVIEW; partially apply or manually substitute cells in an automatic GGSO decision; silently overwrite legacy `surge_proposal_v1`, `recommendation.v1` or DuoCast checkpoints; treat estimated GMV as causal business uplift.

## Template cho task execution (future)

~~~text
Task ID / phase:
Status: PLANNED_SYNTHETIC | SYNTHETIC_PASS | OFFICIAL_DATA_PENDING | POLICY_PRODUCTION_PENDING | BLOCKED_INTEGRATION | IN_PROGRESS | DONE (with actual evidence only)
Authorized owner/scope:
Dependencies and decision approvals:
Existing reusable paths; proposed paths confirmed before editing:
Input data and semantic/config versions:
Output artifact/schema and acceptance IDs:
Tests to run and expected failure branches:
Actual commands, exit codes, timestamps and evidence files:
Diff paths, observed side effects, regression risk:
Unresolved blockers and next phase gate:
~~~

**Scope lock của lần này:** chỉ thay hai files `docs/implementation/IMPLEMENTATION_PLAN.md` và `docs/implementation/TASKS.md`. Không source/config/dataset/tests/DB/UI writes; không train, run tests, stage, commit, push hay deploy.

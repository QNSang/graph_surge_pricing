# Optimization Evaluation — Correctness trước business claims

Status: protocol, chưa chạy solver/evaluation. Nguồn [S1 §7–10, S2 §5–7](../technical_report/README.md); exhaustive oracle và một số ablations là engineering evaluation proposals.

## 1. Optimization correctness

Trên fixture nhỏ, enumerate feasible policy combinations và tính objective độc lập. So solver với exact feasible optimum theo approved tolerance. Kiểm one-action/cell, network completeness, surge/grid/adjustment bounds, booking-rate linearization, **hard nominal modeled network no-loss** và absolute-value penalties.

Reported objective phải tách conservative score, temporal penalty và spatial penalty; nominal estimated GMV là metric khác. Recompute spatial difference từ selected surge, không tin d_ij nếu penalty coefficient bằng0. Ties được chấp nhận khi objective/constraints đúng, trừ khi có tie-break specification.

## 2. Baseline comparison

Reference policy s0 là baseline incremental GMV (nominal delta=0), không mặc định luôn feasible hoặc objective=0. All-HOLD có thể vi phạm network BR dù đạt no-loss. Nếu baseline vi phạm BR/bounds, báo riêng, không giả comparator feasible. Không thêm action0 vào candidate set ngoài support chỉ để đủ baseline.

Ablations đề xuất: independent per-cell choice, nominal thay conservative utility, lambda_t/lambda_g bằng0, grid resolution khác. Ghi rõ constraints khác nhau; policy vi phạm guardrail không được gọi tốt hơn chỉ vì GMV cao hơn. Các variants chưa có code/results trong phiên docs.

## 3. Operational metrics

| Nhóm | Chỉ số |
|---|---|
| Solver | Optimal/accepted-feasible/infeasible/no-incumbent/error rates, runtime, gaps/bounds có thật |
| Validation | Constraint violations, rejected candidates, full-network coverage |
| Invalid/no recommendation | Frequency, error reason của missing artifact/input/solver/validator; zero execution requests/writes |
| Pricing | Action distribution, sum absolute adjustments, weighted adjacency discontinuity |
| Estimated outcomes | Nominal network GMV/delta, modeled BR, completed rides và conservative score tách riêng |

Latency báo measured hardware/config/network size/candidate count và percentiles khi đủ runs; time budget chỉ là target, không là kết quả đã đạt.

## 4. Stress tests

Missing/stale/duplicate cell; zero supply/demand/capacity; extreme finite logits; unsupported prices; no feasible candidate; BR infeasibility; scenarios invalid; solver timeout có/không incumbent; decoded-result corruption; reference-version race; missing reference và partial-execution attempt.

Tolerance/small residual phải được test với solver settings GD-06. Không round/clamp sau solve để làm test pass. Xác nhận INVALID không sinh recommendations, policy hoặc execution request; incumbent giữ nguyên do không có write và không tuyên bố HOLD toàn mạng BR-feasible khi thiếu evidence. Recompute independent selected nominal incremental GMV >=0 với approved tolerance, không sử dụng conservative utility/objective làm no-loss proof.

## 5. Regret và realized impact

Small-fixture objective gap so exhaustive optimum là **optimization correctness gap**, không mặc nhiên là pricing regret của marketplace. Chưa có causal oracle hoặc ground-truth response surface trong nguồn để tính pricing regret thực; nếu thêm simulator oracle, phải ghi data generation/assumptions và phân biệt model misspecification với solver error.

Realized network GMV là primary business metric; realized BR là guardrail trong nguồn. Estimated uplift không chứng minh realized causal uplift. Controlled/quasi-experimental evaluation cần protocol riêng; docs không tự chạy experiment hoặc cấp quyền thay giá.

Sum per-cell 5% utilities không là quantile của total network GMV. Guardrail trong MILP dùng modeled coefficients, không phải guarantee mọi uncertainty scenario hoặc mọi realized outcome đều thỏa.

## 6. Evidence record

Mỗi run lưu dataset/cutoff/node mapping, forecast/response/config versions, candidate table identity, selected IDs, complete reference/policy, solver raw status/runtime/bound/gap, recomputed objective/constraints, technical INVALID reason (nếu có) và execution mode. Chưa có artifacts thực nghiệm mới trong phiên này; các mục trên là yêu cầu lưu bằng chứng sau implementation.
## 7. GD-07 — automatic full-policy execution boundary

GGSO metrics and constraints certify the exact complete policy selected at the cutoff. Evaluation must verify that only this vector can be submitted for automatic application; partial application, per-hex substitution and operator approval are not part of the target flow. Execution checks bounds, precision, reference version and idempotency independently from optimization status. A failed execution precondition produces no write. The next cycle uses the latest confirmed **effective** policy from a fresh snapshot, not a pending request. Report optimization validity and execution validity separately.

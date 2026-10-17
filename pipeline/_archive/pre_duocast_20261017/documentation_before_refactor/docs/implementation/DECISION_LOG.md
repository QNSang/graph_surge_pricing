# Decision Log — GGSO

Cập nhật: 2026-10-18. Phân biệt các quyết định **DESIGN AGREED — verification pending** và chi tiết vẫn OPEN sau khi đối chiếu [nguồn thiết kế](../technical_report/README.md) với repository. Không tự chuyển OPEN thành APPROVED hoặc điền tên người duyệt.

## Những invariant được kế thừa từ nguồn

H3-7, horizon5, forecast tách pricing, response độc lập từng cell, default action grid0.1 trong [-0.3,0.3], quantile0.05, joint MILP, hard guardrails; fail-closed no-recommendation on invalid thay cho historical full-network fallback. Không partial pooling, no cross-cell relocation simulator, không pricing backprop. Các invariant này không chứng nhận implementation hoặc business performance.

## Quyết định cần giải quyết

| ID | Status | Nội dung cần chốt | Bằng chứng/đầu ra cần có | Tác vụ phụ thuộc |
|---|---|---|---|---|
| GD-01 | DESIGN AGREED — ADAPTATION/PARITY PENDING | DuoCast = Temporal GRU + Spatial GATv2 + directed Mobility GATv2 + gated fusion + dual D/S heads; no Geo Encoder/static geo input. Supersedes the 2026-10-16 inheritance decision below. | Verify architecture, source and checkpoint; current `geomobinet_smg` artifact requires adaptation/retraining or a separately verified no-geo variant | G00, G02 |
| GD-02 | DEMAND DEFINITION AGREED — DATA PENDING | `demand_5m` là confirmed valid booking requests/5min; không phải quotes/completions | Check dataset/label parity; Q source/cohort, completion maturity, Q_total=0, D>Q unresolved | G00–G04, G06 |
| GD-03 | SUPPLY DEFINITION AGREED — CAPACITY PENDING | `idle_supply_t` = online, idle, dispatch-eligible stock; GGSO v1 effective available supply là count này theo semantic profile; K riêng | Check state/label parity; r/ETA/method calibration, OD eligibility and units | G00, G02–G04 |
| GD-04 | DESIGN AGREED — PARAMS OPEN | Per-hex Negative Binomial/Binomial fitting và bootstrap parameter scenarios; numerical implementation và thresholds chưa chốt | NB convention, bootstrap blocks/count/weights, support/calibration validation thresholds | G01, G03, G04 |
| GD-05 | DESIGN AGREED — PARAMS OPEN | Grid 0.1, additive ±0.3 và hard nominal modeled network GMV no-loss đã chốt | Fare/currency, absolute surge bounds, BR thresholds, spatial/temporal weights, numerical tolerances | G01, G04, G05 |
| GD-06 | DESIGN AGREED — PARAMS OPEN | HiGHS; timeout feasible incumbent được chấp nhận nếu independent validator pass | HiGHS version, time budget, integrality/feasibility tolerances, MIP gaps, scaling | G05, G06 |
| GD-07 | AUTOMATIC EXECUTION AGREED — INTEGRATION PENDING | Full-network policy qua independent validation được áp dụng tự động mỗi 5 phút; INVALID ⇒ no write; dashboard chỉ monitoring, không Accept/manual/approval | Atomic full-policy execution, price bounds/precision, reference version, idempotency, receipt, backend/UI integration và true effective-price snapshot | G06, G08 |
| GD-08 | DESIGN AGREED — ERROR CODES OPEN | INCREASE/DECREASE/HOLD chỉ mô tả action trong policy VALID; INVALID ⇒ zero recommendations, no optimized policy và no execution; REVIEW không thuộc automatic execution path | Technical error codes, execution states và validator tests | G01, G06 |

Không suy s_max=1.5, delta_max=0.3, epsilon=1e-6, BR_min hay solver timeout từ ví dụ hoặc memory. Không tự chuyển NB thành model khác/clipping D để giải quyết D>Q. Các lựa chọn có thể được đề xuất nhưng cần phân biệt với thiết kế nguồn.

## Scope lock của phiên này

Chỉ cập nhật Markdown; không sửa code/config/data/tests, không training, không restore docs bị xóa, không commit/push/deploy. Đây là giới hạn thao tác hiện tại của người dùng, không phải hạn chế vĩnh viễn cho các phiên được yêu cầu code sau.

## Mẫu ghi quyết định

```text
Decision ID:
Status: OPEN | PROPOSED | APPROVED | SUPERSEDED
Problem and source evidence:
Options considered:
Chosen option and approver/date:
Affected semantic/schema/config versions:
Affected tasks/tests:
Compatibility/migration and rollback:
Unresolved assumptions:
```

Chỉ có kết quả code/test không thay thế phê duyệt business definitions. Khi approved, cập nhật contract/spec liên quan cùng version, không sửa báo cáo lịch sử để làm như quyết định đã có từ đầu.

## Quyết định người dùng xác nhận — 2026-10-16 (lịch sử; GD-01 và GD-07 đã bị supersede)

| ID | Decision | Còn phải xác nhận |
|---|---|---|
| GD-01 — **SUPERSEDED 2026-10-17** | **Historical:** DuoCast dùng lại kiến trúc trước đây mang tên GeoMobiNet-SMG, không redesign; giữ lineage model gốc | Thay bằng quyết định no-geo tại mục GD-01 supersession bên dưới |
| GD-02 | `demand_5m` là **valid confirmed booking requests** trong 5 phút; chỉ chạy GGSO khi source target parity và Q compatible | Kiểm taxonomy/labels; Q source/cohort, maturity, Q=0 và D>Q |
| GD-03 | `idle_supply_t` là online/idle/dispatch-eligible stock; dùng cùng count làm effective available supply GGSO v1 sau khi parity; K riêng | Source/target checks, r, ETA, capacity validation/version |
| GD-04 | Per-hex NB/Binomial; bootstrap parameter scenarios; thresholds từ validation | NB convention, bootstrap block/replicates, support/calibration |
| GD-05 | Grid 0.1, [-0.3,+0.3], hard **nominal network GMV no-loss** | s_min/max, BR bounds, penalties, BR-infeasible HOLD |
| GD-06 | HiGHS; nhận feasible incumbent trên timeout nếu independent validator pass | Timeout, tolerances, gap, scaling |
| GD-07 — **SUPERSEDED 2026-10-18** | **Historical:** Accept Selected và chỉnh tay một hex; không immediate full-network validation/optimization | Thay bằng automatic full-policy execution tại mục GD-07 supersession bên dưới |
| GD-08 | Chỉ 4 recommendation actions; **invalid ⇒ không tạo recommendation/policy mới và không publish** | REVIEW proposal-level rules và technical error enum |

**GD-08 supersedes historical GGSO fallback:** invalid optimizer/input/validation không tạo current-network-surge fallback output; hệ thống giá hiện tại giữ nguyên vì **không có write**. Không đánh invalid thành HOLD/REVIEW hàng loạt. Khi thiếu reference policy cũng no recommendation. Technical status/error metadata tách action.

**No-loss:** thêm hard constraint `sum_i,a z[i,a] * nominal_incremental_gmv[i,a] >= 0`; conservative utility vẫn nằm trong objective. Tất cả hard constraints (BR, bounds, completeness, no-loss) phải cùng pass; reference HOLD không tự động feasible nếu BR không đạt.

Những thông số còn thiếu vẫn là OPEN implementation parameters, không ngầm được chấp thuận từ demo config.

## Forecasting semantics clarification — 2026-10-16 (historical GD-01; superseded)

**Thiết kế đã thống nhất, chưa formal production approval:** GRU + Spatial GATv2 + directed physical driver Mobility GATv2 + fusion + independent D/S heads vẫn là DuoCast trong GGSO, kế thừa GeoMobiNet architecture. No architecture redesign required. D target = new valid **confirmed booking requests** per 5-min interval; S target = online AND idle AND dispatch-eligible drivers at t+5. Eligible-idle count có thể là GGSO v1 effective available supply, không bằng capacity K. Cần kiểm dataset generation, source state machine, training và checkpoint trước đóng GD-01…03. Không tự coi old README text “eligible requests” đã được verified.

## GD-01 — DuoCast architecture supersession (2026-10-17)

**User-approved design:** DuoCast comprises a Temporal GRU, a Spatial GATv2 over H3-adjacent cells, a directed Mobility GATv2 over physical-driver OD edges, gated fusion, and independent demand/effective-supply prediction heads. It has **no separate Geo Encoder and no static geographic-feature input**. Spatial adjacency and directed mobility remain model inputs; they are not geographic features.

**Supersedes:** the 2026-10-16 GD-01 statements that DuoCast inherited the full GeoMobiNet-SMG architecture or its geo branch. The historical entries remain as provenance, not the current design.

**Compatibility gate:** the existing `geomobinet_smg` package/config/checkpoint identifiers and any artifact with a static-geo branch remain implementation evidence for GeoMobiNet-SMG. They cannot be relabeled as DuoCast or reused as DuoCast evidence without an architecture-compatible adaptation or retraining, followed by source/label/checkpoint parity validation. No field name, `contract_version`, config, checkpoint, or code changes are authorized by this decision.

**Đã thống nhất ở lượt trước:** INVALID (bất kỳ critical stage) ⇒ no recommendations, no optimized policy, no publication. Không sinh policy fallback hoặc HOLD hàng loạt. Đây là override so với S1 historical fallback, không phải thay đổi realized incumbent surge.

## Forecast loss weighting clarification — 2026-10-16

**User-approved:** Demand và supply có vai trò ngang nhau trong DuoCast training objective. Core log1p Huber loss là trung bình đều `(L_D + L_S) / 2`; không có `demand_weight` hoặc `supply_weight` trong active training configuration. Training loss và validation `loss_log_huber` phải dùng cùng định nghĩa này.

## GD-04 — GLM training objective/context clarification (2026-10-16)

**Status: DESIGN AGREED, estimation settings still OPEN.** GGSO v1 dùng two independently fitted per-hex GLMs với **pre-decision tabular marketplace context**, không dùng DuoCast graph embeddings và không joint GNN/GLM training. Demand Negative Binomial học `(alpha,w,beta,k)` bằng **Negative Binomial negative log-likelihood**; Fulfillment Binomial học `(a,v,gamma)` bằng **Binomial negative log-likelihood**. Đây là loss objectives suy ra từ phân phối trong source specification, không phải evidence code đã train. `beta`/`gamma` là learned coefficients; fitted model predictions lần lượt là expected demand `mu` và fulfillment probability `pi`. Giữ bounds `0 <= beta <= 4`, `0 <= gamma <= 1`, offline per-cell fitting và online artifact reuse. Bootstrap parameter scenarios đã được chọn về hướng thiết kế.

**Proposed — not approved:** constrained MLE implementation, optional regularization selected on validation, bootstrap temporal blocks, numeric likelihood/dispersion convention, estimator/library and thresholds. **OPEN:** final context feature lists/versioned preprocessing, capacity/cohort parity, Negative Binomial dispersion convention, bootstrap block/replicate/seed/quantile definition, per-hex minimum support, held-out NLL/calibration, coefficient stability and artifact eligibility. Không tự gán default hay tuyên bố causal elasticity. Khi required response artifact invalid, theo GD-08 là **INVALID/no recommendation/no publication**, không tự tạo fallback policy.

## GD-07 — Historical operator-flow revision (2026-10-16; superseded 2026-10-18)

Theo yêu cầu mới, operator có thể Accept Selected hoặc manual adjust một hex mà **không cần** revalidate/re-optimize toàn mạng trong cùng decision interval. Đây là price decision riêng, qua backend policy về quyền, giá/precision, version, idempotency và audit. Một operation hợp lệ ở backend không đồng nghĩa GGSO chứng nhận applied full-network vector vẫn thỏa modeled BR/no-loss. Manual values có thể ngoài grid GGSO 0.1 nếu backend cho phép; không gắn utility từ candidate gần nhất.

Ở kỳ t+5 tiếp theo, GGSO lấy **current surge đã EFFECTIVE** từ snapshot mới làm reference s0 và forecast/candidate/HiGHS/validation từ đầu. Pending/recorded value chưa effective không được dùng làm s0. Không auto-rollback manual decision nếu kỳ sau INVALID. Quyết định này được giữ làm provenance nhưng đã bị thay thế bởi automatic full-policy execution bên dưới.

## GD-07 — Automatic full-policy execution supersession (2026-10-18)

**User-approved target design:** mỗi 5 phút, GGSO tạo một full-network policy, chạy independent validation, rồi tự động áp dụng chính policy đó nếu VALID. Trước khi apply, backend kiểm price bounds, precision, reference version và idempotency. Nếu bất kỳ validation hoặc execution precondition nào thất bại, GGSO không gửi partial write; current effective prices giữ nguyên.

**Dashboard scope:** giao diện chỉ dùng để monitoring forecasts, current/recommended/applied multipliers, validation result, execution status và history. Không có Accept Selected, Accept All, manual one-hex override hoặc bước operator approval trong target flow.

**Compatibility boundary:** legacy DEMO/REPLAY UI và per-hex backend services vẫn là implementation history. Quyết định này không tự bật production pricing. Cần versioned adapter, atomic full-policy execution contract, receipt/status evidence và explicit deployment authorization trước live activation. Chu kỳ kế tiếp luôn dùng latest confirmed effective policy từ fresh snapshot.

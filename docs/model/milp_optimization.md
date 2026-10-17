# Joint Network Optimization — GGSO MILP

Status: consolidated GD-05/GD-06/GD-07 design (revised 2026-10-18); chưa có production solver benchmark hoặc live execution được xác nhận. Nguồn: [current report and source register](../technical_report/README.md). Solver/settings và integration rules phải được chốt qua GD-05/GD-06.

## 1. Trách nhiệm và inputs

Nhận bảng feasible candidates đã tính outcomes/utility, required cell set I, pricing adjacency E, nonnegative edge weights, Q cố định và policy configuration. Không gọi GNN, fit response hoặc tính lại counterfactual bằng một model khác trong solve.

Input phải tương thích [candidate/policy contract](../contracts/CANDIDATE_POLICY_CONTRACT.md). Mỗi cell có ít nhất một candidate; candidate ID unique; không trộn decision snapshots/artifact versions.

## 2. Variables và objective

$$
z_{i,a}\in\{0,1\},\qquad\sum_{a\in\mathcal A_i}z_{i,a}=1,\qquad s_i=\sum_a z_{i,a}s_i(a).
$$

$$
\max_{z,d}\sum_{i,a}z_{i,a}\left[\widetilde U_i(a)-\lambda_t|a|\right]-\lambda_g\sum_{(i,j)\in E}w_{ij}d_{ij}.
$$

Với mỗi pricing edge:

$$
d_{ij}\ge0,\qquad d_{ij}\ge s_i-s_j,\qquad d_{ij}\ge s_j-s_i.
$$

MO-01: chọn đúng một candidate/cell, không average hai actions. MO-02: temporal penalty dùng additive adjustment a; spatial penalty dùng absolute surge difference, không đổi thành difference giữa adjustments.

Các penalty weights phải không âm để có nghĩa penalty và giữ linearization như nguồn. Monetary scale phải nhất quán với utility; trọng số là cấu hình có đơn vị tương ứng, không tự chọn theo forecast loss. Edge weights không âm; policy graph phải có quy ước duplicate/direction rõ. Không đếm cả (i,j) và (j,i) hai lần nếu config quy định một undirected edge.

## 3. Hard constraints

Đặt $Q_{total}=\sum_i Q_i>0$:

$$
BR_{min}Q_{total}\le\sum_{i,a}z_{i,a}\widehat D_i(a)\le BR_{max}Q_{total}.
$$

MO-03: Q là denominator cố định, khớp booking cohort/horizon; không dùng completed rides làm tử số BR. Guardrail này dùng coefficients được cung cấp, không tự biến thành robust chance constraint trên mọi scenarios.

Surge bounds, grid step 0.1 và additive adjustment ±0.3, candidate support được enforce qua feasible sets và được recheck khi decode. MO-04: full required network, không thiếu/trùng/thừa cell. Cấu hình BR/pricing/tolerances chưa được source chốt; không lấy bounds của backend demo làm GGSO defaults.

Q_total=0 với BR_min>0 invalid theo nguồn. Các trường hợp Q_total=0 khác chưa có semantics đầy đủ: ghi GD-02, không chia cho epsilon hoặc báo BR=0 đã hợp lệ.


### 3.1. Hard nominal network GMV no-loss (GD-05 — APPROVED)

$
\boxed{
\sum_{i\in I}\sum_{a\in\mathcal A_i}z_{i,a}\,\Delta U_i(a)\ge0
}
$

Đây là tổng **nominal modeled incremental GMV** trước penalties, KHÔNG phải tổng conservative scores. Cho phép vài hex giảm nominal GMV miễn toàn network không âm; vẫn phải đồng thời đạt Booking Rate và mọi hard constraints. All-HOLD có nominal delta 0 nhưng có thể BR-infeasible; không tự coi là nghiệm feasible. Không có nghiệm acceptable ⇒ INVALID và không tạo recommendation. No-loss trên mô hình không đảm bảo realized GMV.

## 4. Solve và status

MO-05: phân biệt proven optimal, feasible incumbent nhưng chưa proven optimal, infeasible, unbounded, timeout không incumbent, numeric/error. Tên enum serialized là integration proposal, không giả định solver cụ thể.

Solver chọn: **HiGHS** (GD-06). Time limit có feasible incumbent chỉ được chấp nhận nếu independent validator xác nhận đủ hard constraints, bao gồm **nominal network no-loss**. Không yêu cầu chứng minh global optimum nếu accepted feasible incumbent hợp lệ; cũng không tự chấp nhận incumbent thiếu kiểm tra. GD-06 phải chốt solver/library/version, time/gap budgets, integrality và feasibility tolerances.

Lưu runtime, raw status, accepted status, objective và bound/gap khi solver cung cấp. Không bịa gap=0 khi không có chứng minh. Unbounded là lỗi cần điều tra formulation/config; không công bố policy.

## 5. Independent post-solve validation

MO-06: từ candidate IDs được chọn, tính lại coverage, action/grid membership, surge/base/version, bounds, adjustment, expected booking rate, **tổng nominal incremental GMV ≥ 0 theo approved numerical tolerance**, và objective components. Không chỉ tin solver status hoặc auxiliary variables.

MO-07: tính spatial discontinuity bằng multipliers thực. Khi lambda_g*w=0, d_ij có thể lớn hơn abs(si-sj) mà không ảnh hưởng objective; không dùng d đó để báo chênh lệch giá thực.

Decode chỉ dùng approved numerical tolerances. Không round/clamp một nghiệm vi phạm thành một policy khác rồi gọi đó là nghiệm solver.

## 6. Baseline và interpretation

Reference policy có incremental utility bằng 0 nhưng có thể có spatial penalty khác 0 hoặc vi phạm predicted BR. Không tự thêm baseline vào feasible set khi không hợp lệ. Objective có thể đánh đổi conservative utility để giảm spatial penalty, nhưng **GD-05 đã chốt hard nominal modeled network no-loss**. Không được dùng soft penalty để vượt qua ràng buộc này.

Sum per-cell lower quantiles không phải network confidence bound. Joint selection chỉ phối hợp qua constraints/penalties; không mô phỏng driver redistribution.

## 7. Failure và acceptance

Không có acceptable feasible solution hoặc independent validation fail → technical INVALID, `recommendations=[]`, `optimized_policy=null`, không execution request/write theo [decision pipeline](../backend/decision_pipeline.md). Không trả phần mạng tối ưu được hoặc giá incumbent như GGSO fallback output.

Tests MO-01…07: enumerate tất cả combinations trên mạng nhỏ, kiểm objective/constraints độc lập, tie không ép một policy duy nhất khi nhiều nghiệm đồng hạng, test lambda=0, asymmetric prices, invalid nodes/candidates, infeasible BR và timeout có/không incumbent. Chi tiết tại [optimization evaluation](../evaluation/OPTIMIZATION_EVALUATION.md). Chưa chạy tests trong phiên docs này.

## 8. Approved policy and outstanding numerical settings

GD-05: action grid {−0.3,−0.2,−0.1,0,+0.1,+0.2,+0.3}; increment 0.1; hard nominal network no-loss ở §3.1. GD-06: HiGHS, có thể accept feasible incumbent khi timeout nếu independent validator pass. Chưa chốt absolute surge bounds, BR thresholds, penalties, HiGHS time limit, gap, scaling và numerical tolerances. Không sao chép backend demo bounds/step thành GGSO production policy.

## 9. Automatic execution and next optimization cycle (GD-07 revised)

Independent validation certifies the exact full-network policy selected by the MILP at the decision cutoff. The backend may submit that policy for automatic application only as a complete vector; it must not substitute, omit or manually edit individual cells under the same GGSO decision.

Before application, execution checks price bounds, precision, reference version and idempotency. A failed check means no policy write. The monitoring dashboard has no approval or manual pricing action. At the next five-minute interval, GGSO freezes a fresh snapshot and uses the latest confirmed effective policy—not a pending execution request—as the new reference.

Tests cover exact selected-vector equality, atomic full-policy submission, execution rejection without partial writes, stale reference rejection, idempotent retries, next-cycle effective-price input and INVALID empty recommendations/null policy.

# Candidate Surge Simulation — GGSO

Status: specification, chưa implementation/test evidence. Source-derived: [S1 §3.3, §5–6; S2 §4.3](../technical_report/README.md). Numerical/serialization rules được ghi là integration requirements, không thay response assumptions.

## 1. Inputs và responsibilities

Nhận complete decision inputs: forecast confirmed booking demand / eligible idle driver stock, current surge, reference fare trước surge, Q, K hoặc inputs capacity approximation, context và eligible response artifact. Xem [contracts](../contracts/CANDIDATE_POLICY_CONTRACT.md).

Chạy sau một network forecast. Module thuần tính toán: không gọi model, fit regression, solver, DB hoặc pricing gateway. K/context/fare/Q giữ cố định giữa candidates cùng cell/decision.

## 2. Capacity

Nếu không có K trực tiếp, nguồn quy định:

$$
K_i=\widehat S_i r_i\frac{H}{60}\min\left(1,\frac{H}{\max(ETA_i,H)}\right),\quad H=5\text{ phút}.
$$

ETA dùng phút, r dùng rides/driver/hour. Không dùng `eta_sec_t` trực tiếp như phút. GD-03 design đã thống nhất: trong GGSO v1 eligible-idle driver stock là effective available supply theo profile đã validate, nhưng khác K. Dataset/model label parity và capacity calibration vẫn pending. Có K trực tiếp thì ghi provenance/method, không áp approximation lần hai. K=0 là case cần kiểm, không chia cho K.

## 3. Generate/filter

$$
\mathcal A=\{-0.3,-0.2,-0.1,0,0.1,0.2,0.3\},\quad s_i(a)=s_i^0+a.
$$

CS-01: lọc theo support, $s_{min}\le s_i(a)\le s_{max}$ và $|a|\le\Delta_{max}$. Default grid không xác định absolute bounds/adjustment limit. Grid khác phải version riêng. Không clamp candidate out-of-bound thành action khác hoặc round làm thêm/mất candidates.

CS-02: giữ baseline calculations riêng để tính incremental utility kể cả khi action 0 bị loại khỏi feasible set. Nếu reference itself invalid/missing thì fail, không bịa baseline. Nếu không còn candidate ở bất kỳ required cell nào: INVALID, không tạo recommendation, policy hoặc execution request.

## 4. Evaluate nominal outcomes

$$
\widehat D_i(a)=\widehat D_i\left(\frac{s_i(a)}{s_i^0}\right)^{-\beta_i}.
$$

$$
\eta_i^0=a_i+v_i^\top c_i+\gamma_i\log\frac{K_i+\epsilon}{\widehat D_i+\epsilon},\quad FR_i^0=\sigma(\eta_i^0).
$$

$$
FR_i(a)=\sigma\left(\eta_i^0+\gamma_i\log\frac{\widehat D_i+\epsilon}{\widehat D_i(a)+\epsilon}\right).
$$

Giữ baseline logit $\eta_i^0$ để tránh round-trip `logit(sigmoid(...))` bão hòa số học; đây là biến đổi tương đương từ công thức nguồn, không đổi model.

$$
\widehat C_i(a)=\min(\widehat D_i(a)FR_i(a),K_i),\quad U_i(a)=\widehat C_i(a)p_i s_i(a),\quad\Delta U_i(a)=U_i(a)-U_i(0).
$$

CS-03: không đồng nhất FR trước cap với C/D sau cap; không round expected counts thành integers. CS-04: fare trước surge và monetary units đồng nhất; không nhân surge hai lần.

## 5. Conservative score

Mỗi scenario theta=(beta,gamma) recompute baseline logit/FR, candidate outcomes và baseline GMV bằng cùng theta. CS-05: lấy quantile của paired increments:

$$
\widetilde U_i(a)=Q_{0.05}[U_i(a;\theta)-U_i(0;\theta)].
$$

Không lấy `quantile(U_candidate)-quantile(U_baseline)`. Quantile interpolation/weights/scenario count phải ghi trong artifact/config GD-04; chưa tự mặc định. Invalid scenario không tự drop để làm score đẹp hơn. Sum cell scores không là network 5th percentile.

## 6. Invariants và edge cases

CS-06: action=0 có D/FR/C/U bằng baseline và cả incremental scores bằng 0. Beta=0 giữ demand không đổi theo multiplier; gamma=0 giữ FR theo demand change. Với D=0: candidate D=C=U=0 nếu inputs hợp lệ. Với K=0: C=U=0; FR vẫn là modeled probability trước cap.

CS-07: finite outputs, D/C không âm, 0<=FR<=1, C<=D, C<=K. Reject nonpositive surge, negative counts/capacity, invalid context/fare/scenario; không `nan_to_num` thành policy hợp lệ.

Forecast D hoặc candidate D vượt Q có thể làm BR không hợp lệ: chưa có clipping model trong nguồn; báo support/semantic issue GD-02, không tự chặn D bằng Q để đổi response curve.

## 7. Outputs và acceptance

Mỗi candidate có cell/action identity, surge, D, FR, C, GMV, incremental/conservative scores, feasibility/reasons và provenance. Lưu rejection diagnostics riêng; solver chỉ nhận validated feasible candidates.

Tests CS-01…07, ETA unit parity, scenario pairing và deterministic candidate IDs. Fixture hữu ích: beta=gamma=0, D=10, K>=10, baseline logit=0, fare=100, s0=1.2, action=0.1 cho FR=0.5, C=5, baseline U=600, candidate U=650, incremental=50. Đây là test-only arithmetic, không phải pricing configuration hay benchmark.
## 8. Forecast semantics agreed — 2026-10-16

Forecast `forecast_demand` là expected confirmed valid booking requests / next five minutes, không phải quote opportunities. `forecast_supply` là expected online, idle, dispatch-eligible drivers tại target timestamp, tức effective available supply theo GGSO v1 profile sau khi kiểm data/model parity. K có đơn vị rides/5 minutes, được operational adapter supplied/derived; không thay K bằng raw driver counts. Mobility OD dùng observed directed physical driver transitions và không phải modeled relocation phản ứng với surge.

Đúng công thức demand response, fulfillment, completed rides và GMV ở §§4–5; không đổi grid mặc định ±0.3 step 0.1. Mismatch semantics hoặc missing K/Q ⇒ upstream run INVALID, `recommendations=[]`, `optimized_policy=null`, không execution request/write; KHÔNG trả current-policy fallback như GGSO output.

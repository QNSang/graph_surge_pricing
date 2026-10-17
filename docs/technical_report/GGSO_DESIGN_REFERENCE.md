# GGSO — Design reference cho coding agent

**Bản rút trích**, không phải toàn bộ technical report. Nguồn: S1/S2 trong [source register](README.md). Status: proposed design, chưa có kết quả thực nghiệm. Các quyết định và phần còn mở được ghi trong [decision log](../implementation/DECISION_LOG.md).

## 1. Phạm vi đã xác định

H3 resolution 7; horizon 5 phút. Forecast một lần toàn mạng dưới reference policy; response models fit độc lập theo cell; candidate simulation; joint MILP; independent validation. Một full-network policy hợp lệ được áp dụng tự động mỗi 5 phút; nếu validation thất bại thì không có write và current effective prices giữ nguyên. Dashboard chỉ dùng để monitoring. Historical S1/S2 specified a full-network fallback, but the current report supersedes it with fail-closed INVALID and no new recommendation/policy. Không partial pooling, không pricing backprop vào forecast, không surge-induced relocation simulator. [T1 §1–3, §6; S1 §1–4, §10.9; S2 §3–4, §7]

## 2. DuoCast trong report

DuoCast là temporal, spatial, and directed-mobility GNN: shared temporal GRU, spatial GATv2, directed mobility GATv2, gated fusion, và hai prediction heads cho demand và effective available supply.

Với lịch sử $X_i=[x_{i,t-T+1},\ldots,x_{i,t}]$:

$$
h_{i,k}=GRU(x_{i,k},h_{i,k-1}),\qquad l_i=LayerNorm(h_{i,T}).
$$

Mỗi relation $r\in\{spatial,mobility\}$ có parameters riêng:

$$
m_i^{(r)}=\sum_{j\in N_r(i)}\alpha_{ji}^{(r)}W_v^{(r)}l_j,
$$

$$
\alpha_{ji}^{(r)}=softmax_j\left[a_r^\top LeakyReLU\left(W_s^{(r)}l_j+W_t^{(r)}l_i+W_e^{(r)}e_{ji}\right)\right].
$$

Gated residual fusion:

$$
c_i^{graph}=W_c[m_i^{spatial}\Vert m_i^{mobility}],\quad
\omega_i=\sigma(W_g[l_i\Vert m_i^{spatial}\Vert m_i^{mobility}]),
$$

$$
z_i=LayerNorm(l_i+\omega_i\odot c_i^{graph}).
$$

Hai head cho $\widehat\ell^D_i,\widehat\ell^S_i$; targets $\log(1+D_i),\log(1+S_i^{eff})$. Decode $\widehat y=\max(\exp(\widehat\ell)-1,0)$. Core loss là trung bình tổng Huber hai target; auxiliary local/spatial losses tùy chọn chưa có định nghĩa đầy đủ. Report chưa chốt T, hidden dims hoặc optimizer; các giá trị này thuộc versioned configuration và checkpoint evidence. [S1 §2; S2 §4.1]

## 3. Response models

$$
D_{i,t}\sim NegBin(\mu_{i,t},k_i),\quad
\log\mu_{i,t}=\alpha_i+w_i^\top c_{i,t}-\beta_i\log s_{i,t},\quad 0\le\beta_i\le4.
$$

$$
C_{i,t}\sim Binomial(D_{i,t},\pi_{i,t}),\quad
logit(\pi_{i,t})=a_i+v_i^\top c_{i,t}+\gamma_i\log\frac{K_{i,t}+\epsilon}{D_{i,t}+\epsilon},\quad 0\le\gamma_i\le1.
$$

Ký hiệu $\pi$ ở đây phân biệt probability với fare $p_i$, không đổi công thức nguồn. $c$ là pre-decision covariates, không phải graph embedding. Phải fit/lưu intercepts, context coefficients, dispersion, beta/gamma, scenarios, support và validation; không chỉ hai scalar. Estimator/dispersion convention/uncertainty method chưa được nguồn chốt. [S1 §4; S2 §4.2]

## 4. Capacity và candidate

Nếu không có capacity trực tiếp:

$$
K_i=\widehat S_i r_i\frac{H}{60}\min\left(1,\frac{H}{\max(ETA_i,H)}\right).
$$

$H=5$ phút, ETA dùng phút, $r_i$ là configured rides/driver/hour. Đây là approximation, không trained head. [S1 §3.3]

$$
\mathcal A=\{-0.3,-0.2,-0.1,0,0.1,0.2,0.3\},\quad s_i(a)=s_i^0+a.
$$

Giữ candidate được support và thỏa absolute surge bounds/adjustment limit. Không tự clamp sang action khác. Bounds và $\Delta_{max}$ là cấu hình riêng, không suy từ grid. [S1 §5]

$$
\widehat D_i(a)=\widehat D_i\left(\frac{s_i(a)}{s_i^0}\right)^{-\beta_i},
$$

$$
FR_i^0=\sigma\left(a_i+v_i^\top c_i+\gamma_i\log\frac{K_i+\epsilon}{\widehat D_i+\epsilon}\right),
$$

$$
FR_i(a)=\sigma\left(logit(FR_i^0)+\gamma_i\log\frac{\widehat D_i+\epsilon}{\widehat D_i(a)+\epsilon}\right),
$$

$$
\widehat C_i(a)=\min(\widehat D_i(a)FR_i(a),K_i),\quad U_i(a)=\widehat C_i(a)p_i s_i(a).
$$

Capacity/fare/context giữ cố định giữa candidates. D là booking cohort, Q là quote opportunities tương ứng. `FR` trước capacity cap không nhất thiết bằng C/D sau cap. [S1 §5–6; S2 Appendix B]

## 5. Conservative incremental utility

$$
\Delta U_i(a)=U_i(a)-U_i(0),\qquad
\widetilde U_i(a)=Q_{0.05}\left[U_i(a;\theta_i)-U_i(0;\theta_i)\right],\quad\theta_i=(\beta_i,\gamma_i).
$$

Candidate/baseline dùng cùng scenario, bao gồm recompute baseline fulfillment theo scenario gamma. Không lấy hiệu hai quantiles riêng. Action 0 có incremental utility bằng 0. Tổng cell quantiles không là network quantile hoặc causal revenue guarantee. [S1 §6; S2 §4.3, Appendix A]

## 6. Joint MILP

$$
z_{i,a}\in\{0,1\},\quad\sum_a z_{i,a}=1,\quad s_i=\sum_a z_{i,a}s_i(a).
$$

$$
\max_{z,d}\sum_{i,a}z_{i,a}[\widetilde U_i(a)-\lambda_t|a|]-\lambda_g\sum_{(i,j)\in E}w_{ij}d_{ij},
$$

với $d_{ij}\ge0$, $d_{ij}\ge s_i-s_j$, $d_{ij}\ge s_j-s_i$, $w_{ij}\ge0$. Penalties là soft; constraints là hard. [S1 §7–8]

Với $Q_{total}=\sum_i Q_i>0$ cố định:

$$
BR_{min}Q_{total}\le\sum_{i,a}z_{i,a}\widehat D_i(a)\le BR_{max}Q_{total}.
$$

Candidate eligibility, surge bounds, adjustment limits và full network coverage phải được kiểm lại sau solve. Acceptable feasible solution khác proven optimal; time limit không tự có nghĩa thất bại nếu có incumbent được phép chấp nhận và validator pass. Solver/gap/tolerances chưa được nguồn ấn định. [S1 §8–10; S2 §4.4]

## 7. Failure handling, automated execution và evidence

Critical failure tạo kết quả INVALID, không recommendation, không optimized policy và không gửi lệnh ghi giá. Current effective prices giữ nguyên vì GGSO không write; đây không phải fallback policy được sinh ra. Reference policy thiếu cũng là INVALID; không tự chế giá 1.0. Không dùng `used_fallback`, HOLD hoặc REVIEW để che technical failure.

Khi full-network policy qua independent validation, execution backend kiểm price bounds, precision, reference version và idempotency rồi áp dụng policy tự động. Không có Accept Selected, manual one-hex edit hay operator approval trong GGSO target flow. Dashboard hiển thị forecasts, current/recommended/applied prices, validation result, execution status và history sau mỗi chu kỳ 5 phút. [T1 §2, §6]

Forecast errors, response calibration, solver feasibility và realized business impact được đánh giá riêng. Report chưa có benchmark hoặc uplift results. [S1 §10.5–10.8; S2 §5–6]

# Marketplace Response Models — GGSO

Status: source-derived design + implementation requirements; chưa có fit/validation evidence. Nguồn [S1 §4/6, S2 §4.2](../technical_report/README.md). File trước cập nhật rỗng; không thay model code.

## 1. Trách nhiệm

Fit offline hai response models độc lập cho từng required H3 cell. Online chỉ load artifact và evaluate candidates; không refit trong request. Không partial pooling hoặc mượn model cell lân cận trong v1. Forecast vẫn là module riêng.

## 2. Dữ liệu đầu vào

Mỗi row có cell, decision interval, surge thực quan sát, pre-decision context, booking count D, compatible-cohort completed count C và capacity K với definition/version. Training context phải known-at-decision; D/C là labels/outcomes, không được nhầm với covariates available tại t.

C phải thuộc cùng cohort D, có maturity/observation window nhất quán; không lấy mọi completion xảy ra cùng 5 phút làm outcome của mọi booking mới trong khoảng đó. GD-02/GD-03 chốt định nghĩa trước training thực. Xem [DATA_SCHEMA](../contracts/DATA_SCHEMA.md).

## 3. Demand — Negative Binomial

$$
D_{i,t}\sim NegBin(\mu_{i,t},k_i),\qquad
\log\mu_{i,t}=\alpha_i+w_i^\top c_{i,t}-\beta_i\log s_{i,t},\qquad 0\le\beta_i\le4.
$$

Fit/lưu $\alpha_i$, ordered context coefficients $w_i$, elasticity $\beta_i$ và dispersion $k_i$. Không viết NB likelihood hoặc chuyển parameters sang thư viện cho đến khi ghi rõ convention mean/dispersion và parameter mapping; nguồn chưa chọn convention cụ thể.

Forecast anchor dùng online là $\widehat D_i$, không tự thay bằng absolute fitted mean của regression. Hệ số demand vẫn phải lưu để reproduce fit, calibration và validation.

## 4. Fulfillment — Binomial

$$
C_{i,t}\sim Binomial(D_{i,t},\pi_{i,t}),
$$

$$
logit(\pi_{i,t})=a_i+v_i^\top c_{i,t}+\gamma_i\log\frac{K_{i,t}+\epsilon}{D_{i,t}+\epsilon},\qquad 0\le\gamma_i\le1.
$$

$\pi$ ký hiệu probability, không phải reference fare. Fit/lưu $a_i,v_i,\gamma_i$. Historical D/C phải là integer counts với $0\le C\le D$. D=0,C=0 không cung cấp positive-trial Binomial evidence; policy xử lý/count support phải được ghi trong fit configuration, không coi là sample fulfillment 100%.

Baseline online:

$$
FR_i^0=\sigma\left(a_i+v_i^\top c_i+\gamma_i\log\frac{K_i+\epsilon}{\widehat D_i+\epsilon}\right).
$$

$\epsilon>0$ cần configuration version. Không tự dùng graph embedding làm context của regression.

## 5. Fitting workflow

### 5.1. Training objective, inputs và learned outputs (GD-04 clarification)

**Context GGSO v1:** dùng *tabular pre-decision features* (có thể là calendar, lagged demand/supply, backlog/ETA có availability hợp lệ), không dùng DuoCast graph embeddings. Danh sách cuối, preprocessing và missing-value policy phải versioned/validated. Hai GLMs fit **offline độc lập cho mỗi H3 cell**; online chỉ load artifact, không refit theo candidate.

| Thành phần | Negative Binomial Demand GLM | Binomial Fulfillment GLM |
|---|---|---|
| Historical observed outcome | Booking requests `D` trong cohort | `C` completed trên `D` booking trials cùng matured cohort |
| Explanatory inputs | Historical applied surge `s > 0`, tabular `c^D` trước decision | Historical effective capacity `K`, booking trials `D`, tabular `c^F` trước decision |
| Learned parameters | `alpha`, ordered `w`, elasticity `beta`, dispersion `k` | Intercept `a`, ordered `v`, sensitivity `gamma` |
| Model prediction | Expected booking demand `mu` | Fulfillment probability `pi` |
| GGSO use | `beta` điều chỉnh DuoCast baseline demand theo candidate surge | `gamma`, `a`, `v`, `c^F` và `K` để estimate baseline/candidate fulfillment |

**Demand training loss:** đặt `mu_{i,t} = exp(alpha_i + w_i^T c^D_{i,t} - beta_i log(s_{i,t}))`; tối thiểu hóa Negative Binomial negative log-likelihood:

$
\mathcal L_{D,i}(\alpha_i,w_i,\beta_i,k_i) =
-\sum_{t\in\mathcal T_i^{train}}\log P_{NegBin}(D_{i,t}\mid\mu_{i,t},k_i),
\qquad 0\le\beta_i\le4.
$

`beta` là **learned coefficient**, không phải hyperparameter hoặc predicted demand; model prediction là `mu`. Convention của `k`/dispersion phải chốt trước khi implement likelihood; không tự mặc định một NB parameterization.

**Fulfillment training loss:** đặt `eta_{i,t} = a_i + v_i^T c^F_{i,t} + gamma_i log((K_{i,t}+epsilon)/(D_{i,t}+epsilon))`, `pi_{i,t}=sigmoid(eta_{i,t})`. Minimize Binomial negative log-likelihood (bỏ hằng số tổ hợp không phụ thuộc parameters):

$
\mathcal L_{F,i}(a_i,v_i,\gamma_i) =
-\sum_{t\in\mathcal T_i^{train}} \left[C_{i,t}\log\pi_{i,t}
+(D_{i,t}-C_{i,t})\log(1-\pi_{i,t})\right],
\qquad 0\le\gamma_i\le1.
$

`D` là trials và `C` là successes của cùng booking cohort: `0 <= C <= D`; `D=0` không đóng góp Binomial trials. `gamma` là learned coefficient; model prediction là `pi`. Surge không vào Fulfillment GLM trực tiếp theo công thức gốc: surge -> estimated demand -> capacity/demand -> fulfillment, với `K` và context giữ cố định qua candidates.

**Estimation:** tối thiểu NLL dưới bounds là training objective, *constrained MLE* là đề xuất cho implementation, **chưa approved** optimizer/library, regularization, dispersion parameterization hay numeric settings. Bootstrap parameter scenarios đã được chốt ở mức hướng thiết kế; method/block length/replicates/quantile rules và support/calibration thresholds vẫn OPEN GD-04. Fit tốt trên observational data không tự chứng minh causal surge response.

RM-01: validate counts, surge dương, finite K/context, cohort maturity và point-in-time context.

RM-02: split theo thời gian; fit preprocessing và coefficients trên train; đánh giá held-out; không dùng test để chọn settings.

RM-03: fit demand và fulfillment riêng cho mỗi cell dưới bounds; lưu convergence/status/support. Cách fitting, regularization và convergence threshold nằm ở GD-04, chưa được source chốt.

RM-04: tạo scenario artifact có method/version/seed hoặc provenance; không gọi scenarios là posterior/bootstrap samples nếu không được tạo theo cách đó.

RM-05: validate artifact cho mọi required cell. Missing/invalid cell làm whole-network response eligibility fail; không tự tạo beta/gamma mặc định.

## 6. Uncertainty và artifact

Nguồn dùng scenarios $\theta_i=(\beta_i,\gamma_i)$. Các coefficients còn lại giữ nominal nếu scenario definition chỉ gồm hai tham số này. Mỗi scenario phải recompute **cả baseline lẫn candidate**, bao gồm baseline FR với gamma của scenario. Giữ pairing; không sampling baseline/candidate độc lập.

Artifact fields chi tiết: [RESPONSE_ARTIFACT_CONTRACT](../contracts/RESPONSE_ARTIFACT_CONTRACT.md). Ngoài coefficients cần context ordering/preprocessing, train support/time window, calibration status, semantic versions và validation evidence.

## 7. Những gì chưa chốt

Estimator/library, NB parameterization, regularization, **bootstrap method/block length/replicate count**, support thresholds, calibration acceptance và extrapolation support region: GD-04. Bootstrap parameter scenarios là design direction đã chọn, không phải artifacts đã tạo. Không gán numeric defaults như quy định của report. Cell quá ít variation về surge không được tự coi beta=0 là elasticity đáng tin cậy.

Historical predictive fit không tự nhận diện causal price effect. Các response curves hiện là model-based assumptions theo report; không ghi causal uplift đã chứng minh.

## 8. Acceptance

Tests RM-01…05 cùng serialization round-trip, coefficient bounds, wrong context order/version, incompatible cohort, missing cell, invalid scenario, D=0/C>0 rejection. Controlled synthetic parameter recovery chỉ kiểm plumbing/estimator với fixture, không chứng minh causal validity trên marketplace.

Evaluation theo [MODEL_EVALUATION](../evaluation/MODEL_EVALUATION.md). Chưa chạy tests hoặc fit models trong phiên docs này.

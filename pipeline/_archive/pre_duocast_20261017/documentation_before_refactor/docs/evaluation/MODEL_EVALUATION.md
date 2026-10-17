# Model Evaluation — Forecast và Response

Status: evaluation protocol; chưa có kết quả mới. Nguồn [S1 §10.5–10.6, S2 §5–6](../technical_report/README.md) và active pipeline README. Không gộp forecast accuracy với pricing quality.

## 1. Forecast evaluation

Báo cáo riêng demand MAE/RMSE và supply MAE/RMSE trên đúng raw-count targets sau decode. Log-space loss dùng train/selection khác raw-space metrics; không gọi giảm loss là phần trăm GMV uplift.

S1/S2 đề xuất Log D/S MAE, shortage recall và cross-cell ranking metrics nhưng chưa chốt mọi denominator/threshold/tie rules. Active GeoMobiNet README mô tả D/(S+1) proxy, WAPE, shortage precision/recall/F1 và slices. Giữ hai metric profiles/version riêng; không so raw ratio với smoothed proxy như cùng một target.

R1/R2 nêu persistence/seasonal naive, local/network LightGBM và các biến thể GRU/spatial/mobility/dual/geo/road. **M4 DuoCast** là biến thể `gru_dual_graph`: Temporal GRU + Spatial GATv2 + directed Mobility GATv2 + gated fusion + dual prediction heads, không có Geo Encoder hay static geographic-feature input. **M5 GeoMobiNet-SMG** là biến thể lịch sử/implementation evidence có geo MLP; báo cáo riêng M5 nếu chạy để so sánh, không gọi nó là DuoCast M4 bằng rename. GD-01 phải chốt tên comparison và checkpoint/config tương ứng trước experiment.

## 2. Split và selection

Dùng chronological held-out observations. Active configuration có 70/15/15 và strict split/history12; đó là repo setting, không phải kết quả tối ưu đã chứng minh. Fit preprocessing trên train, chọn configurations bằng validation, test dùng để báo cáo sau khi frozen selection. Không test-tune hoặc rò future OD/late data qua features.

So sánh cùng node set, time windows, availability profile, target semantics và input support. Báo theo cell, giờ, peaks, low/zero supply và missing-data segments khi có dữ liệu. Undefined metric denominators phải có null/reason, không cho điểm hoàn hảo giả.

## 3. Response evaluation

| Nhóm | Evidence cần báo cáo |
|---|---|
| Demand model | Held-out count errors và distribution fit theo NB convention đã chọn |
| Fulfillment | Predicted probabilities so với matured cohort outcomes; calibration theo bins/protocol đã chốt |
| Completion | Sai số expected completed rides; ghi rõ trước/sau capacity cap và observation horizon |
| Parameters | Beta/gamma cùng intercept/context/dispersion, stability qua windows/cells |
| Support | Training/validation counts, price/context coverage, số cell eligible và lý do không eligible |
| Uncertainty | Scenario generation/provenance, sensitivity; không gọi confidence coverage khi chưa có protocol |

GD-04 phải chốt metrics/thresholds và estimation method trước promotion. Convergence hoặc predictive error nhỏ không tự chứng minh elasticity causal. Synthetic parameter recovery kiểm estimator plumbing, không chứng nhận observational identification.

### Response GLM fitting/evaluation protocol — GGSO v1

- **Demand:** training objective Negative Binomial NLL; báo cáo held-out NLL (kèm NB dispersion convention), count deviance/MAE và calibration theo surge ranges, giờ và cell support.
- **Fulfillment:** training objective Binomial NLL; đánh giá held-out Binomial NLL/deviance, Brier score, predicted vs observed fulfillment calibration theo capacity/demand bins và booking cohort maturity.
- **Parameters:** beta/gamma bounds, convergence, fraction stuck at bounds, temporal-window stability, historical surge variation, confidence/scenario dispersion, out-of-support extrapolation; good predictive fit **không tự chứng minh** learned response coefficients reliable hoặc causal.
- **Context ablation:** minimal calendar tabular features vs expanded pre-decision tabular context, chronological train/validation/test; **không dùng DuoCast graph embeddings trong acceptance baseline v1**.
- **Uncertainty:** bootstrap scenarios có provenance, paired beta/gamma scenario IDs, stable lower-tail candidate utility, failed-fit counts; scenario count, sampling block và thresholds còn OPEN GD-04.
- **Promotion:** cần evidence về NLL/calibration/support/stability với thresholds được approved; một required hex invalid -> GGSO decision run INVALID, không recommendation/policy/execution request. Không báo giả test PASS, benchmark hoặc GMV uplift.

## 4. Artifact promotion

Tách forecast acceptance khỏi response acceptance; full required-cell validation theo contract. Đủ tests chưa có nghĩa production eligible. Mỗi artifact cần dataset/time/feature/semantic versions, checkpoint/config và actual evaluation references.

Response missing/invalid cells phải thể hiện ở coverage; không xóa khỏi mẫu báo cáo để eligibility đẹp hơn. Không thay model của cell thiếu bằng neighboring fit trong v1.

## 5. Kết quả hiện tại

Chưa đọc experiment logs, fitted response coefficients hoặc held-out results trong phiên docs này. Không báo số MAE, calibration, uplift hoặc winner. Khi có results, ghi exact artifact paths vào task G07 và CURRENT_STATE; report chỉ cập nhật số có nguồn. Không copy số test lịch sử frontend sang model evaluation.

# 11. Hợp đồng post-training analysis

## 1. Mục tiêu và phạm vi

Analysis giải thích/kiểm tra một checkpoint đã cố định và tìm giả thuyết cho experiment tiếp theo. Analysis không sửa weights, normalization, target, selected candidate hoặc registry alias. Core artifacts/metrics tồn tại trước analysis; rich report không là điều kiện để giữ model đã train.

**[Confidence: Medium — thiết kế plugin nghiên cứu.]** Default có permutation importance, profiling và graph snapshot trên validation; SHAP, AutoGluon, tsfresh và Quarto opt-in. Các package được lock ở research environment; không import trong training/serving bootstrap.

## 2. Interface plugin

```python
class AnalysisPlugin(Protocol):
    def supports(self, model_contract, data_contract) -> SupportDecision: ...
    def run(self, context: AnalysisContext) -> AnalysisResult: ...
```

Context chứa bundle/eval/norm/source digests, selected checkpoint numeric identity, read-only train/val views, explicit sample IDs, resource limits, seed và output directory mới. Không đưa registry client có quyền mutation hoặc test labels vào default context.

`AnalysisResult` có `analysis_id`, method/version, status=`PASSED/SKIPPED/FAILED`, elapsed_seconds, sample_ids_sha256, input_bundle_sha256, outputs với hashes, limitations, error_code/reason và environment versions. Status hỗ trợ riêng `unsupported` qua SKIPPED reason; không dùng file ảnh trắng hoặc score0 thay unsupported.

## 3. Plugin contracts

| Plugin | Inputs và phương pháp mặc định | Outputs bắt buộc | Điều kiện / giới hạn |
|---|---|---|---|
| `permutation_importance` | Frozen model, val sampled whole graph windows; permute declared feature groups bằng mapping cố định | baseline_metric, permuted metric/repeat, delta distribution, mapping IDs, sample counts | 5 repeats, seed logged; giữ fixed eligible labels; không shuffle từng node-row như iid |
| `profiling` | Train/val physical features/support, valid labels, missing masks | summary JSON/HTML: schema, missing, quantiles, support, group counts | Không tự impute/update scaler; large report bounded sample và ghi sampling method |
| `graph_snapshot` | Một số timestamp đã chọn; typed directed edges và local/graph forecasts | Graph plot + nodes/edges CSV/JSON; snapshot IDs; method labels | NetworkX chỉ visualization; preserve OD/adjacency types; không gọi attention là causal contribution |
| `shap` | LGBM29/40 current-feature view đầu tiên; background từtrain, explained samples từval | explanation table, background/sample digests, estimator/output space và explainer method | Background tối đa128, explained64 pilot; unsupported GNN explainer phải SKIP rõ |
| `autogluon` | Same training target và current29/40 view; explicit time-based validation table | model leaderboard, exact config/budget, predictions, canonical evaluator report | Không dùng default random holdout/crossvalidation làm so sánh chính; test không đưa vào fit/selection |
| `tsfresh` | Input histories tại/beforecutoff, fit/select feature bằng train-only | discovered feature list, transform definitions, train-only selector state, coverage/cost report | Không sửa input dimension của run hiện tại; thử feature mới bằng contract/dataset/trial mới |
| `quarto` | JSON/Markdown core evidence + optional results | HTML/PDF report, rendered warnings/status, source artifact links | Thiếu Quarto vẫn có model_card.md và JSON report đầy đủ |

Defaults về sample/time là budget engineering, không phải đảm bảo explanation chính xác. Các library APIs cụ thể phải được chọn từ versions đã lock; plugin adapter có smoke riêng, không dựa vào auto-detection của model class.

## 4. Permutation cho temporal graph

Permute cùng một feature group trên **toàn W12 history** của một sample theo mapping giữa temporal blocks/graph samples đã khai báo. Giữ temporal order trong block. Không lấy future values ngoài split được giải thích. Các columns phải thay cùng nhau khi thuộc một representation, ví dụ sin/cos của một time variable hoặc count+support của một rate, nếu contract nêu nhóm đó.

Default experiment cố định graph và chỉ perturb node feature group; kết quả phải ghi đây là **conditional perturbation diagnostic**, có thể tạo input combination ngoài phân phối. Khi cần recompute graph-derived features đồng bộ, dùng transform/plugin version riêng và ghi lại graph digest mới; không so với một baseline mà không nói graph đã thay đổi.

Rank importance theo delta của canonical MAE_q cùng population. Prediction invalid do perturbation được báo, không bỏ hàng để làm importance đẹp. Nếu perturbation làm graph input invalid, method không có valid score cho group đó; không báo0. Các repeats không tạo mẫu độc lập cho statistical confidence của toàn marketplace.

## 5. Explain local/graph/controller riêng

Giải thích forecast ở log1p hoặc q space phải ghi rõ output đang được giải thích. Một attribution trong log-space không được kể trực tiếp thành điểm surge. Với dual model, report riêng local/graph predictions và distribution `q_graph-q_local`; shared encoder/two heads không làm difference trở thành causal effect.

Controller explainability dùng arithmetic trace của q_star, P/R, dead zones, gains, requested/applied caps. Những bước này kiểm được từ audit mà không cần SHAP. Attention heatmap chỉ nêu weight/message diagnostic theo definition; không nói một cạnh gây ra x% surge hoặc tài xế chắc chắn đến theo weight đó.

## 6. Isolation và rerun

Plugin chạy subprocess, read-only input paths, output folder unique và timeout600s mặc định từ config. Stop subprocess của plugin khi hết timeout; không kill trainer đã hoàn tất. Log failure child với reason/traceback sanitized. Không bắt integrity failure của core bundle và tiếp tục gọi bundle hợp lệ; hash mismatch chuyển core artifact statusinvalid.

Rerun plugin dùng same bundle/sample spec và `analysis_attempt_id` mới; không đổi finished trial params. Report addons nằm dưới analysis run/artifact namespace; bundle digest đã registered không thay đổi. Report summarizer ghi PASSED/SKIPPED/FAILED cho từng requested plugin và link evidence thật.

## 7. Acceptance

- Missing optional package và timeout đều có status/reason; core bundle/trial vẫn truy xuất được.
- SHAP background/train feature selection không đọctest; declared sample IDs tái lập được.
- GNN unsupported explainer không tự dùng tabular surrogate rồi gọi đó là explanation trực tiếp.
- AutoGluon predictions được canonical evaluator chấm cùng rows/target inverse; native leaderboard metric không bị lẫn với graph primary score.
- tsfresh không dùng future/horizon labels khi xây input histories và không mutate selected feature contract.
- Graph visualization giữ directed typed multiedges và source timestamp; attention disclaimer mô tả đúng phương pháp.
- Core report luôn có structured metrics/coverage/evidence dù rich renderer lỗi.

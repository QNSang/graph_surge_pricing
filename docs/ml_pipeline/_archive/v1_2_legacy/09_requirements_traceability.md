# 09. Đối chiếu kiến thức trong ảnh với specs

## 1. Hai mươi nguyên tắc được chuyển thành việc code và kiểm tra

| # trong ảnh | Kiến thức | Đặc tả triển khai | Bằng chứng nghiệm thu |
|---:|---|---|---|
| 1 | Dependency management | Groups/locks riêng, version report, no optional import lúc startup | 07 environment + ART-01 |
| 2 | Binary compatibility | Torch/PyG/CUDA/device doctor, exact environment identity | M1, GPU smoke, EXP-01 |
| 3 | Environment separation | Research/training/serving/tracking runtimes tách | 07§1, fresh-serving test |
| 4 | Containerization | Compose service và explicit volumes/network profile | 07§2, OPS-01 |
| 5 | Persistent storage | DB+artifacts+source retention và restore drill | OPS-01/02 |
| 6 | Service architecture | MLflow service riêng, runner/model logic riêng | 01 package boundaries |
| 7 | Configuration management | Typed strict YAML + schema + resolved config hash | CFG-01..04 |
| 8 | Environment variables | Canonical MLFLOW_TRACKING_URI và secrets redaction | 03§4, MLF tests |
| 9 | Experiment tracking | Parent/child runs, failed attempts, params/metrics/artifacts | 05 MLF-01..14 |
| 10 | Training observability | Epoch losses/valid counts/grad/LR/resources | M3, RUN-05/06 |
| 11 | Artifact management | Required manifest, hashes, report/status, immutable bundle | ART-02/04 |
| 12 | Reproducibility | Seed+code+data+config+normalizer+environment+checkpoint | RUN-01, ART-01/03 |
| 13 | Data lineage | Source vs derivative identity, hashes, semantic contract và index | DATA-CORE |
| 14 | Model interface contract | Typed x/edge tensors, names/dtypes/shape/semantic validators | 06§4, CFG-04 |
| 15 | Serialization/packaging | Resume checkpoint, eager bundle và gated pt2 riêng | ART/EXP tests |
| 16 | Critical/noncritical path | Core stage failure vs optional worker failure | 01§7, ANA-01 |
| 17 | Graceful degradation | Optional errors có status/reason, basic report vẫn tồn tại | ANA-01; không degrade integrity |
| 18 | Orchestration vs logic | Pure forward/loss/metrics, runner interfaces | 01§2/3 |
| 19 | Offline evaluation | Chronological split, masks, fixed population, holdout receipt | EVAL-01..04 |
| 20 | Benchmarking | Persistence, GRU29/40, LGBM29/40, graph ablations | M4/M6, G2 |

**[Confidence: High — đối chiếu trực tiếp nội dung ảnh; Medium — cách chuyển thành implementation requirements.]**

## 2. Những điểm ảnh chỉ minh họa, specs làm rõ

| Trong ảnh | Chi tiết dự án cần bổ sung |
|---|---|
| `market_path`, `od_path` | HCM v2 primary là manifest + Parquet features/raw/burn_in; prepare dựng derivative mmap/edge pointers theo contract |
| `TrainPipelineConfiguration` | Strict schema và hashes; source/target/graph/model versions là fields bắt buộc |
| GNNv1 PyTorch+PyG | Archived implementation là custom GAT legacy; PyG hai-head là package mới cần tests |
| Log metrics | Local/graph riêng, log1p/raw q riêng, validity denominators, selection/test boundary |
| SQLite | Development single-worker; PostgreSQL profile cho team; cả DB và artifact volumes được backup |
| `.pt2` | Export có dtype/dynamic-shape/device/parity gate; không thay resume checkpoint |
| Model ready for deployment | Bundle compatible khác model quality và khác permission/evidence production pricing |
| SHAP/AutoGluon/tsfresh | Optional research workers; feature discovery không fit test hoặc thay contract trong run |
| NetworkX visualization | Graph sampled và semantics rõ; attention không phải causal contribution |
| Report Quarto | Optional renderer; core JSON/Markdown evidence không phụ thuộc Quarto |

## 3. Các ràng buộc riêng phải giữ

- Bidding đang có lợi nhuận theo người dùng; tác động cân bằng marketplace chưa được xác minh.
- V1.2 dự báo hai D/S cùng horizon, controller điều chỉnh trên bidding mới nhất; không thêm RL/MPC/pricing reward vào loss.
- HCM v2 đúng30 ngày; legacy training export W4/target cũ, derivative Parquet→W12/H5 phải có identity mới.
- Denominator S_eff=0 được mask cho target; local forecast nhỏ được REVIEW trong controller; hai failure modes riêng.
- Global cap mock khác cap production; ±0.4 là requested correction, applied phụ thuộc cap.
- Không có quote/GMV/counterfactual labels; không fabricating booking/uplift/regret metrics.
- CURRENT.path và CURRENT.manifest được kiểm riêng; config pin meta/manifest.json + schema.yaml sau reorganization, không sửa hash/source để che lỗi.

## 4. Checklist review specs trước code

Mọi doc/example dùng cùng IDs `hex29_edge10_v1_2`, `ds_log1p_h5_v1_2`, `directed_relations_self_v1`, `dual_gru_gatv2_h5_v1_2`. Main selection key `val/graph/mae_q/h5`. Model outputs local/graph cùngH5. Graphraw10/internal12. Source dataset fingerprint đúng P3. Example controller disabled và numerical parameters chỉ minh họa. Schema errors, undefined metrics, optional failures và registration blockers có hành vi explicit.

Khi sửa requirements, cập nhật tài liệu, schema và example trong cùng change; nâng spec version nếu ảnh hưởng contract. Không đổi ý nghĩa một model version sau khi đã có run/bundle sử dụng.

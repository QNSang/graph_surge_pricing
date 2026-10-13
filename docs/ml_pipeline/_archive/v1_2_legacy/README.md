# ML Training Pipeline — Implementation Specs v1.0

**Dự án:** graph_surge_pricing  
**Ngày:** 2026-10-09  
**Mục tiêu:** đặc tả đủ để code lại hệ thống training, tracking, đánh giá, đóng gói và quản lý model.  
**Trạng thái:** specification để triển khai; chưa phải implementation hoặc chứng nhận model đạt chất lượng.

## Bắt đầu ở đâu?

Đọc [hiện trạng và các quyết định](00_scope_and_sources.md), [kiến trúc và stage contracts](01_architecture.md), rồi triển khai theo [kế hoạch và tiêu chí nghiệm thu](08_verification_and_migration.md). Config tham chiếu nằm ở [train_v12.yaml](examples/train_v12.yaml); schema máy kiểm tra nằm trong [schemas](schemas/README.md).

| Tài liệu | Trả lời câu hỏi |
|---|---|
| [00 — Scope, sources, decisions](00_scope_and_sources.md) | Nguồn nào đúng? Cần thay gì? Quyết định nào là mới? |
| [01 — Architecture](01_architecture.md) | Package/module nào làm gì? Stage chạy, lỗi và resume thế nào? |
| [02 — Data contract](02_data_contract.md) | HCM v2 có gì? Tạo target/window/mask V1.2 và graph batch thế nào? |
| [03 — Configuration and CLI](03_configuration_and_cli.md) | Cấu hình, câu lệnh, output, idempotency và exit codes là gì? |
| [04 — Model, training, evaluation](04_model_training_evaluation.md) | Hai head, loss, optimizer, baseline, metric và selection như thế nào? |
| [05 — MLflow and registry](05_mlflow_and_registry.md) | Tìm run, so sánh, log dữ liệu, quản lý candidate/champion/rollback thế nào? |
| [06 — Artifacts and serving](06_artifacts_and_serving.md) | Bundle gồm gì? Resume và inference khác gì? `.pt2` có điều kiện gì? |
| [07 — Environments and operations](07_environments_and_operations.md) | Docker, lưu trữ, CPU/GPU, monitoring, backup và sự cố? |
| [08 — Verification and migration](08_verification_and_migration.md) | Thứ tự code, acceptance gates, chuyển từ legacy và hoàn thành khi nào? |
| [09 — Requirements traceability](09_requirements_traceability.md) | 20 ý trong ảnh đã được chuyển thành yêu cầu kiểm thử nào? |
| [10 — Study and benchmark contract](10_benchmark_and_study_contract.md) | Materialize baselines/ablations, quản lý study và quyết định quality gates? |
| [11 — Post-training analysis](11_post_training_analysis.md) | SHAP, permutation, AutoGluon, tsfresh và báo cáo chạy đúng phạm vi thế nào? |

## Hướng triển khai đã chọn

1. **HCM v2 là nguồn bất biến sau khi chốt layout:** dùng explicit root `data/hcm_data_2`, manifest `meta/manifest.json`, feature contract `meta/feature_contract.json` và source schema `schema.yaml`. `CURRENT` có root path đúng nhưng manifest field còn tên root cũ; trong manifest còn `release_relative_path` lịch sử. Resolver kiểm tra từng reference, không kết luận toàn bộ pointer hợp lệ chỉ từ root path. V1.2 đọc active Parquet `features/`, `raw/`, `burn_in/` theo inventory `raw_features_burn_in_v1`, rồi tạo derivative mmap; `oracle/` bị cấm làm canonical input.
2. **Migration có version:** layout `hcm_v2_parquet_tree_v1` giữ source feature semantics `hex40_edge10_v2.1`; packed arrays W4/H5,10,15/log-smoothed-ratio đã chuyển vào `data/_archive/hcm_data_2_v2_packed/` để audit/replay. V1.2 dựng mới W12/H5/`log1p(D/S_eff)` từ observed Parquet. Không sửa nhãn cũ hoặc đổi inverse checkpoint cũ; fingerprint training archive không thay consumed-Parquet checksums.
3. **Model V1.2:** shared GRU, head local/context và head graph GATv2; cả hai có supervision. Pipeline không train surge, GMV hay causal effect từ bộ dữ liệu này.
4. **MLflow quản lý bằng chứng:** dataset lineage, resolved config, source/code, train/validation curves, selected-test evaluation, artifacts, model versions và promotion receipts.
5. **Vận hành theo CLI trước:** một runner dùng CPU/GPU; MLflow là tracking/registry service. Chưa cần Airflow, Kubernetes, feature store hoặc dashboard tự viết.
6. **Không trộn điều kiện đạt:** run hoàn thành, model có chất lượng, export chạy được và policy có ích cho kinh doanh là các kết luận riêng.

**[Confidence: High — nguồn dự án và hợp đồng đọc trực tiếp; Medium — kiến trúc triển khai được đề xuất, cần acceptance tests.]**

## Bộ file kèm theo

- [Config V1.2](examples/train_v12.yaml), [config legacy replay](examples/train_legacy.yaml), [controller minh họa](examples/controller_v12.example.yaml).
- [MLflow local Compose](examples/compose.mlflow.dev.yaml), [MLflow team Compose](examples/compose.mlflow.team.yaml), [Dockerfile server](examples/Dockerfile.mlflow), [biến môi trường mẫu](examples/mlflow.env.example).
- [Config JSON Schema](schemas/train_config.schema.json), [model metadata schema](schemas/model_metadata.schema.json), [run state schema](schemas/run_state.schema.json), [data contract có thứ tự feature](contracts/feature_contract_v12.json).

Study suite mẫu nằm trong [benchmark_plan.json](contracts/benchmark_plan.json); effective trial có [schema riêng](schemas/trial_config.schema.json).

Các YAML/Dockerfile ở đây là **mẫu triển khai theo specs**. Các lệnh `surge-ml` mô tả CLI sẽ được code; việc có tài liệu không có nghĩa CLI đã tồn tại. Bản legacy là chế độ đối chiếu độc lập, không được đưa vào registry model V1.2.

**Snapshot đối chiếu trước khi ghi specs ngày 09/10/2026:** code training cũ đã được gỡ khỏi `pipeline/`; `model.py`, `prepared_data.py`, `train_v2.py` lịch sử nằm trong `data/_archive/hcm_data_2_v2_packed/source_snapshot_legacy_pipeline/`. Exporter snapshots hiện nằm trong `data/hcm_data_2/meta/source_snapshot/`; `burn_in/` thay `context/`, `oracle/` thay `diagnostics/`. Source schema được giữ hash riêng; feature order, typed graph rows và right-closed time buckets theo contracts đã đối chiếu trong02, không tự thay bằng grouped column order hoặc comment mâu thuẫn của schema. Specs xây package mới từ đầu với source layout và inventory policy đã khóa; không dùng packed archive làm default data reader. Báo cáo model mới dùng ký hiệu `DS`; `q_h5`/`mae_q` nội bộ là alias cho `DS=D/S_eff`, còn API bên ngoài dùng `ds_local`, `ds_graph`, `ds_ref`.

## Cách đọc yêu cầu

**MUST** là điều kiện bắt buộc; **SHOULD** là default triển khai có thể thay bằng decision record; **MAY** là tùy chọn. Mỗi thay đổi feature/target/graph/output phải tạo version mới. Khi prose, YAML và schema khác nhau, dừng tích hợp và sửa specs; không tự chọn phần thuận tiện nhất.

Specs dùng `High` cho nội dung đã có nguồn/toán học và `Medium` cho lựa chọn kỹ thuật mới. Các thông số pilot không phải tham số tối ưu hoặc ngưỡng kinh doanh đã được xác nhận.

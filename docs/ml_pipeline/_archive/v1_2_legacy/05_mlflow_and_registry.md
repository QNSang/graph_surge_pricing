# 05. MLflow Tracking và Model Registry

Trạng thái: specification để triển khai; tài liệu này không khẳng định pipeline hoặc MLflow server đã được chạy.
Phạm vi: quản lý thí nghiệm, provenance, kết quả, failure, model versions và promotion trong môi trường research.
Baseline: MLflow client/server `3.16.1`; package mới `pipeline/src/surge_ml`; CLI `uv run --project pipeline surge-ml`.

## 1. Quy ước và ranh giới trách nhiệm

**MUST** là yêu cầu bắt buộc để nghiệm thu; **SHOULD** là mặc định đề xuất có thể thay đổi bằng quyết định được ghi lại.
Nhãn `[Confidence: High — tài liệu chính thức]` mô tả khả năng API đã có nguồn; `[Confidence: Medium — quyết định thiết kế]` mô tả contract dự án đề xuất.
Các con số metric trong phần này là tên trường hoặc quy tắc, không phải kết quả huấn luyện.

| Thành phần | Trách nhiệm |
|---|---|
| `surge_ml` runner | Điều phối stage, trial, retry, cancel, checkpoint, chọn model, kiểm tra gates |
| MLflow Tracking | Ghi experiment, runs, params, tags, metrics, dataset metadata và artifacts |
| MLflow Registry | Lưu registered model/version, lineage, aliases và version tags |
| Artifact store | Giữ model bundle, checkpoints, manifests, predictions và reports |
| Journal của runner | Giữ trạng thái execution, stage, attempt và sự kiện chưa đồng bộ tracking |
| Registry controller | Serialize promotion, kiểm tra expected version, tạo promotion receipt |

**[Confidence: Medium — quyết định thiết kế]** MLflow MUST NOT được dùng thay job queue hoặc làm nguồn duy nhất để suy ra một tiến trình training còn sống.
Trạng thái OS process, heartbeat và checkpoint thuộc runner. Trạng thái MLflow chỉ được cập nhật từ sự kiện đã xác minh của runner.
Các profile hạ tầng, artifact proxy và lưu trữ bền vững được quy định tại [07_environments_and_operations.md](07_environments_and_operations.md).

## 2. Version và kết nối

**[Confidence: High — tài liệu chính thức]** MLflow `3.16.1` tồn tại; đây là phiên bản pin theo baseline kiến trúc, không gọi là phiên bản mới nhất. Xem [R1] và [R2].
Client MUST kiểm tra `/version` của server trong preflight; canonical study chỉ chạy khi response khớp chính xác `3.16.1`.
Nâng version MUST thay lockfiles, chạy migration có backup và kiểm tra logging, registry, model roundtrip trước khi chấp nhận baseline mới.

| Biến | Giá trị/quy tắc |
|---|---|
| `MLFLOW_TRACKING_URI` | URI đầy đủ gồm scheme, host và port; bắt buộc trong canonical mode |
| Host chạy CLI | Thông thường `http://127.0.0.1:5000` trong local profile |
| Container training trong cùng Compose network | Thông thường `http://mlflow:5000` |
| `MLFLOW_REGISTRY_URI` | Mặc định cùng tracking server; nếu khác MUST khai báo và kiểm tra riêng |
| `MLFLOW_EXPERIMENT_NAME` | `graph-surge/v12/hcm-mock/research` |
| `MLFLOW_S3_ENDPOINT_URL` | Chỉ dùng cho S3-compatible artifact storage; không phải tracking URI |
| `MLFLOW_TRACKING_ENDPOINT` | Không dùng làm cấu hình chuẩn; nếu có legacy field thì adapter phải chuyển đổi rõ ràng |

**[Confidence: High — tài liệu chính thức]** SDK dùng `MLFLOW_TRACKING_URI` hoặc `mlflow.set_tracking_uri()`; catalog chính thức không cung cấp `MLFLOW_TRACKING_ENDPOINT` cho mục đích này [R3, R4].
Canonical mode MUST NOT tự rơi về `./mlruns`, SQLite cục bộ hoặc experiment `Default` khi thiếu cấu hình/kết nối.
Preflight MUST kiểm tra quyền tạo run, log metric, upload/download artifact nhỏ và quyền đọc registry; promotion kiểm tra quyền ghi registry riêng.
Không ghi token/password, connection string có credentials hoặc toàn bộ environment vào params, tags, journal hay artifact.

## 3. Identity và dataset lineage

Các identity dưới đây MUST đi cùng mọi study; trial/analysis phải nhận cùng giá trị từ resolved configuration.

| Trường | Baseline hoặc semantics |
|---|---|
| `project_id` | `graph_surge_pricing` |
| `pipeline_contract_version` | `v1.2` |
| `source_dataset_id` | `hcm_mock_v2_30d_seed42` |
| `source_dataset_path` | `data/hcm_data_2`, đường dẫn nguồn vật lý trong repository |
| `dataset_kind` | `synthetic` |
| `target_contract_id` | `ds_log1p_h5_v1_2` |
| `model_contract_id` | `dual_gru_gatv2_h5_v1_2` |
| `input_contract` | `x[B,12,61,29]`; raw edge features 10, internal edge features 12 |
| `window_steps` / `horizon_minutes` | `12` / `5` |
| `study_id` | Slug/identifier ổn định của study; không đồng nhất với MLflow run ID |
| `attempt_id` | UUID của một attempt thực thi |
| `parent_run_id` / `run_id` | ID thật do MLflow trả về; không dựng từ tên study |
| `source_manifest_file_sha256` / `source_manifest_semantic_sha256` | Byte hash của manifest nguồn / hash semantic projection; không so lẫn |
| `source_schema_sha256` | Byte hash của source schema.yaml; table layout/column roles, các discrepancy với ordered contract được ghi trong source validation |
| `source_parquet_sha256` | Semantic digest của inventory Parquet raw/features/burn_in đã consume; khác fingerprint13 file training legacy |
| `derived_dataset_sha256` | SHA-256 manifest derivative đúng target/window contract |
| `split_manifest_sha256` | SHA-256 split indices, boundaries, purge policy và timezone |
| `config_sha256` / `code_revision` | Config đã resolve và revision/source snapshot thực tế |

**[Confidence: Medium — quyết định thiết kế]** `data/hcm_data_2` là vị trí nguồn, không phải bằng chứng derivative đã được tạo hoặc phù hợp v1.2.
Legacy training export trong `data/_archive/hcm_data_2_v2_packed/training/` có window4, horizons5/10/15 và target `log((D+1)/(Seff+1))`; các arrays này là audit/replay reference. Canonical V1.2 prepare đọc trực tiếp Parquet features/raw/burn_in theo allowlist02, tạo inventory `source_parquet_sha256` và mmap derivative với `ds_log1p_h5_v1_2`, window12/horizon5. Log inventory vào `provenance/source_parquet_manifest.json`; không coi training fingerprint là hash của Parquet.
Không thay tên legacy target trong tracking rồi coi dữ liệu cũ đã có semantics của target mới.
Target formula, valid masks và cách biến đổi giữa output log1p/q phải được lấy nguyên từ data/model contract đã freeze.

**[Confidence: High — tài liệu chính thức]** `mlflow.log_input()` ghi dataset metadata và context; source có thể khác dữ liệu sau filtering/transforms. Vì vậy log input không thay immutable snapshot và manifest [R5].
Mỗi partition MUST log một `mlflow.data.Dataset` với `context="training"`, `"validation"` hoặc `"testing"` phù hợp stage.
SDK dataset digest được giữ nguyên theo SDK; SHA-256 đầy đủ của dự án lưu trong tags và manifest riêng, không giả định digest mặc định kiểm chứng toàn bộ file.
Manifest MUST chứa từng relative path, file SHA-256, byte size, row count, schema hash, generator/code version và seed nếu nguồn là synthetic.
Snapshot MUST có thể truy xuất lại bằng URI/immutable directory; checksum đúng nhưng file đã mất không đạt reproducibility gate.

## 4. Experiment và run topology

**[Confidence: Medium — quyết định thiết kế]** Một canonical study có đúng một parent run `run_role=study` và các child runs bên dưới.

| `run_role` | Cardinality | Dữ liệu được sử dụng | Điều kiện kết thúc |
|---|---:|---|---|
| `study` | 1 | Manifests, aggregate summaries; không trực tiếp fit model | Children bắt buộc, tracking và reports hoàn tất |
| `trial` | N | Train + validation | Trial thành công, failed hoặc pruned đều có inventory |
| `selected_final_eval` | 1 logical evaluation | Holdout test cho selected model và frozen comparators | Bảng đánh giá, predictions, gates được lưu đầy đủ |
| `analysis` | 0..N | Partition được cho phép trong analysis contract | Independent; không quyết định lại selected model |

**[Confidence: High — tài liệu chính thức]** Parent/child runs có thể tạo bằng `nested=True` hoặc `parent_run_id`; SDK dùng `mlflow.parentRunId` để liên kết [R6].
Runner SHOULD tạo parent trước, truyền run IDs tường minh cho worker, dùng một owner logging/process và chờ critical children xong trước khi kết thúc parent.
Fluent tracking không bảo đảm thread-safe và `active_run()` là thread-local [R6]; không dùng active context xuyên thread/process.
Trial name là nhãn dễ đọc, ví dụ `trial-0007-seed-42`; deduplication dùng immutable IDs và journal, không tìm run theo tên rồi coi là duy nhất.
HPO trial bị prune MUST có run và `trial_status=pruned`, `prune_reason`, budget consumed; map MLflow status thành `KILLED` với semantics này ghi rõ.
Trial lỗi MUST giữ error category, failing stage, elapsed seconds, last checkpoint và log đã lọc secrets.

## 5. Selection và quyền truy cập holdout

Trial MAY log training diagnostics; việc xếp hạng MUST chỉ đọc metric validation được freeze trong evaluation configuration.
Các trường `selection_metric_name`, `selection_direction`, tie-break rule, metric definition version và comparator manifest MUST được log trước trial đầu tiên.
Canonical primary metric là `val/graph/mae_q/h5`, direction `min`; tie-break và gate definitions lấy từ chapter evaluation đã freeze.
Trial MUST NOT log `test/*`, đọc test labels để early stop, hoặc chọn hyperparameters/calibration/feature list từ test reports.
Selected model MUST được freeze bằng model/checkpoint SHA-256 trước khi worker `selected_final_eval` được cấp test partition.
`selection/selected_model.json` MUST ghi selected trial, checkpoint, best epoch, selection metric/value, tie-break evidence và config hash.
`evaluation/comparator_manifest.json` MUST freeze comparator model versions, code/config hashes và dataset/split identity trước khi chạy test.
Một logical final evaluation có thể đánh giá selected model và các comparator đã freeze trên cùng holdout; không tạo vòng tuning mới sau khi nhìn test.
Nếu final evaluation crash, retry chỉ được dùng cùng selected model, comparators, inputs và evaluation config; resume attempt không phải lần chọn model mới.
Thay đổi model/config vì kết quả test MUST tạo study mới, đánh dấu holdout đã được sử dụng và áp dụng protocol holdout mới trước khi đưa ra kết luận confirmatory.
Optional SHAP/permutation/report analyses MUST NOT thay đổi selected model, registry aliases hoặc success của các critical stages.

## 6. Params, tags và metric catalog

Params dùng cho cấu hình bất biến trong run; tags dùng cho identity và trạng thái; cấu hình đầy đủ lưu JSON/YAML artifact.
Param không được dùng như kênh ghi giá trị optimizer thay đổi theo epoch; learning-rate schedule thực tế ghi metrics theo step.

| Nhóm | Tên trường bắt buộc |
|---|---|
| Run tags | `project_id`, `pipeline_contract_version`, `run_role`, `study_id`, `attempt_id`, `dataset_kind` |
| Lineage tags | `source_dataset_id`, `source_manifest_file_sha256`, `source_manifest_semantic_sha256`, `source_parquet_sha256`, `source_schema_sha256`, `derived_dataset_sha256`, `split_manifest_sha256`, `code_revision`, `config_sha256` |
| Model tags | `target_contract_id`, `model_contract_id`, `feature_schema_sha256`, `graph_schema_sha256` |
| Execution tags | `execution_status`, `tracking_sync`, `quality_status`, `export_status`, `attempt_number`, `resume_from_run_id` khi có |
| Params dữ liệu | `window_steps=12`, `horizon_minutes=5`, `node_count=61`, `node_feature_count=29`, `raw_edge_feature_count=10`, `internal_edge_feature_count=12` |
| Params training | `seed`, `epochs_max`, `batch_size`, optimizer/lr/weight_decay, early-stop và scheduler config |
| Params architecture | GRU hidden size/layers, GATv2 hidden size/heads/layers, dropout, loss weights theo model contract |
| Params selection | `selection_metric_name`, `selection_direction`, `metric_definition_version`, `tie_break_rule` |
| Runtime artifact | Python/Torch/PyG/MLflow versions, CPU/GPU/device, CUDA/cuDNN, lockfile hashes, deterministic mode |

Metric catalog dưới đây là contract đề xuất; metric nào không được architecture/evaluation contract dùng MUST ghi `not_applicable` trong report thay vì tạo số giả.

| Metric keys | Scope/step | Semantics |
|---|---|---|
| `train/loss_total`, `train/loss_local`, `train/loss_graph` | Trial; optimizer step hoặc epoch đã khai báo | Loss đúng reduction và valid mask của training contract |
| `train/learning_rate`, `train/gradient_norm` | Trial; optimizer step | Diagnostics; không dùng thay validation score |
| `val/local/mae_log1p/h5`, `val/graph/mae_log1p/h5` | Trial; epoch | MAE trong transformed target space |
| `val/local/mae_q/h5`, `val/graph/mae_q/h5` | Trial; epoch | MAE sau inverse transform theo target contract; graph là primary selection metric |
| `val/local/rmse_q/h5`, `val/graph/rmse_q/h5` | Trial; epoch | RMSE trên q, cùng masks và sample set |
| `selection/best_validation_value`, `selection/best_epoch` | Trial + parent summary | Giá trị dùng chọn checkpoint, không lấy last epoch mặc định |
| `test/local/mae_log1p/h5`, `test/graph/mae_log1p/h5` | Final evaluation; step 0 | Holdout transformed-space error |
| `test/local/mae_q/h5`, `test/graph/mae_q/h5` | Final evaluation; step 0 | Holdout q-space error |
| `test/local/rmse_q/h5`, `test/graph/rmse_q/h5` | Final evaluation; step 0 | Holdout q-space RMSE |
| `test/<comparator_id>/mae_q/h5` | Final evaluation; step 0 | Metric của comparator đã freeze; `<comparator_id>` có allowlist và không trùng head IDs |
| `test/coverage/valid_targets`, `test/coverage/valid_fraction` | Final evaluation; step 0 | Denominator và coverage để kiểm chứng metrics |
| `system/duration_seconds`, `system/peak_memory_bytes` | Từng execution run | Wall time và memory; unavailable phải có lý do |
| `export/parity_max_abs_error`, `export/duration_seconds` | Final/export report | Chỉ log khi đã thực sự chạy export/parity |

**[Confidence: Medium — quyết định thiết kế]** Bảng per-node, per-time-slice, per-comparator và confidence intervals lưu artifact Parquet/JSON; không tạo hàng nghìn metric keys theo timestamp/node.
Các metrics pricing/GMV/booking/ETA chỉ xuất hiện khi có evaluator downstream và dữ liệu/engine thực sự hỗ trợ; forecasting accuracy không tự chứng minh business uplift.
Chỉ log metric numeric hữu hạn. NaN/Inf, zero valid denominator hoặc thiếu outcome MUST ghi `null` cùng reason trong artifact table; không log chúng như scalar, không chuyển thành 0 để báo thành công.
Metric summary MUST ghi unit, reduction, weighting, valid count, horizon, label contract và prediction-space rõ ràng.
Trial epoch metrics cần step nhất quán; không trộn optimizer step với epoch trên cùng metric key.

## 7. Artifacts bắt buộc

Artifact paths dưới đây tương đối với run; filenames là contract để reporting và verification tìm được chính xác.

| Artifact | Parent/child | Nội dung |
|---|---|---|
| `config/resolved_config.yaml` | Study + trial | Config sau merge và defaults; không chứa secrets |
| `provenance/source_manifest.json` | Study | Dataset nguồn, metadata/code identity và checksum scope |
| `provenance/source_parquet_manifest.json` | Study V1.2 | Consumed public raw/features/burn_in Parquet inventory, byte hashes, schemas/rows và semantic digest |
| `provenance/derived_manifest.json` | Study | Derivative target/window lineage và checksums |
| `provenance/split_manifest.json` | Study | Time boundaries, indices hashes, purge/masks và timezone |
| `provenance/environment.json` | Mỗi execution run | Runtime versions, device, lock hashes và reproducibility options |
| `contracts/feature_schema.json` | Study + bundle | Node feature order và dimensions |
| `contracts/graph_schema.json` | Study + bundle | Node mapping, edge direction/order và raw10/internal12 semantics |
| `contracts/target_contract.json` | Study + bundle | Canonical target/inverse transforms, valid mask và H5 |
| `inventory/trials.parquet` | Study | Tất cả trials, kể cả failed/pruned/cancelled và run links |
| `selection/selected_model.json` | Study | Frozen selection receipt |
| `evaluation/comparator_manifest.json` | Study + final eval | Frozen comparator identities/configs |
| `evaluation/metrics.json` | Final eval | Aggregate metrics với definitions/denominators |
| `evaluation/predictions.parquet` | Final eval | Join keys, labels, valid masks, local/graph outputs và comparator outputs |
| `evaluation/gates.json` | Final eval | Từng gate, observed value, rule, pass/fail và reason |
| `checkpoints/checkpoint_manifest.json` | Trial | Best/latest checkpoint URI, hash, step và resume compatibility |
| `reports/study_summary.md` | Study | Summary có dẫn run/artifact IDs và limitations |
| `reports/analysis_inventory.json` | Study | Optional analyses với status và failure reasons |

Checkpoint retention và bundle filenames được mô tả tại [06_artifacts_and_serving.md](06_artifacts_and_serving.md); trial không cần upload checkpoint lớn sau mỗi batch.
Full source dataset không MUST được copy vào MLflow; nguồn bất biến có URI, checksums và retention bảo đảm được ưu tiên.
Model export `.pt2` là tùy chọn sau gate; checkpoint `state_dict` cho resume luôn là contract riêng, không bị thay bằng exported program.
**[Confidence: High — tài liệu chính thức]** MLflow có native `.pt2` serialization, nhưng graph nhiều input, mixed dtype và dynamic dimensions cần kiểm chứng flavor/serving compatibility [R7, R8].
Bundle MUST giữ input thật `x[B,12,61,29]`, local/graph H5 outputs và edge contract, không thay bằng ví dụ generic `x[N,F]`.

## 8. Failure, tracking outage và resume

| Trường hợp | Hành vi bắt buộc |
|---|---|
| Preflight tracking thất bại | Dừng trước training; lưu local preflight receipt; không báo canonical study đã được tạo |
| Critical artifact/metric upload lỗi tạm thời | Retry hữu hạn với backoff; giữ local journal và artifact nguyên vẹn |
| Tracking outage giữa train | Checkpoint tại epoch boundary; giữ `tracking_sync=PENDING`, journal reason `tracking_blocked`; không bắt đầu trial mới |
| Retry budget cạn | Dừng có kiểm soát; giữ resume inputs; parent không được coi là thành công |
| Train exception/NaN/OOM | Trial `FAILED`, lưu error category/checkpoint; HPO tiếp tục hay dừng theo policy đã freeze |
| User cancel | Checkpoint nếu an toàn; MLflow `KILLED`, tag `execution_status=CANCELLED` |
| Process chết không cleanup | Reconciler phát hiện heartbeat hết hạn; không tự coi MLflow `RUNNING` là process đang sống |
| Optional analysis thất bại | Analysis child `FAILED`; parent vẫn có thể thành công với analysis warning inventory |

Execution taxonomy canonical: `CREATED`, `PREFLIGHT`, `VALIDATING`, `DERIVING`, `TRAINING`, `EVALUATING`, `PACKAGING` map sang MLflow `RUNNING` khi run đã tồn tại.
`SUCCEEDED`/`SUCCEEDED_WITH_WARNINGS` map `FINISHED`; `FAILED` map `FAILED`; `CANCELLED` map `KILLED`; `INTERRUPTED` do reconciler xác minh map `FAILED`.
`tracking_sync=PENDING|COMPLETE|FAILED`, `quality_status=UNASSESSED|PASSED|FAILED`, `export_status=NOT_REQUESTED|PASSED|FAILED` là các chiều riêng, không tạo MLflow status enum mới.
`tracking_blocked` là reason, không thêm execution status; `trial_status=pruned` map `KILLED` và có `prune_reason` để phân biệt user cancellation.
Nếu server đang down, trạng thái trên MLflow có thể tạm stale; journal ghi `tracking_sync=PENDING` và reconciler cập nhật sau khi reconnect.
Resume MUST kiểm tra code/config/data/split/feature/target hashes và checkpoint checksum trước khi load.
Resume từ cùng training trajectory cần model, optimizer, scheduler, AMP nếu dùng, RNG và sampler progress theo checkpoint contract.
**[Confidence: High — tài liệu chính thức]** `mlflow.start_run(run_id=...)` chỉ resume logging; checkpoint để train tiếp cần trạng thái huấn luyện của PyTorch [R6, R9].
Resume tại epoch boundary tạo child run attempt mới với `resume_from_run_id`, giữ nguyên source paths/hashes; không append step 0 vào run cũ hoặc sửa params bất biến để che việc thay cấu hình.
Canonical attempt chỉ mark success sau khi critical artifacts được download/verify và async logging đã flush/acknowledge.
Journal deduplicate bằng `(attempt_id, event_id)`; không hứa MLflow tự cung cấp exactly-once delivery cho mọi logging request.

## 9. Research registry và model version

Registered model baseline: **`surge-forecast-v12-research`**. Mọi version có `dataset_kind=synthetic` và `deployment_scope=research`.
Aliases được phép: `candidate`, `champion`, `previous`; tất cả chỉ có ý nghĩa trong research registry entry này.
Future production entry phải là tên/model namespace riêng và có evidence gates riêng; synthetic-only results không tự cấp production eligibility.

**[Confidence: High — tài liệu chính thức]** Dùng aliases/tags và URI numeric version; không dùng legacy Model Stages hoặc `transition_model_version_stage()` [R10].
`mlflow.<flavor>.log_model(...)` tạo logged model; registered model version chỉ được tạo từ complete bundle đã qua required checks.
Lưu cả `logged_model_id` khi SDK trả về, `model_uri`, `source_run_id`, `registered_model_name` và numeric `registered_model_version`; chúng không phải cùng một ID.
Registry version tags MUST gồm target/model contracts, hashes của bundle/data/split/code/config, final evaluation run ID và gate report hash.
Version số cố định là identity của release; alias mutable chỉ là pointer tiện sử dụng, không đủ để tái tạo thí nghiệm.
Serving resolve alias tại startup/rollout, pin numeric version + bundle hash trong process và response metadata; không lookup champion trên mỗi prediction.
Alias thay đổi không bảo đảm process đang chạy tự reload; controlled reload và parity được quy định ở chapter serving.

## 10. Promotion, concurrency và rollback

Promotion là thao tác CLI riêng, tường minh, sau final evaluation; train/evaluate mặc định không thay `champion` hoặc `previous`.
Contract lệnh: `uv run --project pipeline surge-ml registry promote --model-name surge-forecast-v12-research --version <candidate_version> --expected-champion-version <version_or_none> --request-id <uuid> --reason <text>`.
Lệnh rollback dùng cùng expected-version checks và receipt; target là numeric version đã verify, không lấy alias `previous` rồi thay pointer mà không kiểm tra.

| Bước | Điều kiện/hành động |
|---|---|
| 1. Resolve | Đọc candidate numeric version, bundle hashes, dataset scope và final evaluation/gates |
| 2. Validate | Required gates PASS, target/model contracts đúng v1.2, candidate không bị blocked/deleted |
| 3. Lock | Giữ một writer lock theo registered model name trong registry controller |
| 4. Compare | Đọc champion hiện tại dưới lock; phải bằng `expected_champion_version`, hoặc absent đúng như yêu cầu |
| 5. Prepare | Ghi durable receipt `PREPARED` với request ID, actor, old/new numeric versions, hashes và reason |
| 6. Mutate | Gán `previous` về old champion nếu có; gán `champion` về candidate; không sửa candidate bundle |
| 7. Verify | Read back aliases; ghi `APPLIED` chỉ khi pointer và version hash khớp receipt |
| 8. Release | Nhả lock; trả receipt ID và numeric versions đã xác minh |

**[Confidence: Medium — quyết định thiết kế]** MLflow alias setters không được coi là transaction compare-and-swap đa alias. Lock/expected-version/receipt là logic ứng dụng bao quanh API.
Research quality gates MUST dùng đúng comparator contract đã freeze: local head so với independent GRU29 có relative regression tolerance `0.05`; nếu baseline gần 0 (`<1e-8`) dùng absolute tolerance `0.01` theo metric được chỉ định ở chapter evaluation. Đây là pilot thresholds đề xuất, không phải bảo đảm thống kê hay business uplift.
Writer lock SHOULD dùng PostgreSQL advisory lock hoặc transaction lock trong application schema riêng; không thêm bảng/sửa schema nội bộ của MLflow.
Mọi canonical promotion MUST đi qua cùng controller/lock; nếu người dùng hoặc client khác đổi alias qua UI/API trực tiếp, không còn bảo đảm serialize của controller.
Request ID được deduplicate qua receipts; request lặp có cùng nội dung trả receipt cũ, cùng ID nhưng nội dung khác phải bị từ chối.
Crash giữa cập nhật `previous` và `champion` tạo `RECONCILE_REQUIRED`; controller kiểm tra state thực tế trước khi retry/khôi phục, không tuyên bố atomic success.
Không tự rollback dựa trên một exception mạng khi chưa biết server đã áp dụng alias update hay chưa.
Receipt MUST chứa actor, timestamp UTC, reason, old/new versions, expected version, evaluation report hash và final status; không dùng mutable tags làm audit trail duy nhất.

## 11. Acceptance criteria

- **MLF-01:** Thiếu URI, sai client/server version hoặc tracking preflight lỗi làm canonical run dừng rõ ràng; không có silent local store.
- **MLF-02:** Study→trial/final-eval/analysis hierarchy đúng; inventory gồm cả success, failure, prune và cancel.
- **MLF-03:** Mỗi trial truy ngược được source/derivative/split/code/config/target hashes và model input contract thực tế.
- **MLF-04:** Trial không chứa test metrics; chỉ một selected model đã freeze và frozen comparators được dùng cho logical final evaluation.
- **MLF-05:** Metric values, units, denominators và masks khớp metric artifacts; NaN/missing không bị biến thành 0.
- **MLF-06:** Failure injection tracking outage tạo checkpoint/journal và trạng thái blocked; reconnect/reconcile không báo success giả.
- **MLF-07:** Resume giữ provenance, attempt lineage và training state; MLflow logging resume không được dùng thay checkpoint restore.
- **MLF-08:** Đọc/download artifacts từ client hoạt động qua proxy; recreate server không mất run, registry version hoặc bundle.
- **MLF-09:** `.pt2` tùy chọn phải qua graph multi-input/dtype/shape/device parity trước khi được ghi export passed.
- **MLF-10:** Registration tạo numeric version và đầy đủ bundle lineage; aliases chỉ thuộc research entry.
- **MLF-11:** Hai promotion cùng expected champion không thể cùng được controller chấp nhận như hai cập nhật tuần tự hợp lệ.
- **MLF-12:** Crash giữa alias writes được nhận diện/reconcile; rollback có expected-version check và receipt.
- **MLF-13:** Không có flow tự chuyển synthetic-only model sang production; optional analyses không thay model selection.
- **MLF-14:** Reports phân biệt forecasting metrics, simulation evidence và actual business outcomes; không ghi uplift chưa đo.

## 12. Tài liệu chính thức và giới hạn xác minh

Ngày đối chiếu: 2026-10-09. Các trang `latest` có thể thay đổi; acceptance MUST chạy trên dependency pins thực tế.
Versioned API docs/source tag 3.16.1 chưa được fetch trong lượt đối chiếu này; không coi mọi chi tiết của `latest` đã được smoke-test trên 3.16.1.

- **[R1]** [MLflow 3.16.1 release](https://github.com/mlflow/mlflow/releases/tag/v3.16.1): release tồn tại, security-related default credential change.
- **[R2]** [MLflow 3.17.0 release](https://github.com/mlflow/mlflow/releases/tag/v3.17.0): chứng minh 3.16.1 là pin, không phải latest tại ngày đối chiếu.
- **[R3]** [Tracking server](https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/): tracking URI, `/version`, artifact proxy, persisted experiment artifact location.
- **[R4]** [Environment variables](https://mlflow.org/docs/latest/api_reference/python_api/mlflow.environment_variables.html): các tên cấu hình chính thức.
- **[R5]** [MLflow Dataset API](https://mlflow.org/docs/latest/api_reference/python_api/mlflow.data.html): dataset metadata, digest, source và input logging.
- **[R6]** [MLflow Python API](https://mlflow.org/docs/latest/api_reference/python_api/mlflow.html): nested runs, run resume, step metrics, thread-local behavior và async flush.
- **[R7]** [PyTorch model flavor](https://mlflow.org/docs/latest/api_reference/python_api/mlflow.pytorch.html): signature, serialization format và input example.
- **[R8]** [MLflow PyTorch implementation](https://mlflow.org/docs/latest/api_reference/_modules/mlflow/pytorch.html): dynamic dimension/export và pyfunc compatibility cần đối chiếu exact pin.
- **[R9]** [PyTorch saving/loading models](https://docs.pytorch.org/tutorials/beginner/saving_loading_models.html): state_dict, optimizer checkpoint và exported program.
- **[R10]** [Registry workflows](https://mlflow.org/docs/latest/ml/model-registry/workflow/): aliases, numeric versions, tags và deprecated stages.
- **[R11]** [Backend stores](https://mlflow.org/docs/latest/self-hosting/architecture/backend-store/): database migration, backup và deletion/garbage collection.
- **[R12]** [MLflow pickle-free model formats](https://mlflow.org/docs/latest/ml/tracking/pickle-free-models/): `.pt2` device/version limitations; xem tiếp packaging contract.

### Cross-document lifecycle contract

Study status WAITING_SELECTION/WAITING_FINALIZE và worker attempt status là hai namespace riêng theo [10_benchmark_and_study_contract.md](10_benchmark_and_study_contract.md). Parent không có worker heartbeat; stale180s chỉ áp active execution attempts. study_id có thể là slug hcm-v12-pilot-001. Experiment name authoritative lấy tracking.experiment_name trong resolvedconfig; env MLFLOW_EXPERIMENT_NAME nếu khác phải reject xung đột hoặc bỏ qua có warning explicit, không silently đổi experiment.

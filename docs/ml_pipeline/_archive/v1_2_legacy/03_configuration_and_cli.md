# 03. Configuration, CLI và quản lý execution

## 1. Hợp đồng config

Config tham chiếu: [V1.2](examples/train_v12.yaml), [legacy replay](examples/train_legacy.yaml). Cấu trúc máy: [train_config.schema.json](schemas/train_config.schema.json). Implementation MUST dùng Pydantic strict validation với `extra='forbid'` hoặc tương đương, rồi kiểm tra cross-field rules. Không dựa vào type annotation đơn thuần.

**[Confidence: Medium — API ứng dụng được đề xuất.]** CLI mới có entrypoint `surge-ml` trong package `pipeline/src/surge_ml`. Một command nhận cùng schema, không có tập default riêng trong notebook/train/export/serve.

Thứ tự resolution: defaults được version trong schema → YAML → explicit CLI overrides được allowlist. Environment chỉ dùng cho hạ tầng/secrets/device visibility, không tự override hyperparameters. Lưu cả YAML gốc, `resolved_config.yaml` đã redact và `config_sha256`. Hash từ JSON canonical UTF-8, sort keys, no NaN, không gồm timestamp/run ID, output location hay secret; các field ảnh hưởng dữ liệu/model MUST nằm trong identity hash. Lưu `execution_config_sha256` riêng cho toàn bộ config nonsecret, gồm output/runtime lựa chọn.

Path trong YAML resolve từ **repo root đã nhận diện**, không từ CWD hoặc thư mục chứa YAML. Command chạy ngoài repo phải có `--project-root`. Path output phải khác source; source data read-only; thư mục run mới dùng create-exclusive. Explicit path có ưu tiên cao hơn CURRENT; resolver cảnh báo nếu pointer hoặc manifest path metadata stale và dùng expected identity để xác minh path explicit. Phải kiểm riêng CURRENT.path và CURRENT.manifest; root hợp lệ không chứng minh manifest reference còn tồn tại sau khi dữ liệu đổi layout.

## 2. Config groups và invariants

| Group | Trường chính | Cross-field MUST |
|---|---|---|
| `experiment` | name, study_id, description, seed | study_id gắn split/selection plan trước tuning |
| `data` | source_root, expected_source_id/fingerprint, verify_checksums, derived_root | expected fingerprint đủ 64 hex; source/derived khác nhau |
| `features` | contract_id, node_profile, selected_indices | V1.2 mặc định exactly0..28; all40 là baseline contract riêng |
| `target` | contract_id, window_steps, horizon_minutes, epsilon, zero_supply_policy | V1.2 W12/H5, epsilon=null, strictly positive supply |
| `split` | days, purge_minutes, history_policy | Train21/val4/test5; không overlap; step5 chia hết purge |
| `graph` | contract_id, raw_edge_dim, internal_edge_dim, add_reverse, self_loop_policy | Raw10/internal12; no automatic PyG self loops |
| `model` | model_id, backend, hidden/heads/layers/dropout, output_domain | Model ID/feature/target/output version tương thích |
| `loss` | smooth_l1_beta, lambda_local, lambda_spatial | beta>0; local>0 cho full bundle; spatial=0 trong spec này |
| `train` | device, batch sizes, epochs, lr, clipping, patience, precision, seed | CUDA unavailable là lỗi khi explicitcuda; batch>0; AMP opt-in |
| `evaluation` | primary_metric, baselines, gates, pairwise settings | H5 raw q metric; no trial test; full prediction coverage |
| `tracking` | enabled, uri_env, experiment_name, required, retries | Full run MUST enabled+required; canonical URI env |
| `artifacts` | runs_root, save_last, save_best, eager_bundle, pt2 | Last/best/eager bắt buộc; pt2 gate riêng |
| `analysis` | enabled plugin list, timeout, sample limit | Optional dependencies lazy; không fit feature discovery vào test |
| `registry` | registered_model, auto_register, allow_production | Mock profile allow_production=false |
| `runtime` | workers, threads, deterministic, max_concurrent_trials | Default one trial; device/thread budget logged |

Scalars số MUST finite; validators không cho NaN/Inf, bool thay int, typo key hoặc silent coercion của string `"false"`. Override CLI được giới hạn: epochs, device, seed, run label, dry-run, smoke và output path; override cấu trúc feature/target phải đưa YAML mới để có diff reviewable.

Không hard-code 61 vào model implementation. Profile dataset này có expected_node_count=61; model contract bind N ở bundle. Tensor input public đặt tên `x`; implementation có thể gọi local view `x_local`. H5 output local/graph shape `[B,N,1]` trong core, inference tensor wrapper ở 06 concat thành `[B,N,2]` theo thứ tự đã khai báo.

## 3. Default pilot và phần không được suy diễn

Config dùng hidden64, 4 heads, 2 GAT layers, head32, dropout0.1, batch8, lr3e-4, AdamW, 50 epochs, patience10, beta1 và local loss weight1. Đây là **[Confidence: Medium — engineering starting point]**, không phải kết quả tuning. CPU, FP32, single-worker là đường chạy đầu tiên dễ tái lập. CUDA chỉ bật khi environment doctor và smoke tương thích.

Primary checkpoint metric: `val/graph/mae_q/h5`, minimize. Candidate quality cần report so với tất cả comparator; khi xét local quality, tolerance pilot relative0.05 so với independent GRU29, absolute0.01 khi MAE baseline<1e-8. Các tolerance này phải freeze trước holdout và không có ý nghĩa bảo đảm kinh tế.

Legacy training arrays không hợp domain target mới vẫn có thể có training_ready cho legacy. `max_invalid_target_fraction=null` nghĩa là chưa có ngưỡng target-coverage phục vụ production được xác nhận; full research run được thực hiện nếu có nhãn hợp lệ và báo coverage. `prediction_valid_fraction_min=1.0` khác hẳn: model MUST trả prediction hợp lệ cho toàn bộ data-eligible population.

### 3.1. Reader nguồn và pin dữ liệu

V1.2 MUST dùng `data.source_format=hcm_v2_parquet`, `parquet_inventory_policy=raw_features_burn_in_v1`, `derivative_storage=mmap_npy`. `prepare` đọc projected Parquet `features/` + public `raw/`/`burn_in/` theo02, tạo inventory và finalized derivative trước training. `expected_source_fingerprint` vẫn là fingerprint13 file legacy training đã ghi, không thay hash Parquet. `expected_source_parquet_sha256=null` chỉ cho phép first prepare ghi nhận digest chưa biết; nếu được cung cấp, mismatch phải fail. `train` luôn bind digest trong finalized derivative receipt và xác minh consistency, không dùng null như cho phép thay source/resume tùy ý. Expected hashes là validation constraints, không tạo khác biệt semantic derivation chỉ vì đổi null sang digest bằng nhau.

Paths `data.manifest_path`, `feature_contract_path`, `source_schema_path` resolve từ `data.source_root`; mặc định lần lượt `meta/manifest.json`, `meta/feature_contract.json`, `schema.yaml`. `source_layout_id=hcm_v2_parquet_tree_v1` khóa mapping raw/features/burn_in/oracle; không suy đoán filename cũ. `source_schema_sha256` phải được resolve vào derivative/MLflow/effective trial cùng inventory digest. `legacy_archive_root` resolve từ repo root và bằng null cho V1.2.

Profile `legacy_replay` dùng `source_format=legacy_training_npy`, `parquet_inventory_policy=not_applicable`, `derivative_storage=legacy_readonly`, cùng `expected_source_parquet_sha256=null`. Replay adapter dùng active meta contract để kiểm identity và `legacy_archive_root=data/_archive/hcm_data_2_v2_packed` để đọc training/targets riêng. Các basename trong training_sha256.json resolve dưới archive_root/training/. Không gọi `pipeline/train_v2.py` đã bị gỡ hoặc giả định PreparedDataset cũ hiểu layout đã đổi.

## 4. Biến môi trường

| Biến | Ai đọc | Ý nghĩa |
|---|---|---|
| `MLFLOW_TRACKING_URI` | Training/management client | Tracking service URL |
| `MLFLOW_TRACKING_USERNAME`, `MLFLOW_TRACKING_PASSWORD` | Client khi auth được bật | Secrets; không log giá trị |
| `MLFLOW_TRACKING_TOKEN` | Client nếu gateway hỗ trợ token | Chỉ dùng cơ chế auth thực sự được triển khai |
| `MLFLOW_S3_ENDPOINT_URL` | Artifact storage adapter | Endpoint object store, không thay tracking URI |
| `CUDA_VISIBLE_DEVICES` | Torch runtime | GPU visibility; log device identity đã chọn |
| `OMP_NUM_THREADS` | Numeric runtime | Giới hạn CPU; không đặt vô hạn mặc định |
| `SURGE_RUNS_ROOT` | Runner | Output root override hạ tầng đã ghi vào execution config |

`MLFLOW_ENDPOINT` trong ảnh được chuẩn hóa sang `MLFLOW_TRACKING_URI`; tên alias cũ nếu hỗ trợ phải warn và reject khi hai giá trị xung đột. Không log toàn bộ environment, connection URI có password, raw access token hoặc URL ký truy cập storage. [MLflow environment reference](https://mlflow.org/docs/latest/api_reference/python_api/mlflow.environment_variables.html).

## 5. CLI cần triển khai

Các ví dụ dưới đây là **contract CLI tương lai**. Chúng chưa chạy được cho tới khi các mốc trong 08 hoàn tất. Chạy từ repo root.

```powershell
uv run --project pipeline surge-ml doctor --config pipeline/configs/train_v12.yaml
uv run --project pipeline surge-ml validate-data --config pipeline/configs/train_v12.yaml
uv run --project pipeline surge-ml prepare --config pipeline/configs/train_v12.yaml
uv run --project pipeline surge-ml train --config pipeline/configs/train_v12.yaml --smoke
uv run --project pipeline surge-ml train --config pipeline/configs/train_v12.yaml
```

| Command | Hành vi / output |
|---|---|
| `doctor` | Python/Torch/PyG/CUDA versions, imports, free disk, tracking/version/artifact probe; không train |
| `validate-data` | Read-only resolver/hash/schema/mask report; exit nonzero nếu invalid |
| `prepare` | Tạo derivative theo content identity; finalized cache tương thích được reuse |
| `train` | Verify prepared derivative → train+validation → core bundle; trainer/HPO không nhận test labels |
| `benchmark` | Train/val suite với baseline/config/seed list frozen; tạo leaderboard |
| `select --study-id ...` | Tạo immutable selection receipt từ val và comparator set |
| `finalize --selection ...` | Đánh giá candidate + frozen comparators trên holdout một lần theo eval key |
| `analyze --run-id ...` | Chạy optional plugins trong môi trường riêng; status từng plugin |
| `predict-batch --bundle ... --input ... --output ...` | Load/verify bundle, validate tensors/mapping, write named H5 forecasts + provenance |
| `export --run-id ... --format eager\|pt2 --device cpu` | Package/reload/parity; lưu version/digest và export status |
| `resume --run-id ...` | Tạo attempt mới từ checkpoint last compatible; giữ lineage |
| `cancel --run-id ...` | Gửi cooperative cancellation tới worker đang sở hữu run |
| `runs list/show/compare` | Query/search execution và MLflow fields; `--json` cho automation |
| `reconcile --run-id ...` | Xử lý interrupted worker / pending tracking, không train lại tự động |
| `registry register --run-id ...` | Kiểm gates và register research version; không đổi champion |
| `registry promote --model-name ... --version ... --expected-champion-version ... --reason ...` | Ghi receipt, compare expected version và đổi alias có khóa |
| `registry rollback --model-name ... --version ... --expected-champion-version ... --reason ...` | Chọn bản trước tương thích và ghi receipt mới |
| `dataset publish-pointer --manifest ... --expected-current-hash ...` | Thao tác migration explicit sau validation; training không gọi ngầm |

Output text ngắn gồm pipeline_run_id, attempt_id, status, stage, run folder, MLflow URL, next actionable command. `--json` trả schema ổn định, không nhét log epoch vào cùng stdout JSON; logs đi stderr/file.

`--dry-run` chỉ resolve config và stage plan, không tạo derived dataset, model version hoặc sửa pointer. `--smoke` đánh dấu experiment/run `smoke_only=true`, tối đa 2 epochs và deterministic train/val subsets; không đọc test và không được chọn champion. Config đã resolve phải phản ánh các thay đổi do smoke, không log số epoch gốc rồi chạy số khác.

## 6. Ví dụ lifecycle quản lý

```powershell
uv run --project pipeline surge-ml benchmark --config pipeline/configs/train_v12.yaml
uv run --project pipeline surge-ml runs list --study-id hcm-v12-pilot-001
uv run --project pipeline surge-ml runs compare --study-id hcm-v12-pilot-001 --split val
uv run --project pipeline surge-ml select --study-id hcm-v12-pilot-001
uv run --project pipeline surge-ml finalize --selection SELECTION_RECEIPT_PATH
uv run --project pipeline surge-ml registry register --run-id SELECTED_RUN_ID
```

`SELECTION_RECEIPT_PATH` là path/URI `selection/selected_model.json` do select command trả về, không dựng path từ study name. `SELECTED_RUN_ID` là placeholder do selection output trả về. Đăng ký model không đồng nghĩa chọn nó làm champion. UI MLflow đọc metrics/params/artifacts; mutations quan trọng đi qua CLI quản lý để giữ quality gates và receipts. Phân quyền team phải hạn chế bypass qua UI/API nếu các gate cần được enforce.

## 7. Exit codes và lỗi ổn định

| Exit | Error family | Ví dụ | Hành động |
|---:|---|---|---|
| 0 | Successful command | Core complete hoặc optional warnings đã ghi | Đọc quality/export status riêng |
| 2 | `CONFIG_INVALID` | Unknown key, target/model mismatch | Sửa config; không retry train |
| 3 | `DATA_INVALID` | Hash mismatch, stale path không explicit override | Resolve/verify đúng dataset |
| 4 | `ENVIRONMENT_INVALID` | CUDA requested nhưng thiếu, binary import fail | Sửa lock/device profile |
| 5 | `TRAINING_FAILED` | Nonfinite loss, empty epoch, no best checkpoint | Đọc batch/gradient diagnostics |
| 6 | `TRACKING_INCOMPLETE` | Required artifacts chưa upload | Reconcile/retry network; không register |
| 7 | `EVALUATION_GATE_FAILED` | Quality gate thiếu comparator/coverage | Lưu report; không promote |
| 8 | `ARTIFACT_INVALID` | Bundle hash/reload/export failure bắt buộc | Rebuild/verify; không deploy |
| 9 | `CONCURRENT_MODIFICATION` | RequestID conflict, champion đổi | Refresh state trước thao tác mới |
| 130 | `CANCELLED` | Người vận hành dừng | Resume từ epoch durable nếu cần |

Command train thành công có quality UNASSESSED được exit0; command `registry register/promote` gặp quality gate fail dùng exit7. Không trả exit0 chỉ vì đã viết `verification.json` dù train exception bị bắt.

## 8. Validation contract phải test

Config strict schema là gate đầu; tiếp theo validate days/purge/window, selected feature order, graph dimension, model IDs, expected fingerprint, metric/head/horizon, run path containment và authority của registry namespace. Sai được phát hiện **trước** tải toàn bộ edge tensor/GPU model. Ví dụ source-root đúng nhưng source fingerprint khác phải fail; không tự update expected hash cho qua.

## 9. Prepare/holdout boundary và benchmark plan

`prepare` là trusted deterministic data stage, có thể dựng/seal labels của mọi split để xác minh hashes và masks. `train` cần derivative đã finalized; nếu thiếu, trả `PREPARE_REQUIRED` (exit3) cùng command prepare, không âm thầm materialize holdout trong trainer process. TrainValViews chỉ cung cấp train/val; test data được cấp cho frozen final-evaluation worker. Hash/read-only integrity inspection không phải sử dụng test labels để tuning.

Benchmark nhận `--plan contracts/benchmark_plan.json` bên cạnh base config; default plan được version và trả trong resolved execution output. Sáu mandatory variants phải có đúngmột enabled instance; unknown/duplicate variant hoặc thiếu comparator fail trước train. Effective trial/schema và aggregate study lifecycle theo [10](10_benchmark_and_study_contract.md). Kiểm thêm `gru_hidden % gat_heads == 0` cho graph model và `stale_seconds > heartbeat_seconds`.

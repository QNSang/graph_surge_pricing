# Machine-readable contracts

V1.2 source reader là `hcm_v2_parquet`; default prepare inventory public raw/features/burn_in Parquet và tạo derivative mmap. `expected_source_fingerprint` có scope13 file legacy training; `source_parquet_sha256` là digest riêng bắt buộc trong effective trial/model metadata. Expected Parquet hash trong YAML có thể null trước first prepare; finalized derivative receipt phải bind digest thật trước train. Public controller/API dùng `ds_*`; các metric `mae_q` vẫn đo cùng `DS=D/S_eff` theo mapping00/04/06.

Các schema dùng JSON Schema Draft7; implementation SHOULD validate bằng JSON Schema và Pydantic strict models/cross-field validators. Schema không chứng minh checksum, point-in-time correctness, gradient hoặc export support; những gate đó nằm trong02/04/06/08.

| File | Phạm vi |
|---|---|
| [train_config.schema.json](train_config.schema.json) | Hai profile strict: V1.2 primary và legacy replay; unknown keys bị chặn |
| [model_metadata.schema.json](model_metadata.schema.json) | Metadata bundle V1.2 research, head order, target inverse và runtime |
| [study_plan.schema.json](study_plan.schema.json) | Suite baselines/ablations và allowlist variants |
| [trial_config.schema.json](trial_config.schema.json) | Effective config theo modelkind, feature29/40, metric và hyperparameters |
| [run_state.schema.json](run_state.schema.json) | Execution/attempt state, hashes, tracking/quality/export states và receipts |

Config V1.2 intentionally khóa semantic identities, W12/H5/selected29/graph policy. Thay hyperparameters trong bounds được phép; thay graph/features/targets là config/contract version mới, không edit một const để giả cùngversion. Baseline factory của benchmark lấy cùngdata/split và tạo view29/40 có contract riêng theo04; main YAML không biến input dimension tùy model một cách ngầm.

Cross-field validators bắt buộc: split order/day lengths; divisibility time step; source vs output path; scalar finite; fingerprint/hashes; N×B indices; sharedE; metric/head/horizon; heartbeat<stale; max_attempts với schedule retry; required quality and export evidence. `max_invalid_target_fraction=null` nghĩa là chưa có target-coverage gate business được calibration, không cho phép invalid prediction trên eligible labels.

`bundle_sha256` lưu ở bundle manifest/registry receipt hoặc envelope ngoài bundle; không đưa digest tự tham chiếu vào một file mà chính digest đang hash. `derived_fingerprint` chỉ xuất hiện sau khi output checksum map finalize; path/created_at không quyết định identity semantic payload.

Các schemas mô tả artifacts sẽ được tạo bởi implementation. Không có model_metadata/run_state mẫu với số metric giả trong specs này.

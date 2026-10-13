# 07. Môi trường, hạ tầng và vận hành

## 1. Tách môi trường theo nhiệm vụ

| Environment | Package cần thiết | Không phải dependency bắt buộc |
|---|---|---|
| `research` | Notebook, pandas, plotting, analysis plugins được chọn | Không đưa tất cả vào serving image |
| `training-cpu` / `training-cuda` | Torch, PyG, NumPy, PyArrow, Pydantic, MLflow client; LightGBM cho baseline | SHAP/AutoGluon/tsfresh/Quarto không được import ở bootstrap |
| `serving-cpu` / `serving-cuda` | Forecast/preprocess package, Torch/PyG eager hoặc runtime export đã kiểm, contract validator | Dataset builder, optimizer tools, notebooks và report generators |
| `tracking-server` | MLflow3.16.1, SQL backend driver nếu dùng PostgreSQL | Không cần GPU, model training dependencies |

**[Confidence: Medium — phân chia engineering.]** Các con số ~300/~100/~20 packages trong ảnh là minh họa, không là target package count. Tiêu chí là dependencies thực sự cần, startup/import tests và reproducibility.

Implementation MUST có lock/version report theo environment. Source dataset manifest ghi package versions của lần sinh; không copy chúng thành yêu cầu installed hiện tại. Python minor, Torch/PyG/CUDA/cuDNN, GPU compute capability, driver và optional native extensions đều được doctor ghi vào artifact. PyG wheels/extensions cần match Torch/CUDA; nếu operator GAT dùng được bản PyG không extensions tùy chọn thì không cài thêm theo thói quen. [PyG installation](https://pytorch-geometric.readthedocs.io/en/latest/install/installation.html).

V1 default FP32. `device=cpu` chạy CPU; `device=cuda:0` mà runtime thiếu GPU thì fail trước train. `auto` nếu bổ sung phải log resolved device rõ; không dùng nó cho replay claim deterministic. Không tự giảm batch/precision hoặc đổi device để né lỗi rồi giữ config hash cũ.

Seed Python/NumPy/Torch/DataLoader, deterministic flags và source code phải được lưu; không cam kết bitwise identical giữa Torch versions, CPU/GPU hoặc platforms chỉ vì seed giống nhau. [PyTorch reproducibility](https://docs.pytorch.org/docs/stable/notes/randomness.html).

## 2. MLflow service profiles

### 2.1. Local development

[compose.mlflow.dev.yaml](examples/compose.mlflow.dev.yaml) dùng image pin3.16.1, SQLite file `/mlflow/db/mlflow.db` và artifact proxy `/mlflow/artifacts`, hai named volumes. Host chỉ publish `127.0.0.1:5000`. Một người/một active training trial là default; image version tồn tại theo [official release](https://github.com/mlflow/mlflow/releases/tag/v3.16.1).

Client trên host dùng `MLFLOW_TRACKING_URI=http://127.0.0.1:5000`; client trong cùng Compose network dùng `http://mlflow:5000`. Trong container server nghe0.0.0.0 để bridge nhận được traffic, không suy ra host đã được phép public. [Docker port publishing](https://docs.docker.com/engine/network/port-publishing/).

### 2.2. Team / nhiều máy ghi đồng thời

[compose.mlflow.team.yaml](examples/compose.mlflow.team.yaml) tách PostgreSQL metadata và artifact named volume; custom server [Dockerfile](examples/Dockerfile.mlflow) cài database driver đã pin qua build arg. SQLite development không được mặc định coi là lựa chọn cho logging concurrent từ laptop/GPU/CI. Trước dùng team profile phải khóa exact PostgreSQL image digest và driver version phù hợp đã test; mẫu env có tên biến cần điền, không dùng tag latest.

Team service vẫn bind localhost của server. Máy khác kết nối qua SSH tunnel/VPN gateway có identity hoặc reverse proxy TLS+auth đã được thiết lập. Middleware Host/CORS của MLflow không thay authentication. Không mở unrestricted port hoặc tắt middleware để giải quyết lỗi từ hostname. [MLflow network protection](https://mlflow.org/docs/latest/self-hosting/security/network/).

MLflow3.16.1 không cung cấp mật khẩu Basic Auth admin mặc định như một số ví dụ cũ. Nếu thêm auth, admin bootstrap và credentials có source riêng, không commit password. Team users có quyền trực tiếp alias mutation phải được hạn chế nếu muốn enforce promotion gates qua management worker. [Release3.16.1](https://github.com/mlflow/mlflow/releases/tag/v3.16.1).

### 2.3. Metadata backend khác artifact store

Postgres/SQLite lưu experiments, runs, params, metric history, model registry metadata. Artifact volume/object store lưu weights, plots, JSON/Parquet, code snapshot. Run folders local còn giữ checkpoint/journal đang chạy. Cả database và artifacts cần backup; chỉ một bên không phục hồi đầy đủ một model release.

Default dùng MLflow artifact proxy với `--serve-artifacts` và `--artifacts-destination`; không cấu hình experiment mới bằng local client-specific artifact URI. Client không cần đọc `/mlflow/artifacts` trên host server. Chuyển sang S3/MinIO là profile sau; server giữ storage credentials, clients qua proxy. Existing experiment có artifact location cố định từ lúc tạo; đổi server flag không tự di chuyển data cũ. [Tracking server](https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/).

## 3. Bootstrap checklist của implementation

1. Khóa dependencies/images trong CI cho chosen profile; validate Compose syntax và secret variables.
2. Tạo named volumes và chạy database migrations bằng đúng MLflow version. Khi nâng version, backup trước `mlflow db upgrade`; không downgrade binary sau schema migration mà chưa kiểm compatibility.
3. Start tracking service, `/health` healthy, `/version` đúng3.16.1; test client version/API khi bootstrap.
4. Doctor tạo experiment/run riêng `system-smoke`, log param, finite metric, tiny artifact; download so SHA256; đăng ký test version trong smoke namespace rồi verify lookup.
5. Recreate service/container, read-back cùng run/version/artifact. Không dùng thao tác xóa volumes khi thử persistence.
6. Train CPU smoke hai epochs với source derivative contract thật; rồi mới CUDA smoke và full run.

Các thao tác trên là acceptance work khi code/deploy implementation, chưa được chạy trong lần viết specs.

## 4. GPU, CPU và tài nguyên

Default one trial, CPU threads2, DataLoader workers0 trên Windows. Prepare đọc projected Parquet columns bằng bounded batches/partitions, ghi mmap derivative. Training chỉ đọc derivative finalized qua mmap/pointer slices, không allocate tất cả windows trên GPU. Train/eval batch8 ban đầu; thay theo profile và benchmark nếu cần. Khoảng422.87MiB là payload legacy training arrays để audit; Parquet input, derivative W12/H5, temporary disk, peak RSS và GPU memory thực phải đo riêng (02).

Pilot resource guard: trước stage output phải còn ít nhất max(2GiB, 2×estimated_new_artifact_bytes) trong output volume; đây là engineering floor có config, không dự báo chắc chắn disk consumption. Log peak RSS, GPU allocated/reserved và batch edge count. CUDA OOM ghi checkpoint durable gần nhất, attempted shape/memory và exit4/5 phù hợp; operator đổi config tạo attempt/trial đúng policy, không silently shrink.

Server tracking không chạy training trong web process. GPU server chạy runner; network delay không nằm trong forward. Log theo epoch/batches có tổng hợp, không tạo run cho mỗi graph/edge. Retain prediction tables theo partition/split, không log hàng trăm nghìn values thành parameters MLflow.

## 5. Monitoring

| Nhóm | Signals | Hành vi đề xuất |
|---|---|---|
| Service | Health/version, request failure rate, artifact roundtrip, DB disk/locks | Alert khi required tracking unavailable; dừng promotion |
| Job | Stage, epoch, heartbeat, last checkpoint, attempt runtime | 30s heartbeat; stale180s → reconcile, không kill vô căn cứ |
| Data quality | Missing grid, timestamps gaps, feature age, mask coverage, source hash | Structural errors fail; masked target coverage report riêng |
| Training | Local/graph/total loss, grad norm, LR, valid-label count, val errors | Nonfinite fail; overfit/constant output cảnh báo có bằng chứng |
| Inference | Feature schema/freshness, prediction distribution, valid fraction, latency | Incompatible contract reject; REVIEW reason cho controller |
| Delayed performance | Forecast vs matured observed q_true theo horizon/version | Chỉ join khi label available; matched/missing counts |
| Policy diagnostics | REVIEW rate, requested/applied histogram, caps, sign changes | Báo hành vi; không gắn uplift nếu không có experiment |

Training data validation và serving data freshness là hai điểm kiểm tra khác nhau. Mock hiện không có ingestion delay; production adapter MUST thêm feature event/availability time. Drift reference lấy từ train/validation artifact đã pin; thống kê trên traffic so theo cùng feature/schema. PSI/KS hoặc feature distributions chỉ là drift indicator, không tự kết luận forecast quality giảm hoặc tự retrain/promote.

Pilot SLO đề xuất: heartbeat30s, stale180s, management artifact probe timeout10s, bounded retries3. Đây là ngưỡng vận hành để thử, phải điều chỉnh theo hardware/network đo được. Không claim latency hay accuracy thực nghiệm chưa có.

## 6. Runbooks

| Sự cố | Chẩn đoán | Khôi phục |
|---|---|---|
| CURRENT trỏ file mất | Explicit path/manifest/fingerprint mismatch report | Chỉ định source đúng; publish pointer bằng command explicit sau validation |
| CURRENT.path đúng nhưng CURRENT.manifest hoặc manifest release path cũ | Root data tồn tại nhưng metadata đã chuyển vào meta/ | Verify explicit root+manifest_path+schema; ghi discrepancy, không rewrite nguồn hoặc đoán file khác |
| Hash mismatch | Expected vs actual file digest | Quarantine derivative/run; restore bytes đúng từ immutable source; không update hash để bỏ qua |
| DB/MLflow down trước run | Health/version + tiny artifact probe | Fix service; không bắt đầu canonical trial thiếu tracking |
| Tracking mất giữa epoch | Local journal và checkpoint boundary | Stop sau durable epoch; reconcile idempotent logs, resume attempt mới |
| GPU OOM/binary mismatch | Device/runtime report, batch graph size | Fix lock hoặc create config mới, dùng checkpoint theo compatibility policy |
| Source thiếu labels hợp lệ | Target reason counts, EMPTY_TRAIN_EPOCH | Sửa source/contract bằng version mới; không fill target0 |
| Optional SHAP/Quarto lỗi | Plugin result/status/traceback | Giữ core model, tạo basic report, rerun plugin sau |
| `.pt2` export lỗi | Operator/shape/device/parity report | Eager-only research bundle; change export profile hoặc model version sau |
| Model regression | Frozen val/test comparison và coverage | Không promote; current research champion giữ nguyên |
| Alias đổi đồng thời | Expected-version/lock mismatch | Reject mutation, refresh registry, tạo receipt mới nếu vẫn phù hợp |
| Process crash | Stale heartbeat, filesystem state, worker ownership | Mark INTERRUPTED, resume từ last durable epoch; không rename failed thành finished |

Đây là recovery procedures, không phải script tự tăng quyền hoặc xóa dữ liệu. Retry logic phải phân biệt transient I/O và deterministic contract error.

## 7. Backup, retention, upgrade

**[Confidence: Medium — policy vận hành pilot.]** Backup database và finalized artifacts hằng ngày, giữ7 daily và4 weekly snapshots khi storage cho phép; đây là lịch đề xuất để implementation, chưa tạo automation. Champion/previous/candidate được pin bởi retention reference và không bị garbage collection khi còn dùng. Dataset source đã dùng cho selected model, derivative manifest và code locks cần giữ cùng vòng đời bundle.

Backup PostgreSQL bằng logical dump/snapshot phù hợp, gồm management receipts/catalog nếu nằm database riêng. SQLite dùng backup API hoặc snapshot nhất quán khi writes được quiesce; không copy ngẫu nhiên một file DB đang ghi rồi gọi full backup. Artifact backup phải giữ checksum map, access-control metadata và object versions nếu dùng object store.

Restore drill: phục hồi database/artifacts sang namespace tách biệt; read registry numeric version; download bundle và verify hashes; fresh-process predict input example; không đổi production alias trong drill. Restore được metrics mà không đọc được weights là fail.

Soft-delete run trong MLflow không tự xóa artifacts. Retention job phải tạo dry-run inventory, kiểm registry/dataset references và pending uploads trước delete; không đặt `mlflow gc` như cron mù. [Backend store documentation](https://mlflow.org/docs/latest/self-hosting/architecture/backend-store/).

Upgrade: backup → run test instance trên copy DB → migrate → tracking/registry/artifact checks → compatibility test chosen model → rollout service → readback. Nếu schema đã migrate, rollback bằng backup/version plan đã test; không giả định downgrade image là đủ.

## 8. Quản lý quyền và dữ liệu

Config/metrics/code artifacts không chứa secrets. Log only selected environment metadata; dataset path chỉ là reference cần thiết. Synthetic release không có thông tin thật nhưng schema giữ `dataset_kind` để sau này dữ liệu thật áp dụng access/retention đúng. Shared artifact credentials chỉ trên server khi proxy. Registry management actor được xác thực bởi service/auth layer; một username string do client tự gửi không là bằng chứng identity.

Local dev chưa có user auth là profile single-user localhost; không dùng cấu hình đó để mở service public. Một test Docker syntax pass không phải security/backup acceptance pass.

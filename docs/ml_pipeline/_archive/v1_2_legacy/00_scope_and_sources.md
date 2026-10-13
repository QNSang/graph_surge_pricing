# 00. Phạm vi, bằng chứng và quyết định kiến trúc

## 1. Kết quả cần tạo khi thực thi specs

Một kỹ sư phải có thể chạy một lệnh để kiểm định dataset, tạo dữ liệu dẫn xuất đúng contract, train, xem metrics trong MLflow và lấy bundle tái lập được. Khi lỗi, họ biết stage nào thất bại, checkpoint nào dùng được, resume bằng cấu hình nào. Khi chọn model, họ thấy model được so với baseline nào, trên split nào và với phạm vi bằng chứng nào.

Phạm vi code tương lai gồm data adapter, config, graph batching, hai head dự báo, training/evaluation, MLflow integration, artifact packaging, CLI quản lý và vận hành service. Giao diện quản lý ban đầu là MLflow UI cộng CLI. Không có yêu cầu tự xây một cổng web mới.

Trong công việc lập specs này chỉ tạo tài liệu dưới `docs/ml_pipeline`. Các kết quả smoke/integrity đã có thuộc lần xuất HCM v2; không được báo thành kết quả chạy V1.2 mới.

## 2. Nguồn và độ ưu tiên

| ID | Nguồn trong repo hoặc hội thoại | Phạm vi quyết định |
|---|---|---|
| P1 | [docs/model/technical_report.md](../model/technical_report.md), V1.2 | Thiết kế model, target mong muốn, loss và controller |
| P2 | [metadata packed export](../../data/_archive/hcm_data_2_v2_packed/metadata.md) | Metadata lịch sử đã chuyển vào archive; không quyết định layout active source mới |
| P3 | [meta/manifest.json](../../data/hcm_data_2/meta/manifest.json) | Machine identity, số lượng, readiness và fingerprints đã ghi; path metadata lịch sử cần kiểm tra riêng |
| P4 | [meta/feature_contract.json](../../data/hcm_data_2/meta/feature_contract.json) | Thứ tự feature/hex và semantics của source release; W/horizon của packed export không tự thành contract V1.2 |
| P5 | [feature_v2.py](../../data/hcm_data_2/meta/source_snapshot/mock_data_pipeline/surge_mock/feature_v2.py), [prepared_data.py](../../data/_archive/hcm_data_2_v2_packed/source_snapshot_legacy_pipeline/prepared_data.py) | Snapshot exporter đang giữ trong meta và loader legacy đã archive; phân biệt nguồn Parquet với packed tensors |
| P6 | [model.py](../../data/_archive/hcm_data_2_v2_packed/source_snapshot_legacy_pipeline/model.py), [train_v2.py](../../data/_archive/hcm_data_2_v2_packed/source_snapshot_legacy_pipeline/train_v2.py) | Snapshot implementation legacy; không phải import path của package V1.2 |
| P7 | [pyproject.toml](../../pipeline/pyproject.toml); snapshot `pipeline/config.yaml`, `train.py`, `evaluate.py`, `spec.md` đọc trước khi chúng bị gỡ | Dependency hiện tại và bằng chứng lịch sử; không coi các snapshot đã gỡ là import path có thể chạy |
| P8 | [legacy readiness.json](../../data/_archive/hcm_data_2_v2_packed/reports/readiness.json), [active validation](../../data/hcm_data_2/meta/validation/), [completion report](../../artifacts/mock_v2_completion.json) | Bằng chứng kiểm tra có scope và thời điểm riêng; chưa được chạy lại thành kết quả V1.2 trong lần viết specs |
| P9 | [data/CURRENT.json](../../data/CURRENT.json) | Root path là `data/hcm_data_2`, nhưng manifest field còn trỏ tên root cũ; không kết luận toàn bộ pointer đã hợp lệ |
| P10 | [schema.yaml](../../data/hcm_data_2/schema.yaml) | Physical table paths và column roles của layout mới; không thay ordered feature contract hoặc row/time semantics đã xác minh |
| P11 | [meta/source_sha256.json](../../data/hcm_data_2/meta/source_sha256.json), [generator config](../../data/hcm_data_2/meta/generator_config.yaml) | Inventory/source provenance đi kèm layout mới; implementation phải xác minh scope và hashes của files thực sự tiêu thụ |
| U1 | Ảnh người dùng đính kèm `image(20261008-205940).png` | 20 nguyên tắc ML system, tracking, analysis, environments và quản lý artifacts |

Khi mô tả **dữ liệu hiện có**, machine contract, payload và code exporter là nguồn quyết định; tên thư mục không đổi dataset identity. P10 mô tả physical layout và column roles; thứ tự40 feature phải lấy từ ordered contract P4, không lấy thứ tự các nhóm trong schema. Graph primary key ghi trong schema chưa đủ mô tả typed multirows, và comment ngày của orders khác quy ước right-closed đã xác minh: các discrepancies được ghi ở02; không tự deduplicate graph hoặc đổi bucket/time rule theo một mô tả xung đột. Khi đặc tả **thiết kế đích**, P1 quyết định semantics; phần chưa chốt được bổ sung bằng ADR dưới đây. Ảnh là định hướng hệ thống, không thay schema đã xuất. Quyết định V1.2 hiện tại thay thế các ý tưởng cũ về behavioral ML/MPC trong phạm vi module này.

**[Confidence: High — đọc trực tiếp các file nêu trên.]**

## 3. Hiện trạng phải biết trước khi code

### 3.1. Path hiện tại, identity và checksum scope

Source được tổ chức lại trong lúc đối chiếu. Layout chốt là `source_layout_id=hcm_v2_parquet_tree_v1`, root `data/hcm_data_2`; config V1.2 chỉ định `manifest_path=meta/manifest.json`, `feature_contract_path=meta/feature_contract.json` và `source_schema_path=schema.yaml` tương đối với source root. `source_schema_sha256` là byte hash của schema đã đọc và MUST được giữ trong source-validation/derivation identity.

| Nhánh active source | Vai trò trong V1.2 |
|---|---|
| `meta/` | Manifest, feature contract, generator config, source SHA-256 inventory, exporter snapshots và validation evidence |
| `features/hex_features/`, `features/graph_edges/` | Parquet features và graph observations; nguồn chính cho prepare |
| `raw/hex_snapshot/`, `raw/orders/`, `raw/weather/`, `raw/hexes/` | Các bảng Parquet nguồn được allowlist theo02 |
| `burn_in/orders/`, `burn_in/hex_snapshot/`, `burn_in/weather/` | Context quá khứ trước khoảng30 ngày chính; thay nhánh `context/` cũ, không thành training targets |
| `oracle/` | Ground truth/oracle phục vụ diagnostics riêng; bị cấm làm input, target shortcut hoặc nguồn chọn model trong canonical V1.2 |

Packed export cũ được lưu tại `data/_archive/hcm_data_2_v2_packed/`, gồm `metadata.md`, `training/`, `targets/`, `training_sha256.json`, `reports/` và `source_snapshot_legacy_pipeline/`. V1.2 primary không yêu cầu các training arrays này để prepare. Manifest giữ machine `dataset_id=hcm_mock_v2_30d_seed42`; fingerprint của13 packed training files lịch sử là:

```text
0e1f4e179ca0c0b8263396463135a7990d7673460a336373a12feaf04122cc06
```

Ở snapshot chốt trước khi ghi specs ngày 09/10/2026, `data/CURRENT.json` có root path `data/hcm_data_2` nhưng manifest field vẫn trỏ `dataset_manifest.json` ở root, trong khi file hiện nằm ở `meta/manifest.json`. Trong manifest, `release_relative_path` vẫn ghi `data/releases/hcm_mock_v2_30d_seed42`. Vì vậy root pointer đúng không đủ chứng minh manifest reference hợp lệ. Resolver mặc định dùng explicit source root + meta paths + `source_schema_path=schema.yaml`, xác minh machine identity và ghi các path discrepancies; không tự rewrite CURRENT hoặc source manifest. Chế độ chỉ dùng CURRENT phải báo lỗi nếu manifest reference không resolve, không tự tìm file có tên gần giống.

V1.2 dùng inventory policy `raw_features_burn_in_v1`: đọc Parquet từ các nhánh `features/`, `raw/`, `burn_in/` được allowlist trong02, ghi derivative mmap tại `data/derived/<derived_id>`. Prepare MUST kiểm tra inventory đi kèm và lập byte hashes của tất cả Parquet thực sự tiêu thụ; `source_parquet_sha256`, source layout ID và inventory policy cùng tham gia derivation identity/MLflow lineage. Không gắn fingerprint packed training cho những bytes ngoài scope đó; không tự fallback sang archive hoặc `oracle/` khi thiếu bảng primary.

### 3.2. Source release có thật nhưng chưa phải model V1.2

| Thành phần | Source HCM v2 / snapshot code legacy | Thiết kế đích |
|---|---|---|
| Thời gian | 30 ngày, 8.640 timestamp × 61 hex | Giữ cùng source, split 21/4/5 ngày |
| Input history của packed export | W=4, 40 node features; arrays đã archive | W=12; default29 local/context features dựng từ active Parquet |
| Horizon của packed export | 5, 10, 15 phút | H=5 phút |
| Nhãn packed export | `ln(D+1)-ln(S_eff+1)` | `log1p(D/S_eff)` với denominator hợp lệ, dựng lại từ observed source |
| Đầu ra | Một đường/head, baseline + residual | Hai head local/graph cùng target |
| Model graph | GATv2 custom; reverse+self tự thêm | PyG GATv2 explicit graph contract; default không thêm reverse |
| Chọn checkpoint | PairAcc ở horizon 10 | MAE D/S của graph ở horizon 5 và gates của local |
| Tracking | Thư mục run, CSV/Parquet/checkpoint | MLflow + durable local run state + hashed bundle |
| Device | `train_v2.py` gọi train CPU | Device explicit; CUDA fail rõ khi không khả dụng |
| Registry | Chưa thấy integration trong dependency/entrypoint đã đọc | Registry nghiên cứu và promotion có receipt |

Các file training `.py` legacy đã bị gỡ khỏi active `pipeline/`, hiện còn `pyproject.toml` và `uv.lock`. Những hành vi code trong bảng là bằng chứng lịch sử và các snapshot tại archive P6, không phải code mới có thể gọi ngay. Package V1.2 MUST được viết mới; không đặt adapter dựa trên import của file đã mất hoặc coi archive là default training entrypoint.

Không chuyển nhãn bằng `expm1(old_target)`: `exp(old_target)=(D+1)/(S_eff+1)` khác `D/S_eff`. Muốn tạo target mới phải đọc D và S_eff ở timestamp tương lai từ source features, áp dụng denominator/mask mới và sinh fingerprint mới.

### 3.3. Phạm vi bằng chứng

Manifest giữ `training_ready=true`, `realism_validation_complete=false`, `deployment_ready=false`; readiness của packed export cũ ghi22 raw checks,15 feature checks và smoke cho LightGBM/GAT đã đạt. Những kết quả này có scope lịch sử; việc di chuyển files và giữ nguyên manifest bytes không tự kiểm chứng active layout mới, consumed-source inventory hoặc derivative V1.2. Chúng không chứng minh dual-head V1.2 đã train, GNN thắng baseline, model đã export `.pt2`, hoặc giá đề xuất tăng GMV.

Canonical training/evaluation contract không có quote events, fare/GMV transactions hoặc counterfactual outcomes được phép dùng. Nhánh `oracle/` tồn tại không thay đổi điều này và bị cấm làm training input/shortcut label. Booking rate, pricing regret và uplift kinh doanh không có đủ evidence trong canonical contract để tính. Báo `NOT_AVAILABLE` kèm lý do và missing source, không log0 hoặc dựng nhãn thay thế.

## 4. ADR — các lựa chọn được specs bổ sung

Các lựa chọn ở bảng này có **[Confidence: Medium — engineering decisions, chưa phải kết quả calibration]**. Chúng làm rõ phần còn mở trong P1 để lập trình viên không tự đoán.

| ADR | Quyết định | Vì sao / đánh đổi |
|---|---|---|
| A01 | Viết mới `pipeline/src/surge_ml`; legacy replay riêng dựa trên packed archive | Active pipeline đã được dọn; tách orchestration khỏi logic và lịch sử |
| A02 | Hai profile `v12` và `legacy_replay`; không chung model identity | Đối chiếu kết quả cũ mà không nhầm semantics |
| A03 | Parquet adapter → dataset dẫn xuất bất biến, mmap-ready tại `data/derived/<derived_id>` | Đọc active features/raw/burn_in theo `raw_features_burn_in_v1`; version W, target, masks, scaler và giữ source nguyên vẹn |
| A04 | Encoder default 29 feature đầu, contract `hex29_edge10_v1_2` | Có ranh giới thông tin rõ cho local vs graph; baseline all40 vẫn bắt buộc |
| A05 | `directed_relations_self_v1`: forward typed rows + synthetic self, no reverse mặc định | Tránh kể cạnh đảo như OD thật; reverse là ablation có version |
| A06 | `dual_gru_gatv2_h5_v1_2`, Softplus ở log1p output | Không sinh ratio âm; đổi architecture, phải train mới |
| A07 | Smooth L1 beta=1; local weight=1; spatial weight=0 | Hai head đều được giám sát; không bật loss chưa có công thức |
| A08 | Train selection bằng validation MAE trên q; test chỉ ở finalize | Tránh tuning theo test và chọn metric không cùng target |
| A09 | MLflow 3.16.1 pin theo ảnh; manual logging cho PyTorch loop | API facts được đối chiếu chính thức; không gọi đây là version mới nhất |
| A10 | CLI runner, concurrent trials=1 mặc định; Postgres khi nhiều máy ghi | Vận hành đủ cho dự án trước khi có scheduler phân tán |
| A11 | Eager bundle là đường bắt buộc; `.pt2` là export có gate riêng | N/E động, GRU/PyG và mixed dtype cần kiểm chứng đúng môi trường |
| A12 | Candidate/champion chỉ trong registry nghiên cứu của dữ liệu mock | Không suy ra production eligibility từ synthetic forecast score |
| A13 | Tracking outage mặc định dừng tại epoch boundary sau checkpoint | Không gắn nhãn thành công khi thiếu bằng chứng; tránh mất toàn bộ tiến độ |

Feature local/context29 vẫn chứa ETA và quan sát bị môi trường ảnh hưởng; không khẳng định baseline bị cô lập vật lý hoàn toàn khỏi mạng. Việc cả hai head cùng dự báo target không chứng minh chênh lệch là causal graph effect.

## 5. Yêu cầu chức năng và phi chức năng

| ID | MUST |
|---|---|
| R01 | Resolve explicit source root/meta paths; xác minh inventory `raw_features_burn_in_v1`, consumed Parquet hashes và contracts; packed training hashes chỉ dùng audit/replay |
| R02 | Sinh v12 target/mask/index/norm bằng transform có version và provenance |
| R03 | Validate input/event cutoff, node order, edge pointer, time split, batch isolation |
| R04 | Train hai head với masked loss, seed/device explicit, finite checks và checkpoint |
| R05 | So sánh persistence, local29, all40, LightGBM và graph trên cùng eligible rows |
| R06 | Log train/validation theo epoch; freeze selection trước test |
| R07 | Mỗi execution có run state, attempt ID, config hash, code identity, lineage |
| R08 | Resume đúng source/config/checkpoint; không overwrite run hoặc tự sửa config |
| R09 | Optional analysis lỗi được ghi nhận riêng, không làm mất core bundle |
| R10 | Bundle chứa weights, code, config, feature/graph/target/norm contract, outputs và hashes |
| R11 | Registry promotion/rollback có identity, gates, actor/reason và concurrency control |
| R12 | Persist metadata/artifact storage, backup/restore, health checks và secrets redaction |
| R13 | Không claim metric chưa tính; không promote synthetic lên production |
| R14 | Forecast/controller/serving contract được version riêng và kiểm tra tương thích |

Mục tiêu kỹ thuật pilot: một run CPU smoke hoàn thành end-to-end với data contract thật; GPU training có cùng semantic outputs; lưu/nạp parity FP32 `rtol=1e-5, atol=1e-6` trên cùng device/environment; không đặt thời gian train/latency tuyệt đối chưa benchmark. SLO vận hành đề xuất ghi trong 07 là mục tiêu thiết kế, không phải kết quả quan sát.

## 6. Điều kiện còn cần đo khi implementation

Tỷ lệ `S_eff=0`, mask coverage mới, chi phí training W12, version Torch/PyG/CUDA tương thích, chất lượng local/graph và giới hạn export chưa được đo trong lần lập specs. Đây là gates có hành vi pass/fail cụ thể ở 02/04/06/08; không phải chỗ để triển khai âm thầm bỏ kiểm tra. Controller q_star, gains và global pricing cap thật phải có quyết định nghiệp vụ trước khi áp dụng giá; config minh họa mặc định giữ controller disabled.

## 7. Snapshot nguồn chốt và ký hiệu

Các hash dưới đây là byte hashes đã có bằng chứng trong phiên đối chiếu; manifest được di chuyển vào `meta/` nhưng bytes giữ nguyên. Chúng không là bằng chứng rehash toàn dataset hoặc xác minh mọi path trong CURRENT. Nếu bytes/layout đổi trước implementation, thực hiện source review và ghi decision record thay vì bỏ qua khác biệt.

| File | SHA-256 |
|---|---|
| `docs/model/technical_report.md` | `7cd8bfecd96825710a848a66eeabb730f1328f28c00927bcdf5f7311922212fa` |
| `data/hcm_data_2/meta/manifest.json` | `74cf46f4ca40eaca07b5fb6e36cbe7af6c4e8d81c77cec8312ebe33e54fda09c` |
| `data/hcm_data_2/meta/feature_contract.json` | `272c7505fa7a19217166ba0f690854fc0549df5a9540a7b14bcb00fee196448b` |
| `data/hcm_data_2/schema.yaml` (`source_schema_sha256`) | `b6673dd8290caea3ac76cc22a18b60cf8acf024e2344f785e315002312401995` |
| `data/_archive/hcm_data_2_v2_packed/metadata.md` | `f80ee7b096077162a3332e54f8c62115698a179722a89cfd3d2dd708f7bb01e7` |

Decision record 2026-10-09: `schema.yaml` (trước đó `7128dcb003bd0854c6c30a5073b12945dcbc5ff967aaa3f77ae262ccb5507b62`) và `meta/manifest.json` (trước đó `7bdbb161a5a70075c3c39f5ff4e6d83b3f5df411c3f8aa1e499b46c253ec8ff2`) được sửa khi tổ chức lại thư mục nguồn; owner chấp nhận bytes hiện tại làm snapshot chốt. `dataset_id` và `v2_packed_fingerprint` trong manifest không đổi.

Hash metadata lịch sử ở archive vẫn có giá trị xác minh đúng bytes đã đọc; nó không chứng minh CURRENT hoặc physical layout active hợp lệ. Implementation MUST kiểm tra lại các hashes đã pin, ghi byte hash CURRENT, `meta/source_sha256.json` và consumed-source inventory vào source-validation artifact trước prepare.

P1 mới đổi ký hiệu sang `DS`, `DS_local`, `DS_graph`, `DS_ref`, `Pressure`, `Revision`; không đổi target/loss/controller semantics. Trong contracts nội bộ, `q`, `q_h5`, `mae_q`, `q_star`, `q_min` lần lượt là alias của `DS`, DS target H5, MAE của DS, `DS_ref`, `DS_min`. API/JSON/controller mới dùng `ds_local`, `ds_graph`, `ds_ref`, `ds_min`; mapping cụ thể ở04/06. Không sinh hai bộ metric khác nghĩa từ việc đổi tên.

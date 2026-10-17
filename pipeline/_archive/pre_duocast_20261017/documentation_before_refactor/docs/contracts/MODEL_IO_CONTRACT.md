# Model I/O Contract

Status: DuoCast architecture agreed (2026-10-17), dataset/code/checkpoint parity and architecture adaptation pending; draft GGSO envelope. Nguồn [R1/R2, S1 §3, S2 §3.5](../technical_report/README.md). Chưa tạo Python/Pydantic/API schema.

## 1. Interface hiện có theo pipeline README

`predict` xuất CSV:

```text
cutoff_time,target_time,hex_id,pred_demand,pred_idle_supply,ds_proxy
```

`pred_demand`: intended **confirmed valid booking requests** trong `(cutoff,target]` (verification pending); `pred_idle_supply`: idle eligible drivers tại target. `ds_proxy=D/(S+1)` là diagnostic, không là target hoặc policy rule. Contract trong active config: `geomobinet_smg_ds_h5_v1`, history12/horizon1. Không đổi các field/values này trong docs-only.

## 2. Approved design mapping, pending parity verification

DuoCast là forecasting component trong GGSO: Temporal GRU, Spatial GATv2 trên H3 adjacency, directed Mobility GATv2 trên physical-driver OD, gated fusion, và hai heads demand/effective-supply. DuoCast **không có Geo Encoder hoặc static geographic-feature input**. `geomobinet_smg_ds_h5_v1` là identifier hiện hành cho artifact/config có static-geo branch; nó không được đổi tên hay tự coi là DuoCast. Chưa có checkpoint DuoCast-compatible được xác minh.

| Existing output | GGSO output | Semantics và gate |
|---|---|---|
| `pred_demand` | `forecast_demand` | Expected valid **confirmed booking requests** /5min trong (t,t+5]; kiểm dataset/training labels |
| `pred_idle_supply` | `forecast_supply` | Expected online, idle, dispatch-eligible **drivers tại t+5**; kiểm driver state/target |
| `cutoff_time` | `cutoff_time` | Decision information cutoff, timezone aware |
| `target_time` | `target_time` | Five-minute target |
| `hex_id` | `hex_id` | H3 Resolution 7 full coverage và mapping đúng |
| `ds_proxy` | Diagnostic optional | Không là independent prediction head / pricing input |

Trong semantic profile GGSO v1, effective available supply có thể là eligible-idle count trên, không thêm weighting chưa phê duyệt. **Capacity K khác stock forecast**. Mapping phải explicit/versioned và được chứng minh qua code, source data, training/inference checkpoint.

## 3. Envelope đề xuất cho adapter

| Field | Kiểu logic | Quy tắc |
|---|---|---|
| schema_version | string | Serialization version tách với model version |
| semantic_profile_id | string | Bao gồm định nghĩa demand/supply và thời gian |
| forecast_model_id, checkpoint_version | string | Phải khai báo đúng architecture; không đổi `geomobinet_smg` thành DuoCast chỉ qua display name |
| dataset_id, feature_version, node_mapping_version | string | Match checkpoint/preprocessing |
| cutoff_time, target_time, generated_at | aware datetime | Cutoff là information boundary; generated_at không thay cutoff |
| history_steps, horizon_minutes | positive integer | Khớp checkpoint; nguồn GGSO horizon=5 |
| reference_policy_version | string hoặc unresolved reason | Không chế version từ filename |
| required_hex_ids | ordered unique strings | Full network identity |
| demand_definition, supply_definition | versioned identifiers | Mandatory trước GGSO consumer |
| rows | list per-cell forecasts | Finite nonnegative D/S; không round counts |
| validity, reasons | structured status | Missing/invalid khác forecast zero |

Tính tương thích cần kiểm fields/units/semantics, không chỉ schema version bằng nhau. Không có surge/GMV/action/response parameters như output head của model. Operational fare/Q/K/context được adapter ghép từ nguồn riêng, không do model bịa.

## 4. Input tensor và train–serve parity

DuoCast yêu cầu dynamic history `X_dyn[B,T,N,F]`, spatial adjacency `G_sp`, directed mobility graph `G_od` (và edge attributes khi được dùng), cùng targets `Y[B,N,2]`. Không có `X_geo[N,Fgeo]` hay geo-version trong DuoCast contract. Đây là design tensor layout; coding agent phải đọc batch/model source trước khi triển khai conversion.

Checkpoint đóng băng feature/node order, preprocessing, history và architecture identity. Reject unknown features; reject a static-geo branch/feature layout when claiming DuoCast; reject shuffled nodes không có explicit remapping, future timestamps hoặc wrong target transform. Không inverse D/S ratio của legacy như hai outputs mới.

## 5. Acceptance

MI-01: round-trip serialized envelope giữ types/precision/timestamps. MI-02: contract mismatch fail trước candidate simulation. MI-03: full-network coverage và stable row→node mapping. MI-04: model inference không phụ thuộc future label, không chạy thêm cho từng surge action.

Tests liên kết FC-01…07 và DT-01…05. Schema ID chính thức, transport và mapping approval thuộc G00/G01/G02, chưa được tài liệu này tuyên bố đã triển khai.

## 6. Design agreement — source-data verification gate (2026-10-16)

Proposed per-cell typed payload (chưa là API code):

~~~python
class DuoCastForecast:
    hex_id: str
    cutoff_time: datetime
    target_time: datetime
    forecast_demand: float     # confirmed valid booking requests / 5min
    forecast_supply: float     # eligible idle drivers at target_time
    model_version: str
    semantic_profile_version: str
~~~

Envelope phải chứa `snapshot_id`, `forecast_run_id`, `checkpoint_version`, `required_hex_ids`, `node_mapping_version`, `feature_version`, `reference_policy_version`, `generated_at` cùng schema/model identity. Model chỉ forecast D/S; Q, fares, K, current surge, beta/gamma, GMV và policies thuộc downstream. Thông tin train/source semantics phải đúng và mọi feature known at cutoff.

**MI-05:** network inference đúng một lần cho toàn required network. **MI-06:** đúng flow/stock semantics. **MI-07:** không đem operational fields vào prediction heads. **MI-08:** source/target mismatch ⇒ technical INVALID, **zero recommendations**, no optimized policy hoặc execution request/write; không đổi tên raw fields để vượt gate.

Chưa xác nhận parity bằng source/test trong task này.

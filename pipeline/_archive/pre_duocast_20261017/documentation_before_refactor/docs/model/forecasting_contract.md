# Forecasting Specification — DuoCast (Dual-Graph)

Status: DESIGN AGREED — dataset/code/checkpoint parity PENDING (revised 2026-10-17); không thay model/config. Nguồn: [R1/R2 và S1/S2](../technical_report/README.md). Requirements có ID để trace sang test.

## 1. Mục tiêu và non-goals

Forecast hai đại lượng cho mỗi H3 cell ở t+5. Không trả surge, GMV, causal effect hoặc action; không chạy lại model cho mỗi candidate. Mọi input phải available tại cutoff. [S1 §2–3; R1 §1/3/11]

## 2. Kiến trúc và target semantics đã thống nhất

**GD-01:** **DuoCast** là kiến trúc forecasting hiện hành của GGSO: shared Temporal GRU, Spatial GATv2 trên H3 adjacency, Mobility GATv2 trên directed physical-driver OD graph, gated fusion, và hai head độc lập cho Demand/Supply. DuoCast không có Geo Encoder riêng và không nhận static geographic features làm node/edge input. Spatial adjacency mô tả quan hệ giữa H3 hex lân cận, không phải geographic features.

Implementation/config hiện có vẫn là **GeoMobiNet-SMG**, bao gồm static geo MLP và `X_geo`; đó là evidence về implementation lịch sử, không phải implementation/checkpoint DuoCast đã xác nhận. Không dùng checkpoint/config GeoMobiNet-SMG cho DuoCast cho đến khi có adaptation và parity dataset/code/checkpoint được kiểm chứng.

**GD-02 — Demand:** `demand_5m` là valid booking requests được khách **xác nhận đặt chuyến**, tạo trong (t−5,t], trước driver fulfillment; observation integer ≥0. Forecast `forecast_demand` là expected booking requests trong (t,t+5], real ≥0, unit **booking requests/5min**. Không phải quotes hoặc completed rides. Đây là agreed target meaning, còn phải kiểm event taxonomy, label-generation và checkpoint.

**GD-03 — Supply:** `idle_supply_t` là drivers **online, idle và dispatch-eligible** tại timestamp t, observation integer ≥0. Forecast `forecast_supply` là expected eligible idle driver stock **tại t+5**, real ≥0, unit drivers. GGSO v1 có thể gọi đây là *effective available supply* khi semantic profile định nghĩa chính xác count này, không thêm weighting. **Driver stock không bằng effective service capacity K (rides/5min)**. Adapter tạo K riêng bằng approved direct method hoặc capacity approximation.

CLI hiện vẫn đặt tên `pred_demand` và `pred_idle_supply`. Versioned mapping qua GGSO adapter chỉ hợp lệ sau khi dataset/training/inference parity được kiểm. `ds_proxy` chỉ diagnostic; không là head độc lập.

| Aspect | Implementation description | GGSO design agreement |
|---|---|---|
| History | 12 snapshots × 5min, horizon=1 | Configurable history length `T`; five-minute forecast horizon |
| Architecture | GeoMobiNet-SMG: GRU + spatial/mobility GATv2 + geo MLP + fusion + two heads | DuoCast: GRU + spatial/mobility GATv2 + gated fusion + two heads; no Geo Encoder/static geo input |
| Demand | Historically described “eligible requests” | Specifically **confirmed valid booking requests** |
| Supply | Eligible idle stock | Same stock as effective available supply under v1 profile |
| Capacity | Not a forecasting head | Versioned operational K estimator |

## 3. Inputs/outputs

Contract chi tiết: [MODEL_IO_CONTRACT](../contracts/MODEL_IO_CONTRACT.md), [DATA_SCHEMA](../contracts/DATA_SCHEMA.md).

DuoCast nhận `X_dyn[B,T,N,F_dyn]`, spatial edge index `[2,E_sp]`, directed mobility edge index `[2,E_od]`, edge attributes `[E_od,F_edge]`, và target `[B,N,2]`. Không có `X_geo`. Tensor layout thực tế phải được xác nhận trong implementation DuoCast trước khi coding, không đoán transposes từ tên biến. `X_geo` trong R1/GeoMobiNet-SMG là historical implementation input và không thuộc DuoCast contract.

R2 `predict` xuất CSV `cutoff_time,target_time,hex_id,pred_demand,pred_idle_supply,ds_proxy`. Đây không phải GGSO decision envelope đã có version; adapter mới là task riêng.

## 4. Invariants

- FC-01: đúng required nodes, unique IDs, deterministic ordering và horizon/cutoff thống nhất.
- FC-02: labels là next interval; không dùng future movement, final trip duration hoặc late-arriving events chưa biết tại t.
- FC-03: directed physical movement không được thay bằng passenger request OD.
- FC-04: empty mobility graph là case hợp lệ nếu đúng snapshot; không biến missing mobility data thành empty graph đã quan sát.
- FC-05: output finite/nonnegative; raw predictions giữ số thực, không round trước downstream calculations.
- FC-06: scaler/feature order/node order/schema phải khớp checkpoint; fit preprocessing trên train only.
- FC-07: model có đúng hai forecast targets, không phụ thuộc response artifact hoặc solver.

## 5. Training/evaluation boundary

Dùng core log1p Huber trong profile đã chốt. Active configuration values là evidence của repo, không mặc định được S1 phê duyệt. Optional local/spatial losses chỉ được bật khi có định nghĩa và acceptance đã duyệt. Forecast tests không tính GMV như loss phụ.

Không tự thay study hoặc retrain. R2 mô tả validation-only selection, frozen test/finalize và smoke artifacts không eligible; cần code/test review để xác nhận trước dùng. Metrics theo [MODEL_EVALUATION](../evaluation/MODEL_EVALUATION.md).

## 6. Error handling và acceptance

Reject incompatible checkpoints, missing nodes, future availability, unknown edge nodes, duplicate keys, nonfinite outputs. Downstream nhận technical INVALID và **không tạo recommendation hoặc optimized policy mới**, không phát forecast zero để qua validation.

Nghiệm thu: tests FC-01…07; parity preprocessing train/serve; fixture empty OD; permuted node-order rejection; inspection xác nhận một inference toàn mạng/decision. Chưa có test result trong phiên docs này.

## 7. Scope khi triển khai

Không tái sử dụng GeoMobiNet-SMG checkpoint/config như DuoCast chỉ bằng đổi tên. Cần implementation hoặc adaptation dual-graph tường minh, rồi kiểm chứng profile/semantics và dataset/code/checkpoint parity trước khi dùng adapter GGSO. Giữ handoff [duocast_model.md](duocast_model.md) như bằng chứng lịch sử GeoMobiNet, không dùng body prototype cũ làm bằng chứng trạng thái DuoCast.
**FC-08:** nếu label/mapping/versions không đáp ứng target agreement, fail closed: `recommendations=[]`, `optimized_policy=null`, no execution request/write. **FC-09:** một inference cho full network, không gọi GNN cho từng surge candidate.

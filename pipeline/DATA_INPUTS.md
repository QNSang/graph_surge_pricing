# Dữ liệu đầu vào cho pipeline DuoCast mới

Chưa cần cung cấp dữ liệu để chạy các bài kiểm thử synthetic. Khi có data, đối chiếu các bảng dưới đây trước khi sửa đường dẫn trong `configs/duocast.yaml`. Không tạo lại hoặc ghi đè dataset cũ; tạo dataset/version mới sau khi kiểm tra semantics.

## 1. Forecasting: bốn bảng và một file metadata

| File | Key | Cột tối thiểu |
|---|---|---|
| `market.parquet` hoặc CSV | `timestamp, hex_id` | `demand_5m, idle_supply_t, backlog_t, eta_sec_t, base_surge, available_at` |
| `spatial_edges.parquet` hoặc CSV | `source_hex, target_hex` | `available_at` hoặc metadata `static_as_of` |
| `od.parquet` hoặc CSV | `timestamp, origin_hex, dest_hex` | `flow_5m, eta_min, available_at` |
| `mobility_snapshots.parquet` hoặc CSV | `timestamp` | `available_at, complete` |
| `meta.json` | dataset-level | Các identities/semantics ở phần dưới |

Spatial graph biểu diễn H3 adjacency. Mobility graph biểu diễn physical driver transitions có hướng, không phải passenger-trip OD.

`market` cần đủ mỗi `(timestamp, hex_id)` trên lưới 5 phút. Demand là số booking requests hợp lệ đã được khách xác nhận trong `(t-5,t]`. Supply là số driver online, idle và dispatch-eligible tại `t`. Cả hai observation là số nguyên không âm. Pipeline tự tạo target next-step; không dịch label thêm một lần trong input.

`available_at <= timestamp`; event_time/window_end nếu có cũng không được ở tương lai. `eta_sec_t` dùng giây, `eta_min` dùng phút. Giá trị thiếu không được thay thành observed zero. Optional nullable features phải được khai báo; hai count targets không được nullable.

Spatial graph không có self-edge, phải có hai chiều và chỉ chứa node trong cùng tập H3-7. Directed mobility không tự được thêm chiều ngược. Các bản ghi edge cần được aggregate unique trước khi đưa vào pipeline.

`mobility_snapshots` phải chứa đúng mọi timestamp của market và `complete=true`, kể cả những thời điểm thực sự không có movement. Có một coverage record complete với zero OD rows nghĩa là empty graph đã quan sát. Thiếu coverage record hoặc `complete=false` là dữ liệu thiếu, pipeline từ chối thay vì đoán empty graph.

Metadata tối thiểu (điền dataset/version thực, không giữ placeholder):

```json
{
  "contract_version": "duocast_ds_h5_v1",
  "dataset_id": "YOUR_DATASET_VERSION",
  "feature_definition_version": "YOUR_FEATURE_VERSION",
  "node_mapping_version": "YOUR_NODE_MAPPING_VERSION",
  "spatial_graph_version": "YOUR_SPATIAL_GRAPH_VERSION",
  "demand_definition": "confirmed_valid_bookings_per_5min",
  "supply_definition": "online_idle_dispatch_eligible_stock_at_target",
  "mobility_semantics": "physical_driver_transitions",
  "synthetic": false
}
```

`node_order` có thể thêm dưới dạng ordered list chứa đúng toàn bộ H3 IDs; nếu không có, loader sắp xếp và đóng băng thứ tự. `static_as_of` có thể thay `available_at` của spatial edges nếu timestamp đó thực sự không sau market snapshot đầu tiên. Không có `geo_version` trong checkpoint/interface mới.

Khai báo semantics trong metadata là điều kiện schema, không tự chứng minh event taxonomy của nguồn đúng. Việc rà soát dữ liệu thực vẫn phải diễn ra khi nhận data. Chỉ synthetic fixtures mới được tắt H3 validation.

## 2. Response fitting: matured booking cohorts

Lệnh `fit-responses` hiện đọc JSON array các `Observation` theo `datasets/responses.py`. Mỗi dòng gồm:

```text
usage: TEST_ONLY
hex_id
decision_time, target_time
feature_available_at, outcome_matured_at
cohort_id
cohort_profile: confirmed_bookings_and_matured_completions.h5.test.v1
capacity_definition: rides_per_horizon.h5.test.v1
applied_surge: decimal string
booking_demand: integer D >= 0
completed_bookings: integer C, 0 <= C <= D
effective_capacity: finite K >= 0

demand_context:
  names: ordered feature names
  values: matching finite values
  schema_version: context schema ID

fulfillment_context:
  names: ordered feature names
  values: matching finite values
  schema_version: context schema ID
```

C phải là completions của chính cohort D, không phải tổng mọi completion event xảy ra trong cùng 5 phút. Context cần available trước decision. Labels train phải matured trước split; mọi labels phải matured trước fit cutoff. Cohort IDs và per-cell decision timestamps không được duplicate.

Trong `configs/responses.yaml`, điền `input`, `output`, `dataset_id`, `node_mapping_version`, `required_hex_ids`, `artifact_version`, `split_time`, `fit_as_of`. Không tự đặt split/maturity chỉ để chạy được. `fit` chứa numerical settings riêng cho NB/Binomial/bootstrap.

Profile response/decision hiện được khóa TEST_ONLY và chưa có quy trình promotion dữ liệu thật/production. Không đổi nhãn dữ liệu thật thành synthetic để vượt gate. Khi data được cung cấp, cần chốt source/cohort/K semantics và calibration thresholds trước khi mở profile offline/operational tương ứng.

## 3. Decision inputs

`surge-ml decide --input ...` nhận một JSON object gồm đúng bốn trường: `identity`, `operational`, `response`, `policy`.

`identity` gồm snapshot/decision/dataset identity, fingerprint, node/feature version, current effective-price version, cutoff/target, required node order và semantic profile v2. Không có geographic version.

`operational` bổ sung mỗi cell: current effective surge, reference fare trước surge, compatible quote opportunities Q, capacity K trực tiếp hoặc r/ETA để xấp xỉ, ordered contexts, timestamps/version và pricing adjacency. Những trường này phải được cung cấp từ nguồn riêng; DuoCast không dự báo hoặc tự chế Q/fare/K/current price.

`response` là artifact đã fit hợp lệ, đầy đủ mọi required cell. `policy` là bản frozen của `PolicyConfig`; có thể được chuẩn bị theo `configs/optimization.yaml`, nhưng numerical values hiện là TEST_ONLY. Không dùng chúng làm giá/BR defaults production.

Xuất JSON schemas để xem chính xác từng field:

```bash
uv run --offline --no-sync --project pipeline surge-ml schemas --output-dir pipeline/runs/my-schemas
```

Checkpoint provider hiện chỉ chấp nhận checkpoint DuoCast đúng contract và đã train trên declared synthetic data để kiểm chứng phần mềm. Thiếu hoặc sai checkpoint trong `decide` được ghi thành kết quả INVALID, không sinh policy mới.

## 4. Kiểm tra trước khi training

```bash
uv run --offline --no-sync --project pipeline surge-ml preflight --config pipeline/configs/duocast.yaml --output pipeline/runs/preflight.json
```

Lệnh xuất số hex, timestamp range, số cạnh OD, các snapshot đã quan sát nhưng không có movement, train/validation/test sample ranges và SHA-256 của từng input. Không fit model/scaler và không sửa dữ liệu nguồn. Nếu cấu trúc không hợp lệ thì trả exit code 2, không tạo báo cáo thành công. File báo cáo đã tồn tại sẽ không bị ghi đè.

`INPUT_STRUCTURE_VALIDATED` chỉ chứng nhận những kiểm tra cấu trúc đã chạy; `source_semantics_verified=false` và `production_eligible=false` vẫn giữ nguyên. Không đổi metadata thành synthetic để vượt điều kiện H3 hoặc source-review.

Response job có thể thêm `report: ../runs/responses/response-v1/calibration.json` để xuất kiểm định held-out theo cell, khoảng xác suất và mức surge. Bỏ trường `report` hoặc đặt `null` để không xuất. Schema job từ chối trường thừa, split không có timezone, danh sách hex rỗng/trùng và thời gian không hợp lệ. Input, output artifact và report phải là các đường dẫn khác nhau. Chỉ số trong report không tự thay calibration gates hoặc phê duyệt elasticity nhân quả.

## 5. Khi giao data

Ưu tiên gửi schema hoặc một sample có đủ các bảng cùng metadata, kèm định nghĩa demand/supply/OD và maturity của booking cohort. Pipeline có thể kiểm tra cấu trúc trước; không cần bắt đầu bằng một lần training dài. Kết quả synthetic đã có chỉ xác nhận code chạy đúng các bài test, không thay thế đánh giá data/model thật.

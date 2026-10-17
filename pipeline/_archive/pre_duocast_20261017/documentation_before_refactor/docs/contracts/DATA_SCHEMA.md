# Data Schema — Semantics trước implementation

Status: DESIGN AGREED về Demand/Supply, dataset/code parity PENDING (2026-10-16). Mô tả active inputs R1/R2 và proposed GGSO fields S1/S2. [Source register](../technical_report/README.md). Chưa tạo schema/config/data mới.

## 1. Forecast tables hiện được repo mô tả

| Table | Key | Minimal columns theo pipeline README/config |
|---|---|---|
| Market | timestamp, hex_id | demand_5m, idle_supply_t, backlog_t, eta_sec_t, base_surge, available_at |
| Geo | hex_id | distance_to_cbd_km, east_offset_km, north_offset_km, road_neighbor_count |
| Spatial | source_hex, target_hex | Minimal config chưa có spatial attributes |
| Mobility | timestamp, origin_hex, dest_hex | flow_5m, eta_min, distance_km, available_at |
| Metadata | dataset identity | dataset_id, feature_definition_version, geo_version, mobility_semantics, static_as_of; node_order nếu được cung cấp |

Nguồn active config: `pipeline/configs/geomobinet.yaml`; file paths resolve relative to YAML theo README. Không giả các production input files đã tồn tại chỉ vì config có đường dẫn.

Market tại t: demand_5m là flow `(t-5min,t]`; idle_supply_t là stock tại t. Label lấy next interval/next snapshot. Mobility là observed physical driver transitions, không phải hourly passenger/request OD của UI.

Timestamp có timezone/offset và quy ước thống nhất; event time/available_at phải <= cutoff cho features. Static dữ liệu phải đúng vintage/as-of. Null/missing khác observed zero; graph missing khác empty graph đã được quan sát. Signed geo offsets không bị log1p tùy tiện.

## 2. GGSO decision inputs cần có thêm

Tên field là contract proposal; semantics của nguồn không đổi.

| Field | Kiểu logic / đơn vị | Validation/source requirement |
|---|---|---|
| hex_id | string H3-7 | Unique trong required node set |
| cutoff_time, target_time | aware datetime | Cùng horizon 5 phút, không chỉ HH:MM |
| forecast_demand | finite real, bookings/interval | Confirmed booking definition đã thống nhất; kiểm label/data/model parity trước mapping |
| forecast_supply | finite real, effective drivers | Eligible-idle stock là effective available supply theo semantic profile v1 sau parity; không là K |
| current_surge | canonical decimal, multiplier | Dương, reference version/validity rõ; không dùng giá proposal làm reference |
| reference_fare | finite nonnegative monetary amount | Giá trước surge, currency/fare definition version; không giả từ surge |
| quote_opportunities | finite nonnegative count/expected count theo profile | Cùng opportunity cohort/window với booking demand; có availability và nguồn |
| effective_capacity | finite nonnegative rides/horizon | Direct operational estimate hoặc approved approximation; method/version rõ |
| capacity inputs | supply, r_i, ETA | Nếu derive K: r rides/driver/hour, ETA phút; không trộn giây/phút |
| context | ordered typed covariates | Pre-decision, khớp regression preprocessing/version |
| coverage/provenance | IDs/versions/timestamps | Không mặc định complete/validated khi thiếu metadata |

Không coi Q của khoảng tương lai là observation available tại t. GD-02 phải chọn nguồn forecast/frozen eligible opportunities hoặc operational protocol phù hợp. Không dùng realized future Q làm online input. Chưa có quy tắc clip D(a) vào Q trong nguồn.

## 3. Response training cohort

Training rows cần decision cell/time, applied surge, pre-decision context, booking cohort D, matured completed outcomes C, capacity definition và observation/maturity timestamps. Raw D/C là integers, 0<=C<=D. Fit labels có thể được hoàn thiện sau decision; không để timestamps đó lọt vào feature availability.

Số completion events xảy ra trong interval không mặc nhiên là số completion của cohort mới phát sinh trong interval. GD-02 phải chốt completion observation horizon; GD-03 phải xác nhận capacity units/horizon tương thích với target completion.

### 3.1. Response-GLM training rows và tabular context — design clarification

| Field | Meaning / role |
|---|---|
| `hex_id`, `decision_time`, `observation_window` | Key, cohort/temporal contract theo H3 và historical interval |
| `applied_surge` | Historical surge thực tế áp dụng, explanatory variable của Demand GLM |
| `booking_demand` (`D`) | Confirmed booking requests; NB target, Binomial trials |
| `completed_bookings` (`C`) | Matured completions của cùng booking cohort D; Binomial successes |
| `effective_capacity` (`K`) | Historical rides/horizon capacity dùng trong Binomial; method/units phải tương thích online K |
| `demand_context`, `fulfillment_context` | Tabular **pre-decision** feature vectors, có thể khác nhau |
| `context_schema_version`, `feature_order`, `preprocessing_version` | Reproduce đúng regressors/coefficient mapping |
| `available_at`, `outcome_matured_at` | Tách thời gian feature available và outcome labels hoàn thiện |

Candidate context gồm cyclical hour/day-of-week, lagged demand/supply, pre-decision backlog hoặc ETA **nếu** tồn tại, hợp lệ tại cutoff và giúp calibration; đây chưa phải final approved feature list. Applied surge và capacity/demand ratio là main explanatory terms riêng trong phương trình tương ứng, tránh duplicate trong `c`. Per-hex static constants không nhận diện riêng khỏi intercept khi fit độc lập theo cell. Không dùng GNN embeddings, post-decision surge reactions hoặc future outcomes làm context GGSO v1.

Historical `C`/`D` là integer counts với `0 <= C <= D`; `D=0` không cung cấp positive Binomial trials. `Q` không bắt buộc cho hai GLM losses theo thiết kế hiện tại; GGSO optimizer vẫn cần Q cho booking-rate guardrail. Historical and online `K` phải tương thích về horizon, cohort và method. Split chronological và freeze preprocessing trên train-only.

## 4. Validation requirements

DT-01: unique keys, complete required cells/timestamps, actual H3-7 IDs; symbolic IDs chỉ trong fixture declared synthetic.

DT-02: đúng temporal cutoff, no future availability, unit metadata; không random row split bỏ qua thời gian.

DT-03: finite/domain checks, no null-to-zero, no passenger-to-driver OD conversion.

DT-04: semantic profile explicit cho D/S/Q/K/fare; missing/incompatible profile chặn GGSO adapter.

DT-05: dataset/node/feature/geo/context versions được ghi và so khớp; kích thước/split/time range lấy metadata, không hardcode từ báo cáo cũ.

## 5. Ngoài phạm vi và quyết định mở

Không regenerate dataset, sửa CURRENT.json, tạo migration hoặc dùng oracle làm input. Thư mục data cũ có tài liệu deleted không được tự restore. GD-02/GD-03/GD-05 giải quyết operational definitions trước data-dependent implementation. Test strategy định nghĩa fixtures; không coi fixture là dữ liệu huấn luyện thực.

## 6. Canonical semantic decision — 2026-10-16

**Demand:** `demand_5m` nghĩa là valid booking requests sau customer confirmation và trước fulfillment, observations là nonnegative integers theo interval (t−5,t], forecast expected real count cho (t,t+5]. **Không phải** quote opportunities, completed rides hoặc fulfillment. `pred_demand` chỉ được map sang `forecast_demand` sau khi kiểm source event taxonomy và training labels thực tế.

**Supply:** `idle_supply_t` là online + idle + dispatch-eligible driver stock tại t (integer). `pred_idle_supply` dự báo eligible idle stock tại t+5 (real). GGSO v1 dùng cùng quantity này làm **effective available supply** khi semantic profile ghi rõ, **không thêm weighting**. **K (rides/horizon) vẫn khác forecast supply (drivers)**. Operational adapter nếu không có direct K thì dùng K = S_hat*r*(H/60)*min(1,H/max(ETA,H)); H=5min, ETA phút, r rides/driver/hour; method, r/ETA version và calibration cần xác nhận.

**Directed OD:** `origin_hex → destination_hex` là observed physical driver movement, một edge có outflow origin và inflow destination (không double count), reverse movement chỉ khi có observation. Arrival không tự đồng nghĩa future eligible idle supply. Bắt buộc giữ `origin_hex,destination_hex,flow_5m,observation_window,available_at,mobility_semantics,source_version`; OD driver ≠ passenger OD.

**Booking Rate ≠ Fulfillment Rate:** BR = booking requests/quote opportunities (cùng cohort/window); FR = completed rides/matured booking cohort. Binomial predicted FR trước capacity cap không bắt buộc bằng completed/demand sau cap. Không lấy future realized Q làm online input.

**Validation:** thiếu/khác semantics hoặc dữ liệu provenance trước cutoff ⇒ INVALID, `recommendations=[]`, `optimized_policy=null` và **không có execution request/write**. Current pricing giữ nguyên vì không có write. Open: Q source/cohort, completion maturity, `Q_total=0`, predicted D>Q, capacity r/ETA calibration. Design agreement **không phải** evidence dataset và checkpoint đã đáp ứng.

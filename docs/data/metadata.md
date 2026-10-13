# Dataset metadata: `hcm_mock_v2_90d_seed42_bounded_tail`

Tài liệu này mô tả dữ liệu mock đang dùng để huấn luyện: cấu trúc thư mục, từng bảng, từng cột, định nghĩa D/S và các quy tắc khi viết code đọc dữ liệu. Nguồn chuẩn của schema là `schema.yaml` trong thư mục dữ liệu; nếu hai nơi khác nhau thì `schema.yaml` và `meta/manifest.json` đúng.

## 1. Tóm tắt

| Mục | Giá trị |
|---|---|
| Dataset id | `hcm_mock_v2_90d_seed42_bounded_tail` |
| Layout | `clean_v1` |
| Feature contract | `hex40_edge10_v2.1` (40 node feature, 10 edge feature) |
| Địa lý | 61 hex H3 res 7 (ring 4 quanh quận 1, TP.HCM), 1 loại xe |
| Thời gian | 90 ngày chính, 2026-01-05 đến 2026-04-04 (snapshot cuối 2026-04-05 00:00), cộng 1 ngày burn-in (2026-01-04) |
| Bước thời gian | 5 phút, 288 mốc mỗi ngày, 25.920 mốc ở giai đoạn chính |
| Múi giờ | Asia/Ho_Chi_Minh, timestamp không có timezone |
| Sinh bởi | `tools/mock_v3/run.py` (cấu hình bounded_tail gộp sẵn), seed 42 |
| Vị trí | `data/hcm_data_2/` (con trỏ ở `data/CURRENT.json`) |

Đây là dữ liệu tổng hợp từ mô phỏng. Tham số là giả định hợp lý, không phải số liệu vận hành thật.

## 2. Cấu trúc thư mục

```
data/hcm_data_2/
  schema.yaml            bảng, cột, khoá, kiểu, đơn vị, cửa sổ thời gian
  README.md              thống kê thực tế của bản phát hành
  raw/                   dữ liệu hệ thống thật sự ghi lại
    hexes/               61 dòng, lưới hex tĩnh
    orders/              date=YYYY-MM-DD/, mỗi đơn một dòng
    hex_snapshot/        date=.../, trạng thái từng hex mỗi 5 phút
    weather/             date=.../, mưa toàn thành phố mỗi 5 phút
  burn_in/               orders, hex_snapshot, weather của ngày đệm (chỉ là lịch sử)
  features/              feature point-in-time, đã tính sẵn
    hex_features/        date=.../, 40 feature mỗi (ts, hex)
    graph_edges/         date=.../, cạnh có hướng mỗi ts
  oracle/                sự thật của simulator, KHÔNG dùng làm input model
    order_audit/ signal_truth/ driver_stats/ calendar.json
  meta/                  manifest, checksum, validation, config sinh dữ liệu
```

Mọi bảng `date=` là parquet phân vùng theo ngày. Ngày của partition là ngày của `ts - 5 phút`, nên snapshot 00:00 thuộc ngày trước.

## 3. Số dòng

| Bảng | Dòng |
|---|---:|
| `raw/hexes` | 61 |
| `raw/orders` | 2.539.401 |
| `raw/hex_snapshot` | 1.581.120 (25.920 ts × 61 hex) |
| `raw/weather` | 25.920 |
| `burn_in/orders` | 26.136 |
| `burn_in/hex_snapshot` | 17.568 |
| `burn_in/weather` | 288 |
| `features/hex_features` | 1.581.120 |
| `features/graph_edges` | 23.149.322 |
| `oracle/order_audit` | 2.565.537 |
| `oracle/signal_truth` | 1.581.120 |
| `oracle/driver_stats` | 26.208 |

Lưới đầy đủ, không có mốc thiếu: mọi `(ts, hex_id)` đều có đúng một dòng ở `hex_snapshot`, `hex_features` và `signal_truth`.

## 4. Bảng raw

### `raw/hexes` (khoá: `hex_id`)

| Cột | Mô tả |
|---|---|
| `hex_id` | Chỉ số H3 res 7 |
| `zone` | `airport`, `cbd`, `office`, `residential`, `suburb`, `venue` |
| `ring` | Khoảng cách ring tới tâm, 0 đến 4 |
| `lat`, `lng` | Tâm hex (độ) |

### `raw/orders` (khoá: `order_id`)

Mỗi dòng là một yêu cầu đặt xe. `origin_hex` và `dest_hex` tham chiếu `hexes`.

| Cột | Mô tả |
|---|---|
| `order_id` | Số thứ tự, tiếp nối `burn_in/orders` |
| `origin_hex`, `dest_hex` | Hex đón và hex trả |
| `created_ts` | Thời điểm yêu cầu |
| `est_trip_duration_min` | Thời lượng ước tính, biết ngay lúc yêu cầu |
| `accepted_ts`, `pickup_ts`, `dropoff_ts`, `cancel_ts` | Mốc vòng đời, null nếu chưa quan sát được |

Các mốc vòng đời bị cắt tại cuối dữ liệu (2026-04-05 00:00). Null nghĩa là "chưa thấy đến lúc kết thúc", không phải "không bao giờ xảy ra". Ràng buộc: có `pickup_ts` thì có `accepted_ts`; có `dropoff_ts` thì có `pickup_ts`; `cancel_ts` và `pickup_ts` không cùng tồn tại.

### `raw/hex_snapshot` (khoá: `ts`, `hex_id`)

| Cột | Đơn vị | Mô tả |
|---|---|---|
| `demand` | đơn | Số yêu cầu tạo trong `(ts - 5 phút, ts]` tại hex làm origin |
| `supply` | tài xế | Tài xế đang rảnh (idle) tại hex lúc `ts` |
| `eta_sec` | giây | ETA đón khách được báo lúc `ts` |
| `surge_multiplier` | hệ số | Hệ số tăng giá đang áp dụng, trong [1, 3] |

### `raw/weather` (khoá: `ts`)

`rain_intensity`: cường độ mưa toàn thành phố, 0 (khô) đến 1.

## 5. Feature point-in-time

Mọi giá trị chỉ dùng sự kiện đã quan sát tại hoặc trước `ts` (đã có kiểm thử prefix trong `meta/validation/feature_validation.json`). Giá trị là đại lượng vật lý, chưa chuẩn hoá. Lịch sử burn-in đã nằm trong các cửa sổ lăn, nên mọi dòng đều có đủ 60 phút lịch sử. Kiểu float32 cho mọi cột không phải khoá.

### `features/hex_features` (khoá: `ts`, `hex_id`), 40 cột feature theo đúng thứ tự

| Nhóm | Cột |
|---|---|
| Local (cung cầu) | `demand_5m`, `idle_supply_t`, `backlog_t`, `eta_sec_t`, `local_pressure_log_t`, `demand_sum_15m`, `demand_mean_60m`, `demand_std_60m`, `demand_momentum_15m`, `idle_supply_mean_15m`, `idle_supply_momentum_15m`, `match_rate_matured_15m`, `cancel_rate_matured_15m`, `pickup_wait_p90_30m`, `current_surge_t`, `surge_delta_15m` |
| Thời tiết | `rain_intensity_t` |
| Thời gian | `hour_sin`, `hour_cos`, `dow_sin`, `dow_cos`, `is_weekend` |
| Tĩnh | `zone_airport`, `zone_cbd`, `zone_office`, `zone_residential`, `zone_suburb`, `zone_venue` (one-hot), `ring` |
| Supply hiệu dụng | `effective_supply_t`, `arriving_trip_count_eta_0_5_t`, `arriving_trip_count_eta_5_10_t`, `arriving_trip_count_eta_10_15_t`, `completed_inflow_15m`, `pickup_outflow_15m` |
| Láng giềng | `neighbor_demand_mean_t`, `neighbor_idle_supply_mean_t`, `neighbor_pressure_mean_t` |
| OD | `od_destination_entropy_30m`, `od_support_30m` |
| Hỗ trợ (đếm) | `mature_request_count_15m`, `matched_within_5m_count`, `cancelled_within_5m_count`, `pickup_wait_support_30m`, `history_steps_available` |

Công thức đáng chú ý:

- `local_pressure_log_t = log1p(demand_5m) - log1p(idle_supply_t)`.
- `backlog_t`: đơn đã tạo nhưng chưa được nhận hoặc huỷ tại `ts`.
- `match_rate_matured_15m`, `cancel_rate_matured_15m`: tính trên các đơn tạo trong `(t-20 phút, t-5 phút]`, làm mượt Beta(1,1) dạng `(k+1)/(n+2)`; tử số và mẫu số nằm ở các cột đếm hỗ trợ.
- `pickup_wait_p90_30m`: P90 của `pickup_ts - created_ts`; nếu không có đơn nào được đón thì dùng ETA hiện tại, và `pickup_wait_support_30m = 0` đánh dấu trường hợp này.
- `demand_momentum_15m = demand_sum_15m(t) - demand_sum_15m(t - 15 phút)`.

### `features/graph_edges` (khoá: `ts`, `src_hex`, `dst_hex`), 10 cột edge feature

Cạnh có hướng, hai quan hệ lưu thành các dòng riêng. Dòng kề (`edge_is_adjacent = 1`) là mọi cặp H3 ring-1, các cột OD bằng 0. Dòng OD (`edge_is_od = 1`) là cặp có yêu cầu trong 30 phút gần nhất hoặc chuyến đang chạy; cạnh tự thân (`src = dst`) được giữ. Mỗi mốc có khoảng 900 dòng.

Cột: `edge_is_adjacent`, `edge_is_od`, `distance_km`, `travel_time_est_min`, `od_requests_5m`, `od_requests_30m`, `od_completed_15m`, `od_in_trip_count_t`, `od_arrivals_eta_le5m_t`, `od_transition_prob_30m` (`= (od_requests_30m + 0.1) / (yêu cầu từ src trong 30 phút + 0.1 × 61)`).

Nhãn huấn luyện, cửa sổ, chuẩn hoá và split không có trong dữ liệu; chúng được dựng ở downstream theo `docs/model/technical_report.md`.

## 6. Oracle (chỉ để chẩn đoán, không đưa vào input model)

- `order_audit`: `order_id`, `driver_id` (-1 nếu chưa nhận), `dispatch_ready_ts`, `patience_deadline_ts`, `driver_available_ts_at_accept`.
- `signal_truth`: tín hiệu cài đặt S1 đến S7 theo `(ts, hex_id)` (`s1_ramp`, `s2_drain`, `s3_airport`, `s4_venue`, `s5_rain`, `s6_sparse`, `s7_boundary`).
- `driver_stats`: `ts`, `online`, `idle`, `pickup`, `in_trip`, `reposition`, trung bình 5 mẫu 1 phút mỗi cửa sổ.
- `calendar.json`: ngày mưa, sự kiện venue, ngày đặc biệt.

## 7. Định nghĩa cung cầu và D/S

- **D** = `demand_5m` = yêu cầu tạo trong `(ts - 5 phút, ts]` tại hex.
- **S idle** = `idle_supply_t` = tài xế rảnh tại `ts`.
- **S_eff** = `effective_supply_t = idle + arriving_0_5 + 0.5 × arriving_5_10 + 0.2 × arriving_10_15`, với `arriving_*` là chuyến đang chở khách sẽ kết thúc tại hex trong khoảng đó. Tài xế đang reposition không được tính.
- **D/S_eff** = `demand_5m / effective_supply_t`, chỉ trên dòng S_eff > 0 (làm tròn S_eff 4 chữ số). Không clip, không rescale.
- **Dòng S_eff = 0**: tỷ lệ không xác định. Khoảng 2,95% dòng có S_eff = 0, trong đó 1,97% tổng dòng có D > 0. Code phải giữ mask `effective_supply_t > 0` thay vì chia cho 0 hoặc thêm epsilon ngầm.

Phân phối D/S_eff (dòng S_eff > 0): p50 0,201, p90 1,429, p99 4,286, p99,9 10,0, max 12,5; 0 dòng vượt 15; khoảng 0,006% vượt 10. Giới hạn 15 đạt được bằng mô phỏng (bộ lọc "hết xe" cùng bảo vệ supply cục bộ), không phải bằng cắt giá trị. Xem `docs/data/mock_data_spec_hcmc.md` mục 13 và `tools/mock_v3/README.md`.

Các giá trị tiêu biểu: demand trung bình 1,606 đơn mỗi hex mỗi cửa sổ, idle trung bình 2,711, S_eff trung bình 5,037; completion trưởng thành 91,98%; 30,42% dòng có demand > idle và 15,95% có demand > S_eff.

## 8. Quy tắc khi viết code

1. Đọc đường dẫn và schema từ `data/CURRENT.json`, không hardcode `hcm_data_2`. Dùng `data_fingerprint` làm khoá cache.
2. Số mốc là `n_days × 288`, lấy từ `meta/manifest.json` (`days`); không hardcode 8640 hay 61 ngày.
3. Chỉ dùng `raw/` và `features/` làm input. `oracle/` chỉ để chẩn đoán và cắt lát đánh giá.
4. Không tái dùng thông tin sau `ts` cho dòng tại `ts`. Mọi cột trong `features/` đã đảm bảo điều này; nhãn tương lai phải tự dựng và loại các dòng chưa đủ tương lai (đơn chưa trưởng thành).
5. Các mốc vòng đời bị cắt ở cuối dữ liệu. Đừng suy ra "không bao giờ đón" từ `pickup_ts` null ở các ngày cuối.
6. Split theo ngày liên tiếp, không xáo trộn ngẫu nhiên các mốc. `meta/manifest.json` có `suggested_split_days_inclusive` (63/13/14 ngày), là gợi ý; split thật do pipeline huấn luyện quyết định.
7. Chuẩn hoá chỉ fit trên train. Feature trong dữ liệu là đại lượng vật lý chưa chuẩn hoá.
8. Khi mở rộng số ngày hoặc đổi case, sinh bản mới vào đường dẫn mới (generator từ chối ghi đè), rồi chạy `tools/mock_v3/refresh_clean.py`. Bản cũ đưa vào `data/_archive/`, không xoá.
9. Mọi cache dẫn xuất (`data/derived`) gắn với `data_fingerprint`; đổi dữ liệu thì phải build lại.

## 9. Giới hạn

- Dữ liệu tổng hợp: kết quả trên mock chứng minh pipeline đúng và model bắt được tín hiệu đã cài, không chứng minh hiệu quả trên dữ liệu thật.
- Hành vi khách và tài xế là luật đơn giản; không có cạnh tranh nền tảng, tài xế chạy nhiều app hay khuyến mãi.
- Booking rate, tỉ lệ nhận cuốc của tài xế, GMV, dịch vụ xe khác và res 9 không được sinh.
- Hex res 7 lớn nên D/S trong hex mượt hơn thực tế ở res 8–9.
- Utilization lấy từ mẫu cuối phút, không phải tích phân thời gian chính xác.
- Citywide trung bình che các hex thiếu và thừa xảy ra đồng thời; luôn kiểm tra ở mức hex.

## 10. Tài liệu liên quan

- `data/hcm_data_2/schema.yaml`, `meta/manifest.json`, `meta/feature_contract.json`: nguồn chuẩn.
- `docs/data/mock_data_spec_hcmc.md`: spec sinh dữ liệu và cơ sở chọn phân phối.
- `tools/mock_v3/README.md`: lệnh sinh, calibration, bộ lọc "hết xe".
- `docs/model/technical_report.md`: định nghĩa nhãn, split và mô hình (đã khoá).

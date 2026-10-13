# 02 — Data contract, lineage và chuyển HCM V2 sang training V1.2

**Trạng thái:** đặc tả để triển khai; chưa tạo dataset dẫn xuất, chưa chạy training V1.2.  
**Phạm vi:** nguồn `data/hcm_data_2`, thời gian, feature/target, graph, split, normalization, cache và điều kiện nghiệm thu.  
**Thiết kế đích:** `dual_gru_gatv2_h5_v1_2`, feature contract `hex29_edge10_v1_2`, target contract `ds_log1p_h5_v1_2`.

Từ **MUST** là yêu cầu bắt buộc để nghiệm thu. Các lựa chọn triển khai trong tài liệu này có nhãn **[Confidence: Medium — engineering decision]**; số liệu nguồn có nhãn **[Confidence: High — source/code inspected]**. Không coi nhãn confidence là giá trị do model tính.

## 1. Nguồn và thứ tự ưu tiên

| Mã | Nguồn trong repository | Nội dung đã đối chiếu |
|---|---|---|
| D1 | [manifest.json](../../data/hcm_data_2/meta/manifest.json) | Định danh nguồn, 30 ngày, số node/edge, split, fingerprint và phạm vi readiness |
| D2 | [feature_contract.json](../../data/hcm_data_2/meta/feature_contract.json) | Thứ tự 40/10 feature, 5 support, target cũ, W=4 và 3 horizon |
| D3 | [metadata.md đã lưu trữ](../../data/_archive/hcm_data_2_v2_packed/metadata.md) | Định nghĩa vật lý, lifecycle, thời gian, tensor và giới hạn dữ liệu; các đường dẫn bên trong thuộc layout packed lịch sử |
| D4 | [feature_v2.py trong source snapshot](../../data/hcm_data_2/meta/source_snapshot/mock_data_pipeline/surge_mock/feature_v2.py) | Công thức feature, graph, target, mask, normalization, sample index và checksum nguồn |
| D5 | [prepared_data.py lịch sử](../../data/_archive/hcm_data_2_v2_packed/source_snapshot_legacy_pipeline/prepared_data.py) | Loader dùng lúc xuất packed release: mmap, hard-code W=4, 40 feature và3 horizon; chỉ là evidence, không gọi trực tiếp để replay layout mới |
| D6 | [dataset_v2.py trong source snapshot](../../data/hcm_data_2/meta/source_snapshot/mock_data_pipeline/surge_mock/dataset_v2.py) | Lifecycle censoring, export raw, kiểm tra integrity nguồn |
| D7 | [readiness.json đã lưu trữ](../../data/_archive/hcm_data_2_v2_packed/reports/readiness.json), [feature_validation.json](../../data/hcm_data_2/meta/validation/feature_validation.json), [raw_integrity.json](../../data/hcm_data_2/meta/validation/raw_integrity.json) | Kết quả kỹ thuật đã lưu; không phải kết quả kiểm thử mới |
| D8 | [technical_report.md](../model/technical_report.md) | Thiết kế V1.2: hai forecast, W=12, H=5 phút, `log1p(D/S_eff)` |
| D9 | [CURRENT.json](../../data/CURRENT.json) | Root path hiện là data/hcm_data_2; embedded manifest path vẫn trỏ tên cũ không tồn tại tại snapshot03:16; không được coi pointer hoàn toàn hợp lệ |
| D10 | [schema.yaml](../../data/hcm_data_2/schema.yaml) | Table paths/layers, SQL logical types và Parquet storage của layout tree; column listing order và một số chú thích phải đối chiếu D2/D4 |

**MUST** phân biệt nguồn mô tả payload hiện có với thiết kế model đích. D8 quyết định thiết kế V1.2. D1/D2/D4 xác định cách đọc dữ liệu cũ. Không sửa lời mô tả target cũ thành target mới rồi xem checkpoint cũ là tương thích.

**Snapshot nguồn cuối khảo sát09/10/2026:** layout active đã chuyển sang `meta/`, `raw/`, `features/`, `burn_in/`, `oracle/`; manifest/feature contract giữ nguyên nội dung ngữ nghĩa và byte hash khi di chuyển. `pipeline/` chỉ còn `pyproject.toml`, `uv.lock`, `.gitignore`. Packed tensors/targets, metadata, reports và legacy source nằm trong `data/_archive/hcm_data_2_v2_packed/`. Nhận xét W4/model cũ là mô tả lịch sử; V1.2 triển khai adapter Parquet mới và tạo derivative riêng. Đường dẫn trong specs theo snapshot này, không tự sửa CURRENT hay di chuyển nguồn.

## 2. Dataset hiện có và xung đột phải xử lý

### 2.1. Những gì đã xác nhận

**[Confidence: High — D1–D7 và danh sách file thực tế.]** Thư mục đang tồn tại là `data/hcm_data_2/`. Machine manifest giữ `dataset_id=hcm_mock_v2_30d_seed42`, feature version `hex40_edge10_v2.1`.

| Thuộc tính nguồn | Giá trị |
|---|---|
| Nguồn | Synthetic, kịch bản `moderate_reposition`, seed 42 |
| Ngày của các cửa sổ sự kiện | 2026-01-05 đến 2026-02-03, đúng 30 ngày |
| Snapshot đầu và cuối | 2026-01-05 00:05:00 đến 2026-02-04 00:00:00 |
| Múi giờ ngữ nghĩa | `Asia/Ho_Chi_Minh` |
| Nhịp thời gian | 5 phút |
| Node | 61 H3 cells, resolution 7; thứ tự theo `hex_ids` trong D2 |
| Timestamp / dòng node | 8.640 / 527.040 |
| Raw order chính | 837.529, theo metadata/báo cáo đã lưu |
| Tensor node gốc | `[8640,61,40]`, float32 chưa z-score |
| Tổng hàng quan hệ graph | 7.642.890, mỗi hàng có 10 edge features |
| W và horizon packed lịch sử | 4 snapshot; 5, 10, 15 phút; active Parquet tables không gắn W/labels mới |
| Sample packed lịch sử | Train6.036; validation1.140; test1.428; sample index này nằm trong archive |
| Readiness | `training_ready_with_realism_warnings`; `deployment_ready=false` |

Fingerprint training payload **được ghi trong manifest**, chưa được tính lại trong công việc viết specs:

```text
0e1f4e179ca0c0b8263396463135a7990d7673460a336373a12feaf04122cc06
```

Đây là fingerprint từ `data/_archive/hcm_data_2_v2_packed/training_sha256.json`, không bao phủ raw/feature Parquet, metadata, config và báo cáo. Loader lịch sử D5 kiểm13 file trong `training/` của packed release; chúng hiện nằm trong archive. Fingerprint này chỉ là evidence cho các payload lịch sử đó. Adapter Parquet mới MUST tạo/xác minh inventory checksum riêng ở mục2.3; không dùng fingerprint13 file để tuyên bố Parquet active đã được xác minh. [D3–D5]

### 2.2. Bảng xung đột

| Vị trí | Giá trị/điểm xung đột | Hành vi bắt buộc khi triển khai |
|---|---|---|
| `data/CURRENT.json` | `path=data/hcm_data_2` tồn tại; embedded manifest vẫn trỏ `data/hcm_data_2/dataset_manifest.json`, hiện đã chuyển sang `meta/manifest.json`; `entrypoint=null` | Không coi root tồn tại là pointer đầy đủ hợp lệ. Config explicit `manifest_path=meta/manifest.json`, `feature_contract_path=meta/feature_contract.json` được ưu tiên và phải kiểm identity/hash. Nếu chỉ dùng broken pointer thì fail rõ; không tự sửa pointer hoặc gọi command legacy |
| Manifest `release_relative_path` | Vẫn giữ đường dẫn cũ `data/releases/hcm_mock_v2_30d_seed42` | Giữ nguyên source evidence; ghi `resolved_source_location` riêng trong provenance. Không dùng trường vị trí stale để phủ nhận CURRENT/explicit root đã được xác minh |
| Metadata packed đã lưu trữ | Human ID vẫn `hcm_data_2`, khác machine ID; các ví dụ file/subfolder thuộc layout trước khi reorganize | Dùng cho công thức và lịch sử, không dùng làm physical path resolver. Machine manifest là định danh nguồn; alias không đổi machine ID |
| Metadata V1 đã quan sát trước đó | Dataset61 ngày, epsilon0.001, path hcm_data | Không dùng cho V2/V1.2 hoặc suy resolver từ tên gần giống |
| D2/D5 so với D8/D10 | Meta contract giữ mô tả packed W4/H3/target cũ, trong khi active tree chỉ chứa source tables; V1.2 yêu cầu W12/H5/log1p tỷ lệ thật | Phân biệt archived training semantics với source-table semantics; tạo derivative contract, target, sample index, scaler và checkpoint mới |
| `normalization.npz` cũ | Fit trên mọi dòng train nguồn | Fit lại theo phạm vi train thực sự của contract mới; không tái sử dụng chỉ vì chọn một subset feature |

CURRENT chưa được coi là fully valid vì embedded manifest stale. Config trong specs dùng source root/layout/metadata paths tường minh để resolve có kiểm chứng. Reconcile pointer hoặc chọn derivative làm active dataset là thao tác publication riêng sau validation; công việc viết specs không tự đổi pointer hay payload. **[Confidence: High — snapshot nguồn cuối; Medium — quy trình publication đề xuất.]**

### 2.3. Nguồn mặc định của adapter V1.2 và phạm vi checksum

**[Confidence: Medium — quyết định implementation.]** Default `source_format=hcm_v2_parquet`, `source_layout_id=hcm_v2_parquet_tree_v1` đọc trực tiếp cây Parquet active, không import `PreparedDataset` lịch sử hoặc dùng archive NPY làm đường tắt. Resolve metadata từ `data.manifest_path=meta/manifest.json`, `data.feature_contract_path=meta/feature_contract.json`, relative với explicit active source root. `prepare` chuẩn hóa bảng nguồn về ordered grid, rồi materialize derivative bất biến, mmap-ready.

`data.source_schema_path=schema.yaml` là authority cho table path/layer. Byte hash D10 tại snapshot tham chiếu là `b6673dd8290caea3ac76cc22a18b60cf8acf024e2344f785e315002312401995`; lưu thành `source_schema_sha256` trong source/derivative lineage. Không dùng thứ tự trình bày cột trong YAML làm tensor order: named selection MUST theo canonical `meta/feature_contract.json.node_features/edge_features/hex_ids`.

| Nhóm nguồn | Cách dùng mặc định |
|---|---|
| `features/hex_features/` | Parquet40 cột vật lý theo D2 cùng5 support; chọn29 cho model chính, giữ source values cho target/sidecar và baseline40 |
| `features/graph_edges/` | Typed adjacency/OD theo timestamp, source, destination và10 edge attributes |
| `raw/hexes/` | Đối chiếu geography/hex mapping với D2; không tự sort lại H3 IDs |
| `raw/hex_snapshot/` | Đối chiếu demand/supply raw với `demand_5m`/`idle_supply_t` theo `(ts,hex_id)`; không tự thay effective supply bằng idle |
| `raw/orders/`, `raw/weather/`, `burn_in/hex_snapshot/`, `burn_in/orders/`, `burn_in/weather/` | Validation/cutoff/lifecycle, weather và past context; không join future actual lifecycle vào input đã dựng |
| `meta/generator_config.yaml`, `meta/source_sha256.json`, `meta/source_snapshot/` | Provenance công thức/config; không đưa config signal ẩn vào encoder |
| `meta/validation/` | Báo cáo integrity đã lưu; không coi đó là verification receipt của derivative mới |
| Archive `data/_archive/hcm_data_2_v2_packed/training/`, `targets/`, `training_sha256.json` | Compatibility/audit hoặc explicit legacy replay, không thuộc active Parquet input allowlist |
| Archive `source_snapshot_legacy_pipeline/` | Bằng chứng code cũ; không gọi loader đó với giả định đường dẫn packed còn tồn tại trong active root |

Inventory policy `raw_features_burn_in_v1` MUST liệt kê tất cả Parquet dưới `raw/`, `features/`, `burn_in/` theo relative path chuẩn hóa `/`, gồm `byte_size`, `sha256`, `row_count`, `arrow_schema_sha256` và role `prepare`/`validation`. Scanner recursive chỉ trong allowlist này, không giả định filename hoặc partition depth ngoài source_layout_id. Bất kỳ file bị thêm, bớt hoặc thay byte sau freeze inventory đều làm verification fail. `oracle/` và archive không thuộc active input allowlist; đổi tên từ diagnostics sang oracle không làm private data trở thành feature hợp lệ.

Ghi inventory vào `source_parquet_manifest.json` trong derivative provenance, không ghi vào source. `source_parquet_sha256` là SHA256 của canonical semantic projection `{schema_version, source_layout_id, inventory_policy, files}` với files sort theo relative path; chính trường digest, absolute source root và verified_at nằm ngoài projection. Hash schema Arrow dùng canonical logical fields/type/nullability, không đưa metadata timestamp kiểm tra vào digest. JSON/YAML metadata nguồn có checksum riêng, không ngụy trang thành Parquet entry. Di chuyển cả root mà giữ relative tree không đổi digest; reorganize relative tree/layout có thể đổi inventory digest dù ngữ nghĩa feature/target không đổi, và phải được ghi là layout/provenance change.

Với `legacy_replay`, `data.source_root` vẫn là active root để resolve `meta/manifest.json` và `meta/feature_contract.json`; thêm `data.legacy_archive_root=data/_archive/hcm_data_2_v2_packed`. `source_format=legacy_training_npy`, `derivative_storage=legacy_readonly` đọc explicit archive `training/`, optional `targets/`, checksum map rồi kiểm against active machine contract. Bảng `legacy_archive_root/training_sha256.json` có13 basename keys; resolve từng key thành `legacy_archive_root/training/<basename>`, không nối thẳng vào archive root. `targets/day01…day30.parquet` nằm ngoài checksum13 file; nếu replay đọc chúng phải có checksum scope riêng. Profile V1.2 đặt `legacy_archive_root=null`. Viết adapter mapping mới, không invoke old loader rồi trông chờ paths cũ, không restore/mutate archive và không đưa old W4 labels vào model V1.2.

Ở lần prepare đầu, `expected_source_parquet_sha256` có thể null và contract mẫu có `source.parquet_sha256_recorded=null`. Builder phải freeze file inventory trước scan, xác minh lại rằng nguồn không đổi trong khi materialize, rồi ghi digest vào resolved config/derivation receipt. Training chỉ load derivative finalized có receipt và digest đã resolve, kể cả YAML gốc dùng expected=null; null không phải quyền bỏ qua verification. Tính checksum lần đầu xác nhận snapshot byte đã sử dụng; nó không chứng minh các byte đó giống bản sinh ban đầu nếu không có reference checksum trước đó. Fingerprint13 file lịch sử và inventory Parquet mới phải được báo riêng, cùng phạm vi chứng minh của mỗi loại.

### 2.4. Discrepancies của schema mô tả, rule triển khai có hiệu lực

| Nội dung D10 | Đối chiếu nguồn/thiết kế | Rule bắt buộc |
|---|---|---|
| Cột node được nhóm lại để đọc, khác order D2 | D2 giữ canonical40 order dùng lúc xuất | Select theo tên rồi reindex theo D2; không dùng vị trí YAML |
| `graph_edges.primary_key=[ts,src_hex,dst_hex]` | Exporter D4 xuất adjacency và OD riêng dù cùng cặp | Effective key=`(ts,src_hex,dst_hex,edge_is_adjacent,edge_is_od)`; giữ typed multiedges, không dedup theo triple |
| Orders partition comment ghi date của created_ts | Export convention right-closed dùng `created_ts−1 microsecond` | Lọc membership bằng actual event timestamp; kiểm midnight theo exporter. Không suy order đúng00:00 thuộc ngày sau chỉ vì comment |
| Seff/arrivals/inflow có `group:local` | Khác cách gọi nhóm aggregate trước đây; field names/formulas không đổi | View29 là engineering ablation theo D2 indices0..28. Không khẳng định11 cột loại ra đều thuộc network theo taxonomy YAML |
| Entropy được mô tả từ smoothed destination distribution | D4 tính `p=R_ij/sum_j R_ij` chưa smoothing; smoothing0.1 dùng cho transition probability riêng | Giữ entropy unsmoothed theo exported formula, không đổi feature để khớp câu mô tả |
| Surge raw có mô tả range1.0…2.6 và “in force at ts” | Generator source có post-update timing và bounds riêng; mô tả chưa đủ làm policy cap | Không lấy2.6 làm global controller cap hoặc đổi effective timing; giữ nguồn/generator contract và ghi discrepancy nếu validation cần range |

Builder MUST xuất `schema_discrepancies.json` với những rule override đã được specs version hóa, source schema hash và actual key/partition validation. Known documentation mismatch không được sửa bằng cách xóa duplicate đúng quan hệ hoặc thay feature formulas. Khác biệt không có rule rõ phải fail compatibility trước materialize. Đây là đối soát tài liệu với exporter, không phải sửa schema nguồn trong công việc viết specs.

## 3. Hợp đồng đích và lớp tương thích

### 3.1. Tách ba định danh

1. `source_dataset_id`: ID trong machine manifest nguồn, kèm `source_parquet_sha256` mới và `source_training_fingerprint` lịch sử được phân biệt rõ phạm vi.
2. `training_dataset_id`: ID của dataset dẫn xuất có W12, H5, split/mask/scaler mới.
3. `model_contract_id`: tập input/output và transform model phải tuân theo.

Contract mới MUST khai báo độc lập:

```yaml
feature_contract_id: hex29_edge10_v1_2
target_contract_id: ds_log1p_h5_v1_2
source_feature_contract_id: hex40_edge10_v2.1
source_format: hcm_v2_parquet
source_layout_id: hcm_v2_parquet_tree_v1
manifest_path: meta/manifest.json
feature_contract_path: meta/feature_contract.json
source_schema_path: schema.yaml
parquet_inventory_policy: raw_features_burn_in_v1
legacy_archive_root: null
derivative_storage: mmap_npy
window_steps: 12
step_minutes: 5
horizons_minutes: [5]
node_selection: source_node_features[0:29]
edge_selection: source_edge_features[0:10]
graph_policy_id: directed_relations_self_v1
target_denominator: effective_supply_v2
target_denominator_policy: strictly_positive_mask_otherwise
target_epsilon: null
history_policy: direct_window_within_split_past_rolling_context_allowed
purge_minutes: 30
timezone_semantics: Asia/Ho_Chi_Minh_local_naive_source
```

Đây là schema thiết kế, không phải file config đã cài đặt. Cấu hình chạy thực tế MUST dùng danh sách tên feature đầy đủ hoặc các index đã resolve và hash; biểu thức slice ở ví dụ chỉ giải thích lựa chọn.

### 3.2. Tách input và dữ liệu phụ

Default encoder chỉ nhận **29 cột đầu**. Nguồn 40 cột được giữ nguyên để truy xuất vật lý, audit và baseline ablation. `effective_supply_t` ở index 29 chỉ đi vào target, persistence baseline, phân nhóm và controller/audit theo contract; nó không tự được nối vào encoder mặc định.

29 cột đầu được gọi là **pointwise local/context view**. Đây là engineering view theo D2, không phải phép chọn tất cả field có `group:local` trong D10; schema mới còn gán Seff/arrivals/inflow vào local. ETA có thể dựa vào tài xế hex lân cận; vì vậy không quảng bá view29 là tách biệt hoàn toàn với thông tin mạng hoặc11 cột loại ra đều có taxonomy network. Baseline40 không message passing là ablation bắt buộc cho information set rộng hơn. [D2/D3/D8/D10; Confidence: High — thông tin nguồn; Medium — lựa chọn view.]

Không thêm 5 support columns vào tensor mặc định. Nếu sau này muốn model biết cohort size hay fallback P90, tạo feature contract khác và benchmark riêng.

## 4. Danh sách feature nguồn và feature view V1.2

Thứ tự dưới đây MUST khớp D2. Không sort tên cột; không xem cột có cùng tên nhưng khác công thức là tương thích. Raw count giữ đơn vị vật lý, không áp `log1p` toàn bộ count trước normalization.

### 4.1. View mặc định: index 0–28

| Index | Feature | Định nghĩa/đơn vị |
|---:|---|---|
| 0 | `demand_5m` | Request mới trong `(t−5m,t]` |
| 1 | `idle_supply_t` | Số tài xế rảnh tại t |
| 2 | `backlog_t` | Request đã tạo, chưa accepted/cancelled tại t |
| 3 | `eta_sec_t` | Pickup ETA hiện tại, giây |
| 4 | `local_pressure_log_t` | `log1p(D_t)−log1p(idle_t)`; đây là một input có công thức legacy, không phải target V1.2 |
| 5 | `demand_sum_15m` | Tổng D của 3 snapshot cuối |
| 6 | `demand_mean_60m` | Mean D của 12 snapshot cuối |
| 7 | `demand_std_60m` | Population std D của 12 snapshot cuối |
| 8 | `demand_momentum_15m` | Tổng D 15 phút hiện tại trừ tổng D 15 phút trước đó |
| 9 | `idle_supply_mean_15m` | Mean idle của 3 snapshot cuối |
| 10 | `idle_supply_momentum_15m` | `idle_t−idle_(t−15m)` |
| 11 | `match_rate_matured_15m` | `(matched_within_5m_count+1)/(mature_request_count_15m+2)` |
| 12 | `cancel_rate_matured_15m` | `(cancelled_within_5m_count+1)/(mature_request_count_15m+2)` |
| 13 | `pickup_wait_p90_30m` | P90 created→pickup của pickup trong `(t−30m,t]`, giây; thiếu support thì fallback ETA tại t |
| 14 | `current_surge_t` | Surge snapshot sau cập nhật, hiệu lực cho bước tiếp theo theo simulator |
| 15 | `surge_delta_15m` | Chênh surge tại t và t−15 phút |
| 16 | `rain_intensity_t` | Cường độ mưa synthetic tại t |
| 17 | `hour_sin` | `sin(2π hour/24)`; có phút lẻ |
| 18 | `hour_cos` | `cos(2π hour/24)` |
| 19 | `dow_sin` | `sin(2π dow/7)`; thứ Hai = 0 |
| 20 | `dow_cos` | `cos(2π dow/7)` |
| 21 | `is_weekend` | Thứ Bảy/Chủ nhật theo local timestamp |
| 22 | `zone_airport` | One-hot zone |
| 23 | `zone_cbd` | One-hot zone |
| 24 | `zone_office` | One-hot zone |
| 25 | `zone_residential` | One-hot zone |
| 26 | `zone_suburb` | One-hot zone |
| 27 | `zone_venue` | One-hot zone |
| 28 | `ring` | Vòng H3 tới tâm |

Rate cohort gồm request tạo trong `(t−20m,t−5m]`, mỗi request được theo dõi 5 phút kể từ creation. Hai rate có thể cùng ghi nhận một request; không bắt chúng cộng thành 1. Khi support=0, prior Beta(1,1) cho 0.5; đó là fallback, không phải 50% conversion đã quan sát. Đây không phải quote booking rate hoặc offer acceptance. [D2–D4; Confidence: High — công thức source.]

### 4.2. 11 cột nguồn còn lại: audit và baseline 40 features

| Index | Feature | Định nghĩa/đơn vị |
|---:|---|---|
| 29 | `effective_supply_t` | `idle + C_(≤5) + 0.5 C_(5,10] + 0.2 C_(10,15]` |
| 30 | `arriving_trip_count_eta_0_5_t` | Chuyến active có ETA còn lại ≤5 phút; gồm ETA quá hạn |
| 31 | `arriving_trip_count_eta_5_10_t` | Chuyến active ETA `(5,10]` phút |
| 32 | `arriving_trip_count_eta_10_15_t` | Chuyến active ETA `(10,15]` phút |
| 33 | `completed_inflow_15m` | Dropoff tại hex trong 15 phút cuối |
| 34 | `pickup_outflow_15m` | Pickup có origin tại hex trong 15 phút cuối |
| 35 | `neighbor_demand_mean_t` | Mean D của các hex kề có trong miền, loại chính node |
| 36 | `neighbor_idle_supply_mean_t` | Mean idle của cùng tập hàng xóm |
| 37 | `neighbor_pressure_mean_t` | Mean `local_pressure_log_t` của hàng xóm |
| 38 | `od_destination_entropy_30m` | Entropy, nat, của phân phối request OD chưa làm mượt trong 30 phút |
| 39 | `od_support_30m` | Tổng request xuất phát tại hex trong 30 phút, gồm nội hex |

Supply này là proxy quy đổi bằng trọng số cố định của V2. Nó không biểu diễn đầy đủ reposition, online/offline hoặc khả năng chắc chắn có tài xế khi khách đặt. Repositioning driver chưa khả dụng đến khi tới nơi theo simulator. Không thêm driver audit vào encoder để “hoàn thiện” supply. [D1/D3/D4/D6]

### 4.3. Support và mask khác nhau

Support có thứ tự: `mature_request_count_15m`, `matched_within_5m_count`, `cancelled_within_5m_count`, `pickup_wait_support_30m`, `history_steps_available`. `feature_support.npy` có shape `[8640,61,5]` float32. Đây là số lượng quan sát/support để audit.

MUST tách `input_valid`, `target_valid`, `current_ratio_valid`, `support_sufficient`. Feature hữu hạn do fallback không có nghĩa support cao. Target không hợp lệ không có nghĩa demand/supply đầu vào bị thiếu. Không dùng `mask_y` để zero input hoặc dùng feature support làm sample weight mà chưa có cấu hình nghiên cứu riêng.

### 4.4. Edge features gốc, đúng thứ tự

| Index | Feature | Định nghĩa |
|---:|---|---|
| 0 | `edge_is_adjacent` | Cờ hàng adjacency |
| 1 | `edge_is_od` | Cờ hàng OD |
| 2 | `distance_km` | Khoảng cách Haversine tâm hex; nội hex bằng 0 |
| 3 | `travel_time_est_min` | Mean duration của completed OD trong trailing 30 phút; thiếu thì prior hình học |
| 4 | `od_requests_5m` | Request theo chiều source→destination trong 5 phút |
| 5 | `od_requests_30m` | Request OD trong 30 phút |
| 6 | `od_completed_15m` | Completed OD trong 15 phút |
| 7 | `od_in_trip_count_t` | Chuyến OD đang active |
| 8 | `od_arrivals_eta_le5m_t` | Active OD có ETA còn lại ≤5 phút |
| 9 | `od_transition_prob_30m` | `(R_ij+0.1)/(sum_j R_ij+0.1×61)` |

Rows adjacency có các cột 4–9 bằng 0 theo quan hệ, không có nghĩa OD cùng cặp chắc chắn không có request. Transition probability làm mượt trên toàn 61 đích trước khi lọc cạnh active; tổng trên cạnh OD được export không bắt buộc bằng 1. Prior travel là `2+1.3×distance/28×60` phút, khoảng cách prior nội hex 1.16 km; không thay đổi cột distance nội hex từ 0 thành 1.16. [D2–D4]

## 5. Thời gian, cutoff và lifecycle

### 5.1. Biên cửa sổ

Snapshot ở t chứa sự kiện `(t−5 phút,t]`. Main dataset lấy endpoint lớn hơn 2026-01-05 00:00 và nhỏ hơn hoặc bằng 2026-02-04 00:00. `end_exclusive` trong manifest mô tả khoảng ngày, nhưng endpoint đóng cửa sổ cuối vẫn được giữ. Không loại dòng cuối bằng phép `<end_exclusive` áp vào snapshot.

Partition snapshot/weather/features theo ngày của `ts−5 phút`; partition orders theo ngày `created_ts−1 microsecond`. Order đúng 00:00 thuộc cửa sổ đóng của ngày trước. Ngày split MUST xuất phát từ contract cửa sổ, không dùng `ts.date()` một cách độc lập. [D3/D4]

Source Parquet timestamps là local-naive; `timestamps_ns.npy` trong packed archive cũng giữ nanosecond của datetime-naive. Adapter MUST localize `Asia/Ho_Chi_Minh` trước khi convert UTC; không diễn giải integer nguồn như Unix UTC rồi chỉ gắn nhãn local. Có thể giữ mapping cả `source_ts_ns` và `decision_ts_utc` trong sample provenance; hash phải xác định rõ ngữ nghĩa timestamp đã chọn.

### 5.2. Prefix invariance

Mọi input của cutoff t chỉ được dùng event đã quan sát tại t. Với source mock không có ingestion delay riêng, điều kiện là `event_ts≤t`. Contract production thêm `available_at≤t` cho event/snapshot/ETA. Đích order và initial estimated duration đã biết khi creation; không dùng future actual dropoff hoặc duration để xây inbound.

Chuyến active khi pickup đã quan sát, chưa dropoff/cancel đã biết tại t. Null lifecycle phải giữ trạng thái mở. ETA còn lại lấy `pickup_ts+initial_estimate−t`; chuyến quá estimated arrival vẫn active và ở bucket ≤5 phút đến khi có sự kiện kết thúc. Burn-in một ngày trong `burn_in/` giữ historical features và chuyến qua đầu main period; đây là layer từng tên context trong packed layout. Các lifecycle của burn-in order cũng phải censor theo cutoff đang replay, không dùng event xảy ra sau cutoff chỉ vì order được tạo ngày trước. [D3/D4/D6/D10]

Direct model window W12 gồm endpoints `t−55,…,t`, tổng 12 snapshot, không phải 13. Rolling feature ở endpoint đầu có thể đọc thêm quá khứ; ví dụ mean60 tại t−55 có event support `(t−115,t−55]`. Carryover lifecycle còn có thể bắt đầu sớm hơn. MUST ghi rõ policy cho past context; không đồng nhất 60 phút input endpoints với toàn bộ historical support của feature.

Source report lưu prefix replay tại ba mốc 25%, 50%, 75%; đó là bằng chứng kỹ thuật có giới hạn. Contract mới phải bổ sung fixture midnight, boundary split, active trip qua cutoff, late event và unknown future fields. Không coi ba prefix source đã đủ kiểm toàn bộ production ingestion. [D4/D7]

### 5.3. Những trường cấm đi vào input

`oracle/signal_truth/`, `oracle/order_audit/`, `oracle/calendar.json`, `oracle/driver_stats/`, dispatch deadline, patience deadline, driver availability audit, future actual duration, target ở t+5 và volume ở t+5 MUST không nằm trong node/edge input. Quy tắc tương tự áp cho alias diagnostics trong source lịch sử. Không dùng forecast mask hoặc trạng thái hoàn tất export để lọc chuyến đang chạy ở cutoff quá khứ.

## 6. Target V1.2 và inverse đúng

### 6.1. Định nghĩa vật lý

Với index k sau khi reindex Parquet, D lấy cột `demand_5m` và S_eff lấy `effective_supply_t` tại endpoint k+1. D phải khớp cột demand của bảng `raw/hex_snapshot/` qua join `(ts,hex_id)`. Vị trí nguồn đã biết lần lượt là0 và29 trong D2; vị trí giúp kiểm schema, không cho phép bỏ qua name/formula check hoặc đọc normalized tensors. Hai head có cùng nhãn:

\[
q_{i,k+1}=\frac{D_{i,k+1}}{S^{eff}_{i,k+1}},\qquad
y_{i,k}=\log(1+q_{i,k+1}).
\]

Domain hợp lệ: `D` hữu hạn và ≥0; `S_eff` hữu hạn và >0; k+1 tồn tại và cùng split. Zero demand với supply dương cho `q=0,y=0`, hợp lệ. `S_eff=0`, gồm cả 0/0, bị mask; không thêm epsilon, không đặt q=0, không tạo finite shortage label tùy ý. Mask này làm evaluation chỉ bao phủ nhãn quan sát hợp lệ; MUST báo riêng coverage và zero-supply segment để tránh kết luận chất lượng trên các node đã bị loại. **[Confidence: High — toán học; Medium — denominator/masking contract đã chọn.]**

Không inverse legacy `log((D+1)/(S_eff+1))` để lấy D/S thật. `exp(y_legacy)` chỉ cho tỷ lệ có cộng 1. `expm1(y_legacy)` cũng không cho D/S thật. Cần tính lại từ hai biến vật lý riêng.

Model dùng `y` theo log1p; inverse dự báo là `q_hat=expm1(y_hat)` sau kiểm domain/output theo model contract. Hai head MUST dùng cùng transform, denominator, H và node ordering. Hàm persistence baseline dùng `q_t` thực khi `S_eff_t>0`; chỗ không hợp lệ phải có mask baseline riêng, không lấy `baseline.npy` cũ làm q_t.

### 6.2. Schema derivative target

| Field | Shape | Kiểu/ý nghĩa |
|---|---|---|
| `q_h5` | `[T,N,1]` | float64, tỷ lệ raw future; invalid giữ NaN trong artifact |
| `y_log1p_h5` | `[T,N,1]` | float32, target log1p; invalid NaN |
| `target_valid` | `[T,N,1]` | bool |
| `invalid_reason_bits` | `[T,N,1]` | uint8: 1 vượt cuối; 2 qua split; 4 nonfinite; 8 D âm; 16 S_eff không dương; 32 overflow khi chuyển dtype |
| `target_ts` | `[T]` | Timestamp của endpoint t+5 hoặc giá trị missing rõ ràng tại cuối |

Lưu q_h5 từ phép chia raw bằng float64; tính log1p bằng float64 rồi chỉ cast y_log1p_h5 sang float32 cho training. target.output_dtype=float32 trong YAML áp dụng cho y; không cast q xuống float32 rồi nâng lại để gọi đó là raw float64 truth. Transform, type, tolerance và mask reason MUST được version. Trong batch, có thể thay NaN invalid bằng 0 để tránh số học NaN, nhưng loss MUST boolean-select phần tử hợp lệ trước aggregate. Không nhân `NaN×0` rồi kỳ vọng kết quả hữu hạn. Batch không có valid label không tạo optimizer step và phải được đếm; epoch train không có label hợp lệ là lỗi.

`future volume` không được đưa vào input; loss mặc định không weight bằng nó. Dùng volume/source support cho audit được phép nếu công thức và tập dữ liệu được log rõ.

## 7. Split và sample eligibility

### 7.1. Giữ khoảng ngày 21/4/5

| Split | Index timestamp `[a,z)` | Ngày cửa sổ | Timestamp nguồn |
|---|---|---|---:|
| Train | `[0,6048)` | 05/01–25/01/2026 | 6.048 |
| Validation | `[6048,7200)` | 26/01–29/01/2026 | 1.152 |
| Test | `[7200,8640)` | 30/01–03/02/2026 | 1.440 |

Tách theo toàn graph timestamp, không chia node row ngẫu nhiên giữa train/validation/test. Một thời điểm có 61 node liên hệ; sample ID là `(derivation_spec_hash,k)`, node-label ID thêm `hex_id,horizon`.

### 7.2. Công thức chọn sample mới

W=12, H=1 bước, purge G=6 bước. Với mỗi split `[a,z)`, candidate:

```python
candidate_k = range(a + (W - 1), z - G - H)
```

Đây là quy tắc kế thừa khoảng trống 30 phút của source với window/horizon mới: direct history `[k−11,k]` ở cùng split; target `k+1` ở cùng split; 6 snapshot endpoint cuối split không được sử dụng làm target. Với snapshot cuối split là boundary đóng cuối ngày, target cuối hợp lệ là 23:30, cutoff sample cuối 23:25.

| Split | Candidate W12/H5 | Cutoff đầu/cuối | Node-target slots trước domain mask |
|---|---:|---|---:|
| Train | **6.030** | 05/01 01:00 → 25/01 23:25 | 367.830 |
| Validation | **1.134** | 26/01 01:00 → 29/01 23:25 | 69.174 |
| Test | **1.422** | 30/01 01:00 → 03/02 23:25 | 86.742 |
| Tổng | **8.586** | W12/H5 | 523.746 |

**[Confidence: High — số học từ T/split nguồn và rule ở trên.]** Đây là candidate counts của thiết kế, chưa phải số mẫu/nhãn V1.2 đã được đo. Giữ mọi temporal candidate có input hợp lệ trong candidate manifest cho inference/evaluation/coverage, kể cả timestamp không có target hợp lệ. Optimizer subset chỉ gồm sample có ít nhất một node target hợp lệ; giữ mask theo node. Count thực tế và số all-masked timestamp phải do builder xuất. Không yêu cầu mọi node của một graph đều có target hợp lệ vì điều này có thể loại mất phần lớn graph khi có zero-supply node.

`legacy_archive_root/training/sample_index.parquet` chỉ dùng cho đối chiếu legacy; MUST không reuse cho W12. History trực tiếp vẫn nằm trong split; rolling đã quan sát trước boundary được phép dùng làm context. Rule này không tuyên bố mẫu thời gian độc lập; CI/evaluation phải xét tương quan thời gian.

### 7.3. Những cột sample index mới

`sample_id`, `k`, `decision_ts`, `target_ts`, `split`, `history_start_k`, `history_end_k`, `valid_target_nodes`, `input_valid`, `exclusion_reason`. Có thể lưu mọi candidate và cờ eligibility hoặc lưu một bảng eligible cộng bảng excluded riêng; phải truy vết được tất cả exclusions. Sorted `(split,k)` deterministic; shuffle chỉ thực hiện trong train iterator với seed của run.

## 8. Normalization và tính đồng nhất offline/serving

**[Confidence: Medium — lựa chọn implementation.]** Node scaler mới fit trên mọi input-valid node thuộc hợp các index lịch sử `[k−11,k]` của **sample train eligible**; mỗi raw node-time chỉ góp một lần dù xuất hiện trong nhiều overlapping windows. Edge scaler fit trên mọi typed observed edge row hợp lệ ở **cutoff k của sample train eligible**. Validation/test không được tham gia fit. Không chọn từng node/edge bằng future target_valid khi fit scaler hay xây input graph.

Chọn z-score cho tất cả 29 cột node và 10 cột edge gốc, gồm one-hot/relation flags, để giữ quy tắc đơn giản gần với source. `std` là population std, tính bằng accumulator float64; `std<1e−6` được thay bằng 1. Không loại cột constant âm thầm. Log số hàng thực fit và cột constant.

MUST lưu `node_mean[29]`, `node_std[29]`, `edge_mean[10]`, `edge_std[10]`, feature order, hex order, fit split/sample hash, population convention, std floor và scaler digest. Baseline all40 có scaler tương ứng 40 cột, cùng sample eligibility; không lấy mean29 áp cho40.

Target ratio tính từ raw D/S_eff, không từ dữ liệu đã chuẩn hóa. Cờ synthetic reverse/self của GAT được thêm sau scaling, không đi vào fit 10 chiều edge source. Synthetic self-loop có 10 thuộc tính chuẩn hóa bằng 0 theo model graph policy, reverse=0,self=1. Node/edge source flags được dùng để xác định quan hệ trước scaling nếu cần phân nhóm.

Một preprocessing implementation hoặc shared versioned transform MUST phục vụ cả offline batch và serving. Test cùng input snapshot phải cho cùng feature, ordering và normalization trong tolerance đã công bố. Không fit lại scaler lúc model load hoặc khi inference.

## 9. Graph representation và batching

Adapter Parquet ánh xạ `src_hex/dst_hex` sang index trong ordered `hex_ids`, bảo toàn relation identity, rồi materialize derivative `edge_src/dst` integer, `edge_attr` float32 và `edge_ptr` int64. Profile61 node cho phép storage index int16; config mở rộng N phải chọn int32/int64 đủ miền, không overflow hoặc hard-code model N. Cutoff k lấy interval `[edge_ptr[k],edge_ptr[k+1])`; thứ tự deterministic `(k,relation_type,src_idx,dst_idx)` và duplicate cùng typed key bị reject. Preserve chiều source→destination. OD active khi có request trailing30 hoặc completed trailing15 hoặc in-trip; adjacency và OD cùng cặp là hai hàng khác quan hệ. Genuine OD self-row phải được giữ. Source NPY lịch sử có cùng họ layout nhưng không được xem là derivative V1.2. [D2/D4]

Default `directed_relations_self_v1`: giữ mọi typed observed edge; thêm đúng một synthetic self-loop/node; không sinh reverse edge. Internal edge vector có 12 chiều: 10 source values đã scale + `[is_reverse,is_self]`. Cả hai flag observed row bằng 0. Flag reverse vẫn có vị trí cố định để schema ổn định; reverse-augmented variant là ablation và cần graph policy ID khác.

MUST không coalesce chỉ theo `(src,dst)`, không gọi tiện ích xóa mọi self-edge trước thêm loop, không bật GAT auto-add-self-loop nếu đã bổ sung loop thủ công. Với graph batch B, node index của sample b cộng offset `b×N`; không có cạnh xuyên sample. `edge_batch` phải khớp pointer slices. Temporal history là node sequence, graph mặc định chỉ lấy cutoff cuối t.

Batch model default:

| Field | Shape | Nội dung |
|---|---|---|
| `x` | `[B,12,61,29]` | Selected raw view sau scaler |
| `y` | `[B,61,1]` | `y_log1p_h5`; invalid có safe placeholder trong batch |
| `target_valid` | `[B,61,1]` | Boolean supervision mask |
| `edge_index` | `[2,E_batch]` | int64 sau offset và graph policy |
| `edge_attr` | `[E_batch,12]` | Edge model input |
| `sample_id`, `decision_ts`, `target_ts` | `[B]` | Provenance |
| `raw_d_t`, `raw_seff_t`, `q_t_valid` | `[B,61]` | Side metadata/persistence; không tự truyền vào encoder |

## 10. Bộ nhớ, cache và IO

**[Confidence: High — tính từ shape/dtype D1/D3/D4, không phải đo peak RSS.]** Trong export NPY lịch sử, raw `node.npy` chiếm80,42 MiB payload; raw `edge_attr.npy`291,55 MiB; source/destination index mỗi file14,58 MiB. Tổng payload11 `.npy` khoảng **422,87 MiB**. Đây chỉ là tham chiếu dung lượng; không phải byte inventory Parquet mới hoặc RAM training bắt buộc. Nó chưa gồm headers, sample Parquet, normalization, Python objects hoặc torch activations.

`prepare` MUST scan Parquet theo partition/record batch, map ordered keys và ghi derivative arrays theo chunk; không gom toàn raw/orders hoặc toàn edge DataFrame vào RAM. Derivative giữ `raw_node40.npy[T,N,40]` float32 chưa z-score để cả study baseline29/40 dùng cùng nguồn. Model chính chọn view `[...,0:29]`; baseline aggregate chọn đủ40. Không xóa11 cột còn lại khỏi derivative hoặc cần quay lại đọc source cho mỗi baseline.

Sidecars `raw_demand.npy[T,N]` và `raw_effective_supply.npy[T,N]` dùng float64, materialize từ cột Parquet có tên đúng trước khi cast node feature matrix sang float32. Chúng bảo toàn độ chính xác hiện có của source type, không tuyên bố phục hồi precision mà source đã làm tròn. Tính q từ sidecars này, không từ z-score, legacy baseline hoặc future target mask.

Derivative còn lưu support, timestamps, typed observed edge arrays/pointers, target/masks/candidate và optimizer indices. `normalization_context29.npz` và `normalization_aggregate40.npz` fit trên cùng hợp eligible train rows; mỗi file có ordered node stats tương ứng29/40 và edge stats cùng cutoff scope. Raw mmap cache được chia sẻ; normalized views chỉ materialize theo batch. Train/validation loaders chỉ nhận split-scoped index view và target payload phù hợp, không tự enumerate test indices hoặc mở raw source. Không reuse normalization legacy.

Nếu materialize toàn bộ8.586 candidate window của cả40 cột, riêng X lặp lịch sử sẽ khoảng **959,01 MiB**. Vì vậy training loader MUST mmap **derivative** read-only, slice theo minibatch và chỉ copy contiguous block cần cho torch. Không mở Parquet lặp lại cho từng minibatch, không `.copy()` toàn derivative node/edge arrays hoặc tạo dense `[T,N,N,F_e]`. Edge slicing theo pointer giúp tránh scan toàn E mỗi batch. Không âm thầm bỏ qua Parquet adapter để load `legacy_archive_root/training/node.npy` bằng legacy loader.

Node input batch32 cho view29 chỉ khoảng **2,59 MiB** float32; đây chưa gồm tensors trung gian và gradients. Batch size, số worker, prefetch và pin memory phải cấu hình theo runtime. CPU smoke default worker0 tránh mỗi Windows worker spawn nhân bộ nhớ/Python state; GPU/full run có thể tăng sau profiling. Đây là default kỹ thuật, không phải giới hạn dataset.

Cache key MUST gồm **source Parquet inventory fingerprint**, checksum/semantic digest nguồn cần diễn giải dữ liệu, selected features, node order, target/mask policy, window/horizon/split, graph policy và scaler fit policy. Fingerprint13 file training lịch sử không thay thế Parquet inventory trong cache key. Absolute source path, output directory và timestamp chạy không tạo identity khoa học mới. Cache hit chỉ khi manifest/hash kiểm tra hợp lệ; path tồn tại không đủ. Checksum có thể stream4 MiB chunks; một stage kiểm toàn vẹn rồi truyền receipt nội bộ, không hash toàn nguồn lại mỗi minibatch.

## 11. Lineage và dataset publication

Derivative phải materialize các arrays cần cho minibatch; có thể tham chiếu immutable Parquet source artifact thay vì copy thêm toàn raw Parquet. MUST bảo đảm URI nguồn, inventory checksum và contract đủ để prepare lại ở môi trường khác; không chỉ lưu đường dẫn ổ D. Model checkpoint chứa preprocess/model contract cần cho inference; training dataset manifest giữ lineage đầy đủ riêng.

Semantic fingerprint mới được tính từ canonical JSON có key sorted, UTF-8, quy tắc separators/number/array order cố định, gồm:

- Source Parquet inventory fingerprint, **source_schema_sha256**, source layout ID, source training fingerprint lịch sử có scope riêng, digest feature contract và digest semantic subset của source manifest. Semantic subset loại `release_relative_path`, absolute location và `generated_at_utc`; checksum toàn manifest gốc vẫn được lưu riêng trong provenance để kiểm tra tài liệu nguồn.
- Raw source/code provenance dùng thực tế; timezone/cutoff và hex order.
- Feature view/formulas, target transform/denominator/mask, W/H, split/purge/history policy.
- Sample index digest, target payload digest, scaler digest, graph policy.

Không đưa fingerprint của chính manifest vào input fingerprint, không tạo vòng tự tham chiếu. Loại absolute storage URI, run timestamp, hostname và report prose khỏi semantic identity; vẫn lưu chúng trong provenance. New payload checksum map dùng relative paths và ghi rõ algorithm. Fingerprint legacy phải được xác minh đúng thuật toán legacy; không áp canonicalization mới rồi kết luận source corrupt.

Publication viết staging riêng, kiểm schema/checksum/coverage rồi finalize vào ID mới. Fail giữa chừng không đổi CURRENT. Khi derivative hoàn tất và được chọn làm active training dataset, cập nhật CURRENT atomically với đường dẫn tồn tại, `dataset_id`, fingerprint, feature/target contract và readiness scope. Không sửa nhãn hoặc tensor nguồn để làm vừa model mới. Nhiều derivative có thể cùng tham chiếu một source.

### 11.1. Canonical hashing và tránh self-reference

MUST dùng JSON canonical UTF-8, ensure_ascii=false, sort_keys=true, separators=(comma,colon), allow_nan=false; normalize path phân tách bằng `/`. `derivation_spec_hash` hash semantic projection gồm source_dataset_id, **source_parquet_sha256**, **source_schema_sha256**, source_format/source_layout_id/inventory_policy, schema discrepancy-rule ID/digest, source_training_fingerprint lịch sử có scope, source feature-contract byte hash, target/window/split rule, selected ordered features/hex IDs, graph policy, normalization algorithm, dtype và transform source-code digest. Loại actual filesystem path, generated_at, inspection metadata, run IDs và output directories khỏi projection; vẫn lưu chúng trong provenance manifest có byte hash riêng. Schema byte hash được bind như source evidence dù một số comment đã có override; không lặng lẽ strip schema text để che source change. `source_parquet_sha256` phải resolve/freeze trước derivation_spec_hash; placeholder null không được hash thành identity của dataset đã publish.

Sample key trong hashed sample_index là `(derivation_spec_hash,k)` hoặc `(source_dataset_id,k)` kèm derivation hash cột riêng, không chứa final training_dataset_id/derived_fingerprint chưa biết. Sau khi arrays/index/norm finalize, hash sorted relative-path→SHA256 map (không gồm chính manifest), rồi derived_fingerprint=SHA256(canonical({derivation_spec_hash,payload_sha256})). training_dataset_id được tạo từ fingerprint này và chỉ ghi vào outer manifest/MLflow metadata. Không hash một ID mà ID đó phụ thuộc chính file đang hash. Full manifest byte hash lưu riêng sau cùng.

## 12. Interface implementation bắt buộc

Trong package mới `pipeline/src/surge_ml`, chia trách nhiệm data thành các interface có thể kiểm thử:

| Interface | Trách nhiệm |
|---|---|
| `resolve_source(explicit_root, pointer)` | Resolve theo cấu hình; lỗi khi pointer thiếu đích; ghi resolution evidence |
| `validate_source(root)` | Kiểm explicit meta manifest/contract/schema paths và hashes, freeze/xác minh raw/features/burn_in Parquet inventory, ordered grid và typed keys; record schema discrepancies; evidence13 archive training files kiểm riêng |
| `prepare_parquet_source(root, inventory, contract)` | Scan/chunk raw+feature Parquet, kiểm join vật lý và materialize ordered mmap-ready derivative; không gọi legacy loader |
| `build_target(raw_d, raw_seff, split_ids, target_contract)` | Tạo q/log1p/masks/reasons, không đọc normalized values |
| `build_sample_index(time_grid, split_spec, W, H, purge, masks)` | Deterministic eligibility, coverage và exclusions |
| `fit_preprocessor(source, eligible_train, feature_view)` | Union input windows; cutoff edge rows; train-only stats |
| `materialize_batch(sample_ids)` | mmap derivative slices, scalers, graph policy, masks và provenance; không đọc legacy source NPY |
| `publish_dataset(staging, manifest)` | Validation receipt, immutable derivative và optional atomic CURRENT update |

Source validation nên tách machine integrity, semantic compatibility và realism. `training_ready=true` của nguồn chỉ là input để kiểm; không đủ cho model V1.2. Khi nguồn có ordered feature40 nhưng model đòi29, adapter explicit được phép; loader không tự cắt F theo mong muốn checkpoint.

## 13. Migration theo thứ tự thực thi

1. Resolve active `data/hcm_data_2` cùng explicit `meta/manifest.json`, `meta/feature_contract.json`, `schema.yaml`; ghi stale embedded manifest trong CURRENT, stale manifest release location và khác biệt human/machine ID. Freeze schema hash và Parquet inventory; lưu digest riêng với evidence13 archive training files lịch sử.
2. Freeze code/config cho derivative. Register `hex29_edge10_v1_2`, `ds_log1p_h5_v1_2`, `directed_relations_self_v1` và sample policy; không thay schema cũ.
3. Scan trực tiếp Parquet raw/features/burn_in theo inventory và table paths D10; named-select/reindex đủ8.640 timestamp ×61 hex theo canonical D2, kiểm5-minute continuity/midnight, demand parity và typed graph. Ghi derivative `raw_node40.npy`, float64 physical sidecars và graph arrays/pointers; expose29/40 views cùng source. Không regenerate simulator hoặc reuse legacy W4 batch logic.
4. Recompute q/log1p H5 và domain masks. Xuất mask reason coverage theo split, hex, giờ, zone và raw supply bucket.
5. Recompute W12 sample index. Kiểm candidate counts, eligible counts, train/val/test isolation và graph sample membership.
6. Fit scaler từ train eligible theo mục 8. Xuất all40 baseline preprocessor riêng dưới cùng sample protocol.
7. Verify một minibatch đầy đủ: X29, H1, graph typed+self, y/mask, provenance; loss backward có valid nodes và no NaN. Đây là gate trong implementation, chưa thực hiện ở specs.
8. Publish immutable derivative, log lineage và integrity/coverage artifacts sang run MLflow theo spec tracking. Chỉ khi publish thành công mới cho training full chọn derivative.

Không tái sinh simulator 30 ngày chỉ để đổi target khi physical source đã có đủ D/S_eff. Rebuild raw/features chỉ cần khi audit phát hiện lỗi point-in-time, formula hoặc source payload, và khi đó tạo source version mới. **[Confidence: Medium — migration tiết kiệm IO, giữ provenance.]**

## 14. Acceptance requirements

| ID | Trường hợp | Kết quả bắt buộc |
|---|---|---|
| DATA-01 | CURRENT root tồn tại nhưng embedded manifest vắng, hoặc source path mất | Lỗi rõ khi không có config metadata-path override đã kiểm identity; không tự sửa pointer/fallback V1 hoặc chọn thư mục gần tên |
| DATA-02 | Đổi byte/thêm/bớt Parquet, source schema, derivative tensor hoặc feature order sau freeze | Inventory/schema/derivative checksum và canonical named-order gate thất bại trước train; fingerprint13 archive NPY không được dùng để cho Parquet qua gate |
| DATA-03 | Grid đúng nguồn | 8.640 endpoint liên tục ×61 hex; duplicate/missing key gây lỗi |
| DATA-04 | D=6, S_eff=2 tại t+5 | q=3; y=`log(4)`; inverse về3 trong tolerance |
| DATA-05 | D=0,S_eff>0 / D≥0,S_eff=0 | Trường hợp đầu y=0 valid; trường hợp sau masked có reason |
| DATA-06 | Label qua split hoặc cuối export | Mask false, không wrap, không forward/backfill |
| DATA-07 | W12/H5/purge30 | Candidate counts6030/1134/1422 trước domain mask; lịch sử12 và target+1 đúng indices |
| DATA-08 | Một node target invalid trong graph | Node đó không góp loss; node hợp lệ còn lại vẫn được học |
| DATA-09 | Graph/batch toàn target invalid | Không optimizer step; log count; epoch không label hợp lệ fail |
| DATA-10 | Thay validation/test values | Scaler train và input train không đổi; target/source hashes thay theo payload |
| DATA-11 | Lặp window overlap | Raw node-time không bị đếm lặp khi fit scaler |
| DATA-12 | Schema triple PK gặp adjacency+OD cùng cặp và OD nội hex | Dùng effective typed key, giữ genuine OD self; source relation flags hợp lệ và thêm một synthetic self/node; không dedup đúng dữ liệu theo schema comment |
| DATA-13 | Batch hai cutoff khác nhau | Edge offset đúng; không nối node giữa hai sample |
| DATA-14 | Truncate lifecycle tại cutoff | Feature/edge ở cutoff khớp prefix replay; active trip có unknown future vẫn đóng góp |
| DATA-15 | Event đúng midnight / đến muộn, comment orders partition mâu thuẫn exporter | Actual event membership/right-closed source cutoff đúng, discrepancy được ghi; production availability policy chặn dữ liệu chưa đến |
| DATA-16 | Input cùng giá trị qua offline và serving | Feature order, normalization, graph policy khớp trong tolerance khai báo |
| DATA-17 | Thay absolute dataset location | Semantic fingerprint không đổi nếu payload/contract như cũ; resolution provenance đổi |
| DATA-18 | Export dở dang | CURRENT vẫn trỏ bản trước; không cho load derivative thiếu integrity receipt |

Các tolerance mặc định cho float32 transform/preprocessor đề xuất `rtol=1e−6, atol=1e−5`; identity index/mask/key phải exact. Không dùng approximate test cho split boundary hoặc node ordering. Báo cáo validation MUST ghi counts thực tế; không copy nguyên candidate counts thành số valid labels.

## 15. Giới hạn phải hiện diện trong data card và MLflow

**[Confidence: High — D1/D3/D7.]** Source đã lưu 22 raw checks, 15 feature checks và smoke legacy; chưa chứng minh model V1.2, realism hoặc lợi ích graph. Completion mature ~91,75% và share surge>1 ~40,92% vượt dải tham chiếu synthetic của dự án; các dải này không phải chuẩn HCMC thực tế.

Dataset không có quote events, booking rate thật, offer acceptance rate, GMV/fare transactions, nhãn pricing tối ưu hoặc counterfactual. Không tự tạo các cột kinh doanh này từ match/cancel. Precision forecasting trên label hợp lệ chưa đủ để kết luận giữ doanh thu của bidding incumbent; evidence đó cần shadow/online protocol riêng.

Exact count S_eff=0 và coverage V1.2 chưa được đo trong công việc viết specs. Builder phải xuất chúng trước full training. D/S chia request-flow cho driver-stock là pressure proxy theo contract; reference kinh tế `q_star` không mặc nhiên bằng1. Các cảnh báo và giới hạn này phải được lưu trong data card, MLflow tags/artifacts và model evaluation để người quản lý đọc được cùng kết quả.

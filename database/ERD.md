# Thiết kế database: Surge Recommendation Console

DDL chạy được nằm ở [schema.sql](schema.sql). Tài liệu này giải thích ERD, lý do chọn từng cấu trúc, và cách các business rule trong spec được chuyển thành ràng buộc của PostgreSQL.

Nguồn contract:

- [docs/backend/spec_backend.md](../docs/backend/spec_backend.md): entity ở mục 3, validation ở mục 5, decision ở mục 6, batch ở mục 7, bảng/index đề xuất ở mục 11, test BE-01 đến BE-24.
- [docs/product/product_spec.md](../docs/product/product_spec.md): eligibility và trạng thái decision.
- [docs/data/metadata.md](../docs/data/metadata.md): định nghĩa D/S và quy tắc null khi supply bằng 0.
- [data/CURRENT.json](../data/CURRENT.json): dataset đang dùng.

Yêu cầu PostgreSQL 15 trở lên. Schema đã được kiểm tra trên PostgreSQL 17 (xem [mục 10](#10-kết-quả-kiểm-tra)).

---

## 1. Phạm vi: dữ liệu nào nằm trong DB, dữ liệu nào ở lại Parquet

Spec để mở câu hỏi TD-03: import toàn bộ snapshot vào PostgreSQL, hay chỉ lưu metadata rồi đọc Parquet. Thiết kế này chọn cách ở giữa.

| Dữ liệu | Nơi lưu | Lý do |
|---|---|---|
| `raw/orders`, `features/hex_features`, `graph_edges`, oracle | Parquet trong `data/` | Dữ liệu huấn luyện, lớn, chỉ pipeline ML đọc. Console không cần đọc từng order. |
| Dataset release, snapshot, market state từng hex | PostgreSQL | UI cần lọc theo thời gian, xem lịch sử một hex, join với recommendation. Khoảng 1,58M dòng (61 hex × 25.920 snapshot), đo được khoảng 200 MB cả index. |
| Provider, policy, recommendation set, recommendation | PostgreSQL | Cần ràng buộc toàn vẹn và cần bất biến sau khi publish. |
| Demo session, decision, batch, idempotency, audit | PostgreSQL | Dữ liệu giao dịch, cần transaction và khoá chống race. |

Số lượng hex, số ngày và số snapshot không được hardcode trong schema. Importer đọc chúng từ `data/CURRENT.json` và `meta/manifest.json` như quy định trong `metadata.md`. Mỗi release là một dòng trong `dataset_releases`, nhận diện bằng `dataset_key` và `fingerprint`.

---

## 2. ERD tổng quan

Sơ đồ dưới chỉ thể hiện quan hệ. Cột của từng bảng nằm trong ba sơ đồ con ở mục 3.

```mermaid
erDiagram
    regions ||--o{ hexes : "chứa"
    regions ||--o{ node_mappings : "có"
    node_mappings ||--o{ node_mapping_hexes : "gồm"
    hexes ||--o{ node_mapping_hexes : "được đánh số"
    metric_definitions ||--o{ dataset_releases : "định nghĩa D/S quan sát"
    dataset_releases ||--o{ snapshots : "gồm"
    regions ||--o{ snapshots : "thuộc vùng"
    node_mappings ||--o{ snapshots : "thứ tự node"
    snapshots ||--o{ hex_market_states : "có"
    hexes ||--o{ hex_market_states : "đo tại"

    providers ||--o{ recommendation_sets : "tạo"
    policy_configs ||--o{ recommendation_sets : "áp dụng khi validate"
    metric_definitions |o--o{ recommendation_sets : "định nghĩa D/S dự báo"
    snapshots ||--o{ recommendation_sets : "là đầu vào của"
    recommendation_sets ||--o{ recommendations : "gồm"
    hex_market_states ||--o{ recommendations : "đề xuất cho"

    actors ||--o{ demo_sessions : "sở hữu"
    demo_sessions ||--o{ decisions : "chứa"
    recommendations ||--o{ decisions : "được quyết định"
    actors ||--o{ decisions : "thực hiện"
    policy_configs ||--o{ decisions : "validate bằng"

    demo_sessions ||--o{ batch_plans : "chứa"
    recommendation_sets ||--o{ batch_plans : "phạm vi"
    batch_plans ||--o{ batch_plan_items : "đóng băng"
    recommendations ||--o{ batch_plan_items : "được chọn"
    batch_plans ||--o| decision_batches : "commit một lần"
    decision_batches ||--o{ decision_batch_items : "gồm"
    batch_plan_items ||--o| decision_batch_items : "được xử lý"
    decisions |o--o| decision_batch_items : "kết quả"

    actors ||--o{ idempotency_records : "gửi"
    demo_sessions ||--o{ idempotency_records : "phạm vi"
    actors |o--o{ audit_events : "gây ra"
    demo_sessions |o--o{ audit_events : "phạm vi"
```

Các bảng chia thành ba nhóm theo vòng đời dữ liệu:

1. **Dữ liệu nguồn**: import một lần và không bao giờ sửa.
2. **Output provider**: ghi trong lúc ingest, bất biến sau khi publish.
3. **Quyết định của operator**: thay đổi theo vòng đời, kèm audit append-only.

---

## 3. Giải thích từng bảng

### 3.1 Nhóm 1: tham chiếu và dữ liệu nguồn

```mermaid
erDiagram
    regions {
        text region_id PK
        text label
        text timezone "Asia/Ho_Chi_Minh"
        smallint h3_resolution
    }
    hexes {
        text hex_id PK "chuỗi H3"
        text region_id FK
        text zone "airport|cbd|office|residential|suburb|venue"
        smallint ring
        float8 lat
        float8 lng
    }
    node_mappings {
        bigint node_mapping_id PK
        text region_id FK
        text version UK
    }
    node_mapping_hexes {
        bigint node_mapping_id PK, FK
        text hex_id PK, FK
        int node_index UK
    }
    metric_definitions {
        text metric_id PK
        text display_name
        text equation
        text units
        text zero_supply_policy
    }
    dataset_releases {
        bigint dataset_id PK
        text dataset_key UK
        text fingerprint UK
        text layout_version
        text schema_version
        text data_kind "SYNTHETIC|HISTORICAL|LIVE"
        text observation_metric_id FK
        jsonb metadata
    }
    snapshots {
        bigint snapshot_id PK
        bigint dataset_id FK
        text region_id FK
        bigint node_mapping_id FK
        timestamptz cutoff_ts
        timestamptz forecast_ts "nullable"
        text snapshot_version
    }
    hex_market_states {
        bigint snapshot_id PK, FK
        text hex_id PK, FK
        int demand
        int idle_supply
        float8 effective_supply
        float8 observed_ds "null khi S_eff = 0"
        text observed_ds_null_reason
        float8 eta_sec
        numeric surge_base "NUMERIC(6,4)"
        jsonb null_reasons
    }
    regions ||--o{ hexes : ""
    regions ||--o{ node_mappings : ""
    node_mappings ||--o{ node_mapping_hexes : ""
    hexes ||--o{ node_mapping_hexes : ""
    metric_definitions ||--o{ dataset_releases : ""
    dataset_releases ||--o{ snapshots : ""
    node_mappings ||--o{ snapshots : ""
    snapshots ||--o{ hex_market_states : ""
    hexes ||--o{ hex_market_states : ""
```

**`regions`, `hexes`**: danh mục vùng và hex H3. `hex_id` dùng luôn chuỗi H3 làm khoá chính, vì đây là định danh tự nhiên, ổn định và đã có trong toàn bộ Parquet. `zone` dùng TEXT kèm CHECK với 6 giá trị lấy từ `metadata.md`, không dùng ENUM, vì thêm giá trị vào CHECK dễ hơn sửa ENUM.

**`node_mappings`, `node_mapping_hexes`**: thứ tự node mà GNN dùng. Spec 3.3 coi node mapping là một phần danh tính của snapshot, vì cùng một thời điểm mà đổi thứ tự node thì input của model đã khác. `UNIQUE (node_mapping_id, node_index)` bảo đảm không có hai hex trùng chỉ số.

**`metric_definitions`**: định nghĩa metric, ví dụ `ds_eff_observed.v1` có công thức `demand_5m / effective_supply`. UI hiển thị nhãn và đơn vị theo bảng này, không tự suy ra. `zero_supply_policy` ghi rõ cách xử lý khi supply bằng 0.

**`dataset_releases`**: một dòng cho mỗi bản phát hành dữ liệu. `dataset_key` và `fingerprint` lấy từ `data/CURRENT.json`. Cả hai đều UNIQUE, nên import lại cùng một release sẽ bị chặn. `data_kind` cho UI biết dữ liệu là SYNTHETIC hay thật, để không hiển thị dữ liệu mock như dữ liệu thật.

**`snapshots`**: trạng thái marketplace tại một `cutoff_ts`. Snapshot không phụ thuộc provider: nhiều provider có thể chạy trên cùng một snapshot. Danh tính là `UNIQUE (dataset_id, region_id, cutoff_ts, node_mapping_id)`. `cutoff_ts` đặt ở vị trí thứ ba để index này phục vụ luôn truy vấn khoảng thời gian (xem mục 6).

**`hex_market_states`**: số liệu thị trường của từng hex tại từng snapshot. Khoá chính là `(snapshot_id, hex_id)`.

- `surge_base` là `surge_multiplier` trong `raw/hex_snapshot`, tức giá bidding hiện hành mà recommendation so sánh với.
- `observed_ds` là NULL khi `effective_supply = 0`, khoảng 2,95% số dòng theo `metadata.md`. Khi đó phải có `observed_ds_null_reason`, ví dụ `ZERO_EFFECTIVE_SUPPLY`. Ràng buộc `CHECK ((observed_ds IS NULL) = (observed_ds_null_reason IS NOT NULL))` buộc hai cột luôn đi cặp.
- `null_reasons` (JSONB) chứa lý do null của các cột khác, phục vụ BE-22 (chart có null hoặc gap phải giữ null kèm lý do).

Cả bốn bảng `dataset_releases`, `snapshots`, `hex_market_states` và `node_mapping_hexes` đều chỉ INSERT. Bảng nào trong số này có trigger thì trigger chặn UPDATE và DELETE (BE-16: replay snapshot lịch sử thì source không đổi).

### 3.2 Nhóm 2: provider, policy, recommendation

```mermaid
erDiagram
    providers {
        bigint provider_id PK
        text provider_key UK
        text kind "MOCK|RULE_BASED|ML|GNN|PRECOMPUTED"
    }
    policy_configs {
        bigint policy_config_id PK
        text policy_version UK
        numeric surge_min
        numeric surge_max
        numeric max_deviation
        numeric step
        smallint precision
        bool override_reason_required
        bool is_active "tối đa 1 dòng true"
    }
    recommendation_sets {
        bigint recommendation_set_id PK
        bigint snapshot_id FK
        bigint provider_id FK
        text provider_version
        bigint policy_config_id FK
        text output_contract_version
        text source_run_id
        text provider_reported_fingerprint
        text forecast_metric_id FK
        text status "INGESTING|PUBLISHED|REJECTED|SUPERSEDED"
        timestamptz generated_at
        timestamptz published_at
        timestamptz superseded_at
        jsonb model_metadata
        jsonb validation_summary
    }
    recommendations {
        bigint proposal_id PK
        bigint recommendation_set_id FK
        bigint snapshot_id FK
        text external_proposal_id
        text hex_id FK
        int proposal_version
        text action "INCREASE|DECREASE|HOLD|REVIEW"
        numeric surge_base
        numeric surge_delta
        numeric surge_proposed
        text explanation
        text_array reason_codes
        jsonb evidence
        jsonb raw_payload
        text validation_status "VALID|INVALID"
        jsonb validation_errors
    }
    providers ||--o{ recommendation_sets : ""
    policy_configs ||--o{ recommendation_sets : ""
    recommendation_sets ||--o{ recommendations : "FK kép (set, snapshot)"
```

**`providers`**: danh mục nguồn đề xuất (mock, rule-based, GNN...). Spec yêu cầu thay provider mà không đổi API (BE-19), nên provider chỉ là một dòng dữ liệu, không phải một bảng riêng.

**`policy_configs`**: giới hạn surge, gồm min, max, độ lệch tối đa so với base, bước giá và số chữ số thập phân. Đổi giới hạn nghĩa là thêm một dòng mới với `policy_version` mới, không sửa dòng cũ. Nhờ vậy mỗi decision vẫn biết nó đã được validate bằng giới hạn nào. Trigger chỉ cho đổi cột `is_active`. Partial unique index `ON policy_configs ((true)) WHERE is_active` bảo đảm tối đa một policy đang hiệu lực.

**`recommendation_sets`**: một lần chạy provider trên một snapshot. Trường `status` có vòng đời cố định:

```
INGESTING ──► PUBLISHED ──► SUPERSEDED
    └──────► REJECTED
```

- Trigger `check_recommendation_set_transition` chặn mọi chuyển trạng thái khác, ví dụ đưa PUBLISHED quay về INGESTING.
- Partial unique index `(snapshot_id, provider_id) WHERE status = 'PUBLISHED'` bảo đảm mỗi snapshot chỉ có một set đang hiệu lực cho mỗi provider. Muốn publish set mới thì phải chuyển set cũ sang SUPERSEDED trong cùng transaction.
- Ngoài vòng đời, chỉ các cột `status`, `published_at`, `superseded_at` và `validation_summary` được đổi.
- `provider_reported_fingerprint` là fingerprint provider tự khai. Backend so nó với `dataset_releases.fingerprint` khi ingest, để phát hiện model chạy trên dữ liệu khác.

**`recommendations`**: mỗi dòng là một proposal cho một hex.

- `proposal_id` là khoá nội bộ. `external_proposal_id` giữ ID provider gửi, ví dụ `rec_001`. Hai provider có thể cùng gửi `rec_001`, nên không dùng ID của provider làm khoá.
- `snapshot_id` được lưu lặp lại (đã có qua set) để làm hai FK kép:
  - `(recommendation_set_id, snapshot_id)` trỏ về `recommendation_sets`: snapshot của proposal phải là snapshot của set.
  - `(snapshot_id, hex_id)` trỏ về `hex_market_states`: hex phải có market state trong đúng snapshot đó. Spec 4.5 mục 4 yêu cầu điều này, và ở đây DB tự kiểm tra thay vì để code ứng dụng làm.
- **Dòng INVALID vẫn được lưu.** Provider có thể gửi dữ liệu hỏng, như NaN, action mâu thuẫn hay hex lạ. Spec yêu cầu chặn nhưng vẫn truy vết được, nên dòng lỗi được lưu với `validation_status = 'INVALID'`, `validation_errors` không rỗng và `raw_payload` là bản gốc. Các CHECK về nghiệp vụ chỉ áp cho dòng VALID; dòng INVALID có thể thiếu trường hoặc có `hex_id` NULL.
- CHECK nhất quán cho dòng VALID, theo Layer B của spec 5.1:
  - `surge_delta = surge_proposed - surge_base`.
  - INCREASE thì proposed > base, DECREASE thì proposed < base, HOLD thì proposed = base.
  - REVIEW không mang giá khác base.
- Không trùng hex và không trùng `external_proposal_id` trong một set. Ràng buộc này dùng partial unique index chỉ trên dòng VALID, vì dòng trùng do provider gửi được lưu dưới dạng INVALID.
- Trigger `check_recommendation_set_open` chỉ cho INSERT khi set còn INGESTING. Sau khi publish, set không nhận thêm dòng nào; mọi UPDATE và DELETE đều bị chặn.

**Eligibility không được lưu.** Eligibility (ELIGIBLE/BLOCKED/SUPERSEDED/UNKNOWN) phụ thuộc vào trạng thái set, policy đang active và decision trong session, và các yếu tố này thay đổi sau khi proposal được tạo. Nếu lưu thành cột thì cột sẽ lỗi thời. View `v_recommendation_eligibility` tính eligibility từ dữ liệu hiện hành:

| Thứ tự kiểm tra | Điều kiện | eligibility | blocked_reason |
|---|---|---|---|
| 1 | set SUPERSEDED | SUPERSEDED | PROPOSAL_SUPERSEDED |
| 2 | set chưa PUBLISHED | BLOCKED | SET_NOT_PUBLISHED |
| 3 | dòng INVALID | BLOCKED | PROVIDER_OUTPUT_INVALID |
| 4 | action REVIEW | BLOCKED | REVIEW_REQUIRED |
| 5 | không có policy active | UNKNOWN | NO_ACTIVE_POLICY |
| 6 | policy active khác policy của set | BLOCKED | POLICY_VERSION_CONFLICT (BE-15) |
| 7 | vượt min/max/max_deviation | BLOCKED | SURGE_LIMIT_EXCEEDED |
| 8 | sai số chữ số thập phân | BLOCKED | INVALID_SURGE_PRECISION |
| 9 | không khớp bước giá tính từ `surge_min` | BLOCKED | INVALID_SURGE_STEP |
| — | còn lại | ELIGIBLE | NULL |

View không sinh EXPIRED vì chế độ DEMO_REPLAY không có hết hạn (spec 5.5). View cũng không xét decision vì decision gắn với từng demo session; phần đó được ghép ở truy vấn queue (mục 6, Q4).

### 3.3 Nhóm 3: quyết định, batch, idempotency, audit

```mermaid
erDiagram
    actors {
        bigint actor_id PK
        text actor_key UK
        text role "OPERATOR|VIEWER|ADMIN"
        bool is_active
    }
    demo_sessions {
        bigint demo_session_id PK
        bigint owner_actor_id FK
        text execution_mode "luôn DEMO"
        text status "ACTIVE|CLOSED"
    }
    decisions {
        bigint decision_id PK
        bigint demo_session_id FK
        bigint proposal_id FK
        int proposal_version FK
        bigint actor_id FK
        bigint policy_config_id FK
        text action "ACCEPT_PROPOSAL|KEEP_BIDDING|OVERRIDE_PROPOSAL"
        numeric requested_surge "chỉ OVERRIDE"
        numeric surge_decided
        text reason
        text status "PENDING|RECORDED|KEPT_BIDDING|REJECTED|FAILED"
        text error_code
        timestamptz recorded_at
    }
    batch_plans {
        bigint batch_plan_id PK
        bigint demo_session_id FK
        bigint actor_id FK
        bigint snapshot_id FK
        bigint recommendation_set_id FK
        bigint policy_config_id FK
        text selection_mode "ALL_ELIGIBLE|SELECTED"
        timestamptz expires_at
    }
    batch_plan_items {
        bigint batch_plan_id PK, FK
        bigint proposal_id PK, FK
        bigint recommendation_set_id FK
        int proposal_version
        bool eligible
        text skip_reason_code
    }
    decision_batches {
        bigint batch_id PK
        bigint batch_plan_id UK, FK
        bigint demo_session_id FK
        text status "PROCESSING|SUCCEEDED|PARTIAL_SUCCESS|FAILED"
        int total_count
        int success_count
        int failure_count
    }
    decision_batch_items {
        bigint batch_id PK, FK
        bigint proposal_id PK, FK
        bigint batch_plan_id FK
        text status "PENDING|SUCCESS|FAILED"
        bigint decision_id UK, FK
        text error_code
    }
    idempotency_records {
        bigint idempotency_record_id PK
        bigint actor_id FK
        bigint demo_session_id FK
        text operation "DECISION|BATCH_COMMIT"
        text idempotency_key
        text request_hash
        text state "IN_PROGRESS|COMPLETED"
        smallint response_code
        jsonb response_body
    }
    audit_events {
        bigint event_id PK
        bigint actor_id FK "NULL = hệ thống"
        bigint demo_session_id FK
        text entity_type
        bigint entity_id
        text action
        jsonb previous_state
        jsonb new_state
        text correlation_id
    }
    actors ||--o{ demo_sessions : ""
    demo_sessions ||--o{ decisions : ""
    demo_sessions ||--o{ batch_plans : ""
    batch_plans ||--o{ batch_plan_items : ""
    batch_plans ||--o| decision_batches : ""
    decision_batches ||--o{ decision_batch_items : ""
    batch_plan_items ||--o| decision_batch_items : ""
    decisions |o--o| decision_batch_items : ""
    demo_sessions ||--o{ idempotency_records : ""
    demo_sessions |o--o{ audit_events : ""
```

**`actors`**: người dùng hoặc định danh demo do backend cấp (TD-05). `actor_key` không do frontend tự khai. Quyền theo `role` được kiểm tra ở tầng API (BE-24); DB chỉ lưu vai trò.

**`demo_sessions`**: phạm vi cô lập các quyết định mô phỏng. `CHECK (execution_mode = 'DEMO')` khẳng định ở mức DB rằng không có decision nào là production execution (BE-20). Khi có production, phải viết migration mở rộng CHECK này; việc đó là một quyết định có chủ đích, không thể xảy ra do nhầm lẫn.

**`decisions`**: quyết định của operator. Bảng này không sửa recommendation và không chép lại base, proposed hay hex. Các giá trị đó lấy qua `proposal_id`, vì recommendation bất biến nên join luôn ra cùng kết quả.

- FK kép `(proposal_id, proposal_version)` trỏ về `recommendations`: gửi sai version thì bị FK chặn (BE-14).
- `policy_config_id` lưu policy đã dùng để validate, nên audit giải thích được vì sao một override hợp lệ tại thời điểm đó.
- Quan hệ action và status:

  | action | status khi thành công | `surge_decided` | `requested_surge` |
  |---|---|---|---|
  | ACCEPT_PROPOSAL | RECORDED | = surge_proposed | NULL |
  | KEEP_BIDDING | KEPT_BIDDING | = surge_base (BE-05) | NULL |
  | OVERRIDE_PROPOSAL | RECORDED | = requested_surge | bắt buộc |

  CHECK trong bảng ép được cột nào NULL hoặc NOT NULL theo action, và cặp action–status nào hợp lệ. Còn việc `surge_decided` bằng đúng giá trị nào thì service tính (xem mục 7), vì CHECK không đọc được bảng khác.
- Thất bại (REJECTED/FAILED) vẫn được lưu kèm `error_code`. Một proposal có thể có nhiều lần thử thất bại nhưng chỉ một lần thành công.
- **Chốt chống race (BE-13)**: partial unique index `decisions_one_final_per_session_key ON (demo_session_id, proposal_id) WHERE status IN ('RECORDED','KEPT_BIDDING')`. Nếu hai request đồng thời cùng vượt qua bước kiểm tra ở tầng ứng dụng, request commit sau vẫn bị index chặn.
- Vòng đời: PENDING được chuyển sang một trạng thái cuối, còn trạng thái cuối thì không đổi nữa (trigger `check_decision_transition`). Chỉ các cột kết quả (status, surge_decided, error_code, error_message, recorded_at) được đổi.

**`batch_plans`, `batch_plan_items`**: kết quả bước Preview của Accept All.

- Plan đóng băng danh sách proposal tại thời điểm preview. Proposal mới xuất hiện sau đó không tự vào plan (BE-23).
- Mỗi plan gắn với đúng một recommendation set và snapshot, qua FK kép `(recommendation_set_id, snapshot_id)`.
- Mỗi item có hai FK kép:
  - `(batch_plan_id, recommendation_set_id)` trỏ về plan.
  - `(proposal_id, recommendation_set_id)` trỏ về recommendation.

  Hai FK này buộc item và plan cùng một set, nên DB không cho một batch trộn nhiều snapshot (BE-09).
- `eligible` và `skip_reason_code` ghi lại vì sao một proposal bị bỏ qua lúc preview. Plan và item đều bất biến.

**`decision_batches`, `decision_batch_items`**: lần commit của một plan.

- `batch_plan_id UNIQUE`: một plan chỉ commit được một lần.
- Item ban đầu là PENDING; mỗi item được xử lý trong một transaction riêng rồi chuyển sang SUCCESS (bắt buộc có `decision_id`) hoặc FAILED (bắt buộc có `error_code`). Nhờ vậy batch hỗ trợ partial success (BE-10: 8 thành công, 2 thất bại).
- FK `(batch_plan_id, proposal_id)` trỏ về `batch_plan_items`: chỉ xử lý được proposal đã có trong plan.
- FK `(decision_id, proposal_id)` trỏ về `decisions`: decision gắn vào item phải đúng proposal của item.
- Nếu server dừng giữa chừng, các item còn PENDING là danh sách cần chạy tiếp. Partial index `WHERE status = 'PENDING'` giúp tìm chúng nhanh (BE-21). Unique `decision_id` và chốt chống race ở `decisions` bảo đảm chạy lại không tạo trùng.
- CHECK `success_count + failure_count = total_count` khi batch đã kết thúc.

**`idempotency_records`**: lưu kết quả của các request thay đổi dữ liệu.

- Khoá duy nhất là `(actor_id, demo_session_id, operation, idempotency_key)`. Scope gồm actor và session, nên hai người dùng trùng key không ảnh hưởng nhau.
- `request_hash` là sha256 của payload đã chuẩn hoá:
  - Cùng key và cùng hash: trả lại `response_code` và `response_body` đã lưu, không tạo decision mới (BE-11).
  - Cùng key nhưng hash khác: trả 409 Conflict (BE-12).
- `state = 'IN_PROGRESS'` đánh dấu request đang chạy, để request trùng gửi đến lúc đó nhận 409 thay vì chạy song song.

**`audit_events`**: nhật ký append-only.

- Trigger chặn UPDATE, DELETE và TRUNCATE.
- `actor_id` NULL nghĩa là sự kiện do hệ thống sinh ra, ví dụ ingestion.
- `correlation_id` nối các sự kiện cùng một request. Với batch, đó là các sự kiện của từng item.
- `previous_state` và `new_state` (JSONB) chụp trạng thái trước và sau, nên đọc audit không cần join về bảng gốc.

---

## 4. Các quyết định thiết kế

**ID là `BIGINT GENERATED ALWAYS AS IDENTITY`, không dùng UUID.** Hệ thống chạy một database, không cần sinh ID phân tán. BIGINT nhỏ hơn, index gọn hơn, và thứ tự tăng dần thuận cho B-tree. Nếu API cần ID khó đoán, có thể thêm cột `public_id UUID` sau mà không phải đổi khoá. Identity có thể bị nhảy số (transaction rollback vẫn tiêu số), và đó là hành vi bình thường. Code và test không được giả định ID liên tiếp; smoke test của schema này từng gặp đúng lỗi đó.

**Surge dùng `NUMERIC(6,4)`, không dùng float.** Các phép so sánh như `proposed > base`, `delta = proposed - base` hay "đúng bước 0,05" phải chính xác tuyệt đối. Với float, `1.1 + 0.2` khác `1.3`, nên CHECK sẽ báo sai. Cần lưu ý ba điểm khi dùng NUMERIC:

- NUMERIC chấp nhận giá trị `NaN`, và PostgreSQL xếp NaN lớn hơn mọi số. Mọi cột surge vì thế có CHECK khoảng hai đầu (`> 0 AND < 100`) để NaN không lọt qua. Đã kiểm tra: NaN bị CHECK chặn.
- `Infinity` không lưu được vào NUMERIC có giới hạn độ chính xác; PostgreSQL báo `numeric field overflow`. Các cột DOUBLE PRECISION (`effective_supply`, `observed_ds`, `eta_sec`) dùng CHECK `< 'Infinity'`, và CHECK này chặn luôn NaN.
- NUMERIC **tự làm tròn** khi số chữ số thập phân vượt scale: 1,23456 thành 1,2346 mà không báo lỗi. API phải kiểm tra precision trước khi ghi; DB không bắt được trường hợp này.

Các số đo thị trường (supply, D/S, ETA) vẫn dùng DOUBLE PRECISION như `schema.yaml` của dataset, vì chúng là số đo, không tham gia so sánh bằng.

**Thời gian dùng `timestamptz`.** Parquet nguồn lưu thời gian không có múi giờ, ngầm hiểu là Asia/Ho_Chi_Minh (theo `schema.yaml`). Importer phải chuyển bằng `ts AT TIME ZONE 'Asia/Ho_Chi_Minh'`. Nếu chèn thẳng, PostgreSQL sẽ hiểu theo timezone của session và lệch 7 giờ.

**Null đi kèm lý do, không thay bằng 0.** Khi supply bằng 0, D/S không xác định. Ghi 0 sẽ khiến chart vẽ D/S thấp nhất đúng lúc thị trường căng nhất. Thiết kế lưu NULL kèm `observed_ds_null_reason`, đúng với `metadata.md`.

**FK kép để ép phạm vi.** Nhiều quy tắc kiểu "A và B phải cùng một set/snapshot" được chuyển thành FK nhiều cột, thay vì kiểm tra trong code. Chi phí là phải thêm một UNIQUE phụ ở bảng đích, ví dụ `UNIQUE (recommendation_set_id, snapshot_id)`. Đổi lại, dữ liệu sai phạm vi không thể ghi vào được, kể cả khi có bug ở tầng ứng dụng.

**Bất biến bằng trigger.** Hàm `guard_immutable_columns(...)` so sánh `to_jsonb(NEW)` với `to_jsonb(OLD)` sau khi bỏ các cột được phép đổi. Gọi không có tham số thì cả dòng bất biến. Một hàm dùng chung cho mọi bảng, danh sách cột được đổi nằm ngay ở câu `CREATE TRIGGER`. Trigger là lớp chặn cuối; lớp chính vẫn là không GRANT UPDATE/DELETE cho role ứng dụng trên các bảng bất biến (mục 8).

**Không partition.** `hex_market_states` có khoảng 1,58M dòng cho mỗi release 90 ngày, còn `recommendations` có khoảng 1,58M dòng mỗi lần chạy provider trên toàn bộ snapshot. Ngưỡng nên cân nhắc partition là khoảng 100M dòng. Khi số release và số lần chạy tăng tới mức đó, nên partition `hex_market_states` theo `RANGE (snapshot_id)` hoặc theo dataset, vì truy vấn luôn lọc theo snapshot. Lưu ý PostgreSQL bắt buộc khoá chính chứa partition key; khoá `(snapshot_id, hex_id)` hiện tại đã thoả.

**TEXT + CHECK thay cho ENUM.** Các tập giá trị như action, status hay zone có thể còn thay đổi. Thêm giá trị vào CHECK chỉ cần một migration đơn giản; ENUM không xoá được giá trị và khó sửa trong transaction.

**JSONB chỉ dùng cho dữ liệu bán cấu trúc** như `evidence`, `model_metadata`, `raw_payload`, `validation_errors` và audit state. Những trường được lọc, join hay ràng buộc đều là cột thật.

---

## 5. Business rule và test được bảo đảm ở đâu

| Test | Quy tắc | Ràng buộc trong DB | Phần còn lại ở service |
|---|---|---|---|
| BE-01, BE-02 | Action và giá phải nhất quán | CHECK nhất quán trên `recommendations` (chỉ dòng VALID) | Gán VALID/INVALID khi ingest |
| BE-03 | Không NaN/Infinity | CHECK khoảng trên NUMERIC, `< 'Infinity'` trên float | Parse JSON, ghi lỗi `NON_FINITE_NUMBER` |
| BE-04, BE-05, BE-06 | Kết quả accept, keep, override | CHECK action ↔ status ↔ cột NULL | Tính `surge_decided` |
| BE-07 | Override vượt giới hạn bị từ chối | `policy_config_id` lưu policy đã dùng | So sánh với policy active |
| BE-08 | Không accept được REVIEW | View eligibility trả BLOCKED/REVIEW_REQUIRED | Từ chối khi eligibility khác ELIGIBLE |
| BE-09 | Batch không trộn snapshot | FK kép plan ↔ set ↔ item | — |
| BE-10 | Partial success | Status theo từng item, CHECK tổng count | Mỗi item một transaction |
| BE-11, BE-12 | Idempotency | UNIQUE scope key, `request_hash` bất biến | So sánh hash |
| BE-13 | Tối đa một quyết định thành công | Partial unique `decisions_one_final_per_session_key` | Đổi lỗi unique thành 409 |
| BE-14 | Sai proposal version | FK `(proposal_id, proposal_version)` | Đổi lỗi FK thành 409 |
| BE-15 | Policy đổi trước khi commit | View trả POLICY_VERSION_CONFLICT | Validate lại khi commit |
| BE-16 | Replay không đổi source | Trigger bất biến trên dataset, snapshot, market state, recommendation | — |
| BE-17 | Decision còn sau khi reload | Lưu bền trong PostgreSQL | — |
| BE-18 | Không có decision thiếu audit | Ghi decision và audit trong cùng transaction (mục 7) | Transaction boundary |
| BE-19 | Provider mới cùng contract | Provider là một dòng dữ liệu | — |
| BE-20 | DEMO không gọi production | `CHECK (execution_mode = 'DEMO')` | Không có executor production |
| BE-21 | Resume batch | Item PENDING + partial index, `decision_id` UNIQUE | Worker resume |
| BE-22 | Giữ null và lý do | CHECK cặp null/reason, `null_reasons` | Serialize `{value: null, reason}` |
| BE-23 | Plan không tự thêm proposal | FK item batch → `batch_plan_items`, plan bất biến | — |
| BE-24 | Không có quyền | `actors.role` | Kiểm tra quyền ở API |

---

## 6. Truy vấn chính và index phục vụ

Mỗi FK đều có index ở phía tham chiếu, vì PostgreSQL không tự tạo index cho FK. Các truy vấn quan trọng:

**Q1: tải một snapshot (61 hex).** Dùng `snapshots_identity_key`, sau đó dùng PK `hex_market_states (snapshot_id, hex_id)`. Đo được 0,24 ms.

```sql
SELECT m.hex_id, m.demand, m.idle_supply, m.observed_ds, m.observed_ds_null_reason, m.surge_base
FROM snapshots s
JOIN hex_market_states m ON m.snapshot_id = s.snapshot_id
WHERE s.dataset_id = $1 AND s.region_id = $2 AND s.cutoff_ts = $3;
```

**Q2: lịch sử một hex trong một ngày (288 điểm).** Range scan trên `(dataset_id, region_id, cutoff_ts)`, rồi nested loop vào PK của market state. Đo được 2,35 ms. Không cần thêm index bắt đầu bằng `hex_id`.

```sql
SELECT s.cutoff_ts, m.demand, m.observed_ds, m.observed_ds_null_reason, m.surge_base
FROM snapshots s
JOIN hex_market_states m ON m.snapshot_id = s.snapshot_id AND m.hex_id = $4
WHERE s.dataset_id = $1 AND s.region_id = $2
  AND s.cutoff_ts >= $3 AND s.cutoff_ts < $3 + interval '1 day'
ORDER BY s.cutoff_ts;
```

**Q3: snapshot mới nhất.** `Index Scan Backward` trên `snapshots_identity_key`, đo được 0,05 ms.

**Q4: queue recommendation kèm trạng thái decision trong session.** Đây là truy vấn chính của màn hình operator.

```sql
SELECT e.*, d.decision_id, d.action AS decided_action, d.status AS decision_status, d.surge_decided
FROM v_recommendation_eligibility e
LEFT JOIN decisions d
  ON d.proposal_id = e.proposal_id
 AND d.demo_session_id = $2
 AND d.status IN ('RECORDED', 'KEPT_BIDDING')
WHERE e.recommendation_set_id = $1
ORDER BY e.hex_id;
```

Index dự kiến phục vụ: `recommendations_set_hex_idx` cho phần lọc theo set, và `decisions_one_final_per_session_key` cho phần LEFT JOIN, vì điều kiện status trùng với điều kiện của partial index. Truy vấn này chưa được đo bằng EXPLAIN ANALYZE; cần kiểm tra lại khi có dữ liệu decision thật. Lọc theo action, ví dụ chỉ xem INCREASE, thì dùng `recommendations_snapshot_action_idx`.

**Q5: audit theo entity.** `audit_events_entity_idx (entity_type, entity_id, created_at)` phục vụ truy vấn "lịch sử của decision X". Truy vấn theo session hoặc actor dùng index `(demo_session_id, created_at)` và `(actor_id, created_at)`.

**Q6: resume batch.** `decision_batch_items_pending_idx` là partial index chỉ chứa item PENDING, nên nhỏ dù bảng lớn.

Bảo trì: chạy `ANALYZE` sau mỗi lần import release hoặc ingest set lớn, để planner có thống kê đúng. Các bảng bất biến không có dead tuple nên gần như không cần VACUUM.

---

## 7. Luồng transaction

### 7.1 Ingest recommendation set

```
BEGIN;
  INSERT recommendation_sets (status = 'INGESTING');
  INSERT recommendations ...;          -- mỗi dòng gán VALID hoặc INVALID
  UPDATE recommendation_sets SET validation_summary = ...;
  -- nếu chấp nhận:
  UPDATE recommendation_sets SET status = 'SUPERSEDED', superseded_at = now()
   WHERE snapshot_id = $s AND provider_id = $p AND status = 'PUBLISHED';
  UPDATE recommendation_sets SET status = 'PUBLISHED', published_at = now() WHERE recommendation_set_id = $new;
  INSERT audit_events (entity_type = 'RECOMMENDATION_SET', action = 'SET_PUBLISHED');
COMMIT;
```

Set cũ phải được chuyển sang SUPERSEDED trước khi set mới chuyển sang PUBLISHED, vì partial unique index không cho hai set PUBLISHED cùng tồn tại. Với set lớn, dùng `COPY` cho recommendations. Trong lần kiểm tra, nạp 1,58M dòng market state mất khoảng 77 giây, chủ yếu do kiểm tra FK từng dòng.

### 7.2 Một decision

Mọi bước nằm trong **một transaction**, để không có decision thành công mà thiếu audit hay thiếu bản ghi idempotency (BE-18):

```
BEGIN;
  INSERT idempotency_records (state = 'IN_PROGRESS') ON CONFLICT DO NOTHING;
    -- đã tồn tại: cùng hash thì trả response đã lưu, khác hash thì 409
  SELECT ... FROM recommendations r JOIN recommendation_sets rs ... WHERE r.proposal_id = $1
    FOR SHARE OF rs;                   -- khoá set để không bị supersede giữa chừng
  SELECT eligibility FROM v_recommendation_eligibility WHERE proposal_id = $1;
  -- validate action, giới hạn policy, reason của override
  INSERT decisions (status = 'RECORDED' hoặc 'KEPT_BIDDING', surge_decided = ...);
    -- unique violation ở decisions_one_final_per_session_key: proposal đã được quyết định, trả 409
  INSERT audit_events (...);
  UPDATE idempotency_records SET state = 'COMPLETED', response_code, response_body, resource_id;
COMMIT;
```

Nếu validate thất bại, service vẫn có thể lưu decision REJECTED và audit tương ứng để truy vết. Bản ghi idempotency cũng chuyển sang COMPLETED với mã lỗi, để retry nhận lại đúng lỗi đó.

### 7.3 Batch commit

1. Một transaction ngắn: tạo `decision_batches` (PROCESSING), tạo mọi `decision_batch_items` ở trạng thái PENDING, ghi idempotency với operation `BATCH_COMMIT`.
2. Với **từng item**, mở một transaction riêng: thực hiện như luồng 7.2, rồi cập nhật item thành SUCCESS hoặc FAILED. Một item lỗi không làm hỏng các item khác.
3. Transaction cuối: đếm kết quả, đặt status SUCCEEDED, PARTIAL_SUCCESS hoặc FAILED, ghi audit.

Nếu server dừng ở bước 2, worker tìm batch còn PROCESSING và chạy tiếp các item PENDING. Item nào đã có decision thành công trong session sẽ bị chốt chống race chặn, nên service đối chiếu và đánh dấu item đó, không tạo decision trùng.

---

## 8. Migration và vận hành

Áp dụng hướng dẫn trong skill `database-migration` cho stack FastAPI + SQLAlchemy 2 + Alembic của backend spec:

- **Revision đầu tiên** của Alembic chạy nội dung `schema.sql`, gọi `op.execute()` theo từng khối. Trigger, partial index và view không được autogenerate tạo đầy đủ, nên viết tay. `downgrade()` drop theo thứ tự ngược với thứ tự tạo.
- **Expand/contract** cho mọi thay đổi sau này trên bảng đã có dữ liệu:
  1. Expand: thêm cột hoặc bảng mới, cột mới phải nullable hoặc có default.
  2. Deploy code ghi được cả hai dạng; backfill theo lô nhỏ.
  3. Contract: đổi sang NOT NULL, bỏ cột cũ ở một release sau.
- Thêm CHECK hoặc FK trên bảng lớn: dùng `ADD CONSTRAINT ... NOT VALID` rồi `VALIDATE CONSTRAINT` ở bước riêng, để không khoá bảng lâu. Tạo index trên bảng lớn: dùng `CREATE INDEX CONCURRENTLY`, chạy ngoài transaction.
- **Bảng bất biến không được sửa dữ liệu bằng migration.** Muốn sửa dữ liệu release thì import release mới. Muốn sửa recommendation thì ingest set mới và supersede set cũ. Release cũ được giữ lại, đúng nguyên tắc lưu trữ chứ không xoá trong `data/`.
- **Rollback**: mỗi revision có `downgrade()`. Trước migration đụng dữ liệu, chụp `pg_dump` của các bảng bị ảnh hưởng.
- **Role**: tách role chủ schema, dùng để chạy migration, khỏi role ứng dụng. Role ứng dụng chỉ có SELECT và INSERT, cộng UPDATE trên các bảng có vòng đời, và không có UPDATE, DELETE hay TRUNCATE trên `audit_events`. Mẫu GRANT nằm ở cuối `schema.sql`.

---

## 9. Điểm lệch giữa các spec cần chốt

1. **`KEEP_BASE` và `KEEP_BIDDING`.** `product_spec.md` (danh sách action và ví dụ JSON) dùng `KEEP_BASE`, trong khi `spec_backend.md` và `ui/app/src/domain/types.ts` dùng `KEEP_BIDDING`. Schema chọn `KEEP_BIDDING` vì đó là contract mà backend và UI đang dùng. Product spec nên được sửa cho khớp.
2. **Trạng thái chỉ có ở UI.** `types.ts` có thêm SUBMITTING, EXECUTING, EFFECTIVE và CANCELLED. SUBMITTING là trạng thái client trong lúc chờ response. EXECUTING và EFFECTIVE thuộc production execution, nằm ngoài phạm vi DEMO. Các trạng thái này không được lưu. Khi có production, cần một bảng execution riêng thay vì mở rộng `decisions.status`.
3. **Action `CANCEL` trong UI.** Backend spec chưa định nghĩa hành động này. Schema chưa hỗ trợ; nếu cần thì phải định nghĩa rõ là huỷ một decision PENDING hay rút lại một decision đã RECORDED. Hai cách có tác động khác nhau lên chốt chống race.
4. **TD-03 (data import) và TD-07 (expiration)** vẫn đang mở trong spec. Thiết kế này đã chọn câu trả lời cho TD-03 ở mục 1. Với TD-07, thiết kế chỉ hỗ trợ `batch_plans.expires_at`, còn proposal không có hạn trong DEMO_REPLAY.

---

## 10. Kết quả kiểm tra

Schema được chạy trên `postgres:17-alpine` với `psql -v ON_ERROR_STOP=1` và không có lỗi.

**Smoke test**: 36 trường hợp vi phạm đều bị DB từ chối với đúng ràng buộc dự kiến. Một số trường hợp tiêu biểu:

- INCREASE có proposed < base; delta khác proposed − base.
- NaN và Infinity, cả trên NUMERIC lẫn DOUBLE PRECISION.
- Hex không thuộc snapshot; snapshot của proposal khác snapshot của set.
- Hex trùng trong một set; thêm recommendation vào set đã PUBLISHED.
- Hai set PUBLISHED cho cùng snapshot và provider; set PUBLISHED quay về INGESTING.
- Hai policy cùng active.
- Hai decision thành công cho cùng session và proposal; sai proposal version; sửa decision đã ở trạng thái cuối.
- Batch item thuộc set khác; item không có trong plan; commit một plan hai lần; item SUCCESS gắn decision của proposal khác.
- Trùng idempotency key; sửa `request_hash`.
- UPDATE, DELETE hoặc TRUNCATE trên audit; UPDATE hoặc DELETE trên recommendation và market state.

Smoke test cũng phát hiện một lỗi thật, đã sửa: `TG_ARGV` là NULL chứ không phải mảng rỗng khi trigger không có tham số, nên phiên bản đầu của `guard_immutable_columns` không chặn được UPDATE.

**Hiệu năng**: với 1.581.120 dòng `hex_market_states` sinh giả (61 hex × 25.920 snapshot, khoảng 200 MB cả index):

| Truy vấn | Kế hoạch | Thời gian |
|---|---|---|
| Q1 tải một snapshot | Index Scan `snapshots_identity_key` + Index Scan PK | 0,24 ms |
| Q2 lịch sử một hex trong một ngày | Bitmap Index Scan + Nested Loop trên PK | 2,35 ms |
| Q3 snapshot mới nhất | Index Scan Backward | 0,05 ms |

Không truy vấn nào dùng Seq Scan.

## 11. Import dữ liệu mock

`database/import_mock.py` nạp dataset đang được `data/CURRENT.json` trỏ tới vào schema này. Hiện đó là `hcm_mock_v2_90d_seed42_bounded_tail`, layout `clean_v1`. DB chạy bằng `compose.yaml` ở gốc repo, project Docker tên `graph_surge_pricing`. Project này có hai container:

- `surge_erd_db`: postgres:17, port 5434, database `surge_erd`, user và password `surge`.
- `surge_erd_pgadmin`: giao diện web xem dữ liệu ở http://localhost:5050. Server "surge_erd (Docker)" đã được cấu hình sẵn; lần đầu mở sẽ hỏi mật khẩu DB `surge`.

Schema này khác schema Alembic trong `backend/compose.yaml` (port 5433), nên hai DB không dùng chung.

```powershell
docker compose up -d --wait                                    # chạy ở gốc repo
backend/.venv/Scripts/python database/import_mock.py          # DSN mặc định: postgresql://surge:surge@localhost:5434/surge_erd
```

Dữ liệu nằm trong volume `database_surge_erd_pg`. Các lệnh `docker compose stop` và `docker compose down` đều giữ dữ liệu. Riêng `docker compose down -v` xoá volume, và sau đó phải import lại.

Script tự áp `schema.sql` nếu DB còn trống. Toàn bộ import chạy trong một transaction. Nếu fingerprint đã có trong DB thì script bỏ qua, vì dữ liệu dataset là bất biến; muốn import lại phải dùng DB mới.

| Bảng | Nguồn | Cách map |
|---|---|---|
| `regions` | `schema.yaml` | `hcmc`, timezone và `h3_resolution` lấy từ dataset |
| `hexes` | `raw/hexes` | zone, ring, lat, lng |
| `node_mappings`, `node_mapping_hexes` | `meta/feature_contract.json` | version = `feature_version`; `node_index` theo thứ tự `hex_ids`, cùng thứ tự pipeline dùng |
| `dataset_releases` | `CURRENT.json`, `manifest.json` | `data_kind = SYNTHETIC`; `schema_version` = feature contract version; `metadata` giữ các cờ `realism_validation_complete` và `deployment_ready` (cả hai đều false) |
| `snapshots` | các `ts` khác nhau trong `raw/hex_snapshot` | `cutoff_ts = ts AT TIME ZONE 'Asia/Ho_Chi_Minh'` (nguồn không có timezone, `ts` là cuối cửa sổ 5 phút) |
| `hex_market_states` | `raw/hex_snapshot` join `features/hex_features` theo (ts, hex_id) | `demand`, `idle_supply` = `supply`, `effective_supply` = `effective_supply_t` làm tròn 4 chữ số, `surge_base` = `surge_multiplier`, `observed_ds` = demand / S_eff làm tròn 4 chữ số; khi S_eff = 0 thì để NULL với lý do `ZERO_EFFECTIVE_SUPPLY` |

Burn-in không được nạp vì chỉ là lịch sử, không thuộc kỳ chính. Script dừng và rollback nếu số dòng khác `hex_count × days × 288` tính từ manifest, nếu join raw/features không khớp đủ dòng, hoặc nếu `demand` hay `supply` khác `demand_5m` hay `idle_supply_t`.

Kết quả lần chạy ngày 2026-10-12 (khoảng 2 phút, DB 319 MB):

- 1 region, 61 hex, 61 node, 1 dataset release.
- 25.920 snapshot, từ 2026-01-05 00:05 đến 2026-04-05 00:00 giờ Việt Nam.
- 1.581.120 market state, mỗi snapshot đủ 61 hex.
- 46.575 dòng `observed_ds` NULL (2,95%), khớp `zero_effective_supply_share` của manifest.
- Quantile `observed_ds` p50/p90/p99/p999/max = 0,2013 / 1,4286 / 4,2857 / 10 / 12,5, khớp `eda_metrics` của manifest. `surge_base` nằm trong 1,0–2,7.
- Đối chiếu mẫu với parquet: dòng đầu tiên của hex `8765b5662ffffff` lúc 00:05 cho demand 0, idle 5, S_eff 10,4, surge 1,15, khớp nguồn.

Chưa nạp: recommendation và decision. Các bảng này được provider và console ghi khi chạy, không đến từ dataset.

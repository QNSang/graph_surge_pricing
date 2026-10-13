# BACKEND SPECIFICATION
## Graph Surge Recommendation System

**Version:** 1.0 — Implementation Draft  
**Date:** 12/10/2026  
**Project:** graph_surge_pricing  
**Component:** Backend Services & API  
**Environment:** DEMO / SYNTHETIC / REPLAY  
**Status:** Ready for Technical Review  
**Source:** Product Specification v0.3

---

# 1. OVERVIEW

## 1.1. Purpose

Backend cung cấp nền tảng quản lý recommendation cho hệ thống Graph Surge Pricing.

Hệ thống nhận kết quả từ Recommendation Provider và cung cấp các chức năng:

- Snapshot Management.
- Recommendation Management.
- Recommendation Validation.
- Recommendation Query API.
- Single Decision Processing.
- Batch Approval Processing.
- Manual Surge Override.
- Keep Base.
- Decision History.
- Audit Logging.
- Historical Replay.
- Provider Integration.

Backend không chịu trách nhiệm huấn luyện Machine Learning hoặc trực tiếp tính toán các thuật toán tối ưu surge.

## 1.2. Core Principle

**Model creates recommendations. Backend manages recommendations. Users make decisions.**

Model/Recommendation Provider cung cấp:

- Recommendation Action.
- Surge Base.
- Surge Delta.
- Surge Proposed.
- Explanation.
- Supporting Evidence.

Backend chịu trách nhiệm:

1. Nhận output.
2. Kiểm tra contract.
3. Kiểm tra tính hợp lệ.
4. Lưu recommendation.
5. Cung cấp dữ liệu cho Frontend.
6. Tiếp nhận quyết định từ người dùng.
7. Kiểm tra giới hạn và trạng thái.
8. Ghi nhận quyết định.
9. Lưu lịch sử và audit.

Backend không được tự tính lại đề xuất bằng một thuật toán khác.

## 1.3. MVP Boundary

MVP sử dụng synthetic dataset và mô phỏng quy trình phê duyệt.

Các quyết định được ghi nhận trong database nhưng không tạo ra thay đổi surge production.

Cần phân biệt ba khái niệm:

- `surge_base`: hệ số gốc từ bidding.
- `surge_proposed`: mức surge mà provider đề xuất.
- `surge_decided`: mức surge người vận hành lựa chọn.

Trong DEMO, `surge_decided` chỉ là kết quả quyết định mô phỏng, không phải surge đang có hiệu lực trong hệ thống ride-hailing.

---

# 2. ARCHITECTURE

## 2.1. Architecture Style

**Recommended: Modular Monolith**

Lý do:

- MVP chưa yêu cầu xử lý tải production.
- Các module có cùng domain dữ liệu.
- Cần triển khai nhanh và dễ kiểm thử.
- Không cần triển khai microservices từ đầu.
- Có thể thay thế Recommendation Provider độc lập.

Backend tổ chức thành các module có boundary rõ ràng.

## 2.2. High-Level Architecture

```text
             SYNTHETIC DATA
                   |
                   v
          +------------------+
          | Snapshot Service |
          +------------------+
                   |
                   v
          +------------------+
          | Recommendation   |
          | Provider Adapter |
          +------------------+
                   |
                   v
          +------------------+
          | Recommendation   |
          | Service          |
          +------------------+
                   |
                   v
          +------------------+
          | Validation       |
          | Service          |
          +------------------+
                   |
                   v
             PostgreSQL
                   |
                   v
          +------------------+
          | REST API         |
          +------------------+
                   |
                   v
              FRONTEND
                   |
          Accept / Edit / Keep
                   |
                   v
          +------------------+
          | Decision Service |
          +------------------+
                   |
              Single/Batch
                   |
                   v
          +------------------+
          | Audit & History  |
          +------------------+
```

Đây là kiến trúc logic. Không bắt buộc mỗi khối là một process hoặc service độc lập.

## 2.3. Technology Stack

**Proposed Stack**

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| API Framework | FastAPI |
| Validation | Pydantic v2 |
| ORM | SQLAlchemy 2.x |
| Database | PostgreSQL |
| Migration | Alembic |
| API Documentation | OpenAPI |
| Testing | pytest, httpx |
| Deployment | Docker Compose |
| Observability | Structured Logging |
| Model Integration | Python Provider Interface |

Redis là thành phần tùy chọn, chưa bắt buộc trong MVP.

Nếu cần inference bất đồng bộ hoặc tính toán model nặng, có thể bổ sung worker/queue sau. Request HTTP không nên phụ thuộc vào một tiến trình training dài.

## 2.4. Module Boundaries

Các module không được phụ thuộc trực tiếp vào implementation nội bộ của GNN.

Recommendation Provider trả về DTO chuẩn.

Decision Service chỉ sử dụng persisted recommendation và policy configuration, không import model architecture hoặc training code.

Frontend truy cập backend qua HTTP API, không truy cập trực tiếp dataset hoặc database.

---

# 3. CORE DOMAIN MODEL

## 3.1. Domain Entities

Các entity chính:

1. Dataset Release.
2. Snapshot.
3. Hex Market State.
4. Recommendation Set.
5. Recommendation.
6. Provider Metadata.
7. Policy Configuration.
8. Demo Session.
9. Decision.
10. Batch Decision.
11. Batch Item.
12. Audit Event.

## 3.2. Dataset Release

Đại diện một phiên bản dữ liệu đã được chuẩn bị.

Fields:

| Field | Type | Description |
|---|---|---|
| dataset_id | UUID/string | Dataset identity |
| dataset_name | string | Dataset name |
| dataset_version | string | Release version |
| fingerprint | string | Data fingerprint |
| source_path | string | Source data location |
| schema_version | string | Data schema |
| created_at | datetime | Import timestamp |
| metadata | JSON | Additional metadata |

MVP đọc dataset active thông qua metadata, không hard-code đường dẫn release.

Dataset gốc được xem là read-only.

## 3.3. Snapshot

Snapshot là trạng thái marketplace tại một thời điểm.

Fields:

| Field | Type |
|---|---|
| snapshot_id | UUID/string |
| dataset_id | FK |
| region_id | string |
| cutoff_ts | timestamptz |
| forecast_ts | timestamptz nullable |
| node_mapping_version | string |
| snapshot_version | string |
| data_kind | enum |
| created_at | timestamptz |

Một snapshot được xác định bởi dataset release, region, thời điểm cutoff và node mapping.

Snapshot identity không phụ thuộc vào loại model được chọn.

Cùng một snapshot có thể được sử dụng bởi nhiều Recommendation Provider.

## 3.4. Hex Market State

Lưu các thông tin cần thiết cho giao diện và provider integration.

Fields:

- snapshot_id.
- hex_id.
- demand.
- idle_supply.
- effective_supply.
- observed_ds.
- surge_base.
- bidding_source_version, nullable.
- market_metadata.
- validity information.

Giá trị thiếu phải là null kèm reason, không được tự thay bằng 0.

Các đơn vị đo và định nghĩa D/S phải gắn với metric metadata.

## 3.5. Recommendation Set

Một Recommendation Set là tập output của một provider trên một snapshot.

Fields:

- recommendation_set_id.
- snapshot_id.
- provider_id.
- provider_version.
- policy_version.
- output_contract_version.
- generated_at.
- dataset_fingerprint.
- model_metadata.
- status.

Một snapshot có thể có nhiều Recommendation Set nếu chạy nhiều provider hoặc nhiều version.

MVP chỉ hiển thị một Recommendation Set đang được chọn tại một thời điểm.

Các quyết định trong một batch mặc định phải thuộc cùng snapshot và cùng Recommendation Set.

## 3.6. Recommendation

Fields:

| Field | Type |
|---|---|
| proposal_id | UUID/string |
| recommendation_set_id | FK |
| snapshot_id | FK |
| hex_id | string |
| proposal_version | string |
| action | enum |
| surge_base | decimal |
| surge_delta | decimal nullable |
| surge_proposed | decimal nullable |
| explanation | text |
| reason_codes | JSON array |
| evidence | JSONB |
| validation_status | enum |
| created_at | timestamptz |

Recommendation sau khi được phát hành là immutable.

Nếu provider chạy lại hoặc tạo phiên bản khác, hệ thống tạo Recommendation Set/Proposal mới, không ghi đè output lịch sử.

## 3.7. Demo Session

Demo Session đại diện một phiên làm việc mô phỏng.

Fields:

- demo_session_id.
- actor_id.
- name.
- created_at.
- status.
- metadata.

Mục đích:

- Tách các lần thực hành phê duyệt.
- Cho phép replay cùng dữ liệu gốc nhiều lần.
- Không cần xóa audit khi bắt đầu một kịch bản mới.
- Ngăn quyết định của một demo session làm thay đổi session khác.

Mỗi quyết định phải gắn với demo session.

## 3.8. Decision

Fields:

| Field | Type |
|---|---|
| decision_id | UUID |
| demo_session_id | FK |
| proposal_id | FK |
| proposal_version | string |
| snapshot_id | FK |
| hex_id | string |
| action | enum |
| surge_base | decimal |
| surge_proposed | decimal nullable |
| requested_surge | decimal nullable |
| surge_decided | decimal nullable |
| reason | text nullable |
| status | enum |
| actor_id | string |
| idempotency_key | string |
| created_at | timestamptz |
| recorded_at | timestamptz nullable |

Decision lưu kết quả do người dùng lựa chọn, không làm thay đổi Recommendation.

Một proposal trong cùng demo session chỉ được có một quyết định cuối cùng thành công.

## 3.9. Batch Decision

Fields:

- batch_id.
- demo_session_id.
- snapshot_id.
- recommendation_set_id.
- actor_id.
- idempotency_key.
- status.
- total_count.
- success_count.
- failure_count.
- created_at.
- completed_at.

Batch Item lưu:

- batch_id.
- proposal_id.
- requested_action.
- status.
- decision_id, nullable.
- error_code, nullable.
- error_message, nullable.

Batch và Batch Item được lưu để truy vết partial success.

## 3.10. Audit Event

Audit Event gồm:

- event_id.
- demo_session_id.
- actor_id.
- entity_type.
- entity_id.
- action.
- previous_state.
- new_state.
- metadata.
- correlation_id.
- created_at.

Audit phải là append-only ở cấp ứng dụng và được bảo vệ bằng quyền database phù hợp.

Không chỉnh sửa/xóa sự kiện cũ để che quyết định hoặc lỗi đã xảy ra.

---

# 4. RECOMMENDATION PROVIDER INTERFACE

## 4.1. Design Goal

Backend có thể nhận recommendation từ nhiều nguồn khác nhau:

- Mock Provider.
- Rule-based Provider.
- ML Provider.
- GNN Provider.

Không phụ thuộc vào cách provider tạo ra output.

## 4.2. Provider Contract

Conceptual interface:

```python
class RecommendationProvider(Protocol):

    def generate(
        self,
        snapshot: SnapshotInput
    ) -> RecommendationBatch:
        ...
```

Provider phải trả về một collection recommendation cùng metadata.

Các implementation có thể sử dụng các cách triển khai khác nhau.

Ví dụ:

```text
MockProvider
RuleBasedProvider
GNNProvider
PrecomputedProvider
```

`PrecomputedProvider` đọc kết quả đã được model tạo trước đó, không nhất thiết chạy inference khi Frontend gọi API.

## 4.3. Provider Responsibilities

Provider chịu trách nhiệm:

1. Nhận input theo contract của provider.
2. Thực hiện inference hoặc logic nội bộ.
3. Xác định recommendation action.
4. Xác định surge proposed.
5. Tạo explanation.
6. Trả về evidence.
7. Gắn model/provider metadata.

Backend không điều chỉnh recommendation để tối ưu D/S hoặc GMV.

## 4.4. Provider Output Contract

```json
{
  "schema_version": "recommendation.v1",
  "snapshot_id": "snapshot_001",
  "provider": {
    "id": "gnn_provider",
    "version": "1.0.0"
  },
  "policy_version": "policy_v1",
  "generated_at": "2026-10-12T13:40:00+07:00",
  "recommendations": [
    {
      "proposal_id": "rec_001",
      "hex_id": "hex_001",
      "action": "INCREASE",
      "surge_base": "1.20",
      "surge_delta": "0.15",
      "surge_proposed": "1.35",
      "explanation": "Network signals indicate increasing pressure.",
      "reason_codes": ["NETWORK_PRESSURE_HIGH"],
      "evidence": {
        "demand": 120,
        "effective_supply": 85,
        "forecast_ds": 1.41
      }
    }
  ]
}
```

Surge values được biểu diễn bằng decimal string trong contract chuẩn hóa để tránh sai lệch số thực nhị phân.

Đây là contract đề xuất. Provider adapter có thể chuyển đổi từ kiểu dữ liệu nội bộ của model.

## 4.5. Provider Validation

Trước khi publish Recommendation Set:

1. Kiểm tra schema version.
2. Kiểm tra provider identity.
3. Kiểm tra snapshot tồn tại.
4. Kiểm tra hex thuộc snapshot.
5. Kiểm tra các trường bắt buộc.
6. Kiểm tra action/surge consistency.
7. Kiểm tra giá trị số hữu hạn.
8. Kiểm tra policy compatibility.
9. Kiểm tra nguồn bidding tham chiếu.
10. Kiểm tra trùng proposal/hex trong cùng set.

Nếu một recommendation không hợp lệ, backend lưu lỗi ingestion/validation và không cho phép nó được phê duyệt.

Validation không được âm thầm biến recommendation sai thành HOLD hợp lệ.

## 4.6. Provider Versioning

Mỗi Recommendation Set phải có:

- Provider ID.
- Provider Version.
- Output Schema Version.
- Policy Version.
- Dataset Fingerprint.
- Generated Timestamp.

Nếu là GNN Provider, metadata có thể bổ sung model checkpoint, feature schema, target transform hoặc inference run ID.

Các metadata này phục vụ truy vết, không bắt buộc hiển thị toàn bộ trên Dashboard.

---

# 5. VALIDATION & SAFETY

## 5.1. Validation Layers

Backend có ba cấp validation.

### Layer A — Contract Validation

Kiểm tra kiểu dữ liệu, required fields, enum và schema version.

### Layer B — Recommendation Validation

Kiểm tra tính nhất quán của recommendation:

- INCREASE: proposed > base.
- DECREASE: proposed < base.
- HOLD: proposed = base.
- REVIEW: không có giá thay đổi có thể phê duyệt.
- Delta phải nhất quán với proposed - base.
- Không có NaN/Infinity.
- Không có giá trị surge không hợp lệ.

### Layer C — Decision Validation

Kiểm tra trước khi ghi nhận quyết định:

- Actor có quyền.
- Demo session hợp lệ.
- Proposal tồn tại.
- Proposal version đúng.
- Snapshot đúng.
- Proposal chưa được xử lý thành công trong session.
- Recommendation Set hợp lệ.
- Policy version tương thích.
- Surge không vượt giới hạn.
- Requested action được phép.

## 5.2. Surge Limits

Surge constraints phải được cấu hình tại backend.

Ví dụ cấu hình:

```yaml
surge_limits:
  min: "1.00"
  max: "1.50"
  max_deviation: "0.40"
  step: "0.01"
  precision: 2
```

Các giá trị chỉ để minh họa, không phải giới hạn đã được phê duyệt.

Ý nghĩa:

- `min`: surge nhỏ nhất.
- `max`: surge lớn nhất.
- `max_deviation`: mức lệch tuyệt đối tối đa so với Surge Base.
- `step`: bước giá hợp lệ.
- `precision`: số chữ số thập phân hợp lệ.

Backend phải dùng decimal arithmetic.

Nếu giá trị không đáp ứng giới hạn, backend trả lỗi và không tự clamp.

## 5.3. Policy Version

Mỗi Recommendation được gắn với một policy version.

Khi xử lý decision, backend phải kiểm tra chính sách áp dụng.

Nếu policy đã thay đổi và proposal không còn hợp lệ, backend từ chối quyết định, yêu cầu người dùng rà soát đề xuất mới.

Không tự động tính lại delta theo policy mới.

## 5.4. Eligibility

Eligibility states:

- ELIGIBLE.
- BLOCKED.
- EXPIRED.
- SUPERSEDED.
- UNKNOWN.

Các trạng thái này độc lập với Recommendation Action.

Ví dụ một proposal INCREASE có thể bị BLOCKED vì vượt surge limit.

Một proposal REVIEW phải không được phê duyệt dù một số trường dữ liệu khác có vẻ hợp lệ.

## 5.5. Replay Eligibility

MVP sử dụng dữ liệu lịch sử synthetic. Vì vậy không được áp dụng TTL theo đồng hồ hiện tại khiến toàn bộ proposal lịch sử tự động hết hạn.

Backend phải phân biệt:

- Thời gian snapshot.
- Thời gian tạo recommendation.
- Thời gian thao tác trong Demo.
- Thời hạn của batch preview.

Trong chế độ `DEMO_REPLAY`, hệ thống cho phép xử lý proposal lịch sử để mô phỏng, nếu proposal đáp ứng quy tắc hợp lệ của demo session.

Quy tắc này không áp dụng cho production.

---

# 6. DECISION SERVICE

## 6.1. Supported Actions

Backend hỗ trợ ba action chính:

- `ACCEPT_PROPOSAL`
- `KEEP_BIDDING`
- `OVERRIDE_PROPOSAL`

Tên `KEEP_BIDDING` được giữ để tương thích với domain types hiện có của Frontend.

Frontend có thể hiển thị nhãn **Keep Base**.

## 6.2. Accept Proposal

Input:

- Proposal ID.
- Expected Proposal Version.
- Snapshot ID.
- Demo Session ID.
- Idempotency Key.

Workflow:

1. Authenticate actor.
2. Load proposal.
3. Validate session/snapshot.
4. Validate proposal version.
5. Validate eligibility.
6. Validate surge limits.
7. Check duplicate or conflicting decision.
8. Create decision.
9. Append audit event.
10. Commit transaction.
11. Return receipt.

Kết quả DEMO:

- Decision status = RECORDED.
- Surge Decided = Surge Proposed.
- Production execution = NOT_APPLICABLE.

## 6.3. Keep Bidding

User quyết định giữ Surge Base.

Workflow giống Accept, nhưng:

- Action = KEEP_BIDDING.
- Surge Decided = Surge Base.
- Status = KEPT_BIDDING.
- Không tạo thay đổi giá.

Recommendation Action ban đầu không bị thay đổi.

Một proposal INCREASE có thể nhận decision KEEP_BIDDING.

HOLD mặc định không cần nằm trong batch action, nhưng có thể được ghi nhận thủ công là giữ bidding.

## 6.4. Manual Override

Input:

- Proposal ID.
- Expected Proposal Version.
- Requested Surge.
- Reason.
- Idempotency Key.

Backend:

1. Validate actor/session.
2. Load proposal.
3. Validate eligibility.
4. Validate requested surge.
5. Validate numeric precision and step.
6. Validate min/max and max deviation.
7. Require reason.
8. Create override decision.
9. Save audit event.
10. Commit transaction.

Manual Override không được sửa Recommendation.

### Example

Model proposal:

- Surge Base = 1.20.
- Surge Proposed = 1.35.

Operator nhập:

- Requested Surge = 1.30.

Backend ghi:

- Original Surge Base = 1.20.
- Model Surge Proposed = 1.35.
- User Surge Decided = 1.30.
- Decision Action = OVERRIDE_PROPOSAL.

Trong MVP, REVIEW không được override.

HOLD có thể override khi eligible, nếu quy tắc này được xác nhận.

## 6.5. Decision Transaction

Một quyết định thành công phải ghi đồng bộ:

- Decision record.
- Audit event.
- Idempotency result.

Các bản ghi này phải nằm trong cùng database transaction.

Không được lưu decision thành công nếu audit bắt buộc chưa được lưu.

Nếu transaction thất bại thì không được trả về kết quả thành công.

## 6.6. Concurrency Control

Khi hai user cùng thao tác một proposal trong cùng demo session:

- Backend phải ngăn hai quyết định cuối cùng khác nhau.
- Dùng transaction và ràng buộc uniqueness.
- Lock hoặc kiểm tra trạng thái trong transaction.
- Trả conflict nếu proposal đã có quyết định cuối cùng.

Recommended: PostgreSQL row-level lock kết hợp unique constraint để bảo vệ khỏi race condition.

---

# 7. BATCH DECISION SERVICE

## 7.1. Supported Operations

- Accept All.
- Accept Selected.
- Batch Result Query.

Manual Edit thực hiện theo từng hex trong MVP.

Không bắt buộc batch manual override trong phiên bản đầu.

## 7.2. Batch Scope

Một batch chỉ được chứa proposals có cùng:

- Snapshot ID.
- Recommendation Set ID.
- Demo Session ID.

Nếu request trộn snapshot hoặc recommendation set, backend từ chối cấu trúc batch.

## 7.3. Accept All Semantics

Accept All có nghĩa:

**Chấp nhận tất cả proposal INCREASE/DECREASE hiện hành, hợp lệ và chưa được xử lý trong snapshot đang xem.**

Không bao gồm:

- HOLD.
- REVIEW.
- BLOCKED.
- EXPIRED.
- SUPERSEDED.
- Proposal đã có quyết định cuối cùng.

Frontend không được tự giả định số lượng proposal hợp lệ; backend là nguồn xác định eligibility.

## 7.4. Batch Preview

Nên hỗ trợ bước Preview trước khi thực hiện Accept All/Accept Selected.

Endpoint:

`POST /api/v1/batches/preview`

Backend trả về:

- Batch Plan ID.
- Snapshot ID.
- Danh sách proposal ID/version cố định.
- Số proposal có thể xử lý.
- Số proposal bị bỏ qua.
- Giá trị surge của từng proposal.
- Lý do không đủ điều kiện.
- Thời hạn hiệu lực của batch plan.

Batch Plan phải đóng băng tập proposal đã được người dùng rà soát.

Không tự động thêm proposal mới xuất hiện sau thời điểm preview.

## 7.5. Batch Commit

Endpoint:

`POST /api/v1/decisions/batch`

Input:

- Batch Plan ID.
- Demo Session ID.
- Idempotency Key.

Backend:

1. Load batch plan.
2. Validate ownership/session.
3. Validate plan expiration.
4. Revalidate từng proposal.
5. Process từng item độc lập.
6. Persist item results.
7. Aggregate batch status.
8. Return detailed results.

## 7.6. Partial Success

Batch sử dụng partial success.

Ví dụ 10 proposals:

| Status | Count |
|---|---:|
| Success | 8 |
| Blocked | 1 |
| Expired | 1 |
| Total | 10 |

Không rollback 8 item thành công do 2 item còn lại thất bại.

Mỗi item phải có result riêng.

## 7.7. Transaction Boundaries

Không sử dụng một transaction duy nhất bao trùm toàn bộ batch nếu điều đó khiến một item lỗi rollback toàn bộ.

Thay vào đó:

- Tạo batch và các batch items.
- Xử lý từng proposal trong transaction độc lập.
- Commit decision và audit cho từng item thành công.
- Ghi lỗi item thất bại.
- Tổng hợp batch status.

Cần đảm bảo quy trình an toàn khi server bị dừng giữa chừng.

Một batch chưa hoàn tất phải có thể tiếp tục hoặc được đối soát từ các item đã ghi nhận, không tạo thêm quyết định trùng.

## 7.8. Idempotency

Một request cùng:

- Actor/session.
- Operation.
- Idempotency key.
- Request payload.

Phải trả lại kết quả của cùng logical operation, không xử lý lại như một quyết định mới.

Nếu cùng key nhưng payload khác, trả lỗi `IDEMPOTENCY_CONFLICT`.

Nếu request timeout, Frontend có thể tra cứu trạng thái theo key.

Không được mặc định timeout có nghĩa là thất bại.

---

# 8. API SPECIFICATION

## 8.1. API Conventions

Base path:

`/api/v1`

Format:

- JSON.
- UTF-8.
- ISO 8601 timestamps with timezone.
- Decimal strings cho surge values.
- Stable error codes.
- Cursor pagination cho collections lớn.
- Correlation ID cho tracing.

API contract phải được công bố bằng OpenAPI.

## 8.2. Snapshot APIs

| Method | Endpoint | Description |
|---|---|---|
| GET | /snapshots | List snapshots |
| GET | /snapshots/{id} | Snapshot detail |
| GET | /snapshots/{id}/recommendations | Recommendations |
| GET | /snapshots/{id}/summary | Action counts |
| GET | /regions/{id}/hexes | Hex geography |

Filters cho `/snapshots`:

- region_id.
- from_ts.
- to_ts.
- dataset_id.
- cursor.
- limit.

## 8.3. Recommendation APIs

| Method | Endpoint | Description |
|---|---|---|
| GET | /recommendations/{id} | Proposal detail |
| GET | /providers | Provider metadata |
| GET | /policies/current | Read-only policy metadata |

Snapshot recommendation list hỗ trợ filter:

- action.
- eligibility.
- decision_status.
- hex_id.
- recommendation_set_id.

Response phải trả tổng count chính xác theo snapshot và bộ lọc.

## 8.4. History APIs

| Method | Endpoint |
|---|---|
| GET | /hexes/{hex_id}/history |
| GET | /decisions |
| GET | /decisions/{id} |
| GET | /audit-events |

History API hỗ trợ:

- from_ts.
- to_ts.
- series.
- dataset_id.
- region_id.
- cursor/limit.

Supported history series:

- BASE_BIDDING.
- DEMAND.
- EFFECTIVE_SUPPLY.
- OBSERVED_DS.
- FORECAST_DS, nếu có.

History data phải giữ rõ định nghĩa metric và source.

## 8.5. Decision APIs

| Method | Endpoint |
|---|---|
| POST | /decisions |
| POST | /batches/preview |
| POST | /decisions/batch |
| GET | /batches/{id} |
| GET | /decisions/by-idempotency/{key} |

## 8.6. Demo Session APIs

| Method | Endpoint |
|---|---|
| POST | /demo-sessions |
| GET | /demo-sessions/{id} |
| GET | /demo-sessions/{id}/decisions |

Demo session là phạm vi dữ liệu quyết định mô phỏng, không thay thế xác thực người dùng.

---

# 9. API REQUEST & RESPONSE CONTRACTS

## 9.1. Single Decision Request

```json
{
  "schema_version": "surge-decision.v1",
  "demo_session_id": "session_001",
  "idempotency_key": "intent_001",
  "proposal_id": "rec_001",
  "expected_proposal_version": "1",
  "snapshot_id": "snapshot_001",
  "action": "ACCEPT_PROPOSAL",
  "requested_surge": null,
  "reason": null
}
```

Backend phải lấy Surge Proposed từ proposal đã lưu, không tin giá surge do client gửi cho action ACCEPT_PROPOSAL.

Nếu client gửi expected bidding version/policy version thì backend phải so sánh với dữ liệu lưu trên server.

## 9.2. Single Decision Response

```json
{
  "decision_id": "dec_001",
  "proposal_id": "rec_001",
  "action": "ACCEPT_PROPOSAL",
  "status": "RECORDED",
  "surge_base": "1.20",
  "surge_proposed": "1.35",
  "surge_decided": "1.35",
  "execution_mode": "DEMO",
  "production_effective": false,
  "recorded_at": "2026-10-12T13:41:00+07:00"
}
```

Không được dùng `RECORDED` để ngụ ý surge đã được thực thi trong production.

## 9.3. Manual Override Request

```json
{
  "schema_version": "surge-decision.v1",
  "demo_session_id": "session_001",
  "idempotency_key": "intent_002",
  "proposal_id": "rec_002",
  "expected_proposal_version": "1",
  "snapshot_id": "snapshot_001",
  "action": "OVERRIDE_PROPOSAL",
  "requested_surge": "1.30",
  "reason": "Manual adjustment by operator"
}
```

Backend không cho phép bỏ trống reason nếu policy yêu cầu lý do override.

## 9.4. Batch Preview Request

```json
{
  "demo_session_id": "session_001",
  "snapshot_id": "snapshot_001",
  "recommendation_set_id": "recset_001",
  "selection_mode": "ALL_ELIGIBLE"
}
```

Với Accept Selected:

```json
{
  "demo_session_id": "session_001",
  "snapshot_id": "snapshot_001",
  "recommendation_set_id": "recset_001",
  "selection_mode": "SELECTED",
  "proposal_ids": [
    "rec_001",
    "rec_002"
  ]
}
```

## 9.5. Batch Preview Response

```json
{
  "batch_plan_id": "plan_001",
  "snapshot_id": "snapshot_001",
  "recommendation_set_id": "recset_001",
  "total_candidates": 3,
  "eligible_count": 2,
  "skipped_count": 1,
  "items": [
    {
      "proposal_id": "rec_001",
      "proposal_version": "1",
      "action": "INCREASE",
      "surge_base": "1.20",
      "surge_proposed": "1.35",
      "eligible": true
    },
    {
      "proposal_id": "rec_002",
      "proposal_version": "1",
      "action": "DECREASE",
      "surge_base": "1.40",
      "surge_proposed": "1.25",
      "eligible": true
    },
    {
      "proposal_id": "rec_003",
      "proposal_version": "1",
      "action": "REVIEW",
      "eligible": false,
      "reason_code": "REVIEW_REQUIRED"
    }
  ],
  "expires_at": "2026-10-12T13:45:00+07:00"
}
```

`expires_at` ở ví dụ là thời hạn batch plan, không phải thời hạn mặc định của recommendation.

## 9.6. Batch Commit Request

```json
{
  "demo_session_id": "session_001",
  "batch_plan_id": "plan_001",
  "idempotency_key": "batch_intent_001"
}
```

## 9.7. Batch Result

```json
{
  "batch_id": "batch_001",
  "status": "PARTIAL_SUCCESS",
  "total": 2,
  "succeeded": 1,
  "failed": 1,
  "results": [
    {
      "proposal_id": "rec_001",
      "status": "SUCCESS",
      "decision_id": "dec_001"
    },
    {
      "proposal_id": "rec_002",
      "status": "FAILED",
      "error_code": "PROPOSAL_SUPERSEDED"
    }
  ]
}
```

Result phải có một item tương ứng cho mỗi proposal được đưa vào batch plan để xử lý.

Các proposal bị loại ngay trong Preview không được tính là đã xử lý ở Commit.

---

# 10. ERROR HANDLING

## 10.1. Standard Error Schema

```json
{
  "error": {
    "code": "SURGE_LIMIT_EXCEEDED",
    "message": "Requested surge exceeds configured limits.",
    "details": {
      "proposal_id": "rec_001",
      "requested_surge": "1.80"
    },
    "correlation_id": "req_001"
  }
}
```

## 10.2. Error Codes

| Code | Description |
|---|---|
| INVALID_REQUEST | Request không hợp lệ |
| SCHEMA_VERSION_UNSUPPORTED | Schema version không hỗ trợ |
| SNAPSHOT_NOT_FOUND | Không tìm thấy snapshot |
| PROPOSAL_NOT_FOUND | Không tìm thấy proposal |
| PROPOSAL_BLOCKED | Proposal không đủ điều kiện |
| PROPOSAL_EXPIRED | Proposal hết hạn |
| PROPOSAL_SUPERSEDED | Proposal bị thay thế |
| PROPOSAL_VERSION_CONFLICT | Proposal version thay đổi |
| POLICY_VERSION_CONFLICT | Policy không tương thích |
| SNAPSHOT_MISMATCH | Batch chứa sai snapshot |
| RECOMMENDATION_SET_MISMATCH | Batch chứa nhiều recommendation set |
| SURGE_LIMIT_EXCEEDED | Vượt giới hạn surge |
| INVALID_SURGE_STEP | Sai bước điều chỉnh |
| INVALID_SURGE_PRECISION | Sai precision |
| REVIEW_REQUIRED | Proposal cần review |
| DECISION_ALREADY_EXISTS | Proposal đã được xử lý |
| IDEMPOTENCY_CONFLICT | Idempotency key bị dùng sai |
| BATCH_PLAN_EXPIRED | Batch plan hết hạn |
| PERMISSION_DENIED | Không có quyền |
| PROVIDER_OUTPUT_INVALID | Output provider sai contract |
| INTERNAL_ERROR | Lỗi hệ thống |

## 10.3. HTTP Status

Khuyến nghị:

- 200 — Successful query/operation result.
- 201 — Resource created.
- 400 — Invalid request syntax/parameters.
- 401 — Unauthenticated.
- 403 — Permission denied.
- 404 — Resource not found.
- 409 — Version/idempotency/decision conflict.
- 422 — Validation failed.
- 503 — Temporarily unavailable.

Batch partial success được biểu diễn bằng JSON body và trạng thái batch, không dựa duy nhất vào HTTP status.

Timeout hoặc mất kết nối không đủ để kết luận một mutation đã thất bại. Client phải tra cứu trạng thái request bằng idempotency key.

---

# 11. DATABASE DESIGN

## 11.1. Proposed Tables

```text
dataset_releases
snapshots
hex_market_states
recommendation_sets
recommendations
provider_metadata
policy_configs
demo_sessions
decisions
decision_batches
decision_batch_items
batch_plans
idempotency_records
audit_events
```

Có thể thêm bảng geography/hex metadata độc lập nếu nhiều snapshot dùng chung polygon và node mapping.

## 11.2. Relationships

```text
dataset_releases
    |
    +-- snapshots
            |
            +-- hex_market_states
            |
            +-- recommendation_sets
                    |
                    +-- recommendations
                            |
                            +-- decisions
                                    |
                                    +-- audit_events

demo_sessions
    |
    +-- decisions
    |
    +-- decision_batches
            |
            +-- decision_batch_items
```

Batch plan chứa danh sách proposal/version được đóng băng khi preview.

## 11.3. Integrity Constraints

Bắt buộc:

- Foreign keys cho các quan hệ chính.
- Unique snapshot identity theo dataset/region/cutoff/node mapping.
- Unique recommendation theo recommendation set và hex.
- Không có hai quyết định cuối cùng thành công cho cùng proposal trong cùng demo session.
- Unique idempotency identity theo actor/session/operation.
- Check constraints cho các trường số hoặc trạng thái phù hợp.
- Timestamp lưu dưới dạng timestamptz.

Đối với successful decision uniqueness, cần sử dụng transaction kết hợp unique constraint/index phù hợp với state machine, không chỉ kiểm tra bằng application code.

## 11.4. Recommended Indexes

- Snapshot: `(dataset_id, region_id, cutoff_ts)`.
- Market state: `(snapshot_id, hex_id)`.
- Recommendation: `(recommendation_set_id, hex_id)`.
- Recommendation: `(snapshot_id, action)`.
- Decision: `(demo_session_id, proposal_id)`.
- Decision: `(actor_id, created_at)`.
- Batch: `(demo_session_id, created_at)`.
- Audit: `(entity_type, entity_id, created_at)`.
- Idempotency: unique `(scope, key)`.

Các index cần được kiểm chứng bằng query plan khi có dữ liệu và workload thực.

## 11.5. Immutability

Các entity nên được xem là immutable sau khi publish:

- Dataset Release.
- Published Snapshot.
- Market Snapshot Data.
- Published Recommendation Set.
- Published Recommendation.

Decision status và batch processing state có thể cập nhật theo lifecycle, nhưng mọi chuyển trạng thái quan trọng phải có audit event.

Không sử dụng UPDATE trên snapshot nguồn để phản ánh manual override.

---

# 12. SNAPSHOT & REPLAY SERVICE

## 12.1. Snapshot Loading

Backend đọc dataset active từ metadata/manifest.

Không hard-code số hex, số ngày hoặc số snapshot.

Nguồn synthetic cần có:

- Dataset fingerprint.
- Region.
- Snapshot timestamps.
- Node mapping.
- Surge Base.
- Market features.
- Data validity.

Frontend chỉ tải phần cần thiết qua API.

Không tải toàn bộ dataset 30 ngày vào browser chỉ để xem một snapshot.

## 12.2. Replay Semantics

Khi user chuyển snapshot:

1. Frontend gửi Snapshot ID.
2. Backend trả market state và recommendation tương ứng.
3. Frontend cập nhật map/queue/panel.
4. Các decision đã được ghi trước đó được truy xuất theo demo session.
5. Snapshot nguồn vẫn giữ nguyên.

User actions trong replay không được tạo snapshot source mới hoặc thay đổi historical bidding.

## 12.3. Market History API

History phải hỗ trợ:

- Hex ID.
- Start timestamp.
- End timestamp.
- Series kind.
- Timezone.
- Metric definition.
- Validity reason.

Ví dụ:

```json
{
  "hex_id": "hex_001",
  "series_kind": "BASE_BIDDING",
  "unit": "multiplier",
  "points": [
    {
      "ts": "2026-01-27T14:20:00+07:00",
      "value": "1.20"
    },
    {
      "ts": "2026-01-27T14:25:00+07:00",
      "value": "1.30"
    }
  ]
}
```

BASE_BIDDING không được lấy từ Surge Proposed hoặc Manual Override.

## 12.4. Read Model Consistency

Map, Queue và Detail Panel phải sử dụng cùng snapshot identity.

Backend nên cung cấp một snapshot read model thống nhất, hoặc các API response có version/identity để Frontend kiểm tra tính đồng bộ.

Không được trả market data ở cutoff A và recommendation ở cutoff B dưới cùng một snapshot response.

D/S observation và forecast phải có metric metadata rõ. Backend không tự đổi công thức target hoặc inverse transform để làm dữ liệu khớp giao diện.

---

# 13. AUTHENTICATION & AUTHORIZATION

## 13.1. Demo Authentication

MVP có thể sử dụng một cơ chế xác thực đơn giản, nhưng actor phải được backend xác định.

Phương án đề xuất:

- Server-issued demo access token.
- Demo operator identity.
- Demo session ownership.

Không tin `actor_id` do frontend tự khai.

## 13.2. Permissions

Các permissions:

- snapshot.read
- recommendation.read
- decision.accept
- decision.override
- decision.keep
- batch.accept
- audit.read

MVP có thể cấp toàn bộ quyền cho role `OPERATOR`.

Nếu có Viewer, chỉ cấp quyền đọc.

## 13.3. Security Rules

- Validate mọi input.
- Không tin eligibility do client gửi.
- Không tin execution mode do client tự chọn.
- Không hard-code secret vào frontend.
- Giới hạn CORS.
- Kiểm tra demo session ownership.
- Rate limit mutation endpoints nếu cần.
- Ghi audit đối với thay đổi quyết định.
- Không expose stack trace hoặc secret trong API errors.

Các Demo APIs không được có đường gọi đến production pricing gateway.

---

# 14. OBSERVABILITY & AUDIT

## 14.1. Structured Logging

Mỗi request cần có:

- request_id/correlation_id.
- endpoint.
- actor_id, nếu có.
- demo_session_id, nếu có.
- snapshot_id, nếu có.
- proposal_id/batch_id, nếu có.
- result status.
- processing duration.
- error code, nếu có.

Không ghi token, credentials hoặc dữ liệu nhạy cảm không cần thiết.

## 14.2. Application Metrics

Các metric đề xuất:

- api_request_count.
- api_error_count.
- api_latency.
- recommendation_validation_failure_count.
- decision_success_count.
- decision_failure_count.
- batch_partial_success_count.
- provider_output_invalid_count.
- idempotency_replay_count.

## 14.3. Audit Requirements

Mọi decision phải truy vết được:

- Ai thực hiện.
- Thao tác gì.
- Trên proposal nào.
- Thuộc snapshot nào.
- Model/provider nào tạo proposal.
- Surge Base là bao nhiêu.
- Model đề xuất bao nhiêu.
- Người dùng lựa chọn bao nhiêu.
- Quyết định được ghi lúc nào.
- Validation và kết quả xử lý là gì.

Audit không được bị thay thế bởi application logs thông thường.

---

# 15. TESTING STRATEGY

## 15.1. Unit Tests

Các nhóm test:

- Recommendation schema validation.
- Action/surge consistency.
- Decimal precision.
- Surge limits.
- Eligibility rules.
- Decision state transitions.
- Error mapping.
- Provider adapters.

## 15.2. Integration Tests

Kiểm thử:

- API với PostgreSQL.
- Snapshot query.
- Recommendation query.
- Decision persistence.
- Batch processing.
- Audit writes.
- Idempotency.
- Concurrency.
- Replay integrity.

## 15.3. Mandatory Test Scenarios

| ID | Scenario | Expected |
|---|---|---|
| BE-01 | Provider trả INCREASE hợp lệ | Proposal được lưu |
| BE-02 | Provider trả action/price mâu thuẫn | Proposal bị chặn |
| BE-03 | Provider trả NaN/Infinity | Không publish hợp lệ |
| BE-04 | Accept một proposal | Decision RECORDED |
| BE-05 | Keep Base | Surge Decided = Base |
| BE-06 | Manual Override hợp lệ | Decision được ghi |
| BE-07 | Manual Override vượt limit | Rejected |
| BE-08 | Accept REVIEW | Rejected |
| BE-09 | Batch nhiều snapshot | Rejected |
| BE-10 | Batch 8 valid, 2 invalid | 8 success, 2 failure |
| BE-11 | Retry cùng idempotency key | Không tạo duplicate |
| BE-12 | Cùng key, payload khác | Conflict |
| BE-13 | Hai request đồng thời trên một proposal | Tối đa một final successful decision |
| BE-14 | Proposal version sai | Conflict |
| BE-15 | Policy thay đổi trước commit | Revalidation/rejection |
| BE-16 | Replay snapshot lịch sử | Source không đổi |
| BE-17 | Decision sau reload | Persisted |
| BE-18 | Audit transaction failure | Không có successful decision thiếu audit |
| BE-19 | Provider mới cùng contract | API không thay đổi |
| BE-20 | DEMO decision | Không gọi production execution |
| BE-21 | Batch bị gián đoạn | Resume/reconcile không tạo trùng |
| BE-22 | Dữ liệu chart có null/gap | Giữ null và reason |
| BE-23 | Accept All sau Preview có proposal mới | Không tự thêm vào plan |
| BE-24 | Actor không có quyền | Permission denied |

## 15.4. End-to-End Testing

E2E flow bắt buộc:

1. Create Demo Session.
2. Load Snapshot.
3. Load Recommendations.
4. Select Hex.
5. Accept Recommendation.
6. Manual Edit another Hex.
7. Keep Base another Hex.
8. Preview Accept All.
9. Commit Batch.
10. Review Batch Results.
11. Query Decision History.
12. Query Audit.
13. Replay Snapshot.
14. Verify Source Data Unchanged.

---

# 16. PERFORMANCE REQUIREMENTS

## 16.1. MVP Workload

Dataset hiện có được thiết kế theo nhịp snapshot 5 phút và nhiều vùng H3.

Backend phải lấy số lượng vùng, thời gian và dữ liệu từ metadata thay vì mã hóa cứng thông số của dataset hiện tại.

## 16.2. Proposed Performance Targets

Các chỉ tiêu sau là mục tiêu kỹ thuật đề xuất, chưa phải KPI đã đo:

| Operation | Target |
|---|---|
| Load snapshot metadata | P95 < 300 ms |
| Get recommendations for snapshot | P95 < 500 ms |
| Get recommendation detail | P95 < 300 ms |
| Single DEMO decision | P95 < 500 ms |
| Batch 100 items | P95 < 3 s |
| Historical chart query | P95 < 500 ms |

Cần đo trên môi trường thử nghiệm có cấu hình phần cứng và dữ liệu cụ thể trước khi đưa vào nghiệm thu chính thức.

## 16.3. Scaling Strategy

MVP không yêu cầu microservices.

Khi cần mở rộng:

- Cache immutable snapshot responses.
- Pagination/cursor cho history/audit.
- Index database.
- Precompute provider output.
- Async inference workers.
- Tách model serving nếu cần GPU.
- Tách execution gateway khi tích hợp production.

Redis/queue chỉ bổ sung khi có yêu cầu cụ thể về latency, concurrency hoặc background processing.

---

# 17. PROJECT STRUCTURE

Cấu trúc đề xuất:

```text
backend/
  app/
    main.py

    api/
      v1/
        snapshots.py
        recommendations.py
        providers.py
        decisions.py
        batches.py
        history.py
        audit.py
        demo_sessions.py

    core/
      config.py
      security.py
      errors.py
      logging.py

    domain/
      enums.py
      entities.py
      schemas.py
      policies.py

    services/
      snapshot_service.py
      recommendation_service.py
      validation_service.py
      decision_service.py
      batch_service.py
      replay_service.py
      audit_service.py

    providers/
      base.py
      registry.py
      mock_provider.py
      rule_provider.py
      precomputed_provider.py
      gnn_adapter.py

    repositories/
      snapshot_repository.py
      recommendation_repository.py
      decision_repository.py
      batch_repository.py
      audit_repository.py

    db/
      base.py
      session.py
      models/
      migrations/

    schemas/
      snapshot.py
      recommendation.py
      decision.py
      batch.py
      history.py
      errors.py

    ingestion/
      dataset_loader.py
      snapshot_builder.py
      recommendation_importer.py

  tests/
    unit/
    integration/
    e2e/
    fixtures/

  scripts/
    import_dataset.py
    prepare_demo.py

  pyproject.toml
  Dockerfile
  compose.yaml
  .env.example
  README.md
```

Đây là cấu trúc tham chiếu cho implementation mới, không phải mô tả thư mục đang tồn tại.

Nên giữ phân tách:

**API → Service → Repository → Database**

Provider adapters chỉ tham gia ở lớp recommendation ingestion/generation.

---

# 18. IMPLEMENTATION ROADMAP

## Phase 1 — Foundation

Deliverables:

- FastAPI application.
- Pydantic schemas.
- PostgreSQL connection.
- Alembic migrations.
- Environment configuration.
- Error handling.
- OpenAPI documentation.

Acceptance:

- Backend khởi động thành công.
- Health checks hoạt động.
- Database migrations chạy được.
- CI chạy unit tests.

## Phase 2 — Read APIs

Deliverables:

- Dataset importer.
- Snapshot Service.
- Recommendation Provider Interface.
- Mock Provider.
- Recommendation validation.
- Snapshot/Recommendation APIs.
- Market History API.

Acceptance:

- Frontend có thể đọc dữ liệu từ Backend.
- API trả đúng snapshot và recommendation.
- Data contract tests đạt.

## Phase 3 — Decision Engine

Deliverables:

- Demo Session.
- Decision Service.
- Accept.
- Keep Bidding.
- Manual Override.
- Surge Validation.
- Decision Persistence.
- Idempotency.

Acceptance:

- Single decisions chạy đúng.
- Không có duplicate decisions.
- Audit được ghi atomically.

## Phase 4 — Batch Processing

Deliverables:

- Batch Preview.
- Accept All.
- Accept Selected.
- Batch Commit.
- Partial Success.
- Batch History.

Acceptance:

- Batch xử lý đúng phạm vi.
- Không tự thêm proposal ngoài preview.
- Item thất bại không rollback các item thành công.
- Retry an toàn.

## Phase 5 — Replay & Audit

Deliverables:

- Replay APIs.
- Historical Market Series.
- Decision History.
- Audit Query.
- Frontend integration.

Acceptance:

- Có thể replay dữ liệu.
- Decision history tồn tại sau reload.
- Không sửa snapshot nguồn.

## Phase 6 — Model Integration

Deliverables:

- GNN Provider Adapter.
- Provider metadata/version integration.
- Output normalization.
- Provider contract tests.

Acceptance:

- Có thể thay Mock Provider bằng GNN Provider.
- Không cần thay đổi business workflow.
- Không cần viết lại Frontend API.
- Backend không phụ thuộc vào training pipeline implementation.

---

# 19. OPEN TECHNICAL DECISIONS

Các điểm cần xác nhận trước khi implementation:

**TD-01 — Stack**

FastAPI/PostgreSQL có được chọn làm stack chính thức hay không?

**TD-02 — Deployment**

Backend chạy local development, Docker Compose hay môi trường cloud cho MVP?

**TD-03 — Data Import**

Import toàn bộ snapshot vào PostgreSQL hay đọc trực tiếp Parquet rồi chỉ lưu metadata/index trong database?

**TD-04 — Provider Execution**

GNN Provider được gọi synchronously, qua model serving API hay sử dụng precomputed recommendation files?

**TD-05 — Demo Authentication**

Sử dụng tài khoản demo có đăng nhập hay một server-issued demo identity cố định?

**TD-06 — Manual Edit for HOLD**

Cho phép Operator chỉnh tay proposal HOLD hay chỉ giữ nguyên base?

**TD-07 — Expiration**

Quy tắc hết hạn của proposal và batch plan trong DEMO/REPLAY.

**TD-08 — Policy Config**

Giá trị và nguồn cấu hình surge min/max/step/max deviation.

**TD-09 — Retention**

Thời hạn lưu Demo Session, Decisions, Audit và Batch Plans.

**TD-10 — Provider Evidence**

Các trường evidence tối thiểu bắt buộc cho mọi provider và những trường chỉ có khi sử dụng GNN.

Các quyết định này không yêu cầu thay đổi ý tưởng sản phẩm, nhưng có ảnh hưởng đến thiết kế kỹ thuật cuối cùng.

---

# 20. DEFINITION OF DONE

Backend MVP được coi là hoàn thành khi:

- Có API load snapshots.
- Có API trả recommendations.
- Có Recommendation Provider Interface.
- Có Mock/Precomputed Provider.
- Có recommendation validation.
- Có surge policy validation.
- Có Accept Proposal.
- Có Keep Bidding.
- Có Manual Override.
- Có Accept Selected.
- Có Accept All.
- Có Batch Preview.
- Có partial success.
- Có idempotency.
- Có concurrency protection.
- Có Demo Session.
- Có Decision History.
- Có Audit Log.
- Có Replay APIs.
- Có immutable historical snapshots.
- Có OpenAPI documentation.
- Có database migrations.
- Có unit/integration/E2E tests.
- Không có đường thực thi surge production trong DEMO.
- Có thể tích hợp provider mới qua contract mà không thay đổi các business endpoints.

## Final Architecture Principle

**Recommendation Provider → Validation → Persistence → API → Operator Decision → Audit**

Backend giữ vai trò orchestration và decision management.

Backend không sở hữu thuật toán GNN hoặc logic tối ưu surge.

Mọi thay đổi model, feature, training hoặc loss phải được cô lập sau Recommendation Provider Interface.

---

**End of Backend Specification v1.0**
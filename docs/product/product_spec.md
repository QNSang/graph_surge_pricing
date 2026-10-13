# PRODUCT SPECIFICATION
## Graph Surge Recommendation System

**Version:** 0.3 — Product Specification Draft  
**Date:** 12/10/2026  
**Project:** graph_surge_pricing  
**Product:** Surge Recommendation Console  
**Environment:** Synthetic Data / Demo / Replay  
**Primary Users:** Pricing & Operations Team  
**Status:** Draft — Pending Final Review

---

# 1. PRODUCT OVERVIEW

## 1.1. Background

Hệ thống ride-hailing hiện có một cơ chế bidding/surge pricing để xác định hệ số giá tại từng khu vực.

Tuy nhiên, thị trường vận hành dưới dạng một mạng lưới các khu vực có liên quan với nhau. Trạng thái của một khu vực có thể chịu ảnh hưởng từ nhu cầu, nguồn cung và sự dịch chuyển tài xế ở những khu vực khác.

Dự án Graph Surge Pricing nghiên cứu việc sử dụng Machine Learning, đặc biệt là Graph Neural Networks, để học thông tin từ mạng lưới và tạo ra các đề xuất điều chỉnh surge dựa trên Surge Base hiện tại.

Hệ thống sản phẩm không trực tiếp giải quyết bài toán huấn luyện model. Thay vào đó, hệ thống đóng vai trò là nền tảng tiếp nhận, quản lý, hiển thị và xử lý các recommendation do model cung cấp.

## 1.2. Product Vision

Xây dựng một hệ thống hỗ trợ Pricing/Ops quan sát và quản lý các đề xuất điều chỉnh surge pricing theo khu vực, với các khả năng:

- Quan sát tình trạng marketplace trên bản đồ.
- Nhận các đề xuất INCREASE, DECREASE, HOLD và REVIEW.
- Theo dõi Surge Base và surge được đề xuất.
- Xem giải thích và bằng chứng liên quan đến recommendation.
- Duyệt đồng loạt hoặc duyệt từng khu vực.
- Điều chỉnh surge thủ công cho từng khu vực.
- Theo dõi lịch sử quyết định và thao tác.
- Replay dữ liệu và recommendation theo thời gian.

Hệ thống phải cho phép tích hợp nhiều loại model mà không thay đổi giao diện người dùng hoặc quy trình vận hành cốt lõi.

## 1.3. Product Goal

Mục tiêu nghiên cứu của dự án là khai thác thông tin mạng lưới để đề xuất các điều chỉnh Surge Base, hướng tới cải thiện cân bằng Demand/Supply.

Tuy nhiên, Product Specification không quy định cách model tối ưu mục tiêu này.

Các thành phần sau thuộc Model/Research Specification:

- Model architecture.
- Feature engineering.
- Graph representation.
- Loss functions.
- Forecasting methods.
- Optimization objectives.
- Causal inference.
- Model evaluation.

Product Specification chỉ quy định cách hệ thống tiêu thụ và xử lý kết quả cuối cùng của Recommendation Provider.

## 1.4. Product Principles

**P1 — Model-agnostic**

Hệ thống không phụ thuộc vào một kiến trúc ML cụ thể. Rule-based, ML và GNN có thể được tích hợp thông qua một output contract chung.

**P2 — Recommendation-first**

Recommendation được tạo bởi provider. Backend không tự tính toán lại thuật toán đề xuất.

**P3 — Human-in-the-loop**

Trong MVP, mọi quyết định thay đổi surge đều do Pricing/Ops xác nhận hoặc chỉnh sửa thủ công.

**P4 — Surge Base Preservation**

Surge Base là giá tham chiếu do cơ chế bidding hiện tại cung cấp. Recommendation là một đề xuất điều chỉnh, không thay thế dữ liệu bidding gốc.

**P5 — Transparent Decisions**

Người dùng phải biết mức surge hiện tại, mức surge được đề xuất, lý do và trạng thái xử lý.

**P6 — Auditability**

Mọi quyết định của người dùng phải được ghi nhận và có khả năng truy vết.

**P7 — Demo Isolation**

MVP sử dụng dữ liệu synthetic và không thực hiện thay đổi giá trong hệ thống production.

---

# 2. SCOPE

## 2.1. MVP Scope

MVP bao gồm:

1. Dashboard giám sát trạng thái các vùng.
2. Bản đồ H3 hiển thị recommendation.
3. Recommendation Queue.
4. Chi tiết recommendation theo hex.
5. Hiển thị Surge Base và Surge Proposed.
6. Biểu đồ lịch sử Surge Base, D/S, Demand và Supply.
7. Accept All.
8. Accept Selected.
9. Accept từng hex.
10. Manual Edit từng hex.
11. Keep Base từng hex.
12. Batch approval với partial success.
13. Snapshot Replay.
14. Decision History.
15. Audit Log.
16. Backend API.
17. Recommendation Provider Interface.
18. Kiểm thử chức năng và tích hợp.

## 2.2. Out of Scope

Các chức năng sau không nằm trong MVP:

- Huấn luyện model trực tiếp trên giao diện.
- Model experiment dashboard.
- MLflow management UI.
- Tự động thay đổi surge production.
- Tích hợp trực tiếp với bidding engine production.
- Rider/Driver application.
- Thanh toán và tính cước chuyến đi.
- Cấu hình loss function trên giao diện.
- Tối ưu model hyperparameters.
- A/B testing production.
- Hệ thống tự động áp dụng recommendation không cần người duyệt.

---

# 3. SYSTEM ARCHITECTURE

## 3.1. High-level Architecture

Luồng dữ liệu tổng quát:

**Marketplace Data → Recommendation Provider → Backend → Frontend → User Decision → Backend → Audit**

### Layer 1 — Data Source

Cung cấp dữ liệu marketplace theo từng snapshot.

Thông tin có thể bao gồm:

- H3 Hex ID.
- Timestamp.
- Demand.
- Effective Supply.
- D/S.
- Surge Base.
- Neighbor information.
- OD flows.
- Các thông tin hỗ trợ recommendation.

MVP sử dụng synthetic dataset hiện có.

### Layer 2 — Recommendation Provider

Recommendation Provider nhận dữ liệu và tạo ra kết quả đề xuất cuối cùng.

Các provider được hỗ trợ về mặt kiến trúc:

- Mock Provider.
- Rule-based Provider.
- Machine Learning Provider.
- GNN Provider.

Tất cả provider phải trả về cùng một Recommendation Output Contract.

Provider có thể sử dụng nhiều bước xử lý nội bộ, nhưng các bước này không phải trách nhiệm của Frontend.

Ví dụ, GNN Provider có thể bao gồm:

1. Data preprocessing.
2. Network feature extraction.
3. GNN inference.
4. Surge adjustment calculation.
5. Action classification.
6. Explanation generation.

Frontend chỉ nhận output cuối cùng.

### Layer 3 — Backend

Backend có các trách nhiệm:

- Nhận output từ Recommendation Provider.
- Kiểm tra schema và dữ liệu hợp lệ.
- Kiểm tra giới hạn surge theo cấu hình.
- Quản lý snapshots và recommendations.
- Cung cấp API cho Frontend.
- Xử lý user decisions.
- Xử lý batch approval.
- Ghi lịch sử và audit.
- Phân biệt trạng thái Demo và trạng thái thực thi production.

Backend không tự huấn luyện model hoặc tự tái tạo logic suy luận của model.

### Layer 4 — Frontend

Frontend là giao diện vận hành cho Pricing/Ops.

Các nhiệm vụ:

- Hiển thị dữ liệu marketplace.
- Hiển thị kết quả recommendation.
- Hỗ trợ lựa chọn và phê duyệt.
- Cung cấp tính năng chỉnh sửa surge thủ công.
- Hiển thị biểu đồ và bằng chứng.
- Hiển thị lịch sử, kết quả xử lý và replay.

Frontend không được tự quyết định tính hợp lệ cuối cùng của proposal.

---

# 4. RECOMMENDATION SYSTEM

## 4.1. Recommendation Actions

Mỗi hex trong một snapshot có thể nhận một trong bốn recommendation actions.

| Action | Meaning | UI Behavior |
|---|---|---|
| INCREASE | Đề xuất tăng surge so với base | Hiển thị mức surge tăng |
| DECREASE | Đề xuất giảm surge so với base | Hiển thị mức surge giảm |
| HOLD | Đề xuất giữ nguyên surge | Hiển thị Surge Base không đổi |
| REVIEW | Recommendation không đủ điều kiện xử lý | Hiển thị cảnh báo và lý do |

## 4.2. Recommendation Output

Mỗi recommendation phải chứa đủ dữ liệu để Frontend hiển thị và Backend xử lý.

### Required Fields

| Field | Type | Description |
|---|---|---|
| proposal_id | string | ID duy nhất của proposal |
| proposal_version | string | Phiên bản proposal |
| snapshot_id | string | Snapshot chứa recommendation |
| hex_id | string | H3 Hex Identifier |
| action | enum | INCREASE / DECREASE / HOLD / REVIEW |
| surge_base | number | Surge từ bidding hiện tại |
| surge_delta | number/null | Mức điều chỉnh surge |
| surge_proposed | number/null | Surge được đề xuất |
| explanation | string | Giải thích ngắn |
| evidence | object | Bằng chứng hỗ trợ |
| provider_id | string | Provider tạo recommendation |
| provider_version | string | Version của provider |
| policy_version | string | Version quy tắc giới hạn/kiểm tra |
| generated_at | datetime | Thời điểm recommendation được tạo |

Các timestamp phải có timezone rõ ràng.

### Example Recommendation

```json
{
  "proposal_id": "rec_0001",
  "proposal_version": "1",
  "snapshot_id": "snapshot_001",
  "hex_id": "hex_001",
  "action": "INCREASE",
  "surge_base": 1.20,
  "surge_delta": 0.15,
  "surge_proposed": 1.35,
  "explanation": "Dự báo áp lực cầu tăng tại khu vực.",
  "evidence": {
    "demand": 120,
    "effective_supply": 85,
    "forecast_ds": 1.41
  },
  "provider_id": "mock_provider",
  "provider_version": "0.1",
  "policy_version": "demo_policy_v1",
  "generated_at": "2026-10-12T13:40:00+07:00"
}
```

Dữ liệu ví dụ chỉ mang tính minh họa.

## 4.3. Recommendation Validation

Backend phải kiểm tra:

- Required fields.
- Schema version.
- Proposal ID và snapshot ID.
- Action hợp lệ.
- Surge Base hợp lệ.
- Surge Proposed hợp lệ.
- Surge Delta hợp lệ.
- Sự nhất quán giữa Base, Delta và Proposed.
- Giới hạn surge theo cấu hình.
- Provider/policy version.
- Trạng thái proposal.

Đối với INCREASE, Surge Proposed phải lớn hơn Surge Base.

Đối với DECREASE, Surge Proposed phải nhỏ hơn Surge Base.

Đối với HOLD, Surge Proposed bằng Surge Base và Delta bằng 0.

Đối với REVIEW, không có thay đổi surge có thể được phê duyệt trong MVP.

Backend từ chối proposal không hợp lệ và trả về lý do có cấu trúc.

Backend không tự động sửa giá trị model đề xuất để vượt qua validation.

## 4.4. Explanation & Evidence

Frontend phải hiển thị hai cấp thông tin.

**Level 1 — Summary**

- Recommendation Action.
- Surge Base.
- Surge Proposed.
- Surge Delta.
- Explanation ngắn.

**Level 2 — Drill-down**

- Demand.
- Effective Supply.
- D/S.
- Surge Base History.
- Relevant Forecast Signals, nếu provider cung cấp.
- Recommendation Metadata.
- Provider/Model Version.
- Lý do validation hoặc cảnh báo.

Không bắt buộc Frontend phải hiển thị toàn bộ feature hoặc attention weight bên trong model.

Bằng chứng phải được lấy từ output hoặc nguồn dữ liệu có contract, không được Frontend tự suy diễn thành kết luận mới.

---

# 5. USER ROLES

## 5.1. Pricing/Ops Operator

Là người dùng chính của sản phẩm.

Có thể:

- Xem dashboard.
- Chọn snapshot.
- Xem recommendations.
- Xem chi tiết từng hex.
- Accept recommendation.
- Accept Selected.
- Accept All.
- Manual Edit surge.
- Keep Base.
- Xem Decision History.
- Xem Audit Log.
- Replay snapshots.

## 5.2. Viewer — Future/Optional

Chỉ có quyền quan sát và phân tích dữ liệu, không có quyền thay đổi trạng thái quyết định.

## 5.3. Admin — Future/Optional

Có thể quản lý quyền truy cập và các cấu hình vận hành.

MVP có thể sử dụng một Operator persona; tuy nhiên, backend vẫn phải phân biệt actor và quyền thao tác trong decision records.

---

# 6. FRONTEND SPECIFICATION

## 6.1. Main Dashboard

Tên màn hình: **Surge Recommendation Console**

Màn hình chính được tổ chức thành các khu vực:

### A. Header

Hiển thị:

- Product Name.
- Region.
- Current Snapshot.
- Data Source.
- Execution Mode.
- Provider/Model Version.
- Timestamp.
- Trạng thái tải dữ liệu.

MVP phải hiển thị rõ chế độ DEMO và dữ liệu SYNTHETIC.

### B. Recommendation Summary

Hiển thị số lượng recommendation theo từng loại:

- INCREASE.
- DECREASE.
- HOLD.
- REVIEW.

Số lượng phải được tính theo snapshot đang xem, không trộn dữ liệu nhiều snapshot.

Có thể hiển thị thêm tổng số proposal đủ điều kiện duyệt.

### C. H3 Map

Bản đồ là thành phần trực quan chính của Dashboard.

Mỗi hex được hiển thị theo dữ liệu recommendation hoặc market layer đang chọn.

Các map layers:

- Recommendation Action.
- D/S.
- Demand.
- Effective Supply.
- Surge Base.
- Surge Delta.

Default Layer: **Recommendation Action**.

Màu sắc đề xuất:

- INCREASE: Orange.
- DECREASE: Blue.
- HOLD: Neutral Gray.
- REVIEW: Purple.

Màu sắc cần đi kèm nhãn/chú giải, không được là dấu hiệu nhận biết duy nhất.

Map phải hỗ trợ:

- Zoom.
- Pan.
- Select Hex.
- Highlight selected hex.
- Tooltip.
- Map Layer Switching.
- Reset View.
- Hiển thị OD/Network Overlay khi có dữ liệu phù hợp.

Khi chọn một hex trên Map, Recommendation Detail Panel phải cập nhật theo hex đó.

### D. Recommendation Detail Panel

Hiển thị thông tin của hex đang chọn.

Các thành phần:

1. Hex Information.
2. Recommendation Action.
3. Surge Base.
4. Surge Proposed.
5. Surge Delta.
6. Explanation Summary.
7. Evidence.
8. History Charts.
9. Action Buttons.

Surge Base và Surge Proposed phải là hai giá trị dễ nhận biết nhất.

Ví dụ:

**HEX H01 — INCREASE**

Surge Base: 1.20×  
Surge Proposed: 1.35×  
Adjustment: +0.15

Explanation: Dự báo áp lực cầu tăng tại khu vực.

Available Actions:

- Accept.
- Edit Manually.
- Keep Base.

### E. Recommendation Queue

Bảng danh sách recommendations theo snapshot.

Columns:

| Column | Description |
|---|---|
| Select | Chọn recommendation |
| Hex ID | Identifier |
| Action | INCREASE / DECREASE / HOLD / REVIEW |
| Surge Base | Surge gốc |
| Surge Proposed | Surge đề xuất |
| Delta | Mức thay đổi |
| Status | Eligibility/Decision Status |
| Actions | Accept / Edit / Keep Base / Details |

Queue hỗ trợ:

- Search by Hex ID.
- Filter by Action.
- Filter by Status.
- Sort.
- Multi-select.
- Select All Eligible.
- Accept Selected.
- Accept All.

Các thao tác chỉ ảnh hưởng đến snapshot đang xem.

### F. History Charts

Recommendation Detail Panel hỗ trợ các biểu đồ:

**Chart 1 — Surge Base History**

Biểu diễn hệ số bidding gốc theo thời gian.

**Chart 2 — D/S History**

Biểu diễn D/S quan sát và/hoặc dự báo, với nhãn thời gian và loại dữ liệu rõ ràng.

**Chart 3 — Demand History**

Biểu diễn Demand theo thời gian.

**Chart 4 — Supply History**

Biểu diễn Effective Supply theo thời gian.

Các biểu đồ sử dụng cùng hex được chọn.

Không được thay lịch sử Surge Base bằng các giá trị recommendation hoặc manual override.

### G. Replay Timeline

Replay được bố trí ở khu vực phía dưới Dashboard.

Chức năng:

- Chọn snapshot.
- Previous Snapshot.
- Next Snapshot.
- Play.
- Pause.
- Điều chỉnh Replay Speed.
- Chuyển đến timestamp cụ thể.

Khi thời điểm replay thay đổi:

- Map cập nhật.
- Recommendation Queue cập nhật.
- Recommendation Detail cập nhật.
- Các chart cập nhật theo context thời gian.

Snapshot nguồn không bị thay đổi bởi thao tác replay.

---

# 7. USER ACTIONS

## 7.1. Accept Recommendation

**Action:** Accept

**Scope:** Một hex.

**Preconditions:**

- Proposal hợp lệ.
- Không bị chặn.
- Chưa có quyết định cuối cùng mâu thuẫn.
- Người dùng có quyền thực hiện.
- Snapshot/proposal version hợp lệ.

**Workflow:**

1. User chọn một hex.
2. User xem recommendation.
3. User nhấn Accept.
4. Backend kiểm tra lại proposal.
5. Backend ghi nhận quyết định.
6. Frontend hiển thị kết quả.
7. Audit được cập nhật.

Trong MVP, Accept chỉ ghi nhận quyết định mô phỏng.

## 7.2. Accept Selected

**Action:** Accept Selected

**Scope:** Nhiều hex được chọn trong cùng snapshot.

**Workflow:**

1. User chọn nhiều recommendation.
2. Frontend hiển thị số lượng đã chọn.
3. User nhấn Accept Selected.
4. Frontend hiển thị Batch Confirmation.
5. User xác nhận.
6. Backend xử lý từng proposal.
7. Frontend hiển thị Batch Result Summary.

Batch sử dụng cơ chế partial success.

Nếu một proposal thất bại, các proposal hợp lệ khác vẫn có thể được xử lý.

## 7.3. Accept All

**Action:** Accept All

**Scope:** Toàn bộ proposal đủ điều kiện áp dụng trong snapshot hiện tại.

Mặc định đề xuất cho MVP: Accept All xử lý các proposal INCREASE và DECREASE hợp lệ, chưa có quyết định cuối cùng.

HOLD không tạo thay đổi giá, REVIEW bị chặn.

**Workflow:**

1. User nhấn Accept All.
2. Frontend mở Confirmation Dialog.
3. Dialog hiển thị số proposal sẽ xử lý và số proposal bị bỏ qua.
4. User xác nhận.
5. Backend kiểm tra lại từng proposal.
6. Backend trả kết quả chi tiết theo item.
7. Frontend hiển thị success/failure summary.

Accept All không được tự động áp dụng cho snapshot khác.

Nếu không có proposal đủ điều kiện thì nút phải disabled hoặc giải thích rõ lý do không thể thực hiện.

## 7.4. Edit Manually

**Action:** Edit Manually

**Scope:** Một hex.

Cho phép Pricing/Ops tự nhập hệ số surge mong muốn.

**Workflow:**

1. User mở Recommendation Detail.
2. User chọn Edit Manually.
3. Frontend hiển thị:
   - Surge Base.
   - Surge Proposed.
   - Manual Surge Input.
   - Resulting Delta.
   - Reason Input.
4. User nhập mức surge.
5. Frontend kiểm tra định dạng và giới hạn cơ bản.
6. User xác nhận.
7. Backend kiểm tra giới hạn surge theo cấu hình.
8. Backend ghi nhận manual override hoặc trả lỗi.
9. Frontend hiển thị kết quả.
10. Audit được cập nhật.

**Rules:**

- Không sửa proposal gốc.
- Manual override được lưu dưới dạng user decision riêng.
- Backend là nguồn xác định giá trị hợp lệ cuối cùng.
- Manual Edit cần lý do để audit (quy tắc đề xuất).
- REVIEW không được manual override trong MVP.
- HOLD có thể manual override nếu proposal vẫn đủ điều kiện (quy tắc đề xuất, cần xác nhận).

## 7.5. Keep Base

**Action:** Keep Base

**Scope:** Một hex.

User quyết định không áp dụng mức surge mà model đề xuất.

**Workflow:**

1. User chọn một proposal.
2. User chọn Keep Base.
3. Backend ghi nhận quyết định giữ Surge Base.
4. Proposal được đánh dấu đã xử lý trong phiên decision tương ứng.
5. Audit ghi nhận hành động.

Keep Base không thay đổi dữ liệu Surge Base nguồn.

## 7.6. REVIEW Behavior

REVIEW biểu thị proposal không thể áp dụng qua workflow phê duyệt thông thường.

Trong MVP:

- Accept bị disabled.
- Edit Manually bị disabled.
- Không nằm trong Accept All.
- Có thể mở chi tiết.
- Có thể xem lý do và các bằng chứng liên quan.

Không được hiển thị REVIEW như một recommendation đã được chấp nhận.

---

# 8. BATCH APPROVAL

## 8.1. Batch Scope

Một batch chỉ chứa proposal thuộc cùng một snapshot.

Không cho phép trộn proposal từ nhiều snapshot khác nhau.

## 8.2. Batch Processing

Backend xử lý từng item độc lập.

Kết quả có thể bao gồm:

- SUCCESS.
- FAILED.
- BLOCKED.
- EXPIRED.
- ALREADY_DECIDED.
- VERSION_CONFLICT.

Tên trạng thái chính thức sẽ được cố định khi hoàn thành API Schema.

## 8.3. Partial Success

Ví dụ: user gửi 10 proposals.

- 8 proposals hợp lệ.
- 1 proposal vượt surge limit.
- 1 proposal không còn hiệu lực.

Backend phải trả về kết quả tương ứng:

- 8 SUCCESS.
- 1 BLOCKED.
- 1 EXPIRED.

Hai item thất bại không làm rollback tám item đã xử lý thành công.

## 8.4. Batch Result UI

Frontend hiển thị:

- Total.
- Success.
- Failed.
- Skipped/Blocked.
- Result per Hex.

User có thể mở chi tiết để biết lý do thất bại.

Không được hiển thị toàn batch thành công khi vẫn có item thất bại.

## 8.5. Batch Idempotency

Mỗi batch request phải có idempotency key.

Gửi lại request giống hệt với cùng key không được tạo thêm quyết định.

Nếu nội dung request thay đổi trong khi dùng lại key, backend phải trả lỗi xung đột.

---

# 9. RECOMMENDATION & DECISION STATES

Recommendation action và trạng thái xử lý phải được lưu riêng.

## 9.1. Recommendation Action

- INCREASE.
- DECREASE.
- HOLD.
- REVIEW.

Đây là kết quả của Recommendation Provider.

## 9.2. Eligibility State

- ELIGIBLE.
- BLOCKED.
- EXPIRED.
- SUPERSEDED.

Đây là kết quả đánh giá điều kiện xử lý ở Backend.

## 9.3. Decision Action

- ACCEPT_PROPOSAL.
- KEEP_BASE.
- OVERRIDE_PROPOSAL.

Đây là hành động người dùng yêu cầu.

## 9.4. Decision Status

Đề xuất trạng thái MVP:

- PENDING.
- RECORDED.
- REJECTED.
- FAILED.

Một quyết định RECORDED trong DEMO không được hiểu là surge production đã được thay đổi.

## 9.5. State Rules

- Một proposal/version không được có hai quyết định cuối cùng mâu thuẫn.
- Proposal bị EXPIRED hoặc SUPERSEDED không thể tiếp tục Accept.
- Proposal bị BLOCKED không được xử lý.
- User actions không được thay đổi recommendation output gốc.
- Mỗi lần xử lý phải có audit record.
- Backend phải trả trạng thái thực tế; Frontend không được tự giả định thành công ngay khi click.

---

# 10. BACKEND SPECIFICATION

## 10.1. Backend Modules

### A. Snapshot Service

Trách nhiệm:

- Quản lý snapshot metadata.
- Load synthetic data.
- Truy xuất snapshot.
- Cung cấp dữ liệu cho Replay.

### B. Recommendation Service

Trách nhiệm:

- Nhận output từ provider.
- Validate schema.
- Validate action/surge consistency.
- Lưu hoặc truy xuất recommendation.
- Trả kết quả cho Frontend.

### C. Provider Adapter

Trách nhiệm:

- Cung cấp interface thống nhất.
- Chuẩn hóa output từ các provider.
- Ghi provider version.
- Cô lập logic nội bộ từng provider.

Việc tích hợp model mới không được yêu cầu thay đổi Frontend contract.

### D. Decision Service

Trách nhiệm:

- Xử lý Accept.
- Xử lý Keep Base.
- Xử lý Manual Edit.
- Kiểm tra eligibility.
- Kiểm tra surge limits.
- Ngăn quyết định trùng lặp.
- Ghi kết quả xử lý.

### E. Batch Service

Trách nhiệm:

- Validate batch.
- Kiểm tra snapshot consistency.
- Xử lý từng item.
- Partial success.
- Idempotency.
- Tổng hợp batch results.

### F. History & Audit Service

Trách nhiệm:

- Ghi decision history.
- Ghi thao tác user.
- Ghi trạng thái xử lý.
- Lưu source proposal/version.
- Truy xuất audit log.

### G. Replay Service

Trách nhiệm:

- Truy xuất snapshots theo thời gian.
- Trả về dữ liệu lịch sử.
- Đồng bộ dữ liệu market và recommendation.
- Bảo đảm dữ liệu nguồn không bị sửa.

## 10.2. Proposed API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | /api/v1/snapshots | List snapshots |
| GET | /api/v1/snapshots/{id} | Get snapshot |
| GET | /api/v1/snapshots/{id}/recommendations | List recommendations |
| GET | /api/v1/recommendations/{id} | Recommendation details |
| GET | /api/v1/hexes/{id}/history | Market/surge chart data |
| POST | /api/v1/decisions | Process a single decision |
| POST | /api/v1/decisions/batch | Process batch decisions |
| GET | /api/v1/decisions | Decision history |
| GET | /api/v1/audit | Audit history |
| GET | /api/v1/providers | Provider metadata |

Đây là API design đề xuất, chưa phải endpoint đã được triển khai.

## 10.3. Batch Decision Contract

Ví dụ request:

```json
{
  "snapshot_id": "snapshot_001",
  "idempotency_key": "batch-001",
  "items": [
    {
      "proposal_id": "rec_001",
      "proposal_version": "1",
      "action": "ACCEPT_PROPOSAL"
    },
    {
      "proposal_id": "rec_002",
      "proposal_version": "1",
      "action": "OVERRIDE_PROPOSAL",
      "requested_surge": 1.30,
      "reason": "Manual adjustment"
    },
    {
      "proposal_id": "rec_003",
      "proposal_version": "1",
      "action": "KEEP_BASE"
    }
  ]
}
```

Backend phải trả trạng thái cho từng item.

Ví dụ response rút gọn:

```json
{
  "batch_id": "batch_001",
  "status": "PARTIAL_SUCCESS",
  "total": 3,
  "succeeded": 2,
  "failed": 1,
  "results": [
    {
      "proposal_id": "rec_001",
      "status": "SUCCESS"
    },
    {
      "proposal_id": "rec_002",
      "status": "SUCCESS"
    },
    {
      "proposal_id": "rec_003",
      "status": "FAILED",
      "reason_code": "PROPOSAL_EXPIRED"
    }
  ]
}
```

Ví dụ thể hiện hợp đồng giao tiếp, không phải kết quả xử lý thực tế.

---

# 11. DATA & PERSISTENCE

## 11.1. Core Entities

Các entity logic cần có:

### Snapshot

- Snapshot ID.
- Region.
- Timestamp.
- Data Source.
- Dataset Version.
- Metadata.

### Market State

- Snapshot ID.
- Hex ID.
- Demand.
- Effective Supply.
- D/S.
- Surge Base.
- Supporting Network Data.

### Recommendation

- Proposal ID.
- Snapshot ID.
- Hex ID.
- Action.
- Surge Base.
- Surge Delta.
- Surge Proposed.
- Explanation.
- Evidence.
- Provider Version.
- Policy Version.

### Decision

- Decision ID.
- Proposal ID.
- Snapshot ID.
- Actor.
- Decision Action.
- Requested Surge.
- Decision Status.
- Timestamp.
- Reason.

### Batch

- Batch ID.
- Snapshot ID.
- Idempotency Key.
- Actor.
- Batch Status.
- Created At.
- Result Summary.

### Audit Event

- Audit Event ID.
- Actor.
- Action.
- Proposal ID.
- Decision ID.
- Timestamp.
- Original Values.
- Requested Values.
- Result.
- Reason/Error.

Các entity này là logical data model, không bắt buộc tương ứng 1:1 với các bảng database vật lý.

## 11.2. Data Integrity

- Synthetic snapshots phải có định danh ổn định.
- Recommendation phải tham chiếu đúng snapshot và hex.
- Snapshot gốc phải được bảo toàn.
- User decisions không được ghi đè recommendation output.
- Manual Override phải được lưu riêng.
- Audit records không được bị sửa để che lịch sử.
- Dữ liệu null/invalid không được tự thay bằng 0.

## 11.3. Replay Integrity

Replay phải sử dụng snapshot data gốc.

Nếu một user thực hiện decision khi đang xem snapshot lịch sử:

- Decision timestamp là thời điểm người dùng thực hiện thao tác.
- Source snapshot timestamp vẫn giữ nguyên.
- Decision được gắn với snapshot lịch sử.
- Không cập nhật lại marketplace state của snapshot.

Đây là hành vi mô phỏng được đề xuất cho MVP.

---

# 12. BUSINESS & VALIDATION RULES

| ID | Rule |
|---|---|
| BR-01 | Một recommendation gắn với một hex và một snapshot cụ thể. |
| BR-02 | Mọi provider dùng chung output contract. |
| BR-03 | Backend kiểm tra surge limits trước khi ghi nhận quyết định. |
| BR-04 | Backend từ chối output model không hợp lệ. |
| BR-05 | INCREASE phải có surge tăng so với base. |
| BR-06 | DECREASE phải có surge giảm so với base. |
| BR-07 | HOLD giữ nguyên Surge Base. |
| BR-08 | REVIEW không được Accept hoặc Manual Edit trong MVP. |
| BR-09 | Accept All chỉ xử lý eligible actionable proposals. |
| BR-10 | Batch chỉ chứa proposal thuộc cùng snapshot. |
| BR-11 | Batch hỗ trợ partial success. |
| BR-12 | Manual Edit không sửa proposal gốc. |
| BR-13 | Mỗi decision phải có actor và timestamp. |
| BR-14 | Backend phải ngăn xử lý trùng hoặc xung đột quyết định. |
| BR-15 | Replay không thay đổi dữ liệu nguồn. |
| BR-16 | DEMO không có tác động tới pricing production. |
| BR-17 | Frontend không tự tính lại recommendation. |
| BR-18 | Mọi hành động lỗi phải trả về lý do rõ ràng. |

Các surge limits được cung cấp từ cấu hình backend.

Không hard-code min/max hoặc maximum delta trong Frontend.

---

# 13. ACCEPTANCE CRITERIA

## 13.1. Dashboard

**AC-01:** Dashboard hiển thị được snapshot thông qua API.

**AC-02:** Map hiển thị đúng recommendation action của từng hex.

**AC-03:** Summary counts khớp với số lượng recommendations trong snapshot.

**AC-04:** Click hex trên Map cập nhật Recommendation Detail.

**AC-05:** Click một recommendation trong Queue cập nhật Map selection.

**AC-06:** Frontend hiển thị đúng Surge Base, Surge Delta và Surge Proposed.

## 13.2. Recommendation Details

**AC-07:** Hiển thị đầy đủ bốn loại action.

**AC-08:** Hiển thị explanation summary.

**AC-09:** Người dùng có thể mở evidence và biểu đồ.

**AC-10:** REVIEW không xuất hiện như proposal có thể phê duyệt.

## 13.3. Approval

**AC-11:** Accept một hex tạo được decision record hợp lệ.

**AC-12:** Accept một hex không làm thay đổi quyết định của hex khác.

**AC-13:** Accept Selected xử lý đúng danh sách được chọn.

**AC-14:** Accept All chỉ gửi các proposal đủ điều kiện trong snapshot hiện tại.

**AC-15:** Accept All có confirmation trước khi gửi.

**AC-16:** HOLD không tạo thay đổi surge.

**AC-17:** REVIEW bị chặn.

## 13.4. Manual Edit

**AC-18:** Người dùng có thể mở Manual Edit cho proposal hợp lệ.

**AC-19:** Manual Edit hiển thị Surge Base và Surge Proposed hiện tại.

**AC-20:** Có thể nhập mức surge mới.

**AC-21:** Backend từ chối mức surge ngoài giới hạn cấu hình.

**AC-22:** Manual Edit không ghi đè recommendation output gốc.

**AC-23:** Manual Edit thành công tạo decision và audit record.

## 13.5. Batch

**AC-24:** Không thể gửi batch chứa proposal từ nhiều snapshot.

**AC-25:** Batch có thể trả partial success.

**AC-26:** Frontend hiển thị kết quả từng hex.

**AC-27:** Một item thất bại không rollback các item thành công.

**AC-28:** Gửi lại cùng idempotency key không tạo quyết định trùng.

## 13.6. Replay

**AC-29:** User có thể di chuyển giữa các snapshot.

**AC-30:** Map, Queue và Detail được cập nhật theo snapshot.

**AC-31:** Surge Base History được lấy từ dữ liệu bidding gốc.

**AC-32:** Replay không thay đổi dữ liệu nguồn.

## 13.7. Audit

**AC-33:** Mọi decision đều có actor và timestamp.

**AC-34:** Audit lưu proposal và version được tham chiếu.

**AC-35:** Manual Edit ghi nhận giá trị được yêu cầu và kết quả validation.

**AC-36:** Decision History vẫn tồn tại sau khi reload ứng dụng.

## 13.8. Provider Independence

**AC-37:** Frontend không cần thay đổi khi sử dụng provider mới tuân thủ contract.

**AC-38:** Mock Provider có thể thay thế bằng Rule-based hoặc GNN Provider thông qua adapter.

**AC-39:** Nếu provider trả dữ liệu không hợp lệ, hệ thống hiển thị lỗi hoặc trạng thái bị chặn thay vì hiển thị kết quả sai.

---

# 14. NON-FUNCTIONAL REQUIREMENTS

## 14.1. Reliability

- Frontend phải xử lý Loading, Empty, Error và Stale states.
- Backend phải trả lỗi có cấu trúc.
- Không được báo thành công trước khi backend xác nhận.
- Batch failure không được làm mất các item thành công.

## 14.2. Consistency

- Snapshot, recommendation và decision phải có version.
- Không trộn dữ liệu từ nhiều snapshot trong một batch.
- UI phải hiển thị đúng dữ liệu do API cung cấp.
- Các thao tác phải có khả năng chống xử lý lặp.

## 14.3. Usability

- Desktop-first.
- Bản đồ và Recommendation Queue là thành phần chính.
- Surge Base → Surge Proposed phải rõ ràng.
- Actions phải dễ nhận biết.
- Confirmation phải thể hiện rõ phạm vi thay đổi.
- Có thể sử dụng bàn phím cho các thao tác thiết yếu.

## 14.4. Performance

Performance targets cụ thể sẽ được xác định sau khi khóa số lượng hex, kích thước snapshot và môi trường chạy MVP.

Hệ thống cần tránh tải lại toàn bộ dữ liệu lịch sử khi chỉ thay đổi selected hex hoặc mở một tab chi tiết.

## 14.5. Security & Audit

- Backend kiểm tra quyền trước khi ghi nhận decision.
- Actor identity phải được xác định bởi backend.
- Không tin tưởng trạng thái eligibility do client tự gửi.
- Không đưa dữ liệu nhạy cảm không cần thiết vào audit.
- Không có production pricing side effects trong DEMO.

---

# 15. DEVELOPMENT ROADMAP

## Phase 1 — Product Foundation

Deliverables:

- Product Specification.
- User Workflow.
- Recommendation Output Contract.
- Decision Actions.
- Acceptance Criteria.

## Phase 2 — Backend Foundation

Deliverables:

- Snapshot Service.
- Recommendation Service.
- Provider Adapter.
- Decision Service.
- Batch Service.
- Audit Service.
- API Contracts.

Backend có thể bắt đầu bằng Mock Provider để phục vụ phát triển mà không cần GNN hoàn thiện.

## Phase 3 — Frontend Development

Deliverables:

- Surge Recommendation Dashboard.
- H3 Map.
- Recommendation Queue.
- Detail Panel.
- Surge History Charts.
- Accept/Keep Base/Manual Edit.
- Batch Approval UI.
- Replay Timeline.
- History & Audit Views.

## Phase 4 — Integration & Testing

Deliverables:

- Frontend–Backend Integration.
- Provider Contract Tests.
- Business Rule Tests.
- Batch Partial Success Tests.
- Replay Integrity Tests.
- End-to-end Tests.

## Phase 5 — Model Integration

Tích hợp model ML/GNN thực tế thông qua Recommendation Provider Interface.

Model có thể thay đổi kiến trúc, training pipeline hoặc thuật toán bên trong mà không làm thay đổi sản phẩm nếu output contract vẫn được giữ nguyên.

---

# 16. ASSUMPTIONS & OPEN DECISIONS

## 16.1. Confirmed Decisions

- MVP chạy trên synthetic data.
- Model cung cấp recommendation cuối cùng.
- Output gồm action, mức surge và giải thích.
- Frontend hiển thị INCREASE, DECREASE, HOLD, REVIEW.
- Backend kiểm tra giới hạn surge.
- Pricing/Ops có thể Accept All.
- Pricing/Ops có thể Accept từng hex.
- Pricing/Ops có thể Accept Selected.
- Pricing/Ops có thể Manual Edit từng hex.
- Pricing/Ops có thể Keep Base.
- Batch chỉ xử lý một snapshot.
- Batch hỗ trợ partial success.
- HOLD giữ Surge Base.
- REVIEW bị chặn.
- Audit và lịch sử được lưu.
- Replay không sửa dữ liệu nguồn.
- MVP có Dashboard, API, Batch, Replay và Testing.

## 16.2. Proposed Defaults

Các hành vi sau được đề xuất để triển khai MVP nhưng chưa được xác nhận cuối cùng:

1. Accept All chỉ áp dụng cho INCREASE/DECREASE hợp lệ, không xử lý HOLD và REVIEW.
2. HOLD có thể được chỉnh thủ công nếu đủ điều kiện.
3. REVIEW không cho phép Manual Edit.
4. Manual Edit yêu cầu lý do.
5. Confirm trước khi Accept All hoặc Accept Selected.
6. Replay cho phép ghi nhận quyết định mô phỏng đối với snapshot lịch sử nhưng không sửa dữ liệu nguồn.
7. Mỗi hex chỉ có một recommendation hiện hành từ provider đang chọn trong cùng snapshot.

## 16.3. Remaining Technical Decisions

Các nội dung cần chốt trong Technical Design:

- Backend technology stack.
- Database technology và physical schema.
- API response/error schema.
- Surge min/max, delta limit và precision từ cấu hình.
- Proposal expiration policy.
- Provider versioning.
- Authentication và RBAC cho Demo.
- Cơ chế lưu trữ và thời hạn giữ audit.
- Performance targets.
- Deployment architecture.

Những nội dung này không làm thay đổi ý tưởng sản phẩm cốt lõi.

---

# 17. DEFINITION OF DONE

MVP được coi là hoàn thành khi:

1. Có thể load synthetic snapshots qua Backend API.
2. Hiển thị recommendation theo từng hex trên Map và Queue.
3. Hiển thị Surge Base, Surge Proposed và explanation.
4. Người dùng có thể Accept từng hex.
5. Người dùng có thể Accept Selected.
6. Người dùng có thể Accept All.
7. Người dùng có thể Manual Edit surge.
8. Người dùng có thể Keep Base.
9. Backend kiểm tra dữ liệu và surge constraints.
10. Batch hỗ trợ partial success.
11. Có Decision History và Audit Log.
12. Có Replay Timeline.
13. Replay không làm thay đổi dữ liệu nguồn.
14. Frontend và Backend không phụ thuộc vào kiến trúc GNN cụ thể.
15. Các acceptance tests bắt buộc đều đạt.
16. Không có tác động đến hệ thống surge production.

---

# 18. FINAL PRODUCT STATEMENT

**Graph Surge Recommendation System** là một hệ thống hỗ trợ quyết định điều chỉnh surge pricing theo khu vực.

Hệ thống sử dụng recommendation do các provider độc lập tạo ra, bao gồm Rule-based, Machine Learning hoặc Graph Neural Networks.

Mỗi recommendation mô tả hành động INCREASE, DECREASE, HOLD hoặc REVIEW, đi kèm hệ số surge được đề xuất và các thông tin giải thích liên quan.

Frontend giúp Pricing/Ops trực quan hóa recommendations, tìm hiểu bằng chứng và thực hiện các hành động Accept All, Accept Selected, Accept từng hex, Manual Edit hoặc Keep Base.

Backend chịu trách nhiệm kiểm tra tính hợp lệ, quản lý decisions, xử lý batch, lưu lịch sử và audit.

MVP sử dụng dữ liệu synthetic và môi trường Demo/Replay, không thực hiện thay đổi surge trong production.

**Nguyên tắc thiết kế cốt lõi: Model tạo recommendation; hệ thống quản lý recommendation; người vận hành quyết định hành động.**

---

**End of Product Specification v0.3**
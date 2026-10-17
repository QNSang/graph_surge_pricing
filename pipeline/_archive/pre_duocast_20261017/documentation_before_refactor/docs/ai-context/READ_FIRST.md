# READ FIRST — Coding agent entrypoint

Cập nhật: 2026-10-18. Đây là hướng dẫn thao tác, không phải lệnh bắt đầu implementation.

## Quy trình một phiên làm việc

1. Đọc `AGENTS.md` tại root; giữ các quy tắc GitNexus và giới hạn quyền hiện có.
2. Xác nhận workspace `graph_surge_pricing`, đọc Git status và [CURRENT_STATE](CURRENT_STATE.md). Không ghi đè thay đổi có sẵn.
3. Chọn task trong [TASKS](../implementation/TASKS.md), đọc dependencies và phạm vi file. Backlog không tự cấp quyền sửa code.
4. Đọc [ARCHITECTURE](ARCHITECTURE.md), contract/spec của module và [CODEBASE_MAP](CODEBASE_MAP.md).
5. Đối chiếu [KNOWN_ISSUES](KNOWN_ISSUES.md) và [DECISION_LOG](../implementation/DECISION_LOG.md). Chưa chốt semantics thì chỉ làm phần độc lập/fixtures, không tự quyết business assumption.
6. Khi được yêu cầu code: chạy impact analysis trước khi sửa symbol theo AGENTS, viết test theo requirement ID, kiểm diff rồi cập nhật evidence.

## Routing

Các đường dẫn trong bảng tính từ `docs/`.

| Task | Đọc trước |
|---|---|
| Forecast/model/target | `model/forecasting_contract.md`, `contracts/MODEL_IO_CONTRACT.md`, `contracts/DATA_SCHEMA.md`, handoff gốc và config active |
| Response fitting | `model/response_model.md`, `contracts/RESPONSE_ARTIFACT_CONTRACT.md`, data contract, GD-02/03/04 |
| Candidate outcomes | `model/candidate_simulation.md`, `contracts/CANDIDATE_POLICY_CONTRACT.md`, GD-03/04/05 |
| MILP | `model/milp_optimization.md`, candidate/policy contract, `evaluation/OPTIMIZATION_EVALUATION.md` |
| Backend integration | `backend/decision_pipeline.md`, contracts và `backend/README.md` tại root; kiểm consumer thật |
| UI integration | `frontend/ggso_monitoring_dashboard.md` + policy contract; frontend specs cũ chỉ là legacy/demo provenance |
| Docs maintenance | Source register, link liên quan và task evidence; chỉ sửa Markdown trong docs-only |

## Không được làm ngầm

DuoCast đã chốt ở mức thiết kế là GRU temporal, spatial GATv2, directed mobility GATv2, gated fusion và hai head demand/effective-supply; không có Geo Encoder hay static geographic feature input. Đây khác với implementation mặc định GeoMobiNet/`geomobinet_smg`, vốn vẫn có nhánh geo, nên cần adaptation và kiểm data/code/checkpoint trước khi map `pred_demand` sang confirmed booking requests và `pred_idle_supply` sang GGSO v1 effective available supply (eligible idle stock). Supply khác capacity K. Không đổi passenger OD thành physical driver movement. Không chạy GNN cho từng candidate, nhét GMV vào forecast loss, thêm partial pooling hoặc relocation simulator vào GGSO v1.

Không phát minh default cho fare, Q, capacity, BR/surge bounds, support thresholds hoặc solver acceptance. Fixture phải ghi synthetic/test-only.

Target flow áp dụng tự động exact full-network policy đã qua independent validation mỗi 5 phút; INVALID hoặc execution precondition failure ⇒ no write. Không thêm Accept Selected, manual override hoặc operator approval vào GGSO target dashboard. Đồng thời không suy rằng docs này đã bật live pricing: current DEMO/REPLAY runtime và production authorization vẫn là ranh giới implementation riêng.

Không đánh dấu PASS từ tài liệu mô tả. Phân biệt đã đọc code, đã chạy lệnh, bị chặn quyền, chưa kiểm chứng và artifact thực tế.

## Kết thúc phiên

Ghi task đã làm, file đã sửa, kiểm chứng thực tế, blockers và task tiếp theo. Không commit/push/deploy nếu chưa được yêu cầu. Nếu skill `gsd-docs-update` không có, dùng workflow đọc nguồn → sửa có giới hạn → read-back/diff; không giả vờ đã chạy skill.

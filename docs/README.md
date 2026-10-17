# GGSO — Bộ tài liệu dự án

Cập nhật: 2026-10-18.

Bộ tài liệu này mô tả kiến trúc DuoCast, mô hình phản ứng thị trường, mô phỏng candidate, tối ưu toàn mạng và quy trình áp dụng chính sách GGSO. Bắt đầu tại [READ_FIRST](ai-context/READ_FIRST.md).

## Thứ tự đọc

`AGENTS.md` → `ai-context/READ_FIRST.md` → `ai-context/CURRENT_STATE.md` → contract hoặc specification liên quan đến task.

## Bản đồ tài liệu

| Nhóm | Tài liệu | Vai trò |
|---|---|---|
| Context | [READ_FIRST](ai-context/READ_FIRST.md), [CURRENT_STATE](ai-context/CURRENT_STATE.md), [ARCHITECTURE](ai-context/ARCHITECTURE.md), [CODEBASE_MAP](ai-context/CODEBASE_MAP.md), [KNOWN_ISSUES](ai-context/KNOWN_ISSUES.md) | Điểm bắt đầu, trạng thái thực thi và ranh giới hệ thống |
| Forecasting | [DuoCast model](model/duocast_model.md), [Forecasting contract](model/forecasting_contract.md) | Kiến trúc, target, input/output và failure handling |
| Response | [Response models](model/response_model.md) | Negative Binomial, Binomial, fitting và validation |
| Candidate | [Candidate simulation](model/candidate_simulation.md) | Action grid, demand, fulfillment, capacity và utility |
| Optimization | [MILP](model/milp_optimization.md) | Joint objective, hard constraints và independent validation |
| Orchestration | [Decision pipeline](backend/decision_pipeline.md) | Chu kỳ quyết định toàn mạng và automatic execution |
| Contracts | [Data](contracts/DATA_SCHEMA.md), [Model I/O](contracts/MODEL_IO_CONTRACT.md), [Response artifact](contracts/RESPONSE_ARTIFACT_CONTRACT.md), [Candidate/policy](contracts/CANDIDATE_POLICY_CONTRACT.md) | Semantics, fields, units và versions |
| Evaluation | [Model](evaluation/MODEL_EVALUATION.md), [Optimization](evaluation/OPTIMIZATION_EVALUATION.md), [Test strategy](evaluation/TEST_STRATEGY.md) | Metrics, protocol và evidence requirements |
| Frontend | [Monitoring dashboard](frontend/ggso_monitoring_dashboard.md) | Dashboard theo dõi, không có pricing action thủ công |
| Report | [Source register](technical_report/README.md), [Design reference](technical_report/GGSO_DESIGN_REFERENCE.md) | Nguồn và phần thiết kế GGSO được trích từ report |

## Trạng thái hiện tại

Pipeline mặc định sử dụng DuoCast: Temporal GRU, Spatial GATv2, directed Mobility GATv2, gated fusion và hai prediction heads cho demand và effective available supply. Mỗi cutoff năm phút tạo một forecast toàn mạng; response layer đánh giá candidates; MILP chọn một full-network policy; independent validator kiểm tra trước khi hệ thống tự động áp dụng policy hợp lệ. Nếu validation thất bại, giá hiện hành được giữ nguyên.

Demand là confirmed valid booking requests trong năm phút tiếp theo. Supply là online, idle, dispatch-eligible driver stock tại thời điểm mục tiêu và khác capacity `K`.

Dashboard chỉ dùng để monitoring. Không có Accept Selected, manual override hoặc operator approval trong target flow.

## Ranh giới bằng chứng

Synthetic tests xác nhận contract và execution behavior. Chúng không chứng minh accuracy trên official data, calibration thực tế, causal uplift hoặc production readiness. Realized GMV impact chỉ được xác nhận qua prospective switchback experiment.

# READ FIRST — Coding agent entrypoint

## Quy trình bắt đầu

1. Đọc `AGENTS.md` và kiểm tra Git status trước khi sửa.
2. Đọc [CURRENT_STATE](CURRENT_STATE.md), [ARCHITECTURE](ARCHITECTURE.md) và [CODEBASE_MAP](CODEBASE_MAP.md).
3. Chọn đúng contract hoặc specification của task.
4. Đối chiếu [KNOWN_ISSUES](KNOWN_ISSUES.md) và [DECISION_LOG](../implementation/DECISION_LOG.md).
5. Với code changes, chạy GitNexus impact analysis trước khi sửa symbol và detect changes trước khi commit.

## Routing

| Task | Đọc trước |
|---|---|
| Forecast/model/target | `model/duocast_model.md`, `model/forecasting_contract.md`, `contracts/MODEL_IO_CONTRACT.md`, `contracts/DATA_SCHEMA.md` |
| Response fitting | `model/response_model.md`, `contracts/RESPONSE_ARTIFACT_CONTRACT.md` |
| Candidate outcomes | `model/candidate_simulation.md`, `contracts/CANDIDATE_POLICY_CONTRACT.md` |
| MILP | `model/milp_optimization.md`, `evaluation/OPTIMIZATION_EVALUATION.md` |
| Backend integration | `backend/decision_pipeline.md`, contracts và `backend/README.md` |
| Dashboard | `frontend/ggso_monitoring_dashboard.md` và policy contract |
| Documentation | Source register, implementation evidence và file liên quan trực tiếp |

## Quy tắc hệ thống

DuoCast gồm Temporal GRU, Spatial GATv2, directed Mobility GATv2, gated fusion và hai prediction heads. Demand là confirmed valid booking requests; supply là eligible idle driver stock và khác capacity `K`. Không đổi passenger-request OD thành observed driver movement.

Model chạy đúng một lần cho full network ở mỗi cutoff. Candidate simulation, response estimation, capacity, GMV và optimization là downstream responsibilities.

Exact full-network policy chỉ được áp dụng tự động sau independent validation. Technical invalid hoặc execution precondition failure không tạo write mới và giá hiện hành được giữ nguyên. Dashboard chỉ monitoring.

Không tự đặt default cho fare, `Q`, capacity, pricing bounds, booking-rate bounds, support threshold hoặc solver tolerance. Fixtures phải được đánh dấu synthetic hoặc test-only.

Không suy production readiness hoặc causal uplift từ unit tests, synthetic data hay modeled GMV.

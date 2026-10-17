# Known Issues

Cập nhật: 2026-10-18. `OPEN` nghĩa là chưa có đủ quyết định hoặc evidence để đóng.

| ID | Vấn đề | Xử lý |
|---|---|---|
| KI-01 | Official demand event taxonomy và label lineage chưa được xác minh | Kiểm source, label generation và checkpoint lineage trước promotion |
| KI-02 | Supply semantics cần khớp online, idle, dispatch-eligible stock | Kiểm driver-state mapping; không đồng nhất supply stock với capacity `K` |
| KI-03 | Response estimator, dispersion convention và support thresholds chưa được phê duyệt cho production | Version artifact và đặt promotion gate riêng |
| KI-04 | Operational `Q`, fare, capacity và pricing bounds chưa có production contract hoàn chỉnh | Không phát minh defaults; dùng fixtures có nhãn test-only |
| KI-05 | Real-data forecast accuracy và calibration chưa có evidence | Chạy protocol trong `evaluation/MODEL_EVALUATION.md` trên frozen splits |
| KI-06 | Actual DB/API execution receipt và atomic full-policy publication chưa được xác minh end-to-end | Giữ production disabled đến khi integration gate hoàn tất |
| KI-07 | Dashboard target là monitoring-only nhưng UI hiện hữu có thể còn controls lịch sử | Migration UI phải xóa action controls và giữ loading/error/empty states |
| KI-08 | Modeled GMV không phải realized causal uplift | Dùng prospective switchback experiment cho business validation |
| KI-09 | Sum của cell-level uncertainty không tự tạo network-level uncertainty hợp lệ | Dùng paired network bootstrap hoặc định nghĩa aggregation được phê duyệt |
| KI-10 | Một số test/library warnings vẫn tồn tại | Theo dõi riêng; hiện không làm test suite thất bại |

Nguồn: [CURRENT_STATE](CURRENT_STATE.md), [Decision log](../implementation/DECISION_LOG.md) và các evaluation contracts.

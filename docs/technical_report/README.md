# Nguồn thiết kế GGSO

Cập nhật: 2026-10-18. Không có `docs/model/technical_report.md` trong working tree.

## Source register

| ID | Nguồn đã đọc | Phạm vi |
|---|---|---|
| T1 | [`GGSO_Technical_Report_EN.tex`](../../GGSO_Technical_Report_EN.tex) | Báo cáo hiện hành: DuoCast, response, MILP, tự động áp dụng policy hợp lệ mỗi 5 phút, monitoring dashboard và đánh giá switchback |
| S1 | `GGSO_Complete_Algorithm_Specification.md` trong hội thoại | Thuật toán, DuoCast, response, candidate, MILP, fallback, evaluation |
| S2 | `GGSO_Technical_Report_VI.md` trong hội thoại | Báo cáo tiếng Việt, phương pháp, giới hạn và khung đánh giá chưa có số liệu |
| R1 | [DuoCast handoff](../model/duocast_model.md) | Temporal, spatial, directed-mobility architecture và target semantics |
| R2 | [Pipeline README](../../pipeline/README.md), `pipeline/configs/duocast.yaml`, `pipeline/src/surge_ml/cli.py` | Active configuration và CLI dispatch |
| R3 | [Backend README](../../backend/README.md), [frontend spec](../frontend/frontend_spec.md) | DEMO/legacy contracts, cần migration riêng |

SHA-256 file hội thoại đã kiểm tra trong môi trường biên soạn:

- S1: `255204ebcb75bc913fd8f983e6fe20f99838116f1caa35d509489884c3b75c91`.
- S2: `94cfd7827cd5e14dba839ea875ea0c35cff57d38c6599ae1c9e9121193e36404`.

Đây là provenance nguồn, không phải hash file trong checkout này. Hai file đầy đủ **chưa được mirror** vào thư mục này. [GGSO_DESIGN_REFERENCE](GGSO_DESIGN_REFERENCE.md) là bản rút trích để agent dùng trong repo, không phải toàn bộ technical report. Module specs dẫn S1/S2 theo section nguồn; phần chưa xác định nằm trong decision log.

## Cách hiểu bằng chứng

T1 là nguồn hiện hành cho target design; S1/S2 được giữ làm provenance lịch sử, còn R1/R2 mô tả implementation hiện có. DuoCast gồm GRU temporal, spatial GATv2, directed mobility GATv2, gated fusion và hai prediction heads. Demand target là confirmed valid booking requests; Supply là eligible idle driver stock và khác capacity `K`. History length `T` được cấu hình theo checkpoint. Source, label, preprocessing và checkpoint parity phải được kiểm chứng trước khi promotion.

Theo T1, mỗi chu kỳ 5 phút tạo một full-network policy. Policy chỉ được áp dụng tự động sau independent validation; nếu validation thất bại thì không có write và current effective prices giữ nguyên. Dashboard là monitoring interface, không có Accept Selected, manual override hoặc bước phê duyệt của operator trong GGSO target flow. Điều này là target design, không phải bằng chứng live pricing đã được bật trong implementation hiện tại.

`Source-derived` là yêu cầu từ nguồn được chỉ rõ. `Integration proposal` là nội dung bộ docs bổ sung: tên envelope/field, module boundaries, error codes, task/test IDs. Những phần đó chưa phải executable contract đã có hoặc được production phê duyệt.

Không bổ sung literature, benchmark, số thực nghiệm hoặc default bên ngoài trong lần này. Không sao chép PASS lịch sử thành kết quả mới. Không thêm Implementation Readiness Checklist vào report; acceptance nằm ở task/test specs.

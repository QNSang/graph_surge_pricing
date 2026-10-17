# Decision Log — GGSO

Cập nhật: 2026-10-18. Bảng dưới đây chỉ chứa các quyết định đang có hiệu lực.

| ID | Quyết định | Evidence hoặc gate còn thiếu |
|---|---|---|
| GD-01 | DuoCast gồm Temporal GRU, Spatial GATv2, directed Mobility GATv2, gated fusion và hai prediction heads | Official source, training lineage và checkpoint eligibility |
| GD-02 | Demand là confirmed valid booking requests trong target five-minute interval | Event taxonomy, label generation và source ownership |
| GD-03 | Supply là online, idle, dispatch-eligible driver stock tại target time; khác capacity `K` | Driver-state mapping và approved capacity method |
| GD-04 | Response dùng per-cell Negative Binomial demand và Binomial fulfillment models; artifact phải chứa toàn bộ fitted parameters, support và validation | Estimator settings, support thresholds và production promotion criteria |
| GD-05 | MILP dùng hard nominal modeled network GMV no-loss constraint; conservative incremental utility thuộc objective | Approved tolerances, bounds và operational parameters |
| GD-06 | Technical failure là fail closed: không recommendation, không optimized policy và không execution write | Production error transport và alerting |
| GD-07 | Mỗi năm phút, exact full-network policy qua independent validation được áp dụng tự động; dashboard chỉ monitoring | Atomic production execution, idempotency và receipt persistence |
| GD-08 | Synthetic tests chứng minh software behavior, không chứng minh official accuracy, causal uplift hoặc production readiness | Official evaluation và prospective switchback experiment |
| GD-09 | Report định nghĩa fusion bằng phép chiếu chung $W_c[m^{(sp)}\Vert m^{(od)}]$ và một gate; code hiện tại dùng gate riêng cho từng branch rồi cộng các message đã gate | Chốt một công thức canonical và đạt equation-to-code/checkpoint parity trước khi phê duyệt official checkpoint |

## Invariants

- Một complete network snapshot cho mỗi cutoff.
- Một batched DuoCast inference cho toàn mạng.
- Candidate simulation không gọi lại forecast model.
- Missing data khác observed zero hoặc observed empty graph.
- Required-cell coverage phải đầy đủ.
- Independent validator không tin trực tiếp solver matrices.
- INVALID giữ nguyên current effective prices vì không có write mới.
- Estimated GMV không được trình bày như realized causal uplift.

## Open numerical settings

Các giá trị fare, `Q`, capacity parameters, surge bounds, booking-rate bounds, support thresholds, bootstrap settings, solver tolerance và promotion thresholds phải đến từ versioned configuration hoặc approved policy. Không suy default từ report hoặc test fixtures.

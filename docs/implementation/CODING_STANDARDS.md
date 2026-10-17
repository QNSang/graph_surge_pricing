# Coding Standards — Khi implementation được yêu cầu

Đây là quy tắc cho task code sau, không cấp quyền thay code trong phiên docs-only. Giữ hướng dẫn [AGENTS](../../AGENTS.md) và quy ước package hiện có.

## 1. Scope và source of truth

Đọc Git status/instructions trước sửa; không restore/reset/stash/xóa file người khác. Impact analysis trước thay symbol theo AGENTS. Không update dependencies, lockfiles, datasets hoặc run training khi chưa nằm trong task được giao.

Report/design reference xác định ý định thuật toán; source/config xác định implementation hiện tại. Mâu thuẫn ghi decision log, không chọn ngầm. Contracts trong Markdown là draft cho tới khi G01 tạo executable schema; sau đó schema/tests là authority cho serialization, docs phải đồng bộ cùng version.

## 2. Module boundaries

Forecast, response fitting/loading, candidate arithmetic, MILP, independent validation và execution adapter tách riêng. Candidate/validation functions ưu tiên pure, deterministic với inputs/config explicit. Không DB/network side effect trong forecast head, utility calculation hoặc validator.

Tận dụng cấu trúc `pipeline/`/`backend/` hiện có. Backend import boundary không thay chỉ vì thuận tiện gọi model. Không duplicate pricing equations giữa frontend và backend.

## 3. Types, numerics và units

Dùng type annotations và validated input/output models theo thư viện đã chọn trong repo; Pydantic có thể là lựa chọn triển khai nhưng docs này không tự thêm dependency. Validate semantic IDs/order/units, không chỉ primitive types.

Canonical decimal/approved precision cho prices/action grid; numeric floating-point cho model/solver theo approved tolerances. Không `round`, `clip`, `nan_to_num` để che invalid policy. Display rounding không thay canonical values.

D/S dự báo là real-valued expectations; D/C training Binomial là integer cohort counts. ETA giây và phút đổi tại boundary có nhãn. K rides/horizon khác driver stock. Dùng stable logit/sigmoid algebra tương đương nguồn; không thêm epsilon khác nhau tùy module.

## 4. Configuration và reproducibility

Không hardcode business bounds, thresholds, fare/Q hoặc solver budgets từ fixture. Config có version/provenance; unset critical field fail rõ. Chỉ fit scalers/context preprocess trên train; checkpoint đóng băng feature/node ordering.

Lưu seed nếu có, versions, hashes/identities, time splits, model/profile và scenario method. Replay dùng đúng inputs/artifact lúc quyết định, không dùng forecast mới rồi gắn vào run cũ.

## 5. Errors, logs và testing

Typed errors/structured reasons, không catch-all rồi tạo HOLD hợp lệ. Critical failure hoặc missing/stale reference ⇒ INVALID và no write; không tạo fallback policy. Retry/execution idempotency nằm ở execution adapter, không nằm trong arithmetic modules.

Logs giữ run/version/cutoff/constraint evidence, không credential hoặc raw rider/driver identities. Không đánh đồng solver success với price effective.

Tests gồm unit/negative/contract/integration và small enumeration solver oracle; giữ synthetic fixtures riêng. Báo NOT RUN nếu lệnh chưa chạy. Không ghi số benchmark, test counts hoặc uplift không có artifact.

## 6. Thay đổi tài liệu

Cập nhật task + CURRENT_STATE khi có evidence mới. Giữ report lịch sử ổn định; algorithm/config changes có decision record và compatibility plan. Không dùng Markdown checklist đã tích sẵn làm bằng chứng production readiness.

# Current State — GGSO implementation / TEST_ONLY

**Target design clarification — 2026-10-18:** current technical report specifies automatic application of the exact independently validated full-network policy every five minutes. INVALID means no write and current effective prices remain unchanged. The GGSO dashboard is monitoring-only, with no Accept Selected, manual override or operator approval. This target decision supersedes the earlier GD-07 operator flow in active specifications, but it does not change the implementation evidence below or authorize live pricing.

## Latest execution update — 2026-10-16

Theo yêu cầu implement mới của user, đã tạo `pipeline/src/surge_ml/ggso/`: typed contracts, per-cell NB/Binomial fitting, bootstrap, candidate simulation, HiGHS MILP, independent validator, mock forecast adapter, fail-closed runner, CLI demo/replay và simulated receipt/reference protocol. Có thêm `backend/app/providers/ggso_provider.py` làm explicit DEMO JSON bridge; không tự đăng ký vào default provider/importer và không đổi frontend.

**Kiểm thử thực tế:** 129 pipeline/GGSO/GeoMobiNet/controller/contract cases PASS (3 library warnings); 49 backend unit cases PASS. Cả hai lệnh cuối exit 0. Fitted-synthetic CLI demo exit 0, VALID với 2 recommendations, publication NOT_REQUESTED, production_effective=false.

**Bằng chứng và lệnh chạy:** [GGSO_IMPLEMENTATION_STATUS](../implementation/GGSO_IMPLEMENTATION_STATUS.md). Final artifacts: `pipeline/runs/ggso-implementation-final-20261016/`. JUnit: `pipeline/runs/ggso-final-pipeline-tests.xml`, `backend/ggso-final-unit-tests.xml`.

**Ranh giới implementation:** P1–P6 engine/mock/JSON/targeted-regression scope có evidence; actual DB/API receipt E2E và G08.3 UI activation NOT RUN. P7–P9 official sources, checkpoint parity, real calibration, official replay/shadow vẫn pending. Chưa có live automatic price write, deploy hoặc thay source/checkpoint GeoMobiNet. Legacy/default CLI/provider giữ nguyên. INVALID không xuất recommendations/policy; pending RECORDED không trở thành effective reference. Các model estimates/test fixtures không chứng nhận uplift thực tế.

Phần dưới là **historical docs-only snapshot trước phiên implement**. Những câu "chưa code/chưa chạy test" bên dưới chỉ mô tả phiên soạn docs cũ, không thay thế execution evidence ở trên.

## Historical documentation handoff

Ngày rà soát: 2026-10-16. Workspace `graph_surge_pricing`, nhánh `main`. Đây là kết quả đọc repository và cập nhật docs, không phải chứng nhận runtime.

## Bằng chứng đã quan sát

| Thành phần | Bằng chứng | Trạng thái |
|---|---|---|
| CLI mặc định | `pipeline/src/surge_ml/cli.py`: không có `legacy` thì gọi `surge_ml.geomobinet.cli` | Đã đọc source; chưa chạy |
| Forecast config | `pipeline/configs/geomobinet.yaml`: `geomobinet_smg_ds_h5_v1`, history 12, horizon 1 | Đã đọc, không sửa |
| Forecast package | `pipeline/src/surge_ml/geomobinet/` có data, model, training, runner, metrics, baselines, CLI | Đã xem inventory; chưa audit đầy đủ |
| Handoff model | `docs/model/duocast_model.md` có tiêu đề GeoMobiNet, request-flow/idle-stock targets | Giữ nội dung gốc, không rename model |
| Response doc trước cập nhật | `docs/model/response_model.md` rỗng | Bổ sung specification GGSO, không phải fit results |
| Backend | README mô tả DEMO/REPLAY, legacy precomputed import và không production gateway | Bằng chứng README, chưa kiểm runtime |
| Frontend | Spec và lịch sử Network Console | Giữ nguyên; số test lịch sử không là test mới |
| GGSO response/candidate/MILP/decision | Specs, contracts và tasks mới | Chưa xác nhận code hoặc artifacts |
| `docs/technical_report/` ban đầu | Thư mục trống | Thêm source register/design reference, không giả bản report đầy đủ |

## Architecture decision update — 2026-10-17

**DuoCast** trong GGSO đã chốt là GRU temporal, spatial GATv2, directed mobility GATv2, gated fusion và hai head dự báo demand/effective supply. DuoCast không có Geo Encoder hay static geographic feature input. Đây là khác biệt có chủ ý với **GeoMobiNet-SMG** hiện có: model/default CLI/config vẫn dùng `geomobinet_smg`, có `geo_encoder` và `geo_features`. Do đó source/data/checkpoint parity cùng adaptation sang DuoCast dual-graph vẫn pending; không được coi việc đổi tên là xác nhận parity.

| Target | Canonical design semantics | Outstanding verification |
|---|---|---|
| `demand_5m` | Valid confirmed booking requests trong một 5-minute interval | Event taxonomy, label generation, training/inference |
| `idle_supply_t` | Online, idle, dispatch-eligible drivers tại timestamp | Driver state mapping và checkpoint |
| `forecast_demand` | Expected valid confirmed booking requests trong next 5min | Versioned adapter, Q semantics |
| `forecast_supply` | Expected eligible-idle driver stock tại t+5 | GGSO v1 effective available supply (no extra weights) |

Forecast supply drivers khác **effective capacity K (rides/horizon)**. Không coi việc đổi tên field là validation. Old prototype handoff và README mô tả các giai đoạn khác nhau, nên cần source parity review thực tế.

## Working tree được bảo toàn

Lúc bắt đầu đã có thay đổi AGENTS/CLAUDE, backend providers/import/tests, pipeline CLI/propose/dependencies; GeoMobiNet và experiments có file untracked. Nhiều docs cũ cùng schema/config trong docs archive đã ở trạng thái deleted. Không restore, stage, commit hoặc xóa thêm các thay đổi đó.

## Kiểm chứng phiên docs

Đã đọc instructions, Git status, docs, active config/CLI và lấy verification baseline trước edit. Không chạy training, pytest, UI build, DB migration hoặc publication.

Lệnh terminal inventory/hash bị `approval_required`, **chưa chạy**. Baseline có cảnh báo CRLF và pseudo-repository lỗi tại `backend/.uv-cache/sdists-v9`/`pipeline/.uv-cache/sdists-v9`; không sửa cache trong docs-only. Skill `gsd-docs-update` không được tìm thấy trong catalog phiên này; dùng đọc nguồn, file edits, read-back/diff.

Trạng thái kiểm chứng cuối: [DOCS_CHANGELOG](../implementation/DOCS_CHANGELOG.md).

## Điểm bắt đầu tiếp theo

Khi được phép code, làm G00 để chốt semantic/interface mappings, rồi G01 cho contracts/fixtures. Không train lại hoặc thay forecast chỉ vì docs mới được tạo; backlog không phải yêu cầu triển khai ngay.
## Tiến độ theo semantic agreement 2026-10-16

Chốt ở mức thiết kế GD-01/02/03; G00 phải kiểm source data/training/checkpoints, G02 xây versioned adapter sau parity, capacity K/Q vẫn cần operational contracts. Failure at any critical GGSO stage ⇒ INVALID, no recommendations, no optimized policy, no publication; không sinh fallback policy. Chưa code hay train trong lần cập nhật tài liệu.

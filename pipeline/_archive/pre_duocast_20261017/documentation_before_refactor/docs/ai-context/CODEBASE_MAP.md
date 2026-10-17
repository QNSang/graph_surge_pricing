# Codebase Map

File inventory/CLI/config/README được đọc ngày 2026-10-16. Đường dẫn tính từ repository root. Không tạo source files trong lần docs-only này.

## Hiện có

| Đường dẫn | Vai trò/bằng chứng |
|---|---|
| `pipeline/src/surge_ml/cli.py` | Dispatch mặc định GeoMobiNet; `legacy` vào parser cũ. Đã đọc |
| `pipeline/configs/geomobinet.yaml` | Active D/S configuration. Đã đọc |
| `pipeline/src/surge_ml/geomobinet/config.py` | Config module có trong inventory |
| `pipeline/src/surge_ml/geomobinet/data.py`, `batch.py` | Data/batch modules có trong inventory |
| `pipeline/src/surge_ml/geomobinet/model.py` | Model file hiện có; cần symbol review trước sửa |
| `pipeline/src/surge_ml/geomobinet/training.py`, `runner.py` | Training/workflow modules hiện có |
| `pipeline/src/surge_ml/geomobinet/metrics.py`, `baselines.py` | Evaluation/baseline modules hiện có |
| `pipeline/src/surge_ml/geomobinet/demo.py`, `cli.py` | Demo/CLI modules hiện có |
| `pipeline/tests/test_geomobinet.py`, `test_geomobinet_workflow.py` | File được Git status/README ghi nhận; chưa chạy trong phiên này |
| `pipeline/src/surge_ml/orchestration/propose.py` | Legacy proposal path, có thay đổi từ trước |
| `backend/app/providers/gnn_adapter.py`, `precomputed_provider.py` | Paths từ Git status/README; chưa xác nhận GGSO integration |
| `backend/README.md` | Mô tả DEMO/precomputed workflow |
| `ui/app/` | React console theo frontend docs |
| `docs/model/duocast_model.md` | GeoMobiNet handoff lịch sử; tên file không chứng minh đây là DuoCast M4 |

## Module dự kiến

Ưu tiên tái sử dụng forecast package hiện có sau semantic review; không tạo `src/` song song ở root chỉ để khớp sơ đồ docs.

Các module contracts, responses, candidates, optimization, decision có thể nằm trong namespace GGSO riêng dưới `pipeline/src/surge_ml/`. **Tên file/thư mục cuối chưa được chốt hoặc tạo.** G00/G01 chốt dependency direction/public interface trước khi code.

Backend giữ import boundary hiện có. Không tự thêm torch/surge_ml vào backend vì sơ đồ có mũi tên forecast → API. Automatic full-policy execution cần versioned contract, independent full-network validation, reference-version/idempotency checks và execution receipt; dashboard chỉ monitoring.

## Đường dẫn cũ thiếu

`docs/model/model.md`, `docs/model/technical_report.md`, `docs/data/metadata.md`, `docs/backend/spec_backend.md` và nhiều file `docs/ml_pipeline/` không tồn tại lúc kiểm tra; nhiều file đã ở Git deleted. Không tự restore. `train.yaml` và ratio contracts cũ không phải active GeoMobiNet profile. Các links lịch sử trong frontend docs được giữ và ghi nhận tại [KNOWN_ISSUES](KNOWN_ISSUES.md).

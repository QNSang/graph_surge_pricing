# ML pipeline spec (V1.2, rút gọn)

Spec này mô tả package `surge_ml` (thư mục `pipeline/`) dùng để train và đánh giá forecast D/S 5 phút trên graph H3 của mock V2.

**Nguồn sự thật:** [`docs/model/technical_report.md`](../model/technical_report.md). Khi spec và report mâu thuẫn, report thắng; sửa spec cho khớp. Spec cũ (W12/log1p/context29) đã được lưu ở [`_archive/v1_2_legacy/`](_archive/v1_2_legacy/) và không còn hiệu lực.

## Tài liệu

| File | Nội dung |
|---|---|
| [01_data_target_split.md](01_data_target_split.md) | Input parquet, feature routing local37/neighbor3, target log-ratio, split và sample index, scaler |
| [02_model_loss_metrics.md](02_model_loss_metrics.md) | Dual-head GRU + GATv2 residual, loss, metrics, checkpoint selection |
| [03_experiments_cli.md](03_experiments_cli.md) | Variants/ablations, seeds, selection, test một lần, MLflow, CLI, config |

## Luồng

```text
data/hcm_data_2 (read-only)
  └─ surge-ml prepare   → data/derived/d_<hash>/   (arrays, sample index, scalers)
       └─ surge-ml train / benchmark → pipeline/runs/<study>/<variant>/seed_<s>/  + MLflow run
            ├─ surge-ml sweep    → runs/<study>/_sweep/<variant>/sweep.md   (tune 1 variant, chỉ dùng val)
            ├─ surge-ml report   → eval_report.md   (Baseline / Local / Network, chỉ dùng val)
            └─ surge-ml select   → selection.json  (chỉ dùng val)
                 └─ surge-ml finalize → test_report.json (test chạy đúng một lần)
```

## Bản đồ code (`pipeline/src/surge_ml/`)

| Phần | File | Vai trò |
|---|---|---|
| Config | `config.py`, `configs/train.yaml` | Pydantic, từ chối key lạ; `overrides` theo variant; `config_sha256(cfg, variant)` |
| Hợp đồng | `features.py` | Cột, split, `Variant` (family, group local/network, kind gnn/handcrafted), `VARIANTS` |
| Dữ liệu | `data/` | Derive, target log-ratio, scaler, batch cửa sổ W=4 |
| Model | `models/` | `dual_gru_gatv2.py` (GRU/GNN), `baselines.py`, **`registry.py` (adapter theo family)** |
| Train | `training/` | `Trainer` (epoch loop, best.pt, resume), loss, checkpoint |
| Điều phối | `orchestration/` | `runner.py` (prepare, run_trial, benchmark), `sweep.py`, `propose.py` |
| Đánh giá | `evaluation/` | metrics, `report.py`, `selection.py`, `finalize.py` |

Code cũ không ai import (registry, artifact bundle, state, gates, hashing) nằm ở `pipeline/_archive/legacy_src/`, không thuộc package.

## Thêm một model mới

1. Viết adapter trong `models/registry.py` (hoặc file riêng rồi đăng ký): `fit(...) -> Fitted` và `predict(..., split) -> (preds, ks)`. Thêm vào `ADAPTERS` với một tên family mới.
2. Thêm dòng `Variant(name, columns, "b", family=...)` vào `VARIANTS` trong `features.py`. Group (local/network) tự suy ra từ cột và `graph`.
3. Nếu model có tham số riêng: thêm một section config (như `ModelConfig`), thêm vào `OVERRIDABLE` và `HASHED` trong `config.py`.
4. Thêm tên variant vào `variants` trong `train.yaml` **và** `benchmark_plan.json` (test contract bắt hai file khớp).

`runner.run_trial` và `finalize` không cần sửa.

## Tune model

- **Sửa chung**: section `model`, `loss`, `train` (GRU/GNN) trong `train.yaml`.
- **Sửa riêng một variant**: `overrides: {gru_gatv2_40: {model: {gru_hidden: 96}}}`. Sai tên key bị từ chối khi load.
- **Thử nhiều giá trị**: `surge-ml sweep --variant gru_gatv2_40 --grid model.gru_hidden=32,64,96 --grid train.lr=1e-3,5e-4 [--seeds 42 43]`. Kết quả xếp hạng theo val MAE_q và một khối `overrides:` sẵn để dán. Sweep không đụng trial của study.
- **Khi nào trial cũ thành STALE**: hash của mỗi trial chỉ gồm các section mà family của nó dùng (GRU: data/model/loss/train; baseline: data). Override `gru_gatv2_40` chỉ làm `gru_gatv2_40` stale. Đổi `data` hoặc section chung thì cần `study_id` mới.
- Sau khi tune: `benchmark` (đủ seed) → `report` → `select` → `finalize`. Điểm sweep chọn trên val nên lạc quan; luôn xác nhận bằng benchmark nhiều seed.

## Quyết định phạm vi

- Chỉ forecast **H=5 phút**. Labels H10/H15 của nguồn không được dùng (report §8.1).
- Package có post-processing Pressure/Revision để sinh proposal surge ở chế độ **DEMO/SHADOW**. Controller tách khỏi training, không backprop, chưa calibration và không có quyền thực thi giá production.
- Baseline: persistence (report §5.3) và seasonal-naive (cùng giờ hôm qua). Model so sánh: `gru_gatv2_40`.
- Nguồn `data/hcm_data_2` chỉ đọc. Mọi dẫn xuất ghi vào `data/derived/`.
- Guardrail vận hành ở mức tối thiểu: không lock, không state machine, không model registry (`models/registry.py` chỉ là bảng adapter theo family). Cache derive dựa trên spec + stat file nguồn. Resume chỉ kiểm `config_sha256`.

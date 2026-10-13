# 03 — Experiments, tracking, CLI

Tham chiếu report: §5.3, §7.3, §13.3–13.5, §15.1 (M3–M4).

## 1. Variants

| Variant | Local cols | Bypass | Graph | Edge relations | Mục đích |
|---|---|---|---|---|---|
| `persistence` | — | `b` | — | — | `ŷ = b`, không train |
| `seasonal_naive` | — | `b` | — | — | `ŷ[k] = y[k−288]` (cùng giờ hôm qua), thiếu thì `b` |
| `gru_gatv2_40` | LOCAL37 (+NEIGHBOR3 qua φ) | `b` | có | adjacency + OD | Model chính dual-head GRU + GATv2 |

Mỗi variant có `family` (`persistence`, `seasonal`, `gru`) để chọn adapter trong `models/registry.py`, và `group` để so sánh: baseline / local (chỉ thông tin của hex) / network (thêm thông tin hex khác: `handcrafted` hoặc `gnn`). `surge-ml report` dựng bảng theo group.

So sánh cần đọc: `gru_gatv2_40` vs persistence/seasonal_naive. `R` lớn không có nghĩa graph chính xác hơn; dùng `paired_gain_q`.

## 2. Protocol

1. `prepare`: dựng derived cache, in ngày và số candidate mỗi split (90 ngày: 18121/3721/4009).
2. `train --variant V --seed s`: một trial. `benchmark` chạy mọi variant trong config × mọi seed.
3. `select`:
   - chỉ đọc `trial_result.json` (metrics val tại best epoch);
   - xếp hạng variant theo trung bình `val/<primary>/mae_q` qua seeds;
   - ghi `runs/<study>/selection.json`.
4. `finalize`:
   - load `best.pt` của mọi trial đã có, evaluate test **một lần**, ghi `runs/<study>/test_report.json` (mean/std theo variant, cờ variant được chọn);
   - nếu file đã tồn tại thì báo lỗi.
   - Không tune gì sau bước này.

Cùng seed, cutoff, mask cho mọi variant. Mỗi trial lưu số tham số model.

## 3. MLflow

- Tracking URI: env `MLFLOW_TRACKING_URI`, mặc định `http://127.0.0.1:5000`.
- Experiment:
  - mỗi lần gọi `train`/`benchmark` tạo experiment mới `<tracking.experiment>_<YYYYmmdd-HHMMSS>`;
  - prefix mặc định là `graph_surge_pricing`.
- Một trial là một MLflow run, tên `<variant>-s<seed>`. `run_id` lưu ở `<trial_dir>/mlflow_run_id.txt`.
  - `--resume` ghi tiếp vào run đó, trong experiment cũ của nó.
  - Train lại không có `--resume`: trial cũ chuyển vào `runs/<study>/_archive/<variant>_seed_<s>_<time>/`, rồi train mới. Study đã finalize thì báo lỗi.
- Hình ảnh:
  - `data_figures/`: tổng quan data, tạo một lần cho mỗi derived dir (`<derived>/figures`). Gồm chuỗi thời gian D/S, profile theo giờ, phân phối target theo split, heatmap hex × giờ, persistence scatter, tương quan feature, số edge theo quan hệ.
  - `figures/`: `learning_curve.png`, `val_predictions.png` (dự đoán so với thực tế, residual theo head) của best checkpoint.
- Params: config đã làm phẳng, `variant`, `seed`, `config_sha256`, `derived_dir`, `n_params`.
- Metrics theo `step = epoch`:
  - `train/loss`, `train/loss_local`, `train/loss_graph`;
  - `val/<head>/<metric>`, `val/paired_gain_q`.
- Artifacts: `best.pt`, `history.json`, `trial_result.json`.
- `persistence` log một run chỉ có metrics val.
- `--no-tracking` (hoặc `tracking.enabled: false`) tắt hoàn toàn MLflow.

## 4. CLI

```text
surge-ml prepare   [--config PATH]
surge-ml train     [--config PATH] [--variant V] [--seed S] [--epochs E] [--smoke] [--resume] [--no-tracking]
surge-ml surge     [--config PATH] [--variant gru_gatv2_40] [--seed S] --cutoff K [--output PATH]
surge-ml benchmark [--config PATH] [--smoke] [--no-tracking]
surge-ml sweep     [--config PATH] --variant V --grid SECTION.FIELD=V1,V2 [--grid ...] [--seeds S ...] [--smoke] [--no-tracking]
surge-ml report    [--config PATH] [--smoke]
surge-ml select    [--config PATH] [--smoke]
surge-ml finalize  [--config PATH] [--smoke]
```

- `--config` mặc định `pipeline/configs/train.yaml`.
- `--smoke`:
  - chạy 2 epoch, giới hạn số batch train/val/test (`smoke_batches`) để kiểm tra end-to-end nhanh;
  - ghi vào study `<study_id>-smoke`, tách khỏi study thật.
  - Với `select`/`finalize`, `--smoke` chỉ chọn study smoke.
- `--resume --epochs E`: chạy tiếp `last.pt` tới E epoch. Kết quả chỉ trùng với chạy liền khi `scheduler` không phụ thuộc tổng số epoch (`none`, `plateau`). Với `cosine`, `T_max` giữ giá trị lúc bắt đầu.
- `sweep`: tích Descartes các `--grid` (section thuộc `model`, `loss`, `train`), mỗi điểm merge vào `overrides[V]`, train vào `runs/<study>/_sweep/V/p_<hash>/seed_<s>/`, ghi `sweep.{json,md}` xếp hạng theo val. Mặc định 1 seed (seed đầu trong config).
- `report`: bảng A/B/C Baseline/Local/Network trên val, ghi `runs/<study>/eval_report.{json,md}`.
- Lỗi in `code: message` và exit 1. Ctrl+C exit 130.

## 5. Config (`pipeline/configs/train.yaml`)

Pydantic `extra="forbid"` để bắt key gõ sai. Hằng số của contract (split, W, index cột) nằm trong code (`surge_ml/features.py`), không đưa vào YAML.

```yaml
study_id: hcm-v12-w4-002
seeds: [42, 43, 44]
variants: [persistence, seasonal_naive, gru_gatv2_40]
data: {current | source_root, derived_root, dataset_id, split_days, std_floor}  # current = data/CURRENT.json; dataset_id phải khớp; split_days null = theo manifest
model: {gru_hidden, neighbor_hidden, gat_layers, gat_heads, head_hidden, dropout}
loss: {smooth_l1_beta, lambda_local}
train: {device, batch_size, eval_batch_size, epochs, lr, weight_decay, grad_clip_norm, patience, scheduler, tie_tolerance, smoke_batches}
overrides: {<variant>: {<model|loss|train>: {key: value}}}   # tune riêng từng variant
tracking: {enabled, experiment}
runs_root: pipeline/runs
```

`config_sha256(cfg, variant)` hash config đã merge override của variant, chỉ gồm các section family đó dùng (GRU: data/model/loss/train trừ epochs; baseline: data + eval). `benchmark`, `select` và `surge` từ chối trial có hash khác (`STALE_TRIAL`).

# 01 — Data, target, split

Tham chiếu report: §5, §5.1–5.3, §6.1–6.3, §13.1–13.2.

## 1. Input

| Bảng | Đường dẫn | Khóa | Nội dung |
|---|---|---|---|
| Node features | `features/hex_features/date=*/part.parquet` | `(ts, hex_id)` | 40 cột theo thứ tự `node_features` trong `meta/feature_contract.json` |
| Graph edges | `features/graph_edges/date=*/part.parquet` | `(ts, src_hex, dst_hex, relation)` | 10 cột theo `edge_features` |

- Dataset lấy từ `data/CURRENT.json` (hiện `hcm_mock_v2_90d_seed42_bounded_tail`): `manifest.days` partition ngày, 61 hex (`hex_ids` trong feature contract), `days × 288` snapshot 5 phút liên tục. Số mốc không hardcode.
- `prepare` kiểm tra:
  - `dataset_id`;
  - 61 hex unique;
  - 40/10 cột với `node_features[0] == demand_5m`, `[1] == idle_supply_t`, `[29] == effective_supply_t`;
  - grid `days × 288` mốc liên tục;
  - mỗi `(ts, hex)` có đúng một hàng;
  - giá trị node hữu hạn;
  - mỗi edge row có đúng một trong `edge_is_adjacent`, `edge_is_od` bằng 1.
- `oracle/`, `raw/`, `burn_in/` không được đọc.

Edge rows giữ nguyên quan hệ kiểu: cùng cặp `(src, dst)` có thể có một row adjacency và một row OD. Self-OD (`src == dst`) được giữ.

## 2. Feature routing

Index theo thứ tự 40 cột của contract:

| Nhóm | Index | Dùng ở |
|---|---|---|
| `NEIGHBOR3` | 35 `neighbor_demand_mean_t`, 36 `neighbor_idle_supply_mean_t`, 37 `neighbor_pressure_mean_t` | Chỉ nhánh graph (encoder φ) |
| `LOCAL37` | 0–34, 38, 39 | Shared local GRU |
| `INBOUND5` | 29 `effective_supply_t`, 30–32 `arriving_trip_count_eta_*`, 33 `completed_inflow_15m` | Bị bỏ trong `gru_strict32` |
| `STRICT32` | `LOCAL37` trừ `INBOUND5` | Feature view của ablation `gru_strict32` |
| `ALL40` | 0–39 | Pointwise40 |

**Ranh giới bắt buộc:** ba cột neighbor bị loại khỏi input của local GRU trước khi encode, không phải sau.

## 3. Target và bypass

Với `D = demand_5m` (cột 0), `S = effective_supply_t` (cột 29), `S_idle = idle_supply_t` (cột 1), cutoff `k`, horizon 1 bước (5 phút):

```text
q[k]   = (D[k] + 1) / (S[k] + 1)              smoothed D/S, luôn > 0
y[k]   = log q[k+1]                           target H5 cho cả hai head
b[k]   = log q[k]                             persistence bypass
b32[k] = log((D[k] + 1) / (S_idle[k] + 1))    bypass của gru_strict32, không đổi target
inverse: q_hat = exp(y_hat)                    không bao giờ dùng expm1
```

- Output log-ratio có thể âm. Không dùng Softplus.
- Mask `m[k, i] = isfinite(y) & isfinite(b)`. Với dữ liệu hiện tại mask luôn đúng, nhưng loss và metrics vẫn tôn trọng mask.

## 4. Split và sample index

Split theo ngày lịch (1-based, inclusive), chỉ số snapshot nửa mở `[(first-1)*288, last*288)`. Ngày lấy từ `data.split_days` trong `train.yaml`; nếu `null` thì dùng `suggested_split_days_inclusive` của `meta/manifest.json`. Bounds và số candidate được ghi vào derived `manifest.json`.

| Split | Ngày (90 ngày hiện tại) | `[a, z)` | Số candidate |
|---|---|---|---|
| train | 1–63 | `[0, 18144)` | 18121 |
| val | 64–76 | `[18144, 21888)` | 3721 |
| test | 77–90 | `[21888, 25920)` | 4009 |

Dataset 30 ngày cũ dùng 21/4/5 ngày: 6025 / 1129 / 1417 candidate.

```text
candidates(split) = range(a + 14, z - 6 - 3)
window(k)         = X[k-3 .. k]          W = 4 snapshot: t-15, t-10, t-5, t
```

- `a+14`: endpoint sớm nhất `k-3` có `demand_mean_60m` cần bin `k-14 ≥ a`. Rolling support không vượt biên split (report §5.2).
- `z-6-3`: 30 phút purge cộng 15 phút horizon lớn nhất được publish, giữ nguyên rule của export (report §13.2).
- Sample không bị loại vì state carry-over (chuyến/backlog mở từ trước biên). Đó là thông tin biết tại cutoff, không phải leakage.

## 5. Graph tại cutoff

- Graph của sample `k` dùng edge rows có `ts == ts[k]`. Không lấy union cả window.
- Hướng `src → dst` nghĩa là message từ `src` cập nhật `dst`.
- Thêm một self-loop tổng hợp cho mỗi node: attribute 10 cột bằng 0 sau chuẩn hóa, cờ `is_self = 1`. Edge quan sát có `is_self = 0`. Edge dim nội bộ = 11.
- Không thêm reverse edge.
- Batch: node `i` của sample `b` có index `i + b·N`. Không có edge giữa các sample.
- Ablation `no_od` giữ row adjacency; `no_adj` giữ row OD. Filter áp dụng đồng thời cho `edge_index` và `edge_attr`; self-loop tổng hợp luôn giữ.

## 6. Chuẩn hóa

- Z-score fit **chỉ trên train**:
  - node: mọi hàng `(ts, hex)` với `ts` thuộc split train, theo từng cột 40;
  - edge: mọi edge row có `ts` thuộc split train, theo từng cột 10.
- Thống kê tính bằng float64, population std. Std nhỏ hơn `std_floor` được thay bằng 1.
- Target `y`, bypass `b`/`b32` **không** chuẩn hóa.

## 7. Derived cache

`prepare` ghi `data/derived/d_<sha16>/`, trong đó `sha16` là hash của derivation spec cộng stat `(path, size, mtime_ns)` của mọi parquet đọc. Nếu thư mục đã có thì dùng lại. Build ghi vào thư mục tạm rồi `os.replace`.

| File | Shape / nội dung |
|---|---|
| `x.npy` | float32 `[T, 61, 40]` raw (T = days × 288) |
| `y.npy`, `b.npy`, `b32.npy` | float32 `[T, 61]` (`y` NaN ở mốc cuối) |
| `edge_src.npy`, `edge_dst.npy` | int64 `[E]`, sắp theo `k` |
| `edge_attr.npy` | float32 `[E, 10]` raw |
| `edge_ptr.npy` | int64 `[8641]` CSR theo `k` |
| `scalers.npz` | `node_mean/std [40]`, `edge_mean/std [10]`; fit chỉ trên snapshot `[train_start, train_end)` (`scaler_fit_bounds` trong manifest) |
| `manifest.json` | spec, `dataset_id`, counts per split, thống kê scaler |

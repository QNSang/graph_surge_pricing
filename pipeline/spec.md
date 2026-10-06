# Spec: Training pipeline V1

**Dự án:** Lớp điều chỉnh surge theo mạng (GRU + GATv2 trên H3 / OD graph)
**Phiên bản:** Draft v1
**Ngày:** 2026-10-06

---

## 1. Mục tiêu và phạm vi

**Mục tiêu:** train và so sánh các model dự đoán λ (điểm khan hiếm tài xế của từng hex) ở horizon 5/10/15 phút, rồi đọc kết quả ngay trên terminal.

**Trong phạm vi:**
- Đọc dữ liệu thật
- Chia train/val/test theo thời gian
- Train 5 model
- Đánh giá bằng PairAcc, Spearman, MAE

**Ngoài phạm vi (làm sau nếu cần):** hàm F và replay policy, nhiều seed, test tự động, biểu đồ tự vẽ, serving, tracking service.

---

## 2. Cấu trúc

```
pipeline/
├── config.yaml
├── data.py
├── features.py      # bạn viết
├── model.py
├── train.py
├── evaluate.py
├── data/            # dữ liệu thật, chỉ đọc, gitignore
└── runs/            # gitignore, tự đánh số 01, 02, ...
```

Cách chạy:

```bash
python train.py config.yaml
python evaluate.py runs/01
```

---

## 3. Dữ liệu

- Mỗi 5 phút một snapshot đồ thị: node là hex H3, cạnh là luồng OD.
- Một mẫu là cửa sổ 4 snapshot `{t-15, t-10, t-5, t}`.
- Nhãn: `y(i, t+h) = log((D + ε) / (S_eff + ε))` với h ∈ {5, 10, 15}.
- Persistence baseline: `b_i = log((D_t + ε) / (S_eff_t + ε))`.
- Chia theo thời gian: train tuần 1-6, val tuần 7, test tuần 8. **Cách ly (purge) 30 phút** giữa các tập (15 phút cửa sổ + 15 phút horizon).
- Thống kê chuẩn hóa chỉ fit trên train.
- Kiểm tra tối thiểu khi load (bằng `assert`, dừng ngay nếu sai):
  - không NaN
  - không hex lạ
  - cạnh không trỏ ra ngoài tập hex
  - đủ 4 snapshot trong cửa sổ

---

## 4. Config

```yaml
note: ""                  # tự ghi run này khác gì
seed: 0

data:
  path: data/
  train: [week1, week6]
  val: week7
  test: week8
  purge_min: 30
  window: 4
  horizons: [5, 10, 15]
  eps: 1.0e-3
  debug_days: null        # số ngày để chạy thử nhanh, null = chạy đủ

model:
  name: gru_gatv2         # logds | logds_eff | lgbm | gru_only | gru_gatv2
  gru_hidden: 64
  gat_layers: 2

loss:                     # tên khớp ký hiệu trong tài liệu thiết kế
  level: {weight: 1.0, huber_delta: 1.0, rho: 0.5}
  diff:  {weight: 0.0}    # γ
  rank:  {weight: 0.0, temperature: 1.0}   # η, T
  short: {weight: 0.0, tau_s: 0.5}         # δ

train:
  lr: 3.0e-4
  epochs: 50
  batch_size: 8
  patience: 10
  select_by: val_pairacc_10
```

Quy tắc:
- Mọi hằng số nằm ở đây, code không hard-code số nào.
- Key lạ hoặc sai kiểu thì dừng ngay khi load.
- Ablation = đặt trọng số loss bằng 0.

---

## 5. Các file

### `data.py`
- Đọc snapshot, chạy kiểm tra ở mục 3, chia train/val/test có purge.
- Dựng mẫu cửa sổ 4 snapshot thành batch.
- Nếu `debug_days` khác null thì chỉ lấy chừng đó ngày.

### `features.py` (bạn viết)
- `s_eff(...)`: **một hàm duy nhất**, cả feature lẫn nhãn đều gọi hàm này, để tránh hai định nghĩa lệch nhau.
- `build_features(window)` trả về: `node_x [4, N, F]`, `edge_index`, `edge_attr`, mask (hex thưa, thiếu snapshot).
- `target_y(...)` và `persistence_b(...)`.

### `model.py`
Mọi model có cùng đầu ra: `λ [N, H]`.

| Model | Mô tả |
|---|---|
| `logds`, `logds_eff` | Công thức, không train |
| `lgbm` | Dữ liệu phẳng (feature hiện tại + trend), dự đoán **phần dư** `y - b_i` |
| `gru_only` | GRU rồi các head theo horizon |
| `gru_gatv2` | GRU rồi GATv2 hai lớp trên OD graph (edge feature vào attention), rồi các head. `λ = b_i + g_h(z_i)`, nên model chỉ học phần thay đổi so với persistence |

Các loss: `level` (Huber có trọng số volume, phạt bất đối xứng ρ), `diff`, `rank`, `short`. Tổng loss là tổng có trọng số từ config; trọng số 0 nghĩa là tắt. Công thức chi tiết lấy từ Phụ lục A của tài liệu thiết kế.

### `train.py`
- Đọc config, tạo `runs/NN/`, copy config vào đó.
- Với `lgbm`: fit một lần. Với model Torch: vòng lặp epoch, chọn checkpoint theo **PairAcc val ở horizon 10**, dừng sớm theo `patience`.
- In một dòng mỗi epoch, cột cố định:

  ```
  ep | loss level diff rank short | val PA@5 PA@10 PA@15 | spearman | corr(b,y) | gnorm | sec
  ```

- Tự in cảnh báo khi:
  - loss hoặc gradient NaN
  - λ gần như hằng số
  - PairAcc val không cải thiện sau `patience` epoch
- Cuối cùng chạy trên test **một lần** với checkpoint tốt nhất, in bảng kết quả.
- In git hash và data path ở đầu log.

### `evaluate.py`
- **PairAcc:** tỉ lệ cặp OD mà `sign(λ_i − λ_j) = sign(y_i − y_j)`, chỉ tính cặp có volume cao, bỏ cặp gần hòa (ngưỡng `|Δ*| ≤ m` đặt trong config).
- **Spearman** giữa λ và y; **MAE**. Báo cáo cho từng horizon.
- Chỉ đọc `predictions.parquet`, không import `model.py`, nên mọi model được đánh giá bằng cùng một đoạn code.
- Nhận một hoặc nhiều thư mục run và in bảng so sánh.

---

## 6. Đầu ra mỗi run

```
runs/01/
├── config.yaml          # bản copy tham số đã dùng
├── train.log            # đúng nội dung terminal
├── history.csv          # mỗi epoch một dòng: các loss, PairAcc val, spearman, gnorm
├── predictions.parquet  # cột: ts, hex, horizon, lambda, y, b
└── checkpoint.pt        # model tốt nhất (với lgbm: file model)
```

---

## 7. Thứ tự làm

| # | Làm gì | Xong khi |
|---|---|---|
| 0 | Chốt 3 định nghĩa: demand là gì, `S_eff` làm nhãn dùng inbound tại `t` hay `t+h`, graph `E_t` là OD của `t` hay hợp 4 snapshot | Ghi vài dòng đầu `features.py` |
| 1 | `config.yaml`, `data.py`: load, validate, split | Chạy với `debug_days: 2` không lỗi, in số mẫu từng tập |
| 2 | `features.py`, `evaluate.py` | In được PairAcc của `logds` trên val |
| 3 | `model.py` baseline: `logds_eff`, `lgbm`, `gru_only` | Có bảng baseline |
| 4 | `gru_gatv2` chỉ với `level` loss | Overfit được một batch nhỏ, thắng `logds` trên val |
| 5 | Bật dần `diff`, `rank`, `short` bằng cách sửa weight | Bảng ablation |

Bước 3 đứng trước model chính vì không có số baseline thì không đọc được kết quả của GNN.

---

## 8. Tiêu chí hoàn thành

- `python train.py config.yaml` chạy hết từ đầu đến cuối trên dữ liệu thật, không lỗi.
- Đổi `model.name` là chạy được cả 5 model, cùng định dạng `predictions.parquet`.
- Đổi một tham số trong `config.yaml` là đủ để thử ý tưởng mới, không sửa code.
- PairAcc val ở epoch đầu không cao bất thường. Nếu cao thì nghi leakage trước khi mừng.
- Test chỉ nhìn một lần ở cuối mỗi run, không dùng để chọn tham số.
- Muốn nói "graph có giá trị" thì `gru_gatv2` phải thắng `gru_only` và `lgbm`. Nếu không thắng `lgbm` thì dừng và xem lại, không tune tiếp.

---

## 9. Cần chốt

1. Ba định nghĩa ở bước 0 (demand, `S_eff` nhãn, graph `E_t`).
2. Dữ liệu snapshot ở dạng nào: parquet theo timestamp, một bảng lớn, hay DB?
3. Dùng PyTorch Geometric cho GATv2, hay thư viện khác?
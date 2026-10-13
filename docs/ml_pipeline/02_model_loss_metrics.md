# 02 — Model, loss, metrics

Tham chiếu report: §6.4, §7, §8, §9, §13.4–13.5.

## 1. Model `SurgeNet`

Input một batch:
- `x [B, 4, N, 40]` đã chuẩn hóa;
- `b [B, N]` bypass (`b32` cho `gru_strict32`);
- `edge_index [2, E_batch]`, `edge_attr [E_batch, 11]`.

```text
h   = GRU_E( x[..., local_cols] )                 shared, per node; local_cols = LOCAL37 | STRICT32 | ALL40
ŷ_L = b + g_L(h)                                  local head: MLP(d → head_hidden → 1)

# chỉ khi use_graph:
n   = GRU_N( x[..., NEIGHBOR3] )                  φ: neighbor history qua window4
z0  = LayerNorm( Linear([h ; n]) )                Fuse
z   = GATv2Block^L( z0, edge_index, edge_attr )   L lớp
ŷ_G = b + g_G(z)                                  graph head
```

- `GATv2Block(h) = LayerNorm(h + Dropout(ELU(Linear(GATv2Conv(h)))))`.
  - `GATv2Conv` (PyG) có `heads`, `concat=True`, `edge_dim=11`, `add_self_loops=False`; self-loop tổng hợp đã có trong batch.
  - Edge attribute chỉ vào attention score.
- Head tuyến tính ở log-space, không có activation đầu ra. Output có thể âm.
- Đường gradient (report §9.1):
  - local head chỉ nhận gradient từ `λ_L·L_L`;
  - φ, Fuse, GATv2 và graph head chỉ nhận từ `L_G`;
  - GRU_E nhận từ cả hai.
  - Graph branch lấy `h`, không lấy `g_L(h)`.

**Reference.** `gru_gatv2_40` (`SurgeNet`, `models/dual_gru_gatv2.py`) là kiến trúc duy nhất được train, theo handoff Dual GRU + GATv2 V1.2. Baseline: `persistence`, `seasonal_naive`.

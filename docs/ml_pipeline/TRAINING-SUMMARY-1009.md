# Training Summary - 1009

| Dataset | Hex | Snapshots | Interval | Train / Val / Test | Node / Edge features | Target | Device | Version |
|---|---:|---:|---:|---:|---:|---|---|---|
| `hcm_mock_v2_30d_seed42` | 61 | 8,640 | 5 min | 21 / 4 / 5 days | 40 / 10 | H5 log D/S ratio | CPU | `w4_logratio_v1` |

| Model | Short architecture | Objective | Params | Epochs | Best epoch | Time (s) | Status |
|---|---|---|---:|---:|---:|---:|---|
| `persistence` | Current D/S baseline | None | 0 | N/A | N/A | 6 | Complete |
| `gru_strict32` | GRU, 32 strict local features | Min masked Smooth L1 | 23,041 | 21 | 15 | 109 | Complete |
| `gru_local37` | GRU, 37 local features | Min masked Smooth L1 | 24,001 | 22 | 16 | 603 | Complete |
| `gru_pointwise40` | GRU, all 40 features, no graph | Min masked Smooth L1 | 24,577 | 22 | 16 | 144 | Complete |
| `gru_gatv2_40_no_od` | Dual-head GRU + GATv2, adjacency only | Min `L_graph + 0.3 * L_local` | 61,426 | 18 | 12 | 746 | Complete |
| `gru_gatv2_40_no_adj` | Dual-head GRU + GATv2, OD only | Min `L_graph + 0.3 * L_local` | 61,426 | N/A | N/A | N/A | Incomplete |
| `gru_gatv2_40` | Dual-head GRU + GATv2, adjacency + OD | Min `L_graph + 0.3 * L_local` | 61,426 | 22 | 16 | 1,040 | Complete |

| Model | MAE_q | RMSE_q | Bias_q | MAE_log | Pair accuracy | Spearman | Rank by MAE_q |
|---|---:|---:|---:|---:|---:|---:|---:|
| `gru_gatv2_40` | **0.3148** | **0.6541** | -0.1240 | 0.5039 | **0.7508** | **0.6713** | **1** |
| `gru_pointwise40` | 0.3161 | 0.6636 | -0.1341 | 0.5055 | 0.7493 | 0.6681 | 2 |
| `gru_gatv2_40_no_od` | 0.3164 | 0.6650 | -0.1377 | **0.5030** | 0.7497 | 0.6693 | 3 |
| `gru_local37` | 0.3193 | 0.6705 | -0.1369 | 0.5095 | 0.7483 | 0.6657 | 4 |
| `gru_strict32` | 0.3385 | 0.7133 | -0.1497 | 0.5470 | 0.7201 | 0.6034 | 5 |
| `persistence` | 0.4586 | 0.9093 | -0.0001 | 0.6795 | 0.6740 | 0.5005 | 6 |
| `gru_gatv2_40_no_adj` | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

| Evaluation scope | Seed | Selection metric | Validation observations | Final test |
|---|---:|---|---:|---|
| Validation | 42 | Minimum primary-head MAE_q | 68,869 | Not run |

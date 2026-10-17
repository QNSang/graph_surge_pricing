"""Z-score chỉ fit trên train: thống kê float64, std quần thể, std gần 0 thì thay bằng 1."""

import numpy as np

CHUNK = 200_000  # rows per float64 chunk (~60 MB at 40 columns)


def fit_zscore(rows: np.ndarray, std_floor: float) -> tuple[np.ndarray, np.ndarray]:
    """rows [..., F] -> (mean [F], std [F]) float32; cột gần hằng có std 1."""
    flat = rows.reshape(-1, rows.shape[-1])
    mean = np.zeros(flat.shape[1], np.float64)
    sq = np.zeros(flat.shape[1], np.float64)
    for start in range(0, len(flat), CHUNK):  # chunked to bound float64 copies
        chunk = flat[start:start + CHUNK].astype(np.float64)
        mean += chunk.sum(0)
        sq += (chunk * chunk).sum(0)
    mean /= len(flat)
    std = np.sqrt(np.maximum(sq / len(flat) - mean * mean, 0.0))
    std[std < std_floor] = 1.0
    return mean.astype(np.float32), std.astype(np.float32)


def apply_zscore(values: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    """Một bản float32 của `values` (có thể là memmap chỉ đọc), chuẩn hoá tại chỗ."""
    out = np.array(values, dtype=np.float32)
    out -= mean
    out /= std
    return out


def fit_scalers(x: np.ndarray, edge_attr: np.ndarray, edge_ptr: np.ndarray, train: tuple[int, int],
                std_floor: float) -> dict[str, np.ndarray]:
    """Fit scaler node và cạnh chỉ trên snapshot [a, z) của split train (không dùng ngày trước train)."""
    a, z = train
    node_mean, node_std = fit_zscore(x[a:z], std_floor)
    edge_mean, edge_std = fit_zscore(edge_attr[edge_ptr[a]:edge_ptr[z]], std_floor)
    return {"node_mean": node_mean, "node_std": node_std, "edge_mean": edge_mean, "edge_std": edge_std}

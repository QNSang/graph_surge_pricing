"""Hằng số hợp đồng: chỉ số cột, quy tắc chia split, cutoff mẫu, các variant. Chỉ số theo `node_features` của nguồn."""

from dataclasses import dataclass

import numpy as np

N_NODE_FEATURES = 40
N_EDGE_FEATURES = 10
EDGE_DIM = N_EDGE_FEATURES + 1  # + is_self flag
SNAPSHOT_SECONDS = 300
SNAPSHOTS_PER_DAY = 24 * 3600 // SNAPSHOT_SECONDS
WINDOW = 4  # default: t-15, t-10, t-5, t (report §5.1); override with data.window_steps
HORIZON = 1  # default target step (5 min); override with data.horizon_steps
DEMAND_SUPPORT = 10  # demand_mean_60m at row r reads r-11 .. r; earliest row k-(W-1) needs k-(W-1)-11 >= a

IDX_DEMAND = 0  # demand_5m
IDX_IDLE = 1  # idle_supply_t
IDX_EFFECTIVE = 29  # effective_supply_t
IDX_CURRENT_SURGE = 14  # current_surge_t / bidding baseline
IDX_EDGE_ADJ = 0  # edge_is_adjacent
IDX_EDGE_OD = 1  # edge_is_od
ANCHORS = {IDX_DEMAND: "demand_5m", IDX_IDLE: "idle_supply_t", IDX_EFFECTIVE: "effective_supply_t",
           35: "neighbor_demand_mean_t", 36: "neighbor_idle_supply_mean_t", 37: "neighbor_pressure_mean_t"}
EDGE_ANCHORS = {IDX_EDGE_ADJ: "edge_is_adjacent", IDX_EDGE_OD: "edge_is_od"}

ALL40 = list(range(N_NODE_FEATURES))
NEIGHBOR3 = [35, 36, 37]
INBOUND5 = [29, 30, 31, 32, 33]
LOCAL37 = [i for i in ALL40 if i not in NEIGHBOR3]
STRICT32 = [i for i in LOCAL37 if i not in INBOUND5]
COLUMNS = {"local37": LOCAL37, "strict32": STRICT32, "all40": ALL40}

# Calendar split by whole days (report §13.2). The days come from the dataset (meta/manifest.json
# `suggested_split_days_inclusive`, or `data.split_days` in train.yaml); bounds are snapshot indices [a, z).
SPLIT_NAMES = ("train", "val", "test")
Splits = dict[str, tuple[int, int]]
PURGE = 6  # 30 min purge after each split
MAX_HORIZON = 3  # 15 min largest published horizon
END_GAP = PURGE + MAX_HORIZON


def warmup(window: int = WINDOW) -> int:
    """Số snapshot đầu split bỏ qua để cả cửa sổ có đủ 60 phút lịch sử (W=4 -> 14, W=6 -> 16)."""
    return window + DEMAND_SUPPORT


WARMUP = warmup()


def split_bounds(days_inclusive: dict, n_days: int) -> Splits:
    """Đổi ngày split (từ 1, gồm cả hai đầu) thành ranh giới snapshot, ví dụ {"train": (0, 18144), ...}."""
    if set(days_inclusive) != set(SPLIT_NAMES):
        raise ValueError(f"split days must name exactly {SPLIT_NAMES}, got {sorted(days_inclusive)}")
    prev_last = 0
    out = {}
    for name in SPLIT_NAMES:
        first, last = (int(d) for d in days_inclusive[name])
        if not prev_last < first <= last <= n_days:
            raise ValueError(f"split {name} days [{first}, {last}] must be ordered, disjoint and within 1..{n_days}")
        out[name] = ((first - 1) * SNAPSHOTS_PER_DAY, last * SNAPSHOTS_PER_DAY)
        prev_last = last
    return out


def candidates(split: str, splits: Splits, window: int = WINDOW) -> np.ndarray:
    a, z = splits[split]
    return np.arange(a + warmup(window), z - END_GAP, dtype=np.int64)


def shift_target(b: np.ndarray, horizon: int) -> np.ndarray:
    """y[k] = b[k + h]; h bước cuối là NaN."""
    if not 1 <= horizon <= MAX_HORIZON:
        raise ValueError(f"horizon must be in 1..{MAX_HORIZON}, got {horizon}")
    y = np.full_like(b, np.nan)
    y[:-horizon] = b[horizon:]
    return y


BASELINE_FAMILIES = ("persistence", "seasonal")


@dataclass(frozen=True)
class Variant:
    name: str
    columns: str | None  # key into COLUMNS; None = no fitted model
    bypass: str  # "b" or "b32"
    graph: bool = False
    relations: tuple[str, ...] = ()  # subset of ("adj", "od")
    family: str = "gru"  # "persistence" | "seasonal" | "gru"

    @property
    def trainable(self) -> bool:
        """Model torch có checkpoint (GRU hoặc GRU+GATv2)."""
        return self.family == "gru"

    @property
    def primary_head(self) -> str:
        return "graph" if self.graph else "local"

    @property
    def group(self) -> str:
        """Nhóm so sánh: "baseline", "local" (chỉ dùng hex của mình) hoặc "network" (dùng hex khác)."""
        if self.family in BASELINE_FAMILIES:
            return "baseline"
        if self.graph or set(NEIGHBOR3) & set(COLUMNS[self.columns]):
            return "network"
        return "local"

    @property
    def kind(self) -> str | None:
        """Trong "network": graph học được ("gnn") hoặc tổng hợp hàng xóm làm tay ("handcrafted")."""
        if self.group != "network":
            return None
        return "gnn" if self.graph else "handcrafted"


VARIANTS = {v.name: v for v in [
    Variant("persistence", None, "b", family="persistence"),
    Variant("seasonal_naive", None, "b", family="seasonal"),
    Variant("gru_gatv2_40", "local37", "b", True, ("adj", "od")),
]}

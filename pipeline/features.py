"""features.py - feature, nhan va persistence baseline.

Ba dinh nghia da chot (buoc 0 cua spec):

1. demand  = cot `demand` cua hex_snapshot_5min (so don tao trong cua so (ts-5, ts],
             origin_hex = hex). Khong dung supply de suy ra demand.
2. S_eff   = supply + sum w(ETA) tren cac chuyen dang chay ve hex (mock_data_spec 7.1).
             Chuyen dang chay tai ts: pickup_ts <= ts < dropoff_ts.
             ETA = pickup_ts + est_trip_duration - ts (chi dung est, dropoff_ts chi dung de
             loai chuyen da ket thuc truoc ts, nen khong ro ri tuong lai).
             w: ETA<=5 -> 1.0, 5-10 -> 0.5, 10-15 -> 0.2, >15 -> 0 (config `features`).
             Nhan y(i,t+h) goi CUNG ham `s_eff` nay, tai ts = t+h. Chi co mot dinh nghia.
3. E_t     = OD cua rieng snapshot t (khong hop 4 snapshot). Mot cap (o,d) la canh tai t
             neu co request, in-trip hoac completed > 0 trong snapshot t.

Nhan va persistence dung chung mot cong thuc: log((D + eps) / (S_eff + eps)).
Do do `target_y(grid, k, h)` chinh la `persistence_b` tai k+h.

Grid = toan bo feature/nhan tinh san tren luoi ts lien tuc cua mot split. Moi mau chi la
mot lat cat cua grid, nen khong co phep tinh nao nhin qua ts cua cua so.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

NODE_DYN = ["demand", "supply", "s_eff", "backlog", "inflow", "outflow", "eta_min", "log_ds"]
NODE_TIME = ["hour_sin", "hour_cos", "dow_sin", "dow_cos", "weekend", "rain"]
EDGE_COLS = ["log_request", "log_completed", "log_in_trip", "travel_min", "dist_km", "dest_eta_min"]
_BIG = np.int64(2**62)


# ----------------------------------------------------------------------------- thoi gian
def _ceil_div(a, b):
    return -((-a) // b)


def to_k(times_ns, t0_ns, step_ns):
    """Chi so cua so k sao cho ts_k - step < time <= ts_k (ts_k = t0 + k*step)."""
    return _ceil_div(times_ns - t0_ns, step_ns)


def _ns(series: pd.Series) -> np.ndarray:
    """datetime64 -> int64 ns, NaT -> _BIG."""
    s = series.astype("datetime64[ns]")
    out = s.to_numpy().astype("int64")
    out = np.where(s.isna().to_numpy(), _BIG, out)
    return out


def _interval_sum(k_lo, k_hi, col, w, T, N):
    """Tong w tren moi (k, col) voi k in [k_lo, k_hi). Tra ve [T, N]."""
    lo = np.clip(k_lo, 0, T)
    hi = np.clip(k_hi, 0, T)
    keep = hi > lo
    lo, hi, col = lo[keep], hi[keep], col[keep]
    wt = np.full(lo.shape, w, dtype=np.float64) if np.isscalar(w) else np.asarray(w)[keep]
    size = (T + 1) * N
    acc = np.bincount(lo * N + col, weights=wt, minlength=size) - np.bincount(hi * N + col, weights=wt, minlength=size)
    return np.cumsum(acc.reshape(T + 1, N), axis=0)[:T]


def _point_count(k, col, T, N):
    keep = (k >= 0) & (k < T)
    return np.bincount(k[keep] * N + col[keep], minlength=T * N).reshape(T, N).astype(np.float64)


# ----------------------------------------------------------------------------- orders
@dataclass
class Orders:
    origin: np.ndarray       # int hex index
    dest: np.ndarray
    created: np.ndarray      # int64 ns
    accepted: np.ndarray     # _BIG neu null
    pickup: np.ndarray
    dropoff: np.ndarray
    cancel: np.ndarray
    est_ns: np.ndarray       # est_trip_duration, ns

    @property
    def completed(self):
        return (self.pickup < _BIG) & (self.dropoff < _BIG)


def orders_from_frame(df: pd.DataFrame, hex2idx: dict) -> Orders:
    return Orders(
        origin=df["origin_hex"].map(hex2idx).to_numpy().astype(np.int64),
        dest=df["dest_hex"].map(hex2idx).to_numpy().astype(np.int64),
        created=_ns(df["created_ts"]),
        accepted=_ns(df["accepted_ts"]),
        pickup=_ns(df["pickup_ts"]),
        dropoff=_ns(df["dropoff_ts"]),
        cancel=_ns(df["cancel_ts"]),
        est_ns=(df["est_trip_duration_min"].to_numpy() * 60e9).astype(np.int64),
    )


# ----------------------------------------------------------------------------- S_eff
def s_eff(supply, orders: Orders, t0_ns, step_ns, eta_edges_min, eta_weights):
    """S_eff[T, N] = supply + tong trong so cac chuyen dang chay ve hex. DUY NHAT mot dinh nghia."""
    T, N = supply.shape
    c = orders.completed
    pickup, dropoff, dest = orders.pickup[c], orders.dropoff[c], orders.dest[c]
    end_est = pickup + orders.est_ns[c]
    edges = [np.int64(round(e * 60e9)) for e in eta_edges_min]
    inflight = np.zeros((T, N))
    for j, wj in enumerate(eta_weights):
        lo = end_est - edges[j]
        hi = end_est - edges[j - 1] if j > 0 else np.full_like(end_est, _BIG)
        lo = np.maximum(lo, pickup)          # chi tinh khi dang chay
        hi = np.minimum(hi, dropoff)
        k_lo = to_k(lo, t0_ns, step_ns)
        k_hi = np.where(hi >= _BIG, 2**40, to_k(np.minimum(hi, _BIG - 1), t0_ns, step_ns))
        inflight += _interval_sum(k_lo, k_hi, dest, wj, T, N)
    return supply + inflight


def order_flows(orders: Orders, t0_ns, step_ns, T, N):
    """backlog, inflow, outflow [T, N]. Chi dung su kien da xay ra tai/truoc ts."""
    k_created = to_k(orders.created, t0_ns, step_ns)
    leave = np.minimum(orders.accepted, orders.cancel)
    k_leave = np.where(leave >= _BIG, 2**40, to_k(np.minimum(leave, _BIG - 1), t0_ns, step_ns))
    backlog = _interval_sum(k_created, k_leave, orders.origin, 1.0, T, N)
    c = orders.completed
    inflow = _point_count(to_k(orders.dropoff[c], t0_ns, step_ns), orders.dest[c], T, N)
    p = orders.pickup < _BIG
    outflow = _point_count(to_k(orders.pickup[p], t0_ns, step_ns), orders.origin[p], T, N)
    return backlog, inflow, outflow


# ----------------------------------------------------------------------------- canh OD
def haversine_km(lat, lng):
    la, lo = np.radians(lat), np.radians(lng)
    dlat = la[:, None] - la[None, :]
    dlon = lo[:, None] - lo[None, :]
    a = np.sin(dlat / 2) ** 2 + np.cos(la)[:, None] * np.cos(la)[None, :] * np.sin(dlon / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def pair_est_matrix(orders: Orders, dist):
    """Fallback travel_time [N, N]: trung vi est_trip_duration theo cap, fit tren orders duoc dua vao (train)."""
    N = dist.shape[0]
    est_min = orders.est_ns / 60e9
    df = pd.DataFrame({"o": orders.origin, "d": orders.dest, "est": est_min})
    med = df.groupby(["o", "d"])["est"].median()
    mat = np.full((N, N), np.nan)
    mat[med.index.get_level_values(0), med.index.get_level_values(1)] = med.to_numpy()
    off = dist > 0
    ratio = np.nanmedian((mat / np.where(off, dist, np.nan)))
    fill = np.where(off, dist * ratio, np.nanmedian(np.diag(mat)) if np.isfinite(np.nanmedian(np.diag(mat))) else np.nanmedian(mat))
    return np.where(np.isnan(mat), fill, mat)


def edge_table(orders: Orders, t0_ns, step_ns, T, N, travel_w_steps, pair_est):
    """Canh theo snapshot, dang CSR theo k. Tra ve ptr[T+1], src, dst, attr[E, 4]."""
    NN = N * N
    c = orders.completed
    o_all, d_all = orders.origin, orders.dest

    k_req = to_k(orders.created, t0_ns, step_ns)
    m = (k_req >= 0) & (k_req < T)
    key_req = k_req[m] * NN + o_all[m] * N + d_all[m]

    k_comp = to_k(orders.dropoff[c], t0_ns, step_ns)
    oc, dc = o_all[c], d_all[c]
    m = (k_comp >= 0) & (k_comp < T)
    key_comp = k_comp[m] * NN + oc[m] * N + dc[m]

    lo = np.clip(to_k(orders.pickup[c], t0_ns, step_ns), 0, T)
    hi = np.clip(k_comp, 0, T)
    n = np.maximum(hi - lo, 0)
    idx = np.repeat(np.arange(len(n)), n)
    off = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
    key_in = (lo[idx] + off) * NN + oc[idx] * N + dc[idx]

    keys = np.concatenate([key_req, key_comp, key_in])
    uniq, inv = np.unique(keys, return_inverse=True)
    U = len(uniq)
    a, b = len(key_req), len(key_req) + len(key_comp)
    n_req = np.bincount(inv[:a], minlength=U)
    n_comp = np.bincount(inv[a:b], minlength=U)
    n_in = np.bincount(inv[b:], minlength=U)

    # travel_time: trung binh thoi gian chuyen da hoan thanh trong travel_w_steps cua so gan nhat
    dur_min = (orders.dropoff[c] - orders.pickup[c]) / 60e9
    sum_dur = np.zeros(U)
    cnt = np.zeros(U)
    for r in range(travel_w_steps):
        k = k_comp + r
        m = (k >= 0) & (k < T)
        tk = k[m] * NN + oc[m] * N + dc[m]
        pos = np.searchsorted(uniq, tk)
        pos = np.minimum(pos, U - 1)
        ok = uniq[pos] == tk
        sum_dur += np.bincount(pos[ok], weights=dur_min[m][ok], minlength=U)
        cnt += np.bincount(pos[ok], minlength=U)

    k_e = uniq // NN
    o_e = (uniq % NN) // N
    d_e = uniq % N
    travel = np.where(cnt > 0, sum_dur / np.maximum(cnt, 1), pair_est[o_e, d_e])
    attr = np.stack([np.log1p(n_req), np.log1p(n_comp), np.log1p(n_in), travel], axis=1).astype(np.float32)
    ptr = np.searchsorted(k_e, np.arange(T + 1))
    return ptr, o_e.astype(np.int64), d_e.astype(np.int64), attr


# ----------------------------------------------------------------------------- grid
@dataclass
class Grid:
    ts: np.ndarray                  # datetime64[ns] [T]
    hexes: list
    node: np.ndarray                # [T, N, F] float32
    node_cols: list
    present: np.ndarray             # [T, N] bool
    d: np.ndarray                   # raw demand [T, N]
    s: np.ndarray                   # raw supply
    s_eff: np.ndarray
    b: np.ndarray                   # log((D+eps)/(S_eff+eps))
    ptr: np.ndarray
    esrc: np.ndarray
    edst: np.ndarray
    eattr: np.ndarray               # [E, Fe] float32
    edge_cols: list = field(default_factory=lambda: list(EDGE_COLS))


def log_ds(d, s, eps):
    return np.log((d + eps) / (s + eps))


def build_grid(snap, orders: Orders, hexes: pd.DataFrame, weather: pd.DataFrame, pair_est, dist, cfg) -> Grid:
    """snap: DataFrame (ts, hex_id, demand, supply, eta_sec) da validate, 1 split."""
    dcfg, fcfg = cfg["data"], cfg["features"]
    step_min = dcfg["snapshot_min"]
    step_ns = np.int64(step_min * 60e9)
    hex_ids = hexes["hex_id"].tolist()
    hex2idx = {h: i for i, h in enumerate(hex_ids)}
    N = len(hex_ids)

    ts = np.sort(snap["ts"].unique())
    T = len(ts)
    ts_ns = ts.astype("datetime64[ns]").astype("int64")
    t0_ns = ts_ns[0]
    assert (np.diff(ts_ns) == step_ns).all(), "snapshot ts khong lien tuc"

    ti = ((snap["ts"].astype("datetime64[ns]").astype("int64").to_numpy() - t0_ns) // step_ns).astype(np.int64)
    hi = snap["hex_id"].map(hex2idx).to_numpy().astype(np.int64)
    D = np.zeros((T, N)); S = np.zeros((T, N)); ETA = np.zeros((T, N)); present = np.zeros((T, N), bool)
    D[ti, hi] = snap["demand"].to_numpy()
    S[ti, hi] = snap["supply"].to_numpy()
    ETA[ti, hi] = snap["eta_sec"].to_numpy()
    present[ti, hi] = True

    Seff = s_eff(S, orders, t0_ns, step_ns, fcfg["eta_edges_min"], fcfg["eta_weights"])
    backlog, inflow, outflow = order_flows(orders, t0_ns, step_ns, T, N)
    b = log_ds(D, Seff, dcfg["eps"])

    # thoi gian, thoi tiet, tinh
    tsd = pd.DatetimeIndex(ts)
    hour = tsd.hour.to_numpy() + tsd.minute.to_numpy() / 60.0
    dow = tsd.dayofweek.to_numpy()
    rain = weather.set_index("ts")["rain_intensity"].reindex(tsd).fillna(0.0).to_numpy()
    tfeat = np.stack([np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24),
                      np.sin(2 * np.pi * dow / 7), np.cos(2 * np.pi * dow / 7),
                      (dow >= 5).astype(float), rain], axis=1)                       # [T, 6]
    zones = sorted(hexes["zone"].unique())
    static = np.concatenate([np.stack([(hexes["zone"] == z).to_numpy().astype(float) for z in zones], axis=1),
                             hexes["ring"].to_numpy()[:, None].astype(float)], axis=1)  # [N, Z+1]

    dyn = np.stack([np.log1p(D), np.log1p(S), np.log1p(Seff), np.log1p(backlog), np.log1p(inflow),
                    np.log1p(outflow), ETA / 60.0, b], axis=-1)                     # [T, N, 8]
    dyn = np.where(present[..., None], dyn, 0.0)
    node = np.concatenate([dyn,
                           np.broadcast_to(tfeat[:, None, :], (T, N, tfeat.shape[1])),
                           np.broadcast_to(static[None], (T, N, static.shape[1]))], axis=-1).astype(np.float32)
    cols = NODE_DYN + NODE_TIME + [f"zone_{z}" for z in zones] + ["ring"]

    ptr, src, dst, attr4 = edge_table(orders, t0_ns, step_ns, T, N, fcfg["travel_window_min"] // step_min, pair_est)
    kk = np.repeat(np.arange(T), np.diff(ptr))
    extra = np.stack([dist[src, dst], ETA[kk, dst] / 60.0], axis=1).astype(np.float32)
    eattr = np.concatenate([attr4, extra], axis=1)

    assert np.isfinite(node).all() and np.isfinite(eattr).all(), "feature co NaN/inf"
    return Grid(ts=ts.astype("datetime64[ns]"), hexes=hex_ids, node=node, node_cols=cols, present=present,
                d=D, s=S, s_eff=Seff, b=b, ptr=ptr, esrc=src, edst=dst, eattr=eattr)


# ----------------------------------------------------------------------------- lat cat cho mot mau
def build_features(grid: Grid, k: int, window: int):
    """Cua so {t-15..t} ket thuc o snapshot k.

    Tra ve node_x [window, N, F], edge_index [2, E] (OD cua snapshot k), edge_attr [E, Fe],
    mask [N] (hex co mat o ca `window` snapshot)."""
    assert k - window + 1 >= 0, "thieu snapshot trong cua so"
    node_x = grid.node[k - window + 1:k + 1]
    a, z = grid.ptr[k], grid.ptr[k + 1]
    edge_index = np.stack([grid.esrc[a:z], grid.edst[a:z]])
    mask = grid.present[k - window + 1:k + 1].all(axis=0)
    return node_x, edge_index, grid.eattr[a:z], mask


def persistence_b(grid: Grid, k: int):
    """b_i = log((D_t + eps)/(S_eff_t + eps)) tai snapshot k. [N]"""
    return grid.b[k]


def target_y(grid: Grid, k: int, steps):
    """y(i, t+h) cho cac h (don vi snapshot). Tra ve y [N, H], mask [N, H], vol [N, H].

    y chinh la b tai k+h: cung ham s_eff, cung eps."""
    kh = k + np.asarray(steps)
    y = grid.b[kh].T
    mask = grid.present[kh].T
    vol = (grid.d[kh] + grid.s_eff[kh]).T
    return y, mask, vol

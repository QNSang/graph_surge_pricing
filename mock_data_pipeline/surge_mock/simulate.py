"""Run the kernel for one graph-signal strength g and turn the buffers into raw tables."""
import time

import numpy as np
import pandas as pd

from . import kernel as K
from .exogenous import SNAP
from .geo import ZID, ZONES
from .rng import numba_seed, stream


def build_params(cfg):
    P = np.zeros(K.N_PARAMS)
    d, t, dr, e = cfg.demand, cfg.trip, cfg.drivers, cfg.eta
    P[K.P_INTRA_PROB] = d["intra_hex_prob"]
    P[K.P_PRICE] = d["price_sensitivity"]
    P[K.P_PAT_MEAN] = d["patience_mean_min"]
    P[K.P_PAT_MAX] = d["patience_max_min"]
    P[K.P_PC_BASE] = d["post_accept_cancel"]["base"]
    P[K.P_PC_PER] = d["post_accept_cancel"]["per_min_over_4"]
    P[K.P_SPD_PEAK] = t["speed_kmh"]["peak"]
    P[K.P_SPD_OFF] = t["speed_kmh"]["offpeak"]
    P[K.P_ROAD] = t["road_factor"]
    P[K.P_FIXED] = t["fixed_min"]
    P[K.P_SIGMA] = t["duration_noise_sigma"]
    P[K.P_INTRA_FLOOR] = t["intra_hex_min_floor"]
    P[K.P_PK_SAME_F] = dr["pickup_same_hex"]["fixed"]
    P[K.P_PK_SAME_E] = dr["pickup_same_hex"]["exp_mean"]
    P[K.P_PK_NB_F] = dr["pickup_neighbor"]["fixed"]
    P[K.P_PK_NB_E] = dr["pickup_neighbor"]["exp_mean"]
    P[K.P_REPO_PROB] = dr["reposition"]["prob"]
    P[K.P_REPO_POW] = dr["reposition"]["power"]
    P[K.P_REPO_MIN] = dr["reposition"]["minutes"]
    P[K.P_REPO_IDLE] = dr["reposition"]["idle_min"]
    P[K.P_SHIFT_LOGMED] = np.log(dr["shift_lognormal"]["median_min"])
    P[K.P_SHIFT_SIG] = dr["shift_lognormal"]["sigma"]
    P[K.P_MIN_SESS] = dr["min_session_min"]
    sg = cfg.base_surge
    P[K.P_SG_GAIN], P[K.P_SG_EMA] = sg["gain"], sg["ema"]
    P[K.P_SG_MIN], P[K.P_SG_MAX], P[K.P_SG_STEP] = sg["min"], sg["max"], sg["step"]
    P[K.P_SG_DEAD] = sg.get("deadzone", 0.0)
    gate = d.get("no_cars_filter", {})
    P[K.P_GATE_THETA] = gate.get("theta", 0.0)
    P[K.P_GATE_BETA] = gate.get("beta", 0.0)
    P[K.P_GATE_FLOOR] = gate.get("floor", 0.2)
    P[K.P_ETA_SAME_F], P[K.P_ETA_SAME_E] = e["same_hex"]["fixed"], e["same_hex"]["exp_mean"]
    P[K.P_ETA1_F], P[K.P_ETA1_E] = e["ring1"]["fixed"], e["ring1"]["exp_mean"]
    P[K.P_ETA2_F], P[K.P_ETA2_E] = e["ring2"]["fixed"], e["ring2"]["exp_mean"]
    P[K.P_ETA_FAR] = e["far_min"]
    P[K.P_RAIN_SPD] = cfg.rain["speed_factor"]
    P[K.P_RAIN_ETA] = cfg.rain["eta_factor"]
    P[K.P_DISP_LO], P[K.P_DISP_HI] = dr["dispatch_delay_sec"]
    return P


def assign_homes(cfg, geo, n_drivers, rng):
    share = cfg.drivers["home_zone_share"]
    groups = [geo.hexes_of("residential"), geo.hexes_of("suburb"),
              np.concatenate([geo.hexes_of(z) for z in ("cbd", "office", "venue", "airport")])]
    p = np.array([share["residential"], share["suburb"], share["other"]], dtype=float)
    p /= p.sum()
    g = rng.choice(3, size=n_drivers, p=p)
    return np.array([rng.choice(groups[k]) for k in g], dtype=np.int32)


def run_simulation(cfg, geo, exo, g, log=print):
    """Returns the raw simulation buffers (including burn-in) for strength g."""
    P = build_params(cfg)
    radius = float(geo.intra_radius_km)
    if not np.isfinite(radius) or radius <= 0:
        raise ValueError("intra-hex radius must be finite and positive")
    P[K.P_INTRA_R] = radius
    n_drivers = int(exo.target.max() * cfg.drivers["pool_margin"]) + 50
    home = assign_homes(cfg, geo, n_drivers, stream(cfg.seed, "drivers"))
    order_cap = int(exo.intents.sum()) + 1000
    S = K.make_state(geo.adj, geo.adj_n, geo.hex_dist, geo.dist_km, home, order_cap, exo.W)
    K.seed_rng(numba_seed(cfg.seed, f"sim-g{g}"))
    A, L = exo.dest_inputs(g)
    A = np.ascontiguousarray(A)
    L = np.ascontiguousarray(L)
    chunk = 288
    t0 = time.time()
    for w0 in range(0, exo.W, chunk):
        w1 = min(w0 + chunk, exo.W)
        K.run_windows(S, P, w0, w1, exo.intents, A, L, exo.rain, exo.vpeak, exo.target)
        if (w0 // chunk) % 10 == 0 or w1 == exo.W:
            log(f"  g={g}: day {w1 // chunk}/{exo.W // chunk}  orders={S.cnt[K.C_ORDERS]:,}  "
                f"({time.time() - t0:.0f}s)")
    K.finalize(S)
    return S


def _to_ts(minutes, base):
    sec = np.round(np.asarray(minutes, dtype=np.float64) * 60.0)
    out = np.full(sec.shape, np.datetime64("NaT"), dtype="datetime64[ms]")
    ok = ~np.isnan(sec)
    out[ok] = base + (sec[ok].astype("int64") * 1000).astype("timedelta64[ms]")
    return out


def build_tables(cfg, geo, exo, S):
    """Slice off the burn-in and build the raw tables (spec 1) as DataFrames / arrays."""
    b = cfg.burn_in_days
    N = cfg.n_days
    H = geo.n
    base = np.datetime64(cfg.start_date, "ms") - np.timedelta64(b * 1440, "m")
    n = int(S.cnt[K.C_ORDERS])
    created = S.o_created[:n]
    keep = created > b * 1440
    idx = np.where(keep)[0]
    cells = np.array(geo.cells)
    orders = pd.DataFrame({
        "order_id": np.arange(1, len(idx) + 1, dtype=np.int64),
        "origin_hex": cells[S.o_origin[idx]],
        "dest_hex": cells[S.o_dest[idx]],
        "created_ts": _to_ts(created[idx], base),
        "est_trip_duration_min": S.o_est[idx],
        "accepted_ts": _to_ts(S.o_accept[idx], base),
        "pickup_ts": _to_ts(S.o_pickup[idx], base),
        "dropoff_ts": _to_ts(S.o_dropoff[idx], base),
        "cancel_ts": _to_ts(S.o_cancel[idx], base),
    })
    orders["_origin_zone"] = geo.zone[S.o_origin[idx]].astype(np.int8)

    w0 = b * 288
    nw = N * 288
    ts = base + ((np.arange(w0, w0 + nw, dtype=np.int64) + 1) * (SNAP * 60 * 1000)).astype("timedelta64[ms]")
    sl = slice(w0, w0 + nw)
    snap = pd.DataFrame({
        "ts": np.repeat(ts, H),
        "hex_id": np.tile(cells, nw),
        "demand": S.snap_demand[sl].reshape(-1),
        "supply": S.snap_supply[sl].reshape(-1),
        "eta_sec": S.snap_eta[sl].reshape(-1),
        "surge_multiplier": S.snap_surge[sl].reshape(-1),
    })
    weather = pd.DataFrame({"ts": ts, "rain_intensity": exo.rain[w0 * SNAP + SNAP - 1:(w0 + nw) * SNAP:SNAP]})
    tr = exo.truth
    truth = pd.DataFrame({
        "ts": np.repeat(ts, H), "hex_id": np.tile(cells, nw),
        "s1_ramp": tr["s1_ramp"][sl].reshape(-1),
        "s2_drain": tr["s2_drain"][sl].reshape(-1),
        "s3_airport": tr["s3_airport"][sl].reshape(-1),
        "s4_venue": tr["s4_venue"][sl].reshape(-1),
        "s5_rain": np.repeat(tr["s5_rain"][sl], H),
        "s6_sparse": np.tile(geo.s6_sparse, nw),
        "s7_boundary": np.tile(geo.s7_boundary, nw),
    })
    debug = pd.DataFrame({
        "ts": ts,
        "online": S.stats[sl, 0] / SNAP, "idle": S.stats[sl, 1] / SNAP,
        "pickup": S.stats[sl, 2] / SNAP, "in_trip": S.stats[sl, 3] / SNAP,
        "waiting": S.snap_wait[sl].sum(axis=1),
    })
    snap_wait = pd.DataFrame({"ts": snap["ts"], "hex_id": snap["hex_id"], "waiting": S.snap_wait[sl].reshape(-1)})
    return dict(orders=orders, hex_snapshot_5min=snap, weather_5min=weather, signal_truth=truth,
                debug_driver_stats=debug, debug_waiting=snap_wait)


def shuffle_destinations(orders, seed):
    """Control set (spec 5.2): permute dest_hex within (origin zone, calendar hour), table-only."""
    rng = stream(seed, "shuffle")
    hour = orders["created_ts"].values.astype("datetime64[h]").astype("int64")
    key = hour * 8 + orders["_origin_zone"].values.astype("int64")
    order_by_key = np.argsort(key, kind="stable")
    perm = np.lexsort((rng.random(len(orders)), key))
    out = orders.copy()
    dest = orders["dest_hex"].values
    new = dest.copy()
    new[order_by_key] = dest[perm]
    out["dest_hex"] = new
    return out

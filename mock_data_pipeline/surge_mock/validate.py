"""Realism checks (spec 8) and signal checks (spec 8.1) on written datasets."""
import json
import os

import numpy as np
import pandas as pd
import yaml

from .geo import haversine_km
from .writers import read_table

# (key, label, lo, hi, formula note)
TARGETS = [
    ("trip_km_mean", "Khoảng cách chuyến trung bình (km)", 4, 7),
    ("trip_min_median", "Trung vị thời gian chuyến (phút)", 15, 25),
    ("intra_share", "Tỷ lệ chuyến nội hex", 0.15, 0.25),
    ("pickup_min_median", "Trung vị thời gian đón (phút)", 4, 8),
    ("completion_rate", "Tỷ lệ hoàn thành toàn kỳ", 0.75, 0.90),
    ("nodriver_cancel_share_peak", "Hủy do không tài xế / tổng hủy, cao điểm", 0.5, 1.0),
    ("util_peak", "Utilization cao điểm", 0.65, 0.80),
    ("util_offpeak", "Utilization thấp điểm", 0.35, 0.55),
    ("surge_gt1_share", "Tỷ lệ dòng snapshot surge > 1", 0.15, 0.30),
    ("surge_ge2_share", "Tỷ lệ dòng snapshot surge >= 2", 0.0, 0.05),
    ("airport_trip_share", "Tỷ lệ chuyến từ/đến sân bay", 0.03, 0.06),
    ("demand_vmr", "Phương sai / trung bình demand theo hex-giờ", 1.2, 3.0),
    ("day_cv", "CV tổng cầu giữa các ngày cùng thứ", 0.05, 0.12),
    ("suburb_ds_median", "Suburb: trung vị demand + supply mỗi 5 phút", 0.0, 6.0),
    ("est_err_median", "Sai số tuyệt đối trung vị est vs thực tế", 0.07, 0.13),
]
NOTES = [
    ("completion_peak_lt_off", "Tỷ lệ hoàn thành cao điểm < thấp điểm", None, None),
    ("completion_rain_lt_dry", "Tỷ lệ hoàn thành khi mưa < không mưa", None, None),
]


def _peak_mask(ts):
    hour = ts.dt.hour.values
    wk = ts.dt.dayofweek.values < 5
    return wk & (((hour >= 6) & (hour < 10)) | ((hour >= 16) & (hour < 20)))


def compute_metrics(root, hexes, out_cfg):
    orders = read_table(root, "orders")
    snap = read_table(root, "hex_snapshot_5min")
    weather = read_table(root, "weather_5min")
    dbg = pd.read_parquet(os.path.join(root, "_debug", "driver_stats_5min.parquet"))
    truth = read_table(root, "signal_truth")
    zone = hexes.set_index("hex_id")["zone"]
    lat = hexes.set_index("hex_id")["lat"]
    lng = hexes.set_index("hex_id")["lng"]
    m = {}

    o = orders
    done = o["dropoff_ts"].notna()
    peak = _peak_mask(o["created_ts"])
    dkm = haversine_km(lat[o["origin_hex"]].values, lng[o["origin_hex"]].values,
                       lat[o["dest_hex"]].values, lng[o["dest_hex"]].values)
    intra = (o["origin_hex"] == o["dest_hex"]).values
    dkm = np.where(intra, 1.16, dkm)
    m["trip_km_mean"] = float(dkm.mean())
    m["intra_share"] = float(intra.mean())
    dur = (o["dropoff_ts"] - o["pickup_ts"]).dt.total_seconds() / 60
    m["trip_min_median"] = float(dur[done].median())
    m["trip_min_median_peak"] = float(dur[done & peak].median())
    m["trip_min_median_offpeak"] = float(dur[done & ~peak].median())
    pk = (o["pickup_ts"] - o["accepted_ts"]).dt.total_seconds() / 60
    m["pickup_min_median"] = float(pk[done].median())
    m["completion_rate"] = float(done.mean())
    m["completion_peak"] = float(done[peak].mean())
    m["completion_offpeak"] = float(done[~peak].mean())
    # rain at order creation (window = ceil(created / 5min))
    wts = weather["ts"].values
    win = np.searchsorted(wts, o["created_ts"].values, side="left").clip(0, len(wts) - 1)
    rainy = weather["rain_intensity"].values[win] > 0
    m["completion_rain"] = float(done[rainy].mean()) if rainy.any() else float("nan")
    m["completion_dry"] = float(done[~rainy].mean())
    canc = o["cancel_ts"].notna()
    nod = canc & o["accepted_ts"].isna()
    m["nodriver_cancel_share_peak"] = float(nod[peak].sum() / max(1, canc[peak].sum()))
    m["nodriver_cancel_share_all"] = float(nod.sum() / max(1, canc.sum()))
    m["cancel_rate"] = float(canc.mean())
    m["no_driver_rate"] = float(nod.mean())

    # utilization from driver stats
    pk_w = _peak_mask(dbg["ts"] - pd.Timedelta(minutes=5))
    util = (dbg["pickup"] + dbg["in_trip"]) / dbg["online"].clip(lower=1)
    m["util_peak"] = float(util[pk_w].mean())
    m["util_offpeak"] = float(util[~pk_w].mean())
    h = (dbg["ts"] - pd.Timedelta(minutes=5)).dt.hour
    m["util_by_hour"] = {int(k): round(float(v), 3) for k, v in util.groupby(h.values).mean().items()}
    m["online_by_hour"] = {int(k): int(v) for k, v in dbg["online"].groupby(h.values).mean().items()}

    s = snap["surge_multiplier"]
    m["surge_gt1_share"] = float((s > 1.001).mean())
    m["surge_ge2_share"] = float((s >= 1.999).mean())
    m["surge_mean"] = float(s.mean())
    z = zone[o["origin_hex"]].values
    zd = zone[o["dest_hex"]].values
    m["airport_trip_share"] = float(((z == "airport") | (zd == "airport")).mean())

    # demand dispersion per hex-hour-of-day (weekdays)
    sw = snap.copy()
    tshift = sw["ts"] - pd.Timedelta(minutes=5)
    sw["hod"] = tshift.dt.hour
    sw["wk"] = tshift.dt.dayofweek < 5
    g = sw[sw["wk"]].groupby(["hex_id", "hod"])["demand"].agg(["mean", "var"])
    g = g[g["mean"] >= 1.0]
    m["demand_vmr"] = float((g["var"] / g["mean"]).median())

    # day-to-day CV of total demand for the same weekday
    d = o.groupby(o["created_ts"].dt.normalize()).size()
    dd = pd.DataFrame({"n": d.values, "dow": d.index.dayofweek})
    cvs = dd.groupby("dow")["n"].agg(lambda x: x.std(ddof=1) / x.mean() if len(x) > 2 else np.nan)
    m["day_cv"] = float(cvs.mean())
    m["orders_per_day_mean"] = float(d.mean())
    m["n_orders"] = int(len(o))

    sub = snap[zone[snap["hex_id"]].values == "suburb"]
    m["suburb_ds_median"] = float((sub["demand"] + sub["supply"]).median())

    est = o["est_trip_duration_min"]
    m["est_err_median"] = float(((dur[done] - est[done]).abs() / est[done]).median())

    # remaining ETA of in-flight trips at hourly sample points
    od = o[done].sort_values("pickup_ts")
    pt = od["pickup_ts"].values
    end_est = (od["pickup_ts"] + pd.to_timedelta(od["est_trip_duration_min"], unit="m")).values
    dropoff = od["dropoff_ts"].values
    t0, t1 = o["created_ts"].min().ceil("h"), o["created_ts"].max().floor("h")
    long_n = tot_n = 0
    for ts in pd.date_range(t0, t1, freq="h").values:
        lo = np.searchsorted(pt, ts - np.timedelta64(180, "m"))
        hi = np.searchsorted(pt, ts, side="right")
        a = slice(lo, hi)
        inflight = (dropoff[a] > ts)
        rem = (end_est[a][inflight] - ts) / np.timedelta64(1, "m")
        tot_n += inflight.sum()
        long_n += (rem > 15).sum()
    m["inflight_eta_gt15_share"] = float(long_n / max(1, tot_n))

    m.update(signal_metrics(o, snap, truth, zone, hexes, out_cfg))
    return m


def signal_metrics(o, snap, truth, zone, hexes, root_cfg):
    out = {}
    H = len(hexes)
    snap = snap.sort_values(["hex_id", "ts"]).reset_index(drop=True)
    truth = truth.sort_values(["hex_id", "ts"]).reset_index(drop=True)
    b = np.log((snap["demand"].values + 1.0) / (snap["supply"].values + 1.0))
    snap["b"] = b
    shift = lambda arr, k: pd.Series(arr).groupby(snap["hex_id"].values).shift(-k).values
    y10 = shift(b, 2)
    y15 = shift(b, 3)
    ok = ~np.isnan(y10)
    out["corr_b_y10"] = float(np.corrcoef(b[ok], y10[ok])[0, 1])

    # in-trip outbound OD count per origin hex at ts (orders picked up, not yet dropped off)
    ts_vals = np.sort(snap["ts"].unique())
    T = len(ts_vals)
    tidx = {t: i for i, t in enumerate(ts_vals)}
    hid = {h: i for i, h in enumerate(sorted(hexes["hex_id"]))}
    pk = o[o["pickup_ts"].notna() & o["dropoff_ts"].notna()]
    w_up = np.searchsorted(ts_vals, pk["pickup_ts"].values, side="left").clip(0, T)
    w_dn = np.searchsorted(ts_vals, pk["dropoff_ts"].values, side="left").clip(0, T)
    hi = pk["origin_hex"].map(hid).values
    delta = np.zeros((T + 1, H))
    np.add.at(delta, (w_up, hi), 1)
    np.add.at(delta, (w_dn, hi), -1)
    in_trip_out = np.cumsum(delta, axis=0)[:T]
    ts_i = snap["ts"].map(tidx).values
    hx_i = snap["hex_id"].map(hid).values
    flow = in_trip_out[ts_i, hx_i]
    dsr = (snap["demand"].values + 1.0) / (snap["supply"].values + 1.0)
    for name, flag in (("s2", truth["s2_drain"].values),):
        sel = ok & ~np.isnan(y15) & flag
        if sel.sum() > 50:
            out[f"{name}_corr_outflow_y15"] = float(np.corrcoef(flow[sel], y15[sel])[0, 1])
            out[f"{name}_corr_dsratio_y15"] = float(np.corrcoef(dsr[sel], y15[sel])[0, 1])
            out[f"{name}_rows"] = int(sel.sum())

    # S3 / S4: inbound orders into airport/venue in flagged windows vs the same time of day on unflagged days
    wi_d = np.searchsorted(ts_vals, o["created_ts"].values, side="left").clip(0, T - 1)
    tod = np.arange(T) % 288
    for key, zname, col in (("s3", "airport", "s3_airport"), ("s4", "venue", "s4_venue")):
        hexes_z = set(hexes.loc[hexes["zone"] == zname, "hex_id"])
        sel_o = o["dest_hex"].isin(hexes_z).values & ~(o["origin_hex"].isin(hexes_z).values)
        cnt = np.bincount(wi_d[sel_o], minlength=T).astype(float)
        flag_w = truth.loc[truth["hex_id"].isin(hexes_z)].groupby("ts")[col].any().reindex(ts_vals).fillna(False).values
        sb = snap[snap["hex_id"].isin(hexes_z)].groupby("ts")["b"].mean().reindex(ts_vals).values
        if not flag_w.any():
            continue
        for lab, arr in (("inbound_per_window", cnt), ("b", sb)):
            base = np.array([np.nanmean(arr[(tod == k) & ~flag_w]) if ((tod == k) & ~flag_w).any() else np.nan
                             for k in range(288)])
            out[f"{key}_{lab}_flag"] = float(np.nanmean(arr[flag_w]))
            out[f"{key}_{lab}_same_tod_unflagged"] = float(np.nanmean(base[tod[flag_w]]))

    # S2a: day-to-day variation of the realised office outbound share to residential/suburb, 16-20h weekdays
    t = o["created_ts"]
    sel = (t.dt.hour >= 16) & (t.dt.hour < 20) & (t.dt.dayofweek < 5) & (zone[o["origin_hex"]].values == "office")
    oo = o[sel]
    if len(oo):
        res = zone[oo["dest_hex"]].isin(["residential", "suburb"]).values
        day = oo["created_ts"].dt.normalize().values
        share = pd.Series(res).groupby(day).mean()
        out["s2a_office_out_share_mean"] = float(share.mean())
        out["s2a_office_out_share_sd"] = float(share.std())
    return out


def evaluate(m):
    rows = []
    for key, label, lo, hi in TARGETS:
        v = m.get(key)
        ok = v is not None and not np.isnan(v) and lo <= v <= hi
        rows.append((label, key, v, lo, hi, ok))
    return rows


def write_report(out_dir, names, hexes, log=print):
    results = {}
    for n in names:
        log(f"validating {n}")
        results["g1.0" if n == "." else n] = compute_metrics(os.path.join(out_dir, n), hexes, None)
    with open(os.path.join(out_dir, "validation_metrics.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, default=float)
    lines = ["# Validation report (spec mục 8)", ""]
    for n, m in results.items():
        lines += [f"## {n}", "", "| Chỉ tiêu | Giá trị | Khoảng mục tiêu | OK |", "|---|---|---|---|"]
        for label, key, v, lo, hi, ok in evaluate(m):
            lines.append(f"| {label} | {v:.3f} | {lo}–{hi} | {'✅' if ok else '❌'} |")
        lines += ["", "Thông tin thêm:", ""]
        extra = ["trip_min_median_peak", "trip_min_median_offpeak", "completion_peak", "completion_offpeak",
                 "completion_rain", "completion_dry", "cancel_rate", "no_driver_rate",
                 "nodriver_cancel_share_all", "surge_mean", "orders_per_day_mean", "n_orders",
                 "inflight_eta_gt15_share"]
        for k in extra:
            lines.append(f"- {k}: {m[k]:.3f}")
        lines += ["", "Utilization theo giờ: " + json.dumps(m["util_by_hour"]),
                  "", "Online theo giờ: " + json.dumps(m["online_by_hour"]), "",
                  "### Tín hiệu (8.1)", ""]
        for k, v in m.items():
            if k.startswith(("s2", "s3", "s4", "corr_")):
                lines.append(f"- {k}: {v:.4f}" if isinstance(v, float) else f"- {k}: {v}")
        lines.append("")
    with open(os.path.join(out_dir, "validation_report.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return results


def load_hexes(out_dir):
    return pd.read_parquet(os.path.join(out_dir, "hexes.parquet"))

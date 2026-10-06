"""Parquet writers, partitioned by date (spec 10)."""
import json
import os

import numpy as np
import pandas as pd

RAW_TABLES = ["hex_snapshot_5min", "orders", "weather_5min", "signal_truth"]
# the date of a row: orders by created_ts; window tables by the date of the window start (ts - 5 min)
TS_COL = {"orders": "created_ts"}


def _dates(df, table):
    col = TS_COL.get(table, "ts")
    t = df[col].values
    if table != "orders":
        t = t - np.timedelta64(5, "m")
    return t.astype("datetime64[D]")


def write_partitioned(df, root, table, drop_cols=("_origin_zone",)):
    d = _dates(df, table)
    df = df.drop(columns=[c for c in drop_cols if c in df.columns])
    order = np.argsort(d, kind="stable")
    d_sorted = d[order]
    days, starts = np.unique(d_sorted, return_index=True)
    ends = list(starts[1:]) + [len(d_sorted)]
    for day, a, b in zip(days, starts, ends):
        path = os.path.join(root, table, f"date={str(day)}")
        os.makedirs(path, exist_ok=True)
        df.iloc[order[a:b]].to_parquet(os.path.join(path, "part.parquet"), index=False)


def write_dataset(tables, root, shuffled_orders=None):
    for name in RAW_TABLES:
        write_partitioned(tables[name], root, name)
    dbg = os.path.join(root, "_debug")
    os.makedirs(dbg, exist_ok=True)
    tables["debug_driver_stats"].to_parquet(os.path.join(dbg, "driver_stats_5min.parquet"), index=False)
    tables["debug_waiting"].to_parquet(os.path.join(dbg, "waiting_5min.parquet"), index=False)


def read_table(root, table):
    path = os.path.join(root, table)
    parts = sorted(os.listdir(path))
    return pd.concat([pd.read_parquet(os.path.join(path, p, "part.parquet")) for p in parts], ignore_index=True)


def calendar_json(cal, geo, cfg):
    def f(x):
        return float(x) if isinstance(x, (np.floating, float)) else int(x)
    return {
        "profile": cfg.profile, "n_days": cal.n_days, "split": cfg.split,
        "rain_days": cal.rain_days,
        "rain_episodes_min": [[f(a), f(b), f(c)] for a, b, c in cal.rain_episodes],
        "venue_events": [{k: f(v) for k, v in e.items()} for e in cal.venue_events],
        "drain_events": [{k: f(v) for k, v in e.items()} for e in cal.drain_events],
        "venue_hex": geo.cells[geo.venue_idx],
        "airport_hexes": [geo.cells[i] for i in geo.airport_idx],
        "note": "minutes are on the simulation axis, 0 = 00:00 of the burn-in day "
                f"({cfg.burn_in_days} day before start_date)",
    }


def dump_json(obj, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)

"""evaluate.py - danh gia tu predictions.parquet, khong import model.py.

    python evaluate.py runs/01 [runs/02 ...] [--split val|test]

Cot predictions.parquet: ts, hex, horizon, lambda, y, b, vol, split
  (vol = D + S_eff tai t+h, dung de loc cap co volume cao; split = val | test)
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.stats import rankdata

COLS = ["ts", "hex", "horizon", "lambda", "y", "b", "vol", "split"]


def _grids(df: pd.DataFrame):
    """df cua mot horizon -> cac mang [n_ts, n_hex] (NaN neu thieu)."""
    ti = pd.factorize(df["ts"], sort=True)[0]
    hi = pd.factorize(df["hex"], sort=True)[0]
    shape = (ti.max() + 1, hi.max() + 1)
    out = {}
    for c in ("lambda", "y", "b", "vol"):
        a = np.full(shape, np.nan)
        a[ti, hi] = df[c].to_numpy()
        out[c] = a
    return out


def pair_acc(lam, y, vol, margin_m, min_volume, chunk=256):
    """Ti le cap hex (cung ts) ma sign(lam_i - lam_j) = sign(y_i - y_j).

    Chi tinh cap ma ca hai hex co vol >= min_volume, bo cap gan hoa |y_i - y_j| <= m.
    lam hang so -> sign = 0 -> tinh la sai (khong duoc 'hoa' diem)."""
    i, j = np.triu_indices(lam.shape[1], 1)
    hit = tot = 0
    for s in range(0, len(lam), chunk):
        l, yy, v = lam[s:s + chunk], y[s:s + chunk], vol[s:s + chunk]
        dl, dy = l[:, i] - l[:, j], yy[:, i] - yy[:, j]
        ok = np.isfinite(dl) & np.isfinite(dy) & (v[:, i] >= min_volume) & (v[:, j] >= min_volume) & (np.abs(dy) > margin_m)
        hit += int((np.sign(dl) == np.sign(dy))[ok].sum())
        tot += int(ok.sum())
    return (hit / tot if tot else float("nan")), tot


def spearman(lam, y):
    """Spearman cat ngang theo ts (giua cac hex), lay trung binh. Hang so -> 0."""
    rs = []
    for l, yy in zip(lam, y):
        m = np.isfinite(l) & np.isfinite(yy)
        if m.sum() < 3:
            continue
        a, b = rankdata(l[m]), rankdata(yy[m])
        a, b = a - a.mean(), b - b.mean()
        den = np.sqrt((a * a).sum() * (b * b).sum())
        rs.append((a * b).sum() / den if den > 0 else 0.0)
    return float(np.mean(rs)) if rs else float("nan")


def compute_metrics(df: pd.DataFrame, margin_m: float, min_volume: float) -> dict:
    """{horizon: {pairacc, spearman, mae, corr_by, n_pairs, lam_std}} tren mot split."""
    res = {}
    for h, sub in df.groupby("horizon"):
        g = _grids(sub)
        pa, n = pair_acc(g["lambda"], g["y"], g["vol"], margin_m, min_volume)
        m = np.isfinite(g["lambda"]) & np.isfinite(g["y"])
        res[int(h)] = {
            "pairacc": pa, "n_pairs": n,
            "spearman": spearman(g["lambda"], g["y"]),
            "mae": float(np.abs(g["lambda"] - g["y"])[m].mean()),
            "corr_by": float(np.corrcoef(g["b"][m], g["y"][m])[0, 1]),
            "lam_std": float(np.nanmean(np.nanstd(g["lambda"], axis=1))),
        }
    return res


def table(rows: dict, horizons) -> str:
    """rows: {ten: metrics} -> bang in terminal."""
    head = f"{'run':<28}" + "".join(f"{'PA@' + str(h):>8}" for h in horizons) + \
           "".join(f"{'Sp@' + str(h):>8}" for h in horizons) + "".join(f"{'MAE@' + str(h):>9}" for h in horizons)
    lines = [head, "-" * len(head)]
    for name, m in rows.items():
        lines.append(f"{name:<28}" + "".join(f"{m[h]['pairacc']:8.4f}" for h in horizons) +
                     "".join(f"{m[h]['spearman']:8.4f}" for h in horizons) +
                     "".join(f"{m[h]['mae']:9.4f}" for h in horizons))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--split", default="val", choices=["val", "test"],
                    help="mac dinh val; test chi nen nhin o cuoi moi run (train.py da in)")
    a = ap.parse_args()
    rows, horizons = {}, None
    for r in a.runs:
        r = Path(r)
        cfg = yaml.safe_load((r / "config.yaml").read_text(encoding="utf-8"))
        df = pd.read_parquet(r / "predictions.parquet")
        df = df[df["split"] == a.split]
        m = compute_metrics(df, cfg["eval"]["margin_m"], cfg["eval"]["min_volume"])
        horizons = sorted(m)
        rows[f"{r.name} {cfg['model']['name']}"] = m
    print(f"split={a.split}  (PairAcc: |dy|>m, vol>=min_volume; Spearman cat ngang theo ts)")
    print(table(rows, horizons))


if __name__ == "__main__":
    main()
